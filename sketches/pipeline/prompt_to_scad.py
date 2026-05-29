"""Prompt → OpenSCAD code. Uses OpenAI/Gemini if configured, else templates."""
from __future__ import annotations
import json
import re
from typing import Callable

import requests
from django.conf import settings

from .catalog import from_keywords

# Most recent provider error (read by the view to surface in the UI).
LAST_PROVIDER_ERROR: str = ""

# Callback signature: fn(partial_text: str) -> None. Called as tokens arrive.
DeltaCB = Callable[[str], None]

_SYS = (
    "You are an expert CAD/OpenSCAD generator for small printable concept models. "
    "Convert the user's short description into one self-contained OpenSCAD program. "
    "Output ONLY valid OpenSCAD code, no markdown, no prose. Do not use include(), "
    "use(), import(), file IO, external assets, or animation. Prefer simple solid "
    "constructive geometry. Use $fn for smoothness, center the model near the origin, "
    "and keep it renderable by OpenSCAD 2021. If the user asks for a bridge, include "
    "recognizable engineering features such as a deck, railings, piers, arches, truss "
    "members, towers, or cables."
)

_SYS_BRIEF = (
    "You are a senior structural / mechanical engineer producing a concise design brief "
    "for a 3D-printable OpenSCAD model. Output 6-12 short bullets in plain text, no "
    "markdown, no code. Cover: overall form, key dimensions in mm, structural members, "
    "materials/aesthetic intent, symmetry, and any printability notes. Be specific and "
    "numerical. Do NOT write OpenSCAD code."
)

_SYS_FROM_BRIEF = (
    "You are a senior mechanical / architectural designer producing ONE COMPONENT "
    "for a print-ready CAD library that civil engineers and architects will review. "
    "\n\n"
    "MULTI-AGENT CONTEXT (important): your output is a single reusable part. A SEPARATE "
    "composer agent will later arrange your part alongside other components into a scene. "
    "Do NOT design surroundings, ground planes, scenery, lighting, or related parts. "
    "Spend ALL your effort making this one part excellent: correct proportions, fine "
    "detail, clean geometry, print-ready.\n\n"
    "OUTPUT CONTRACT — strict:\n"
    " - Output ONLY OpenSCAD code. No markdown, no prose, no comments narrating changes.\n"
    " - Exactly ONE top-level module that takes the design's parameters with sensible \n"
    "   defaults; all other modules are helpers called from it.\n"
    " - Call the top-level module ONCE at the bottom of the file with defaults.\n"
    " - The top-level module name should be a snake_case noun matching the part.\n"
    " - Declare named anchor points as comments using this exact format so the composer \n"
    "   can place neighbouring parts:  // @anchor <name> = [x, y, z]\n"
    " - Include at minimum the anchors: base_center, top_center, and any natural \n"
    "   attachment points (e.g. seat_left, lantern_center, deck_end).\n\n"
    "PRODUCTION-GRADE CONSTRAINTS:\n"
    " - Units: millimetres. Real-world scale (a person is ~1700 mm tall; a bench \n"
    "   seat is ~450 mm high; a park lamppost is ~4000-5000 mm tall).\n"
    " - Z is up. Base of the part sits at z = 0; centered on the XY origin.\n"
    " - Manifold geometry only. No zero-thickness faces. Minimum wall 1.2 mm for FDM.\n"
    " - Prefer hull(), minkowski(), and small chamfers for production feel.\n"
    " - $fn: 24-48 for visible curves, 8-16 for hidden / internal.\n"
    " - Eye-candy is encouraged: chamfered edges, panel lines, rivets, woodgrain via \n"
    "   shallow linear_extrude, subtle taper, realistic proportions.\n"
    " - STL export should complete in under ~30 s on a laptop. No giant boolean trees.\n\n"
    "FORBIDDEN: include(), use(), import(), file IO, surface(), animation, $t.\n\n"
    "EXEMPLAR (shape of a good component — do not copy verbatim):\n"
    "  // @anchor base_center = [0, 0, 0]\n"
    "  // @anchor top_center  = [0, 0, 900]\n"
    "  module park_bollard(height=900, diameter=140, chamfer=8, $fn=36) {\n"
    "    difference() {\n"
    "      hull() {\n"
    "        cylinder(h=height-chamfer, d=diameter);\n"
    "        translate([0,0,height-chamfer]) cylinder(h=chamfer, d=diameter-2*chamfer);\n"
    "      }\n"
    "      for (a=[0:60:359]) rotate([0,0,a]) translate([diameter/2-2,0,height*0.6])\n"
    "        sphere(d=4);\n"
    "    }\n"
    "  }\n"
    "  park_bollard();\n\n"
    "SELF-CHECK before output: single top-level module, all params have defaults, base at \n"
    "z=0, all braces / brackets / parens balanced, no use/include, anchors declared."
)


