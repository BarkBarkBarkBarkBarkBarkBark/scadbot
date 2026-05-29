"""Assembly views: library, compose-assembly, edit, render."""
from __future__ import annotations
import json
import re
import tempfile
from pathlib import Path

from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import ComponentRef, Sketch
from . import worker


def library(request):
    components = (
        Sketch.objects.filter(kind="component", status="done")
        .order_by("-created")
    )
    return render(request, "sketches/library.html", {"components": components})


def assemble(request):
    if request.method == "POST":
        prompt = (request.POST.get("prompt") or "").strip()
        if prompt:
            with transaction.atomic():
                assembly = Sketch.objects.create(
                    kind="assembly",
                    prompt=prompt,
                    status="idle",
                    generator="manual-assembly",
                )
                assembly.log("assembly created")
                assembly.save()
            return redirect("sketches:edit_assembly", pk=assembly.pk)
    components = (
        Sketch.objects.filter(kind="component", status="done")
        .order_by("-created")
    )
    return render(request, "sketches/assemble.html", {"components": components})


def edit_assembly(request, pk: int):
    assembly = get_object_or_404(Sketch, pk=pk, kind="assembly")
    refs = ComponentRef.objects.filter(assembly=assembly).select_related("component")
    components = (
        Sketch.objects.filter(kind="component", status="done")
        .order_by("-created")
    )
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "add")
        if action == "add":
            try:
                comp_id = int(request.POST["component_id"])
                comp = get_object_or_404(Sketch, pk=comp_id, kind="component", status="done")
                t_raw = request.POST.get("translate", "0,0,0")
                r_raw = request.POST.get("rotate", "0,0,0")
                p_raw = (request.POST.get("params") or "{}").strip()
                translate = [float(x) for x in t_raw.split(",")][:3]
                rotate    = [float(x) for x in r_raw.split(",")][:3]
                params    = json.loads(p_raw) if p_raw else {}
                instance  = (request.POST.get("instance_name") or comp.module_name or f"part{comp_id}").strip()
                ComponentRef.objects.create(
                    assembly=assembly,
                    component=comp,
                    instance_name=instance,
                    translate=translate,
                    rotate=rotate,
                    params_json=params,
                    order=refs.count(),
                )
                assembly.log(f"added {instance} (component #{comp_id})")
                assembly.save()
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                error = f"could not add component: {exc}"
            return redirect("sketches:edit_assembly", pk=assembly.pk)

    return render(request, "sketches/edit_assembly.html", {
        "assembly": assembly,
        "refs": refs,
        "components": components,
        "error": error,
        "in_progress": assembly.status in {"pending", "planning", "generating", "rendering"},
    })


@require_POST
def remove_slot(request, pk: int, ref_pk: int):
    assembly = get_object_or_404(Sketch, pk=pk, kind="assembly")
    ref = get_object_or_404(ComponentRef, pk=ref_pk, assembly=assembly)
    label = ref.instance_name or ref.component.module_name
    ref.delete()
    assembly.log(f"removed slot: {label}")
    assembly.save()
    return redirect("sketches:edit_assembly", pk=assembly.pk)


@require_POST
def render_assembly(request, pk: int):
    assembly = get_object_or_404(Sketch, pk=pk, kind="assembly")
    refs = ComponentRef.objects.filter(assembly=assembly)
    if not refs.exists():
        assembly.log("render requested but no components added")
        assembly.save()
        return redirect("sketches:edit_assembly", pk=assembly.pk)
    scad = build_assembly_scad(assembly)
    assembly.scad_source = scad
    assembly.status = "pending"
    assembly.error = ""
    assembly.log("render queued")
    assembly.save()
    worker.start(assembly.pk)
    return redirect("sketches:show_assembly", pk=assembly.pk)


def show_assembly(request, pk: int):
    assembly = get_object_or_404(Sketch, pk=pk, kind="assembly")
    refs = ComponentRef.objects.filter(assembly=assembly).select_related("component")
    in_progress = assembly.status in {"pending", "planning", "generating", "rendering"}
    return render(request, "sketches/assembly_result.html", {
        "assembly": assembly,
        "refs": refs,
        "in_progress": in_progress,
    })


# ---------------------------------------------------------------------------
# SCAD builder — writes component stubs to a temp dir and returns wrapper text
# ---------------------------------------------------------------------------

def build_assembly_scad(assembly: Sketch) -> str:
    refs = list(
        ComponentRef.objects.filter(assembly=assembly)
        .order_by("order")
        .select_related("component")
    )
    lines = [
        f"// scadforge assembly: {assembly.prompt}",
        "",
    ]
    for ref in refs:
        comp = ref.component
        if not comp.scad_source:
            lines.append(f"// WARNING: component #{comp.pk} has no source — skipped")
            continue
        lines.append(f"use <component_{comp.pk}.scad>;")

    lines.append("")

    for ref in refs:
        comp = ref.component
        if not comp.scad_source:
            continue
        module = comp.module_name or _guess_module(comp.scad_source) or f"part_{comp.pk}"
        t = ref.translate if isinstance(ref.translate, list) and len(ref.translate) == 3 else [0, 0, 0]
        r = ref.rotate    if isinstance(ref.rotate,    list) and len(ref.rotate)    == 3 else [0, 0, 0]
        overrides = []
        for p in (comp.interface_json.get("params") or []):
            name = p["name"]
            val = ref.params_json.get(name, p.get("default"))
            if val is not None:
                overrides.append(f"{name}={val}")
        param_str = ", ".join(overrides)
        label = ref.instance_name or module
        indent = "  "
        lines.append(f"// {label}")
        lines.append(f"translate([{t[0]}, {t[1]}, {t[2]}])")
        if any(v != 0 for v in r):
            lines.append(f"{indent}rotate([{r[0]}, {r[1]}, {r[2]}])")
            lines.append(f"{indent}  {module}({param_str});")
        else:
            lines.append(f"{indent}{module}({param_str});")
        lines.append("")

    return "\n".join(lines)


def write_assembly_tempdir(assembly: Sketch):
    """Write all component stubs + wrapper into a TemporaryDirectory.
    Returns (wrapper_path: Path, tmp: TemporaryDirectory).
    Caller must keep `tmp` alive until rendering is complete, then call tmp.cleanup().
    """
    tmp = tempfile.TemporaryDirectory(prefix="scadforge_asm_")
    tmp_path = Path(tmp.name)

    refs = (
        ComponentRef.objects.filter(assembly=assembly)
        .order_by("order")
        .select_related("component")
    )
    for ref in refs:
        comp = ref.component
        if comp.scad_source:
            (tmp_path / f"component_{comp.pk}.scad").write_text(comp.scad_source, encoding="utf-8")

    wrapper = build_assembly_scad(assembly)
    wrapper_path = tmp_path / "assembly.scad"
    wrapper_path.write_text(wrapper, encoding="utf-8")
    return wrapper_path, tmp


def _guess_module(scad: str) -> str | None:
    hits = re.findall(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", scad, re.MULTILINE)
    return hits[-1] if hits else None
