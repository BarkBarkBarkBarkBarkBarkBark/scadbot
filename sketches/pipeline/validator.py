"""
Bridge design validator.

Pipeline:
  1. detect_element_type()  – tag the structural element (deck / pylon / cable / arch / …)
  2. extract_scad_params()  – regex-mine numeric variables from SCAD source
  3. run_rules()            – deterministic Rule checks against extracted params
  4. run_rag_review()       – retrieve relevant standard chunks → LLM commentary
  5. validate()             – orchestrate all steps, persist ValidationResult
"""
from __future__ import annotations

import re
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Element-type detection ────────────────────────────────────────────────────

#: Ordered keyword → element_type mapping.  First match wins.
_ELEMENT_KEYWORDS: list[tuple[list[str], str]] = [
    (["pylon", "tower", "mast"], "pylon"),
    (["cable", "suspension", "hanger", "stay"], "cable"),
    (["arch", "rib"], "arch"),
    (["truss", "lattice", "warren", "pratt", "howe"], "truss"),
    (["abutment", "pier", "footing", "foundation"], "abutment"),
    (["deck", "roadway", "carriageway", "slab"], "deck"),
    (["beam", "girder", "box girder", "i-beam"], "girder"),
    (["bridge", "span", "crossing"], "bridge"),
]


def detect_element_type(sketch) -> str:  # type: ignore[return]
    """Return a short element-type label by scanning prompt + SCAD comments."""
    corpus = " ".join([
        (sketch.prompt or "").lower(),
        (sketch.brief or "").lower(),
        (sketch.category or "").lower(),
        # first 500 chars of SCAD (comments, variable names)
        (sketch.scad_source or "")[:500].lower(),
    ])
    for keywords, label in _ELEMENT_KEYWORDS:
        if any(kw in corpus for kw in keywords):
            return label
    return "bridge"


# ── SCAD parameter extraction ─────────────────────────────────────────────────

# Maps our canonical param name → list of SCAD regex patterns (first match wins)
_PARAM_PATTERNS: dict[str, list[str]] = {
    "span_length": [
        r"bridge_length\s*=\s*([\d.]+)",
        r"span_length\s*=\s*([\d.]+)",
        r"\bspan\s*=\s*([\d.]+)",
    ],
    "deck_width": [
        r"deck_width\s*=\s*([\d.]+)",
        r"\bwidth\s*=\s*([\d.]+)",
        r"road_width\s*=\s*([\d.]+)",
    ],
    "deck_thickness": [
        r"deck_thickness\s*=\s*([\d.]+)",
        r"slab_thickness\s*=\s*([\d.]+)",
    ],
    "deck_height": [
        r"deck_height\s*=\s*([\d.]+)",
        r"road_height\s*=\s*([\d.]+)",
    ],
    "clearance": [
        r"clearance\s*=\s*([\d.]+)",
        r"vertical_clearance\s*=\s*([\d.]+)",
        r"under_clearance\s*=\s*([\d.]+)",
    ],
    "pylon_height": [
        r"pylon_height\s*=\s*([\d.]+)",
        r"tower_height\s*=\s*([\d.]+)",
        r"mast_height\s*=\s*([\d.]+)",
    ],
    "arch_height": [r"arch_height\s*=\s*([\d.]+)", r"rise\s*=\s*([\d.]+)"],
    "cable_radius": [r"cable_r(?:adius)?\s*=\s*([\d.]+)", r"cable_d(?:ia)?\s*=\s*([\d.]+)"],
    "lane_count": [r"lane_count\s*=\s*(\d+)", r"lanes\s*=\s*(\d+)"],
    "lane_width": [r"lane_width\s*=\s*([\d.]+)"],
    "support_count": [r"support_count\s*=\s*(\d+)", r"pylons\s*=\s*(\d+)"],
    "wall_thickness": [r"wall_thickness\s*=\s*([\d.]+)", r"thickness\s*=\s*([\d.]+)"],
}


