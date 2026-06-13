# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
WORKDIR /build
RUN pip install --no-cache-dir build hatchling
COPY . .
RUN python -m build --wheel --outdir /dist

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    SINK=signalk \
    DATA_DIR=/data
RUN useradd -u 1000 -m sim && mkdir -p /data && chown sim:sim /data
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
USER sim
VOLUME ["/data"]
# Pre-warm the GEBCO depth cache at build time so the board doesn't pay the
# ~30s first-run fetch (cache lands in DATA_DIR=/data; mount a volume to persist).
ENTRYPOINT ["yey-boats-sim"]
