"""Background worker that drives sketch generation through staged phases.

Phases:
  planning   – ask the model for a short engineering brief (bullets), streamed
  generating – ask the model for full OpenSCAD using the brief, streamed
  rendering  – run OpenSCAD CLI: thumbnail → full preview → STL
"""
from __future__ import annotations
import threading
import time
from django.core.files.base import ContentFile

from .models import Sketch
from .pipeline import prompt_to_scad as p2s
from .pipeline.prompt_to_scad import (
    generate_brief, generate_scad_with_brief, generate_scad, revise_scad,
    extract_interface,
)
from .pipeline.standards_retrieval import build_standards_context
from .pipeline.scad_runner import render_png, render_stl, repair_scad, render_png_file, render_stl_file
from .pipeline.validator import validate as run_validation
from .views_assembly import write_assembly_tempdir


def _save(sketch: Sketch, **fields) -> None:
    for k, v in fields.items():
        setattr(sketch, k, v)
    sketch.save()


def _throttled_writer(sketch_id: int, field: str, min_interval: float = 0.4):
    """Return a callback that writes partial text to one Sketch field, throttled."""
    state = {"last": 0.0, "len": 0}

    def write(partial: str) -> None:
        now = time.time()
        # Always flush if grew a lot or enough time passed
        if now - state["last"] < min_interval and len(partial) - state["len"] < 200:
            return
        state["last"] = now
        state["len"] = len(partial)
        Sketch.objects.filter(pk=sketch_id).update(**{field: partial})

    return write


def _heartbeat(sketch_id: int, label: str, stop_event: threading.Event,
               interval: float = 5.0) -> None:
    """Append an elapsed-time line to stage_log every `interval` seconds until stopped."""
    start = time.time()
    while not stop_event.wait(interval):
        elapsed = int(time.time() - start)
        sketch = Sketch.objects.get(pk=sketch_id)
        sketch.log(f"… {label} still running — {elapsed}s elapsed, "
                   f"brief={len(sketch.brief)}c, scad={len(sketch.scad_source)}c")
        sketch.save(update_fields=["stage_log"])


def _run_with_heartbeat(sketch_id: int, label: str, fn):
    stop = threading.Event()
    t = threading.Thread(target=_heartbeat, args=(sketch_id, label, stop), daemon=True)
    t.start()
    try:
        return fn()
    finally:
        stop.set()
        t.join(timeout=1.0)