def extract_scad_params(scad_source: str) -> dict[str, float]:
    """Extract numeric parameters from OpenSCAD source using regex patterns."""
    result: dict[str, float] = {}
    for param, patterns in _PARAM_PATTERNS.items():
        for pat in patterns:
            m = re.search(pat, scad_source, re.IGNORECASE)
            if m:
                try:
                    result[param] = float(m.group(1))
                except ValueError:
                    pass
                break
    # Also pull request_json values as fallback (from compose form)
    return result


def _merge_request_params(params: dict[str, float], request_json: dict) -> dict[str, float]:
    """Fill gaps in SCAD-extracted params from the structured request_json."""
    mapping = {
        "span_mm": "span_length",
        "deck_width_mm": "deck_width",
        "clearance_mm": "clearance",
        "max_height_mm": "pylon_height",
        "lane_count": "lane_count",
    }
    merged = dict(params)
    for form_key, param_key in mapping.items():
        if param_key not in merged and form_key in request_json:
            try:
                merged[param_key] = float(request_json[form_key])
            except (TypeError, ValueError):
                pass
    return merged


# ── Deterministic rule engine ─────────────────────────────────────────────────

def run_rules(
    sketch,
    params: dict[str, float],
    element_type: str,
    bridge_type: str = "",
) -> list[dict[str, Any]]:
    """Run all active Rules against extracted params. Returns list of check dicts."""
    from sketches.models import Rule  # avoid circular at module level

    results: list[dict[str, Any]] = []

    rules = Rule.objects.filter(active=True).select_related("source_standard")

    for rule in rules:
        # Filter by bridge_type
        if rule.bridge_types and bridge_type and bridge_type not in rule.bridge_types:
            continue
        # Filter by element_type
        if rule.element_types and element_type and element_type not in rule.element_types:
            continue

        value = params.get(rule.parameter)
        check: dict[str, Any] = {
            "rule_id": rule.rule_id,
            "parameter": rule.parameter,
            "description": rule.description,
            "severity": rule.severity,
            "value": value,
            "threshold_min": rule.threshold_min,
            "threshold_max": rule.threshold_max,
            "comparator": rule.comparator,
            "source": str(rule.source_standard) if rule.source_standard else "",
            "quote": rule.quote[:200] if rule.quote else "",
        }

        if value is None:
            check["status"] = "skip"
            check["message"] = f"parameter '{rule.parameter}' not found in SCAD"
        else:
            passed, msg = _evaluate(rule, value)
            check["status"] = "pass" if passed else rule.severity
            check["message"] = msg

        results.append(check)

    return results


def _evaluate(rule, value: float) -> tuple[bool, str]:
    param = rule.parameter
    if rule.comparator == "min":
        lo = rule.threshold_min or 0
        ok = value >= lo
        return ok, (f"{param}={value:.1f} ≥ {lo:.1f} ✓" if ok
                    else f"{param}={value:.1f} < required {lo:.1f}")
    if rule.comparator == "max":
        hi = rule.threshold_max or float("inf")
        ok = value <= hi
        return ok, (f"{param}={value:.1f} ≤ {hi:.1f} ✓" if ok
                    else f"{param}={value:.1f} > max allowed {hi:.1f}")
    if rule.comparator == "range":
        lo = rule.threshold_min or 0
        hi = rule.threshold_max or float("inf")
        ok = lo <= value <= hi
        return ok, (f"{param}={value:.1f} in [{lo:.1f}, {hi:.1f}] ✓" if ok
                    else f"{param}={value:.1f} outside [{lo:.1f}, {hi:.1f}]")
    return True, "unknown comparator"


# ── RAG-backed LLM review ─────────────────────────────────────────────────────