_SYS_REVISE = (
    "You are an expert OpenSCAD author. The user has an existing OpenSCAD program "
    "and wants targeted modifications. Output ONLY one complete revised OpenSCAD "
    "program (no markdown, no prose, no diff). Preserve the existing structure, "
    "module names, and conventions wherever possible. Apply the change request "
    "precisely. Do not use include(), use(), import(), file IO, surface(), or "
    "animation. Keep it renderable by OpenSCAD 2021."
)


def _strip_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:scad|openscad)?\s*(.+?)\s*```$", text, re.S)
    return m.group(1) if m else text


def _extract_responses_text(data: dict) -> str | None:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks) if chunks else None


def _call_openai(prompt: str, key: str, system: str | None = None,
                 strip_code_fence: bool = True,
                 on_delta: DeltaCB | None = None,
                 model: str | None = None) -> str | None:
    base = settings.OPENAI_BASE_URL.rstrip("/")
    model = model or settings.OPENAI_MODEL
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    sys_msg = system or _SYS

    # If a streaming callback is requested, use Chat Completions with stream=True.
    # This gives us token deltas we can show in the UI immediately.
    if on_delta is not None:
        return _stream_chat(base, model, headers, sys_msg, prompt,
                            on_delta=on_delta, strip_code_fence=strip_code_fence)

    responses_body = {
        "model": model,
        "input": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ],
        "max_output_tokens": 4000,
    }
    global LAST_PROVIDER_ERROR
    try:
        r = requests.post(
            f"{base}/responses",
            headers=headers,
            json=responses_body,
            timeout=settings.GENERATION_TIMEOUT,
        )
        if r.ok:
            text = _extract_responses_text(r.json())
            if text:
                return _strip_fence(text) if strip_code_fence else text.strip()
        else:
            LAST_PROVIDER_ERROR = f"OpenAI /responses {r.status_code}: {r.text[:240]}"
    except (requests.RequestException, json.JSONDecodeError) as exc:
        LAST_PROVIDER_ERROR = f"OpenAI /responses network error: {exc!r}"

    chat_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ],
        "max_completion_tokens": 4000,
    }
    try:
        r = requests.post(
            f"{base}/chat/completions",
            headers=headers,
            json=chat_body,
            timeout=settings.GENERATION_TIMEOUT,
        )
        if not r.ok:
            LAST_PROVIDER_ERROR = f"OpenAI /chat/completions {r.status_code}: {r.text[:240]}"
            return None
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        return _strip_fence(text) if strip_code_fence else text.strip()
    except (requests.RequestException, KeyError, json.JSONDecodeError) as exc:
        LAST_PROVIDER_ERROR = f"OpenAI chat error: {exc!r}"
        return None


def _stream_chat(base: str, model: str, headers: dict, sys_msg: str, user_msg: str,
                 *, on_delta: DeltaCB, strip_code_fence: bool) -> str | None:
    """Stream OpenAI chat completions, calling on_delta(full_text_so_far) as chunks arrive."""
    global LAST_PROVIDER_ERROR
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        "max_completion_tokens": 12000,
        "stream": True,
    }
    # gpt-5.x reasoning models: reduce silent thinking so tokens arrive fast.
    effort = (settings.OPENAI_REASONING_EFFORT or "").strip().lower()
    if effort in {"minimal", "low", "medium", "high"} and model.startswith(("gpt-5", "o1", "o3", "o4")):
        body["reasoning_effort"] = effort
    accumulated: list[str] = []
    finish_reason: str | None = None
    try:
        with requests.post(
            f"{base}/chat/completions",
            headers=headers,
            json=body,
            timeout=settings.GENERATION_TIMEOUT,
            stream=True,
        ) as r:
            if not r.ok:
                LAST_PROVIDER_ERROR = f"OpenAI stream {r.status_code}: {r.text[:240]}"
                return None
            for raw in r.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                if raw.startswith("data: "):
                    payload = raw[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        ev = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    try:
                        choice = ev["choices"][0]
                        delta = choice["delta"].get("content")
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                    except (KeyError, IndexError):
                        delta = None
                    if delta:
                        accumulated.append(delta)
                        try:
                            on_delta("".join(accumulated))
                        except Exception:  # noqa: BLE001
                            pass
    except requests.RequestException as exc:
        LAST_PROVIDER_ERROR = f"OpenAI stream network error: {exc!r}"
        if not accumulated:
            return None

    text = "".join(accumulated)
    if not text.strip():
        return None

    # If the model was cut off, ask it to continue once.
    if finish_reason == "length":
        LAST_PROVIDER_ERROR = (
            f"model output truncated at {len(text)} chars; "
            "attempting a continuation pass."
        )
        cont = _continue_chat(base, model, headers, sys_msg, user_msg, text,
                              on_delta=on_delta, strip_code_fence=strip_code_fence)
        if cont:
            text = text + cont

    return _strip_fence(text) if strip_code_fence else text.strip()


def _continue_chat(base: str, model: str, headers: dict, sys_msg: str, user_msg: str,
                   so_far: str, *, on_delta: DeltaCB,
                   strip_code_fence: bool) -> str | None:
    """Ask the model to continue exactly where it stopped."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": so_far},
            {"role": "user", "content":
             "Continue exactly where you stopped. Do not repeat any prior content. "
             "Do not add prose or markdown. Finish the OpenSCAD program cleanly."},
        ],
        "max_completion_tokens": 8000,
        "stream": True,
    }
    effort = (settings.OPENAI_REASONING_EFFORT or "").strip().lower()
    if effort in {"minimal", "low", "medium", "high"} and model.startswith(("gpt-5", "o1", "o3", "o4")):
        body["reasoning_effort"] = effort
    added: list[str] = []
    try:
        with requests.post(
            f"{base}/chat/completions",
            headers=headers,
            json=body,
            timeout=settings.GENERATION_TIMEOUT,
            stream=True,
        ) as r:
            if not r.ok:
                return None
            for raw in r.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data: "):
                    continue
                payload = raw[6:].strip()
                if payload == "[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                    delta = ev["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, json.JSONDecodeError):
                    delta = None
                if delta:
                    added.append(delta)
                    try:
                        on_delta(so_far + "".join(added))
                    except Exception:  # noqa: BLE001
                        pass
    except requests.RequestException:
        pass
    return "".join(added) if added else None


def _call_gemini(prompt: str, key: str) -> str | None:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-1.5-flash:generateContent?key={key}"
    )
    body = {
        "system_instruction": {"parts": [{"text": _SYS}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1024},
    }
    global LAST_PROVIDER_ERROR
    try:
        r = requests.post(url, json=body, timeout=30)
        if not r.ok:
            LAST_PROVIDER_ERROR = f"Gemini {r.status_code}: {r.text[:240]}"
            return None
        data = r.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return _strip_fence(text)
    except (requests.RequestException, KeyError, json.JSONDecodeError) as exc:
        LAST_PROVIDER_ERROR = f"Gemini error: {exc!r}"
        return None


def generate_scad(prompt: str) -> tuple[str, str]:
    """Returns (scad_source, generator_label)."""
    global LAST_PROVIDER_ERROR
    LAST_PROVIDER_ERROR = ""
    bridge_words = {"bridge", "viaduct", "overpass"}
    if settings.BRIDGE_TEMPLATE_FIRST and any(word in prompt.lower() for word in bridge_words):
        return from_keywords(prompt), "template:bridge"

    preferred = settings.PREFERRED_PROVIDER.lower()
    if settings.OPENAI_API_KEY and preferred in {"openai", "chatgpt", "gpt"}:
        out = _call_openai(prompt, settings.OPENAI_API_KEY)
        if out and out.strip():
            return out, f"openai:{settings.OPENAI_MODEL}"

    if settings.GEMINI_KEY and preferred in {"gemini", "google"}:
        out = _call_gemini(prompt, settings.GEMINI_KEY)
        if out and out.strip():
            return out, "gemini"

    # If the preferred provider failed, try the other configured provider once.
    if settings.OPENAI_API_KEY and preferred not in {"openai", "chatgpt", "gpt"}:
        out = _call_openai(prompt, settings.OPENAI_API_KEY)
        if out and out.strip():
            return out, f"openai:{settings.OPENAI_MODEL}"

    if settings.GEMINI_KEY and preferred not in {"gemini", "google"}:
        out = _call_gemini(prompt, settings.GEMINI_KEY)
        if out and out.strip():
            return out, "gemini"

    return from_keywords(prompt), "heuristic"


def generate_brief(prompt: str, on_delta: DeltaCB | None = None) -> str:
    """Phase 1: produce a short engineering brief. Returns '' if no LLM available."""
    global LAST_PROVIDER_ERROR
    LAST_PROVIDER_ERROR = ""
    if not settings.OPENAI_API_KEY:
        return ""
    out = _call_openai(prompt, settings.OPENAI_API_KEY,
                       system=_SYS_BRIEF, strip_code_fence=False,
                       on_delta=on_delta,
                       model=settings.OPENAI_PLAN_MODEL)
    return (out or "").strip()


def generate_scad_with_brief(prompt: str, brief: str,
                              on_delta: DeltaCB | None = None) -> tuple[str, str]:
    """Phase 2: convert prompt + brief into OpenSCAD."""
    global LAST_PROVIDER_ERROR
    LAST_PROVIDER_ERROR = ""
    if not settings.OPENAI_API_KEY:
        return generate_scad(prompt)
    user_msg = (
        f"USER REQUEST:\n{prompt}\n\nDESIGN BRIEF:\n{brief}\n\n"
        "Now produce the OpenSCAD program that realises this brief."
    )
    out = _call_openai(user_msg, settings.OPENAI_API_KEY,
                       system=_SYS_FROM_BRIEF, on_delta=on_delta,
                       model=settings.OPENAI_CODE_MODEL)
    if out and out.strip():
        return out, f"openai:{settings.OPENAI_CODE_MODEL} (briefed)"
    # Fall back to single-shot generation if phase 2 fails
    return generate_scad(prompt)


def revise_scad(original_prompt: str, prior_scad: str, change_request: str,
                brief: str = "",
                on_delta: DeltaCB | None = None) -> tuple[str, str]:
    """Apply targeted modifications to an existing OpenSCAD program.

    `brief` carries the engineering brief plus any prior revision history so the
    model retains context across successive in-place revisions.
    """
    global LAST_PROVIDER_ERROR
    LAST_PROVIDER_ERROR = ""
    if not settings.OPENAI_API_KEY:
        return prior_scad, "no-op (no api key)"
    brief_block = f"DESIGN BRIEF & REVISION HISTORY:\n{brief}\n\n" if brief.strip() else ""
    user_msg = (
        f"ORIGINAL REQUEST:\n{original_prompt}\n\n"
        f"{brief_block}"
        f"NEW CHANGE REQUEST:\n{change_request}\n\n"
        f"EXISTING OPENSCAD PROGRAM:\n```\n{prior_scad}\n```\n\n"
        "Return the complete revised program. Preserve all working parts unless "
        "the change requires removing them."
    )
    out = _call_openai(user_msg, settings.OPENAI_API_KEY,
                       system=_SYS_REVISE, on_delta=on_delta,
                       model=settings.OPENAI_CODE_MODEL)
    if out and out.strip():
        return out, f"openai:{settings.OPENAI_CODE_MODEL} (revised)"
    return prior_scad, f"revision failed — kept prior scad ({LAST_PROVIDER_ERROR or 'no output'})"


# ---------------------------------------------------------------------------
# Interface extraction — derive a Component contract from generated SCAD.
# Zero-LLM: pure regex. Cheap, deterministic, runs on every successful gen.
# ---------------------------------------------------------------------------

_MODULE_RE = re.compile(
    r"^\s*module\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*\{",
    re.MULTILINE,
)
_ANCHOR_RE = re.compile(
    r"//\s*@anchor\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\[\s*"
    r"(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]",
)
_PARAM_RE = re.compile(
    r"\s*([A-Za-z_$][A-Za-z0-9_]*)\s*=\s*([^,]+?)\s*(?:,|$)",
)


def extract_interface(scad: str) -> dict:
    """Parse the generated SCAD and return a small JSON-able interface contract.

    Returns:
      {
        "module_name": str | None,        # top-level (last-defined) module
        "params": [ {"name": str, "default": str}, ... ],
        "anchors": [ {"name": str, "xyz": [x,y,z]}, ... ],
        "modules": [str, ...],            # all module names declared
        "warnings": [str, ...],
      }
    """
    warnings: list[str] = []

    modules = _MODULE_RE.findall(scad or "")
    module_names = [m[0] for m in modules]

    # Pick the top-level module: the one CALLED at the bottom (last non-comment
    # statement of the form `name(...);`). Fall back to last-defined.
    top_name: str | None = None
    call_re = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
    calls = [c for c in call_re.findall(scad or "") if c in module_names]
    if calls:
        top_name = calls[-1]
    elif module_names:
        top_name = module_names[-1]

    if not top_name:
        warnings.append("no module declarations found")

    params: list[dict] = []
    if top_name:
        # find that module's signature
        for name, sig in modules:
            if name == top_name:
                # naive split by comma; ignore [] groups
                depth = 0
                buf = ""
                pieces: list[str] = []
                for ch in sig:
                    if ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                    if ch == "," and depth == 0:
                        pieces.append(buf)
                        buf = ""
                    else:
                        buf += ch
                if buf.strip():
                    pieces.append(buf)
                for piece in pieces:
                    piece = piece.strip()
                    if not piece:
                        continue
                    if "=" in piece:
                        key, _, default = piece.partition("=")
                        params.append({
                            "name": key.strip(),
                            "default": default.strip(),
                        })
                    else:
                        params.append({"name": piece, "default": None})
                        warnings.append(f"param '{piece}' has no default")
                break

    anchors = [
        {"name": m.group(1),
         "xyz": [float(m.group(2)), float(m.group(3)), float(m.group(4))]}
        for m in _ANCHOR_RE.finditer(scad or "")
    ]
    if not anchors:
        warnings.append("no @anchor comments declared")

    if len(module_names) == 0:
        warnings.append("module enforcement: no modules at all")
    elif top_name and module_names.count(top_name) > 1:
        warnings.append(f"module '{top_name}' defined multiple times")

    return {
        "module_name": top_name,
        "params": params,
        "anchors": anchors,
        "modules": module_names,
        "warnings": warnings,
    }
