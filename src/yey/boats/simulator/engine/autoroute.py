# src/yey/boats/simulator/engine/autoroute.py
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Land/shallow-avoiding autorouting over a GeoGrid.

A* over ~2 km navigable cells with a tiered depth-cost model: never traverse
water shallower than draft+1 m; prefer >=10 m; tolerate 5-10 m and 3.2-5 m
with rising penalties. Falls back to the straight leg (logged) when no path
is found within the bounded search.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]
from yey.boats.simulator.engine.route import haversine_nm  # type: ignore[import]


@dataclass(frozen=True)
class AutorouteConfig:
    hard_min_m: float = 3.2          # draft (2.2) + 1.0
    soft_min_m: float = 5.0
    prefer_m: float = 10.0
    penalty_necessary: float = 25.0  # 3.2-5 m band
    penalty_tolerated: float = 5.0   # 5-10 m band
    bbox_margin_deg: float = 0.3
    max_cells: int = 8000            # cap on bbox pre-sample size
    max_nodes: int = 20000           # cap on A* expansions


def depth_penalty(depth_m: float, cfg: AutorouteConfig) -> float:
    if depth_m < cfg.hard_min_m:
        return math.inf
    if depth_m < cfg.soft_min_m:
        return cfg.penalty_necessary
    if depth_m < cfg.prefer_m:
        return cfg.penalty_tolerated
    return 1.0


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return haversine_nm(a[0], a[1], b[0], b[1]) * 1.852  # nm -> km


def _line_points(a, b, step_deg):
    n = max(2, int(_deg_dist(a, b) / step_deg) + 1)
    return [(a[0] + (b[0] - a[0]) * k / (n - 1),
             a[1] + (b[1] - a[1]) * k / (n - 1)) for k in range(n)]


def _deg_dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def autoroute_leg(grid: GeoGrid, a: tuple[float, float], b: tuple[float, float],
                  cfg: AutorouteConfig) -> list[tuple[float, float]]:
    cell = grid._cell  # degrees per cell

    # Fast path: straight leg if every sampled point is deep (>= prefer).
    probe = _line_points(a, b, cell)
    grid.sample(probe)
    if all(grid.depth_at(lat, lon) >= cfg.prefer_m for lat, lon in probe):
        return [a, b]

    # Pre-sample the inflated bbox once (bounded), then A* in-memory.
    m = cfg.bbox_margin_deg
    lat_lo, lat_hi = min(a[0], b[0]) - m, max(a[0], b[0]) + m
    lon_lo, lon_hi = min(a[1], b[1]) - m, max(a[1], b[1]) + m
    ci0, cj0 = grid._cell_of(lat_lo, lon_lo)
    ci1, cj1 = grid._cell_of(lat_hi, lon_hi)
    n_cells = (ci1 - ci0 + 1) * (cj1 - cj0 + 1)
    if n_cells > cfg.max_cells:
        print(f"[autoroute] bbox too large ({n_cells} cells) {a}->{b}; "
              f"straight leg", flush=True)  # noqa: T201
        return [a, b]
    centers = [( (ci + 0.5) * cell, (cj + 0.5) * cell )
               for ci in range(ci0, ci1 + 1) for cj in range(cj0, cj1 + 1)]
    grid.sample(centers)

    start, goal = grid._cell_of(*a), grid._cell_of(*b)

    def center(c):
        return ((c[0] + 0.5) * cell, (c[1] + 0.5) * cell)

    def passable(c) -> bool:
        if c in (start, goal):
            return True            # always allow leaving/entering the endpoints
        lat, lon = center(c)
        return grid.depth_at(lat, lon) >= cfg.hard_min_m

    def step_cost(c) -> float:
        if c in (start, goal):
            return 1.0             # endpoint cells always crossable
        lat, lon = center(c)
        return depth_penalty(grid.depth_at(lat, lon), cfg)

    # A* over 8-connected cells.
    open_heap = [(0.0, start)]
    g_cost = {start: 0.0}
    came = {}
    expanded = 0
    found = False
    while open_heap:
        _f, cur = heapq.heappop(open_heap)
        if cur == goal:
            found = True
            break
        expanded += 1
        if expanded > cfg.max_nodes:
            break
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                nb = (cur[0] + di, cur[1] + dj)
                if not (ci0 <= nb[0] <= ci1 and cj0 <= nb[1] <= cj1):
                    continue
                if not passable(nb):
                    continue
                tentative = g_cost[cur] + _km(center(cur), center(nb)) * step_cost(nb)
                if tentative < g_cost.get(nb, math.inf):
                    g_cost[nb] = tentative
                    came[nb] = cur
                    h = _km(center(nb), b)        # admissible (min penalty 1.0)
                    heapq.heappush(open_heap, (tentative + h, nb))

    if not found:
        print(f"[autoroute] no path within bounds {a}->{b}; straight leg", flush=True)  # noqa: T201
        return [a, b]

    # Reconstruct cell path -> centers, then simplify collinear runs.
    cells = [goal]
    while cells[-1] != start:
        cells.append(came[cells[-1]])
    cells.reverse()
    pts = [a] + [center(c) for c in cells[1:-1]] + [b]
    return _simplify(pts)


def _simplify(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop points that lie on a near-straight run (collinear pruning)."""
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        ax, ay = out[-1]
        bx, by = pts[i]
        cx, cy = pts[i + 1]
        cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(cross) > 1e-9:        # not collinear -> keep the vertex
            out.append(pts[i])
    out.append(pts[-1])
    return out