def run_rag_review(sketch, params: dict[str, float], element_type: str) -> str:
    """Retrieve relevant standard chunks and ask LLM to flag compliance issues."""
    try:
        from .standards_retrieval import retrieve_relevant_chunks
        from .prompt_to_scad import _call_openai
        from django.conf import settings

        query = f"{element_type} bridge {sketch.prompt} span={params.get('span_length', '?')}mm"
        chunks = retrieve_relevant_chunks(query, limit=5)
        if not chunks:
            return ""

        context_parts = []
        for c in chunks:
            if isinstance(c, dict):
                title = c.get("standard_title", "")[:60]
                text = c.get("text", "")[:600]
            else:
                title = getattr(getattr(c, "standard", None), "title", "")[:60]
                text = getattr(c, "text", "")[:600]
            context_parts.append(f"[Standard: {title}]\n{text}")
        context = "\n\n".join(context_parts)

        param_summary = "\n".join(
            f"  {k} = {v:.1f} mm" for k, v in params.items()
        )

        system = (
            "You are a CalTrans bridge standards compliance reviewer. "
            "Given extracted design parameters and relevant standard excerpts, "
            "list any compliance concerns concisely. "
            "Format: one bullet per concern. If fully compliant say 'No issues found.'"
        )
        user = (
            f"Bridge element: {element_type}\n"
            f"Design parameters:\n{param_summary}\n\n"
            f"Relevant standard excerpts:\n{context}\n\n"
            "List compliance concerns:"
        )

        result = _call_openai(
            user,
            settings.OPENAI_API_KEY,
            system=system,
            strip_code_fence=False,
        )
        return (result or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("rag_review failed: %s", exc)
        return ""


# ── Auto-repair prompt builder ────────────────────────────────────────────────

def build_repair_prompt(sketch, check_results: list[dict]) -> str:
    """Build a targeted revision prompt from failed/warned rule checks."""
    failures = [c for c in check_results if c["status"] in ("fail", "warn")]
    if not failures:
        return ""

    lines = ["Revise this bridge design to fix the following standards violations:"]
    for c in failures:
        lines.append(f"  • {c['rule_id']}: {c['message']}")
        if c.get("quote"):
            lines.append(f"    (CalTrans: \"{c['quote'][:120]}\")")
    lines.append("Keep all other design elements unchanged.")
    return "\n".join(lines)


# ── Compliance score ──────────────────────────────────────────────────────────

def _score(results: list[dict]) -> float:
    """0–100 score: skipped checks are excluded from denominator."""
    active = [r for r in results if r["status"] != "skip"]
    if not active:
        return 100.0
    passed = sum(1 for r in active if r["status"] == "pass")
    return round(100.0 * passed / len(active), 1)


# ── Main entry point ──────────────────────────────────────────────────────────

def validate(sketch) -> "ValidationResult":  # type: ignore[return]
    """Run full validation pipeline on a Sketch and persist a ValidationResult."""
    from sketches.models import ValidationResult

    logger.info("validate: sketch#%d", sketch.pk)

    # 1. Detect element type
    element_type = detect_element_type(sketch)

    # 2. Extract params (SCAD + form fallback)
    params = extract_scad_params(sketch.scad_source or "")
    params = _merge_request_params(params, sketch.request_json or {})

    bridge_type = (sketch.request_json or {}).get("bridge_type", "")

    # 3. Deterministic rule checks
    check_results = run_rules(sketch, params, element_type, bridge_type)

    # 4. RAG LLM commentary (best-effort)
    rag_notes = run_rag_review(sketch, params, element_type)

    # 5. Auto-repair prompt
    repair_prompt = build_repair_prompt(sketch, check_results)

    # 6. Aggregate
    passed = sum(1 for r in check_results if r["status"] == "pass")
    warned = sum(1 for r in check_results if r["status"] == "warn")
    failed = sum(1 for r in check_results if r["status"] == "fail")
    skipped = sum(1 for r in check_results if r["status"] == "skip")
    score = _score(check_results)

    vr, _ = ValidationResult.objects.update_or_create(
        sketch=sketch,
        defaults=dict(
            compliance_score=score,
            passed=passed,
            warned=warned,
            failed=failed,
            skipped=skipped,
            element_type=element_type,
            results_json=check_results,
            rag_notes=rag_notes,
            auto_repair_prompt=repair_prompt,
        ),
    )
    logger.info(
        "validate: sketch#%d element=%s score=%.0f%% pass=%d warn=%d fail=%d skip=%d",
        sketch.pk, element_type, score, passed, warned, failed, skipped,
    )
    return vr
