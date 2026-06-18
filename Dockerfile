# syntax=docker/dockerfile:1

# ── Stage 1: build the React/Vite SPA ──────────────────────────────────────
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
# Emit into /web/dist (not the default ../src/... which doesn't exist here)
RUN VITE_OUT_DIR=/web/dist npm run build

# ── Stage 2: build the Python wheel ────────────────────────────────────────
FROM python:3.12-slim AS build
WORKDIR /build
RUN pip install --no-cache-dir build hatchling
COPY . .
# Bring in the built SPA so hatch force-include can package it
COPY --from=web /web/dist ./src/yey/boats/simulator/web/static
RUN python -m build --wheel --outdir /dist

# ── Stage 3: lean runtime image ────────────────────────────────────────────
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    SINK=signalk \
    DATA_DIR=/data \
    SIM_WEB_HOST=0.0.0.0
RUN useradd -u 1000 -m sim && mkdir -p /data && chown sim:sim /data
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
USER sim
EXPOSE 8080
VOLUME ["/data"]
# The GEBCO depth cache is built lazily on first run into DATA_DIR=/data (mount a
# volume to persist it). If the first run is offline the sim degrades to a default
# depth and retries caching on a later run.
ENTRYPOINT ["yey-boats-sim"]
