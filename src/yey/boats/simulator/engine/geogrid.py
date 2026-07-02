# src/yey/boats/simulator/engine/geogrid.py
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Lazy, persistent GEBCO bathymetry grid.

Maps any (lat, lon) to depth-below-surface (m) and land/water, fetching and
caching GEBCO 2020 elevation cells on demand via OpenTopoData. depth_at() is
non-blocking (safe to call every tick); sample() does synchronous batched
fetches for deliberate off-tick work (autorouting); fetch_loop() drains the
per-tick miss queue in the background.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Callable, Iterable

import httpx  # type: ignore[import]

CELL_DEG = 0.02
FALLBACK_DEPTH_M = 50.0
_OPENTOPO_URL = "https://api.opentopodata.org/v1/gebco2020"

# Fetcher: given [(lat,lon)...] returns elevations in metres
# (negative = below sea level, per GEBCO).
Fetcher = Callable[[list[tuple[float, float]]], list[float]]


def _opentopo_fetch(points: list[tuple[float, float]]) -> list[float]:
    # GEOGRID_API_URL lets the lab point at a self-hosted OpenTopoData-compatible
    # server (e.g. deploy/bathy-server) to avoid the public per-second/daily
    # quota. The 1.1 s inter-batch sleep is only needed for the public endpoint.
    base = os.environ.get("GEOGRID_API_URL", _OPENTOPO_URL)
    is_public = base == _OPENTOPO_URL
    out: list[float] = []
    for i in range(0, len(points), 100):
        batch = points[i:i + 100]
        locs = "|".join(f"{lat:.5f},{lon:.5f}" for lat, lon in batch)
        resp = httpx.get(f"{base}?locations={locs}", timeout=30)
        resp.raise_for_status()
        for r in resp.json()["results"]:
            out.append(float(r.get("elevation") or 0.0))
        if is_public and i + 100 < len(points):
            time.sleep(1.1)  # OpenTopoData public rate limit
    return out


class GeoGrid:
    def __init__(self, cache_path: Path | None = None,
                 fetcher: Fetcher = _opentopo_fetch,
                 cell_deg: float = CELL_DEG,
                 fallback_depth_m: float = FALLBACK_DEPTH_M) -> None:
        self._cache_path = Path(cache_path) if cache_path else None
        self._fetch = fetcher
        self._cell = cell_deg
        self._fallback = fallback_depth_m
        self._elev: dict[tuple[int, int], float] = {}
        self._misses: set[tuple[int, int]] = set()
        if self._cache_path and self._cache_path.exists():
            self._load()

    # ── cell math (floor-based corner indices for bilinear) ──────────────
    def _cell_of(self, lat: float, lon: float) -> tuple[int, int]:
        return (math.floor(lat / self._cell), math.floor(lon / self._cell))

    def _corner(self, c: tuple[int, int]) -> tuple[float, float]:
        return (c[0] * self._cell, c[1] * self._cell)

    # ── persistence ──────────────────────────────────────────────────────
    def _load(self) -> None:
        raw = json.loads(self._cache_path.read_text())
        self._elev = {(int(k.split(",")[0]), int(k.split(",")[1])): float(v)
                      for k, v in raw.items()}

    def save(self) -> None:
        if not self._cache_path:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        raw = {f"{a},{b}": v for (a, b), v in self._elev.items()}
        self._cache_path.write_text(json.dumps(raw))

    # ── elevation / depth (non-blocking) ─────────────────────────────────
    def elevation_at(self, lat: float, lon: float) -> float:
        c = self._cell_of(lat, lon)                 # lower-left corner cell
        c00, c10 = c, (c[0] + 1, c[1])
        c01, c11 = (c[0], c[1] + 1), (c[0] + 1, c[1] + 1)
        vals = [self._elev.get(k) for k in (c00, c10, c01, c11)]
        if all(v is not None for v in vals):
            lat0, lon0 = self._corner(c00)
            u = (lat - lat0) / self._cell           # 0..1 across latitude
            t = (lon - lon0) / self._cell           # 0..1 across longitude
            v00, v10, v01, v11 = vals               # type: ignore[misc]
            return ((1 - u) * (1 - t) * v00 + u * (1 - t) * v10
                    + (1 - u) * t * v01 + u * t * v11)
        # miss: queue the four corners; return nearest cached / fallback
        for k in (c00, c10, c01, c11):
            if self._elev.get(k) is None:
                self._misses.add(k)
        if self._elev:
            nearest = min(self._elev.keys(),
                          key=lambda k: (k[0] - c[0]) ** 2 + (k[1] - c[1]) ** 2)
            return self._elev[nearest]
        return -self._fallback

    async def fetch_loop(self, interval: float = 1.1, batch: int = 100) -> None:
        import asyncio
        while True:
            if self._misses:
                cells = list(self._misses)[:batch]
                pts = [self._corner(c) for c in cells]
                try:
                    elevs = await asyncio.to_thread(self._fetch, pts)
                    # Materialize the pairing (and let strict=True raise) before
                    # writing anything, so a length mismatch can't leave the
                    # cache partially/misalignedly populated.
                    pairs = list(zip(cells, elevs, strict=True))
                    for c, e in pairs:
                        self._elev[c] = e
                        self._misses.discard(c)
                    self.save()
                except Exception as exc:  # noqa: BLE001
                    print(f"[geogrid] background fetch failed: {exc!r}", flush=True)  # noqa: T201
            await asyncio.sleep(interval)

    def depth_at(self, lat: float, lon: float) -> float:
        return max(0.0, -self.elevation_at(lat, lon))

    def is_land(self, lat: float, lon: float) -> bool:
        return self.elevation_at(lat, lon) >= 0.0

    # ── synchronous batched sampling (off-tick: autorouting) ─────────────
    def sample(self, points: Iterable[tuple[float, float]]) -> None:
        want: dict[tuple[int, int], tuple[float, float]] = {}
        for lat, lon in points:
            c = self._cell_of(lat, lon)
            if c not in self._elev and c not in want:
                want[c] = self._corner(c)
        if not want:
            return
        cells = list(want.keys())
        elevs = self._fetch([want[c] for c in cells])
        # See fetch_loop(): materialize before writing so a length mismatch
        # raises without corrupting the cache.
        pairs = list(zip(cells, elevs, strict=True))
        for c, e in pairs:
            self._elev[c] = e
            self._misses.discard(c)