def _work(sketch_id: int) -> None:
    sketch = Sketch.objects.get(pk=sketch_id)
    prompt = sketch.prompt
    standards_context = build_standards_context(prompt, limit=4)
    prompt_for_model = prompt
    if standards_context:
        sketch.log("rag: attached CalTrans standards context")
        prompt_for_model = (
            f"{prompt}\n\n"
            "RELEVANT CALTRANS STANDARDS CONTEXT:\n"
            f"{standards_context}"
        )
        sketch.save(update_fields=["stage_log"])
    try:
        # Assembly branch: scad_source was already built by the assembler view;
        # skip all LLM phases and go straight to rendering using temp files so
        # OpenSCAD can resolve the use<> stubs.
        if sketch.kind == "assembly" and sketch.scad_source and not sketch.revision_request:
            sketch.log("assembly render — skipping LLM phases")
            sketch.save()
            wrapper_path, tmp = write_assembly_tempdir(sketch)
            try:
                _render_phases_from_file(sketch_id, str(wrapper_path))
            finally:
                tmp.cleanup()
            return

        # In-place revision: sketch already has scad + a new revision_request.
        if sketch.scad_source and sketch.revision_request:
            change = sketch.revision_request
            sketch.log(f"revision requested: {change[:80]}")
            _save(sketch, status="generating")
            prior_scad = sketch.scad_source
            prior_brief = sketch.brief
            scad_writer = _throttled_writer(sketch_id, "scad_source")
            scad, label = _run_with_heartbeat(
                sketch_id, "revision",
                lambda: revise_scad(
                    prompt_for_model, prior_scad, change,
                    brief=prior_brief, on_delta=scad_writer,
                ),
            )
            sketch = Sketch.objects.get(pk=sketch_id)
            repaired, note = repair_scad(scad)
            if note:
                sketch.log(f"safety repair applied — {note}")
                scad = repaired
            sketch.scad_source = scad
            sketch.generator = label
            # Append to brief so the next revision sees the running history.
            rev_count = (sketch.brief.count("\n--- revision ") if sketch.brief else 0) + 1
            sketch.brief = (sketch.brief or "") + f"\n--- revision {rev_count}: {change}"
            sketch.revision_request = ""  # consumed
            iface = extract_interface(scad)
            sketch.interface_json = iface
            sketch.module_name = iface.get("module_name") or sketch.module_name
            if iface.get("warnings"):
                sketch.log("interface warnings: " + "; ".join(iface["warnings"]))
            sketch.log(f"generator: {label} ({len(scad)} chars)")
            if p2s.LAST_PROVIDER_ERROR:
                sketch.error = (sketch.error + "\n\n" if sketch.error else "") + \
                               "provider: " + p2s.LAST_PROVIDER_ERROR
            sketch.save()
            _render_phases(sketch_id, scad)
            return

        # Phase 1 — brief (streamed)
        sketch.log("phase 1: requesting engineering brief from gpt-5.5 (streaming)")
        _save(sketch, status="planning")
        brief_writer = _throttled_writer(sketch_id, "brief")
        brief = _run_with_heartbeat(
            sketch_id, "brief",
            lambda: generate_brief(prompt_for_model, on_delta=brief_writer),
        )
        sketch = Sketch.objects.get(pk=sketch_id)  # reload after writer updates
        if brief:
            sketch.brief = brief
            sketch.log(f"brief complete ({len(brief)} chars)")
        elif p2s.LAST_PROVIDER_ERROR:
            sketch.log(f"brief failed — {p2s.LAST_PROVIDER_ERROR}")
        else:
            sketch.log("brief skipped — no key or empty response")
        sketch.save()

        # Phase 2 — full SCAD (streamed)
        sketch.log("phase 2: streaming openscad source from gpt-5.5")
        _save(sketch, status="generating")
        scad_writer = _throttled_writer(sketch_id, "scad_source")
        def _gen():
            if brief:
                return generate_scad_with_brief(prompt_for_model, brief, on_delta=scad_writer)
            return generate_scad(prompt_for_model)
        scad, label = _run_with_heartbeat(sketch_id, "scad", _gen)
        sketch = Sketch.objects.get(pk=sketch_id)
        # Safety repair: balance braces / comment a truncated trailing line.
        repaired, note = repair_scad(scad)
        if note:
            sketch.log(f"safety repair applied — {note}")
            scad = repaired
        sketch.scad_source = scad
        sketch.generator = label
        iface = extract_interface(scad)
        sketch.interface_json = iface
        sketch.module_name = iface.get("module_name") or ""
        if iface.get("warnings"):
            sketch.log("interface warnings: " + "; ".join(iface["warnings"]))
        sketch.log(f"generator: {label} ({len(scad)} chars)")
        if p2s.LAST_PROVIDER_ERROR and "provider: " not in (sketch.error or ""):
            sketch.error = (sketch.error + "\n\n" if sketch.error else "") + \
                           "provider: " + p2s.LAST_PROVIDER_ERROR
        sketch.save()

        # Phase 3a — fast thumbnail
        sketch.log("phase 3a: fast thumbnail preview (OpenCSG)")
        _save(sketch, status="rendering")
        _render_phases(sketch_id, scad)

        # Phase 4 — standards validation
        sketch = Sketch.objects.get(pk=sketch_id)
        sketch.log("phase 4: validating against CalTrans standards")
        sketch.save()
        try:
            vr = run_validation(sketch)
            sketch = Sketch.objects.get(pk=sketch_id)
            sketch.log(
                f"validation complete — score={vr.compliance_score:.0f}% "
                f"pass={vr.passed} warn={vr.warned} fail={vr.failed} skip={vr.skipped} "
                f"element={vr.element_type}"
            )
            sketch.category = vr.element_type or sketch.category
            sketch.save()
        except Exception as ve:  # noqa: BLE001
            sketch.log(f"validation error (non-fatal): {ve!r}")
            sketch.save()

    except Exception as exc:  # noqa: BLE001
        sketch = Sketch.objects.get(pk=sketch_id)
        sketch.log(f"worker crashed: {exc!r}")
        sketch.error = (sketch.error + "\n\n" if sketch.error else "") + repr(exc)
        sketch.status = "failed"
        sketch.save()


