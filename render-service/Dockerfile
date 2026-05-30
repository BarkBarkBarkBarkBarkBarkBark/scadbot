# openscad/trixie has built-in EGL — no xvfb needed for PNG rendering
FROM openscad/openscad:trixie

# Add Python on top of the OpenSCAD image
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /app/.venv \
    && /app/.venv/bin/pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV PATH="/app/.venv/bin:$PATH"
ENV SCAD_BIN="openscad"
ENV RENDER_TIMEOUT="120"

EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
