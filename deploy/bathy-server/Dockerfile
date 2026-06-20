# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Tiny stdlib-only bathymetry server (OpenTopoData-compatible) for the lab.
# No GDAL / rasterio — loads a regional GEBCO grid from NOAA ERDDAP on first
# boot and caches it to /data. Runs on arm64.
FROM python:3.12-alpine

WORKDIR /app
COPY server.py /app/server.py

# Region/resolution + port are overridable via -e at run time (see server.py).
EXPOSE 8089
ENV BATHY_CACHE=/data/bathy_grid.json
VOLUME ["/data"]

# Use 127.0.0.1 (IPv4): the server binds 0.0.0.0 only, and `localhost` resolves
# to ::1 first under --network host, which would falsely report unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=20 \
  CMD wget -qO- http://127.0.0.1:8089/health || exit 1

ENTRYPOINT ["python3", "-u", "/app/server.py"]
