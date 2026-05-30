"""
OpenSCAD render service — runs on Fly.io.
Accepts SCAD source, produces PNG preview or STL mesh.

POST /render
  Header: Authorization: Bearer <RENDER_TOKEN>
  Form field: scad=<source text>
  Query:  format=png|stl   (default: png)
          px=640            (PNG dimensions, ignored for STL)

GET /health → {"status":"ok"}
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, Form, Header, HTTPException, Query
from fastapi.responses import Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("render_service")

app = FastAPI(title="scadbot-render", docs_url=None, redoc_url=None)

RENDER_TOKEN  = os.environ.get("RENDER_TOKEN", "")
SCAD_BIN      = os.environ.get("SCAD_BIN", "openscad")
RENDER_TIMEOUT = int(os.environ.get("RENDER_TIMEOUT", "120"))

_PNG_FLAGS = ["--colorscheme=Tomorrow Night", "--autocenter", "--viewall"]


def _auth(authorization: str | None) -> None:
    if not RENDER_TOKEN:
        return  # open in dev; always set token in production
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing Authorization header")
    if authorization.removeprefix("Bearer ") != RENDER_TOKEN:
        raise HTTPException(403, "invalid token")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "binary": SCAD_BIN}


@app.post("/render")
def render(
    scad: str = Form(...),
    format: str  = Query("png", pattern="^(png|stl)$"),
    px: int      = Query(640, ge=64, le=2048),
    authorization: str | None = Header(None),
) -> Response:
    _auth(authorization)

    with tempfile.TemporaryDirectory(prefix="scad_") as tmp:
        src = Path(tmp) / "model.scad"
        out = Path(tmp) / f"model.{format}"
        src.write_text(scad, encoding="utf-8")

        if format == "png":
            args = [
                SCAD_BIN, "-o", str(out),
                f"--imgsize={px},{px}",
                *_PNG_FLAGS,
                str(src),
            ]
        else:
            args = [SCAD_BIN, "-o", str(out), str(src)]

        logger.info("render start format=%s px=%d scad_len=%d", format, px, len(scad))
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=RENDER_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, f"OpenSCAD timed out after {RENDER_TIMEOUT}s")

        if proc.returncode != 0 or not out.exists():
            err = (proc.stderr or proc.stdout or "")[:1000]
            logger.warning("render failed rc=%d: %s", proc.returncode, err)
            raise HTTPException(422, f"OpenSCAD error:\n{err}")

        data = out.read_bytes()
        logger.info("render ok %d bytes", len(data))

    media = "image/png" if format == "png" else "model/stl"
    return Response(content=data, media_type=media)