def _render_phases(sketch_id: int, scad: str) -> None:
    """Shared 3a/3b/3c render phases used by both initial and revision paths."""
    sketch = Sketch.objects.get(pk=sketch_id)
    requested = sketch.requested_formats()
    _save(sketch, status="rendering")

    thumb = render_png(scad, basename=f"sketch_{sketch.pk}_thumb", px=320)
    if thumb.ok and thumb.png_bytes:
        sketch.preview.save(f"{sketch.pk}_thumb.png",
                            ContentFile(thumb.png_bytes), save=False)
        sketch.log(f"thumbnail ready ({len(thumb.png_bytes)}B)")
    else:
        sketch.log(f"thumbnail skipped: {thumb.message[:140]}")
    sketch.save()

    if "png" in requested:
        sketch.log("phase 3b: full-resolution preview")
        full = render_png(scad, basename=f"sketch_{sketch.pk}", px=960)
        if full.ok and full.png_bytes:
            sketch.preview.save(f"{sketch.pk}.png",
                                ContentFile(full.png_bytes), save=False)
            sketch.log(f"full preview ready ({len(full.png_bytes)}B)")
        else:
            sketch.log(f"full preview failed: {full.message[:240]}")
            sketch.error = (sketch.error + "\n\n" if sketch.error else "") + full.message
    else:
        sketch.log("phase 3b: skipped full preview (PNG export not requested)")
    sketch.save()

    if "stl" in requested:
        sketch.log("phase 3c: CGAL STL export — slowest phase")
        stl = render_stl(scad, basename=f"sketch_{sketch.pk}")
        if stl.ok and stl.stl_bytes:
            sketch.mesh.save(f"{sketch.pk}.stl",
                             ContentFile(stl.stl_bytes), save=False)
            sketch.log(f"STL ready ({len(stl.stl_bytes)}B)")
            sketch.status = "done"
        else:
            sketch.log("STL export failed")
            sketch.error = (sketch.error + "\n\n" if sketch.error else "") + stl.message
            sketch.status = "failed"
    else:
        sketch.log("phase 3c: skipped STL export")
        sketch.status = "done"
    sketch.save()


def _render_phases_from_file(sketch_id: int, scad_path: str) -> None:
    """Same as _render_phases but works from an on-disk file (assembly use<> stubs)."""
    sketch = Sketch.objects.get(pk=sketch_id)
    requested = sketch.requested_formats()
    _save(sketch, status="rendering")

    sketch.log("phase 3a: thumbnail (assembly file render)")
    thumb = render_png_file(scad_path, px=320)
    if thumb.ok and thumb.png_bytes:
        sketch.preview.save(f"{sketch.pk}_thumb.png",
                            ContentFile(thumb.png_bytes), save=False)
        sketch.log(f"thumbnail ready ({len(thumb.png_bytes)}B)")
    else:
        sketch.log(f"thumbnail skipped: {thumb.message[:140]}")
    sketch.save()

    if "png" in requested:
        sketch.log("phase 3b: full-resolution preview")
        full = render_png_file(scad_path, px=960)
        if full.ok and full.png_bytes:
            sketch.preview.save(f"{sketch.pk}.png",
                                ContentFile(full.png_bytes), save=False)
            sketch.log(f"full preview ready ({len(full.png_bytes)}B)")
        else:
            sketch.log(f"full preview failed: {full.message[:240]}")
            sketch.error = (sketch.error + "\n\n" if sketch.error else "") + full.message
    else:
        sketch.log("phase 3b: skipped full preview (PNG export not requested)")
    sketch.save()

    if "stl" in requested:
        sketch.log("phase 3c: CGAL STL export")
        stl = render_stl_file(scad_path)
        if stl.ok and stl.stl_bytes:
            sketch.mesh.save(f"{sketch.pk}.stl",
                             ContentFile(stl.stl_bytes), save=False)
            sketch.log(f"STL ready ({len(stl.stl_bytes)}B)")
            sketch.status = "done"
        else:
            sketch.log("STL export failed")
            sketch.error = (sketch.error + "\n\n" if sketch.error else "") + stl.message
            sketch.status = "failed"
    else:
        sketch.log("phase 3c: skipped STL export")
        sketch.status = "done"
    sketch.save()


def start(sketch_id: int) -> None:
    threading.Thread(target=_work, args=(sketch_id,), daemon=True).start()
