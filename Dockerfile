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
# The GEBCO depth cache is built lazily on first run into DATA_DIR=/data (mount a
# volume to persist it). If the first run is offline the sim degrades to a default
# depth and retries caching on a later run.
ENTRYPOINT ["yey-boats-sim"]
