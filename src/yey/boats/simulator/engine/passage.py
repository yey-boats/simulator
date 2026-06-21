# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Random-passage generation: pick a navigable destination ~40-60 nM away and
autoroute a navigable path to it.

Used by the "random passages" demo mode (runner): when the boat nears its
destination the runner asks for a fresh passage, the navigable polyline is
adopted as the active route, and the route is pushed to SignalK. This keeps the
autorouter continuously exercised at the leg size where it works well, and the
SignalK course updates as each passage is laid.

Pure and grid-driven (no engine/asyncio deps) so it can run in a worker thread
against a private GeoGrid and is unit-testable with a fake grid.
"""
from __future__ import annotations

import math
import random
from typing import Any

from yey.boats.simulator.engine.autoroute import AutorouteConfig, autoroute_leg
from yey.boats.simulator.engine.route import Waypoint, dead_reckon, haversine_nm

# A destination must sit in open water at least this deep (m), so passages start
# and end offshore rather than in a harbour/shoal the boat could not reach.
DEST_MIN_DEPTH_M = 12.0


def destination_point(lat: float, lon: float, bearing_deg: float,
                      dist_nm: float) -> tuple[float, float]:
    """Great-circle destination `dist_nm` from (lat,lon) on `bearing_deg`."""
    # dead_reckon advances sog_kts for dt_s seconds; sog*dt/3600 = dist_nm.
    return dead_reckon(lat, lon, dist_nm * 3600.0, bearing_deg, 1.0)


def _sample_line(a: tuple[float, float], b: tuple[float, float],
                 step_deg: float) -> list[tuple[float, float]]:
    n = max(2, int(math.hypot(a[0] - b[0], a[1] - b[1]) / step_deg) + 1)
    return [(a[0] + (b[0] - a[0]) * k / (n - 1),
             a[1] + (b[1] - a[1]) * k / (n - 1)) for k in range(n)]


def _path_is_navigable(grid: Any, leg: list[tuple[float, float]],
                       cfg: AutorouteConfig) -> bool:
    """Every point along the polyline is at least `hard_min_m` deep."""
    cell = grid._cell
    for a, b in zip(leg, leg[1:]):
        pts = _sample_line(a, b, cell)
        grid.sample(pts)                       # off-tick fetch (thread context)
        for lat, lon in pts:
            if grid.depth_at(lat, lon) < cfg.hard_min_m:
                return False
    return True


def make_passage(start_lat: float, start_lon: float, grid: Any,
                 cfg: AutorouteConfig, min_nm: float = 40.0, max_nm: float = 60.0,
                 rng: random.Random | None = None, tries: int = 40) -> list | None:
    """Pick a navigable destination `min_nm`..`max_nm` away and autoroute to it.

    Returns a Waypoint list [START, …auto…, DEST] for a clear (fully navigable)
    passage, or None if no clear destination was found within `tries` attempts.
    Runs against `grid` synchronously (fetches as needed) — call from a worker
    thread, not the event loop.
    """
    rng = rng or random.Random()
    for _ in range(tries):
        bearing = rng.uniform(0.0, 360.0)
        dist = rng.uniform(min_nm, max_nm)
        dlat, dlon = destination_point(start_lat, start_lon, bearing, dist)
        grid.sample([(dlat, dlon)])
        if grid.depth_at(dlat, dlon) < DEST_MIN_DEPTH_M:
            continue                           # destination on land / too shoal
        leg = autoroute_leg(grid, (start_lat, start_lon), (dlat, dlon), cfg)
        if not _path_is_navigable(grid, leg, cfg):
            continue                           # straight fallback crosses land/shoal
        wps = [Waypoint(name="PASSAGE-START", lat=start_lat, lon=start_lon,
                        marina="", berth_heading=bearing, refill_water=False,
                        refill_fuel=False, pump_out_bw=False)]
        for i, (lat, lon) in enumerate(leg[1:-1]):
            wps.append(Waypoint(name=f"auto-{i}", lat=lat, lon=lon, marina="",
                                berth_heading=0.0, refill_water=False,
                                refill_fuel=False, pump_out_bw=False))
        wps.append(Waypoint(name=f"DEST-{int(round(dist))}nm-{int(bearing):03d}",
                            lat=dlat, lon=dlon, marina="", berth_heading=0.0,
                            refill_water=False, refill_fuel=False, pump_out_bw=False))
        return wps
    return None


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_nm(lat1, lon1, lat2, lon2)
