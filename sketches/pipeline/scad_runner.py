"""Run the OpenSCAD CLI to produce a PNG preview and an STL mesh.

Remote mode: when settings.SCAD_RENDER_URL is set every render is dispatched
to the Fly.io render service instead of a local binary.  The local binary is
used as a fallback when the env var is absent or the remote call fails AND a
local binary exists.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import logging
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

_MAC_DEFAULT = "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"


def locate_binary() -> str | None:
    if settings.SCAD_BIN and Path(settings.SCAD_BIN).exists():
        return settings.SCAD_BIN
    found = shutil.which("openscad") or shutil.which("OpenSCAD")
    if found:
        return found
    if Path(_MAC_DEFAULT).exists():
        return _MAC_DEFAULT
    return None


@dataclass
class RenderOutcome:
    ok: bool
    png_bytes: bytes = b""
    stl_bytes: bytes = b""
    message: str = ""


# ── Remote render helpers ─────────────────────────────────────────────────────

def _render_url() -> str:
    return (getattr(settings, "SCAD_RENDER_URL", None) or "").rstrip("/")


def _render_token() -> str:
    return getattr(settings, "SCAD_RENDER_TOKEN", None) or ""


def _remote_render(scad: str, fmt: str, px: int = 640) -> RenderOutcome:
    """POST scad source to the Fly.io render service; return RenderOutcome."""
    base = _render_url()
    if not base:
        return RenderOutcome(False, message="no SCAD_RENDER_URL configured")

    qs = urllib.parse.urlencode({"format": fmt, "px": px})
    url = f"{base}/render?{qs}"

    body = urllib.parse.urlencode({"scad": scad}).encode()
    headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}
    token = _render_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = getattr(settings, "SCAD_RENDER_TIMEOUT", 120)
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        logger.info("remote render ok format=%s %d bytes", fmt, len(data))
        if fmt == "png":
            return RenderOutcome(ok=True, png_bytes=data)
        return RenderOutcome(ok=True, stl_bytes=data)
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode(errors="replace")[:500]
        msg = f"render service HTTP {exc.code}: {err_body}"
        logger.warning("remote render failed: %s", msg)
        return RenderOutcome(False, message=msg)
    except Exception as exc:  # noqa: BLE001
        msg = f"render service unreachable: {exc}"
        logger.warning("remote render error: %s", msg)
        return RenderOutcome(False, message=msg)


# ── Local binary helpers ──────────────────────────────────────────────────────

def _invoke(binary: str, args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [binary, *args],
            capture_output=True, text=True, timeout=settings.SCAD_RENDER_TIMEOUT,
        )
        return proc.returncode, (proc.stderr or proc.stdout)
    except subprocess.TimeoutExpired:
        return 124, f"OpenSCAD timed out after {settings.SCAD_RENDER_TIMEOUT}s. Try a simpler model."


def validate_scad(scad: str) -> str | None:
    """Return a human-readable error when generated SCAD is unsafe to render."""
    if len(scad) > settings.SCAD_MAX_CHARS:
        return f"Generated SCAD is too large ({len(scad)} chars)."

    blocked = [
        r"\binclude\s*<", r"\buse\s*<", r"\bimport\s*\(",
        r"\bsurface\s*\(", r"\bsearch\s*\(", r"\becho\s*\(",
        r"\.\./", r"/Users/", r"/tmp/", r"/etc/", r"[A-Za-z]:\\",
    ]
    for pattern in blocked:
        if re.search(pattern, scad, flags=re.IGNORECASE):
            return f"Generated SCAD contains a blocked construct: {pattern}"
    return None


def repair_scad(scad: str) -> tuple[str, str]:
    """Best-effort cleanup of truncated/malformed model output.

    Returns (repaired_text, note). `note` describes what (if anything) was changed.
    """
    notes: list[str] = []
    text = scad.rstrip()

    # If the last non-empty line is clearly mid-statement (no terminator, no brace),
    # comment it out so the parser doesn't choke at EOF.
    lines = text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        last = lines[-1].rstrip()
        if last and last[-1] not in ";{}":
            lines[-1] = "// truncated: " + last
            notes.append("commented truncated last line")
    text = "\n".join(lines)

    # Balance braces / parens (count only outside of // line comments and strings — cheap heuristic).
    stripped = re.sub(r'//[^\n]*', '', text)
    stripped = re.sub(r'"(?:\\.|[^"\\])*"', '""', stripped)
    open_curly = stripped.count("{") - stripped.count("}")
    open_paren = stripped.count("(") - stripped.count(")")
    open_brack = stripped.count("[") - stripped.count("]")
    if open_paren > 0:
        text += ")" * open_paren
        notes.append(f"closed {open_paren} paren(s)")
    if open_brack > 0:
        text += "]" * open_brack
        notes.append(f"closed {open_brack} bracket(s)")
    if open_curly > 0:
        text += "\n" + ("}\n" * open_curly)
        notes.append(f"closed {open_curly} brace(s)")

    if not text.endswith("\n"):
        text += "\n"
    return text, "; ".join(notes)


def _cleanup(work: Path) -> None:
    for p in work.iterdir():
        try:
            os.unlink(p)
        except OSError:
            pass
    try:
        os.rmdir(work)
    except OSError:
        pass


def _prepare() -> tuple[str, Path] | RenderOutcome:
    binary = locate_binary()
    if not binary:
        return RenderOutcome(False, message=(
            "OpenSCAD binary not found. Install it (brew install --cask openscad) "
            "or set SCAD_BIN in your .env."
        ))
    return binary, Path(tempfile.mkdtemp(prefix="scadforge_"))


def render_png(scad: str, basename: str, px: int | None = None) -> RenderOutcome:
    """Fast OpenCSG preview PNG. Seconds, not minutes."""
    err = validate_scad(scad)
    if err:
        return RenderOutcome(False, message=err)
    px = px or settings.RENDER_PX
    if _render_url():
        return _remote_render(scad, "png", px)
    prep = _prepare()
    if isinstance(prep, RenderOutcome):
        return prep
    binary, work = prep
    try:
        src = work / f"{basename}.scad"
        png = work / f"{basename}.png"
        src.write_text(scad, encoding="utf-8")
        rc, log = _invoke(binary, [
            "-o", str(png),
            f"--imgsize={px},{px}",
            "--colorscheme=Tomorrow Night",
            "--autocenter", "--viewall",
            str(src),
        ])
        if rc != 0 or not png.exists():
            return RenderOutcome(False, message=f"PNG render failed:\n{log}")
        return RenderOutcome(ok=True, png_bytes=png.read_bytes())
    finally:
        _cleanup(work)


def render_stl(scad: str, basename: str) -> RenderOutcome:
    """Full CGAL STL export. The slow phase."""
    err = validate_scad(scad)
    if err:
        return RenderOutcome(False, message=err)
    if _render_url():
        return _remote_render(scad, "stl")
    prep = _prepare()
    if isinstance(prep, RenderOutcome):
        return prep
    binary, work = prep
    try:
        src = work / f"{basename}.scad"
        stl = work / f"{basename}.stl"
        src.write_text(scad, encoding="utf-8")
        rc, log = _invoke(binary, ["-o", str(stl), str(src)])
        if rc != 0 or not stl.exists():
            return RenderOutcome(False, message=f"STL export failed:\n{log}")
        return RenderOutcome(ok=True, stl_bytes=stl.read_bytes())
    finally:
        _cleanup(work)


def render_scad(scad: str, basename: str) -> RenderOutcome:
    """One-shot full render. Kept for back-compat."""
    png = render_png(scad, basename, px=settings.RENDER_PX)
    if not png.ok:
        return png
    stl = render_stl(scad, basename)
    return RenderOutcome(
        ok=stl.ok,
        png_bytes=png.png_bytes,
        stl_bytes=stl.stl_bytes,
        message=stl.message,
    )


def render_png_file(scad_path: str, px: int | None = None) -> RenderOutcome:
    """Render a PNG from an on-disk .scad file (e.g. an assembly wrapper).
    No string-based validation — the file may legitimately use use<>.
    """
    px = px or settings.RENDER_PX
    if _render_url():
        # Read file and forward source text to remote service
        try:
            scad = Path(scad_path).read_text(encoding="utf-8")
        except OSError as exc:
            return RenderOutcome(False, message=f"cannot read scad file: {exc}")
        return _remote_render(scad, "png", px)
    prep = _prepare()
    if isinstance(prep, RenderOutcome):
        return prep
    binary, work = prep
    try:
        png = work / "out.png"
        rc, log = _invoke(binary, [
            "-o", str(png),
            f"--imgsize={px},{px}",
            "--colorscheme=Tomorrow Night",
            "--autocenter", "--viewall",
            scad_path,
        ])
        if rc != 0 or not png.exists():
            return RenderOutcome(False, message=f"PNG render failed:\n{log}")
        return RenderOutcome(ok=True, png_bytes=png.read_bytes())
    finally:
        _cleanup(work)


def render_stl_file(scad_path: str) -> RenderOutcome:
    """Export STL from an on-disk .scad file (e.g. an assembly wrapper)."""
    if _render_url():
        try:
            scad = Path(scad_path).read_text(encoding="utf-8")
        except OSError as exc:
            return RenderOutcome(False, message=f"cannot read scad file: {exc}")
        return _remote_render(scad, "stl")
    prep = _prepare()
    if isinstance(prep, RenderOutcome):
        return prep
    binary, work = prep
    try:
        stl = work / "out.stl"
        rc, log = _invoke(binary, ["-o", str(stl), scad_path])
        if rc != 0 or not stl.exists():
            return RenderOutcome(False, message=f"STL export failed:\n{log}")
        return RenderOutcome(ok=True, stl_bytes=stl.read_bytes())
    finally:
        _cleanup(work)
