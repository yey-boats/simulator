# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Lightweight, self-hosted bathymetry server (OpenTopoData-compatible).

Loads a regional GEBCO 2020 grid once (from a persisted cache, else fetched
from NOAA CoastWatch ERDDAP — a single strided bbox subset, no per-point
quota), holds it in memory, and answers the subset of the OpenTopoData API the
simulator's GeoGrid uses:

    GET /v1/<dataset>?locations=LAT,LON|LAT,LON|...
    -> {"status":"OK","results":[{"elevation":<m|null>,"location":{"lat":..,"lng":..}}, ...]}

elevation is metres (negative below sea level), GEBCO convention. Stdlib only —
no GDAL, no rasterio — so the image is tiny and runs on arm64. Designed to sit
next to signalk-server on the lab host so the sim can autoroute the whole route
corridor without hitting the public OpenTopoData rate limit.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# Region + resolution (env-overridable). Defaults cover the Adriatic + Ionian
# operating area at ~0.0208 deg (~2.3 km), matching the sim's 0.02 deg cells.
LAT_MIN = float(os.environ.get("BATHY_LAT_MIN", "36.0"))
LAT_MAX = float(os.environ.get("BATHY_LAT_MAX", "46.0"))
LON_MIN = float(os.environ.get("BATHY_LON_MIN", "12.0"))
LON_MAX = float(os.environ.get("BATHY_LON_MAX", "20.0"))
STRIDE = int(os.environ.get("BATHY_STRIDE", "5"))  # ERDDAP index stride (GEBCO node = 1/240 deg)
PORT = int(os.environ.get("BATHY_PORT", "8089"))
CACHE_PATH = os.environ.get("BATHY_CACHE", "/data/bathy_grid.json")
ERDDAP = os.environ.get(
    "BATHY_ERDDAP",
    "https://coastwatch.pfeg.noaa.gov/erddap/griddap/GEBCO_2020.csv")

NODE_DEG = 1.0 / 240.0          # GEBCO 2020 grid spacing
STEP_DEG = STRIDE * NODE_DEG    # effective cell size of our subset


def _erddap_url(lat0: float, lat1: float) -> str:
    # elevation[(lat0):stride:(lat1)][(lonmin):stride:(lonmax)]
    sel = (f"elevation%5B({lat0:.5f}):{STRIDE}:({lat1:.5f})%5D"
           f"%5B({LON_MIN:.5f}):{STRIDE}:({LON_MAX:.5f})%5D")
    return f"{ERDDAP}?{sel}"


def _fetch_band(lat0: float, lat1: float) -> list[tuple[float, float, float]]:
    url = _erddap_url(lat0, lat1)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310
                text = r.read().decode("utf-8", "ignore")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[bathy] ERDDAP band {lat0:.2f}-{lat1:.2f} attempt {attempt}: {exc!r}",
                  flush=True)
            time.sleep(3 * (attempt + 1))
    else:
        raise RuntimeError(f"ERDDAP fetch failed for band {lat0}-{lat1}")
    rows = []
    for line in text.splitlines()[2:]:        # skip header + units rows
        parts = line.split(",")
        if len(parts) != 3:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
        except ValueError:
            continue
    return rows


def _cell(lat: float, lon: float) -> tuple[int, int]:
    """Integer cell index on the subset grid (nearest node)."""
    return (round((lat - LAT_MIN) / STEP_DEG), round((lon - LON_MIN) / STEP_DEG))


def _build_grid() -> dict[str, float]:
    """Load the grid from cache, else fetch the region from ERDDAP (in lat
    bands) and persist it. Keys are "i,j" cell indices; values are elevation m."""
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH) as f:
                g = json.load(f)
            print(f"[bathy] loaded {len(g)} cells from cache {CACHE_PATH}", flush=True)
            return g
        except (OSError, ValueError) as exc:
            print(f"[bathy] cache unreadable ({exc!r}); refetching", flush=True)

    print(f"[bathy] fetching GEBCO {LAT_MIN}-{LAT_MAX}N {LON_MIN}-{LON_MAX}E "
          f"(stride {STRIDE}) from ERDDAP...", flush=True)
    grid: dict[str, float] = {}
    band = 2.0
    lat = LAT_MIN
    while lat < LAT_MAX:
        hi = min(lat + band, LAT_MAX)
        for la, lo, elev in _fetch_band(lat, hi):
            i, j = _cell(la, lo)
            grid[f"{i},{j}"] = elev
        print(f"[bathy]   band {lat:.1f}-{hi:.1f}: {len(grid)} cells so far", flush=True)
        lat = hi
        time.sleep(1.0)            # be polite to ERDDAP
    try:
        os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump(grid, f)
        print(f"[bathy] cached {len(grid)} cells to {CACHE_PATH}", flush=True)
    except OSError as exc:
        print(f"[bathy] cache write failed (non-fatal): {exc!r}", flush=True)
    return grid


GRID: dict[str, float] = {}


def _lookup(lat: float, lon: float):
    i, j = _cell(lat, lon)
    # Exact cell, else the NEAREST existing neighbour (orthogonal before
    # diagonal) — for coast/grid edges where the exact cell is missing.
    for di, dj in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1),
                   (-1, -1), (-1, 1), (1, -1), (1, 1)):
        nv = GRID.get(f"{i + di},{j + dj}")
        if nv is not None:
            return nv
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):       # quiet default logging
        pass

    def _send(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"status": "OK", "cells": len(GRID)})
            return
        if "/v1/" not in parsed.path:
            self._send(404, {"status": "NOT_FOUND"})
            return
        qs = parse_qs(parsed.query)
        locs = qs.get("locations", [""])[0]
        results = []
        for pair in locs.split("|"):
            pair = pair.strip()
            if not pair:
                continue
            try:
                lat_s, lon_s = pair.split(",")
                lat, lon = float(lat_s), float(lon_s)
            except ValueError:
                results.append({"elevation": None, "location": {"lat": None, "lng": None}})
                continue
            results.append({"elevation": _lookup(lat, lon),
                            "location": {"lat": lat, "lng": lon}})
        self._send(200, {"status": "OK", "results": results})


def main() -> None:
    global GRID
    GRID = _build_grid()
    if not GRID:
        raise SystemExit("[bathy] empty grid — refusing to start")
    print(f"[bathy] serving {len(GRID)} cells on :{PORT} "
          f"(step ~{STEP_DEG:.4f} deg)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()  # noqa: S104


if __name__ == "__main__":
    main()
