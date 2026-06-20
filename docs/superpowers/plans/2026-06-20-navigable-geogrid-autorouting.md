# Navigable geo-grid + autorouting + realistic depth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Source boat depth from real GEBCO bathymetry at the current location, and auto-insert land/shallow-avoiding navigable legs between the route planner's waypoints.

**Architecture:** A lazy, persistent `GeoGrid` samples GEBCO 2020 elevation per ~2 km cell on demand (one dataset gives both depth = −elevation and land = elevation ≥ 0). A weighted A* autorouter consumes the grid to replace straight legs that cross land/shallow water with navigable polylines. The navigator reads depth from the grid; the SignalK writer derives `belowKeel`/`belowTransducer` from depth-below-surface.

**Tech Stack:** Python 3.13, `httpx` (already a dep), `asyncio`, `pytest` + `pytest-asyncio`. Data: OpenTopoData `gebco2020` HTTP API.

## Global Constraints

- License header on every new file: `# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0`
- SI units on the wire: depth metres, angles radians (unchanged).
- `depth_at()` is called every engine tick and MUST NOT block on network.
- Lint: `ruff check` must pass on all changed files.
- Tests run with `PYTHONPATH=src python -m pytest`; package uses a `src/` layout.
- GEBCO cell size `CELL_DEG = 0.02` (~2 km). Boat draft `2.2 m`.
- Routing depth bands: impassable `< 3.2 m` (draft+1); prefer `≥ 10 m` (×1); tolerate `5–10 m` (×5); necessary-only `3.2–5 m` (×25).
- No live network in the default test run; the real-GEBCO fixture is downloaded once behind `YEYBOATS_REFRESH_GEOGRID_FIXTURE=1` and committed.

---

### Task 1: `GeoGrid` core — cells, cache, non-blocking depth

**Files:**
- Create: `src/yey/boats/simulator/engine/geogrid.py`
- Test: `tests/test_geogrid.py`

**Interfaces:**
- Produces:
  - `Fetcher = Callable[[list[tuple[float,float]]], list[float]]` (points → elevations m, negative below sea level)
  - `class GeoGrid(cache_path: Path|None=None, fetcher: Fetcher=_opentopo_fetch, cell_deg: float=0.02, fallback_depth_m: float=50.0)`
  - `GeoGrid.depth_at(lat,lon) -> float` (≥0, non-blocking)
  - `GeoGrid.elevation_at(lat,lon) -> float`
  - `GeoGrid.is_land(lat,lon) -> bool`
  - `GeoGrid._cell_of(lat,lon) -> tuple[int,int]` (floor-based corner index)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_geogrid.py
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from __future__ import annotations

from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]


def _flat_fetcher(elev_m):
    """Fetcher that returns a constant elevation for every requested point."""
    def f(points):
        return [elev_m for _ in points]
    return f


def test_depth_at_uses_fetched_elevation_via_sample():
    g = GeoGrid(fetcher=_flat_fetcher(-30.0), cell_deg=0.02)
    g.sample([(45.0, 13.0)])              # one cell now cached at elev -30
    assert g.depth_at(45.0, 13.0) == 30.0  # depth = -elev
    assert g.is_land(45.0, 13.0) is False


def test_depth_at_miss_returns_fallback_and_queues_without_network():
    calls = {"n": 0}
    def counting(points):
        calls["n"] += 1
        return [-5.0 for _ in points]
    g = GeoGrid(fetcher=counting, cell_deg=0.02, fallback_depth_m=50.0)
    # No sample() yet -> depth_at must NOT call the fetcher (non-blocking).
    assert g.depth_at(10.0, 10.0) == 50.0
    assert calls["n"] == 0
    assert g._cell_of(10.0, 10.0) in g._misses


def test_land_classification_positive_elevation():
    g = GeoGrid(fetcher=_flat_fetcher(12.0), cell_deg=0.02)
    g.sample([(45.5, 13.5)])
    assert g.is_land(45.5, 13.5) is True
    assert g.depth_at(45.5, 13.5) == 0.0   # land => depth clamped to 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_geogrid.py -q`
Expected: FAIL — `ModuleNotFoundError: ...geogrid`.

- [ ] **Step 3: Write minimal implementation**

```python
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
    out: list[float] = []
    for i in range(0, len(points), 100):
        batch = points[i:i + 100]
        locs = "|".join(f"{lat:.5f},{lon:.5f}" for lat, lon in batch)
        resp = httpx.get(f"{_OPENTOPO_URL}?locations={locs}", timeout=30)
        resp.raise_for_status()
        for r in resp.json()["results"]:
            out.append(float(r.get("elevation") or 0.0))
        if i + 100 < len(points):
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
        c = self._cell_of(lat, lon)
        v = self._elev.get(c)
        if v is not None:
            return v
        self._misses.add(c)  # queue for background fetch
        if self._elev:
            nearest = min(self._elev.keys(),
                          key=lambda k: (k[0] - c[0]) ** 2 + (k[1] - c[1]) ** 2)
            return self._elev[nearest]
        return -self._fallback  # fallback elevation => fallback depth

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
        for c, e in zip(cells, elevs):
            self._elev[c] = e
            self._misses.discard(c)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_geogrid.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/yey/boats/simulator/engine/geogrid.py tests/test_geogrid.py
git commit -m "feat(geogrid): lazy GEBCO grid core (non-blocking depth + sample)"
```

---

### Task 2: `GeoGrid` bilinear interp, persistence round-trip, background `fetch_loop`

**Files:**
- Modify: `src/yey/boats/simulator/engine/geogrid.py`
- Test: `tests/test_geogrid.py`

**Interfaces:**
- Produces:
  - `GeoGrid.depth_at` now bilinear-interpolates when the 4 surrounding cells are cached.
  - `GeoGrid.save()` / load round-trip (already partly present).
  - `async GeoGrid.fetch_loop(interval: float = 1.1, batch: int = 100)` — drains `_misses`, persists.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_geogrid.py
import asyncio
from pathlib import Path

import pytest  # type: ignore[import]


def _plane_fetcher(points):
    # elevation varies with lon so bilinear interpolation is observable:
    # elev = -10 - 1000*lon  (deeper as lon grows)
    return [-10.0 - 1000.0 * lon for _lat, lon in points]


def test_bilinear_interpolation_between_cells():
    g = GeoGrid(fetcher=_plane_fetcher, cell_deg=0.02)
    # cache the four corners around (45.01, 13.01)
    g.sample([(45.00, 13.00), (45.00, 13.02), (45.02, 13.00), (45.02, 13.02)])
    d = g.depth_at(45.01, 13.01)
    # exact plane => interpolated depth equals the plane value at that point
    assert d == pytest.approx(10.0 + 1000.0 * 13.01, rel=1e-6)


def test_persistence_round_trip(tmp_path: Path):
    p = tmp_path / "geogrid.json"
    g1 = GeoGrid(cache_path=p, fetcher=lambda pts: [-42.0 for _ in pts], cell_deg=0.02)
    g1.sample([(45.0, 13.0)])
    g1.save()
    g2 = GeoGrid(cache_path=p, fetcher=lambda pts: [0.0 for _ in pts], cell_deg=0.02)
    assert g2.depth_at(45.0, 13.0) == 42.0  # loaded from disk, no fetch


@pytest.mark.asyncio
async def test_fetch_loop_drains_misses():
    g = GeoGrid(fetcher=lambda pts: [-20.0 for _ in pts], cell_deg=0.02)
    g.depth_at(45.0, 13.0)                  # miss -> queued
    assert g._misses
    task = asyncio.create_task(g.fetch_loop(interval=0.01))
    for _ in range(50):
        if not g._misses:
            break
        await asyncio.sleep(0.02)
    task.cancel()
    assert not g._misses
    assert g.depth_at(45.0, 13.0) == 20.0
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python -m pytest tests/test_geogrid.py -q`
Expected: FAIL — bilinear test mismatch (currently nearest-cell) and `fetch_loop` missing.

- [ ] **Step 3: Implement bilinear + fetch_loop**

Replace `elevation_at` with a bilinear version and add `fetch_loop`:

```python
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
                    for c, e in zip(cells, elevs):
                        self._elev[c] = e
                        self._misses.discard(c)
                    self.save()
                except Exception as exc:  # noqa: BLE001
                    print(f"[geogrid] background fetch failed: {exc!r}", flush=True)  # noqa: T201
            await asyncio.sleep(interval)
```

Note: delete the old single-cell `elevation_at` body (the new one above replaces it entirely).

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src python -m pytest tests/test_geogrid.py -q`
Expected: PASS (6 tests). `ruff check src/yey/boats/simulator/engine/geogrid.py` clean.

- [ ] **Step 5: Commit**

```bash
git add src/yey/boats/simulator/engine/geogrid.py tests/test_geogrid.py
git commit -m "feat(geogrid): bilinear interp, persistence, background fetch_loop"
```

---

### Task 3: Config + resources cache path

**Files:**
- Modify: `src/yey/boats/simulator/config.py:17-28` (add fields)
- Modify: `src/yey/boats/simulator/resources.py:48` (add helper)
- Test: `tests/test_config.py` (extend), `tests/test_geogrid.py` (path helper)

**Interfaces:**
- Produces:
  - `Settings.boat_draft_m: float = 2.2`, `Settings.transducer_depth_m: float = 0.6`
  - `resources.geogrid_cache_path(data_dir: Path) -> Path` → `data_dir/geogrid.json`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_geogrid.py
def test_geogrid_cache_path(tmp_path):
    from yey.boats.simulator import resources  # type: ignore[import]
    p = resources.geogrid_cache_path(tmp_path)
    assert p == tmp_path / "geogrid.json"
    assert tmp_path.exists()
```

```python
# append to tests/test_config.py
def test_settings_has_boat_geometry_defaults():
    from yey.boats.simulator.config import Settings  # type: ignore[import]
    s = Settings()
    assert s.boat_draft_m == 2.2
    assert s.transducer_depth_m == 0.6
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python -m pytest tests/test_geogrid.py::test_geogrid_cache_path tests/test_config.py::test_settings_has_boat_geometry_defaults -q`
Expected: FAIL — attribute / function missing.

- [ ] **Step 3: Implement**

In `config.py`, add two fields after `data_dir` (do NOT add to `_PERSIST_KEYS` — these are code-level tuning defaults, not user-persisted config):

```python
    data_dir: Path = field(default_factory=lambda: _DEFAULT_DATA_DIR)
    # Boat geometry (depth derivations + routing draft floor)
    boat_draft_m: float = 2.2
    transducer_depth_m: float = 0.6
```

In `resources.py`, add after `depth_cache_path`:

```python
def geogrid_cache_path(data_dir: Path) -> Path:
    """Path to the lazily-built GEBCO grid cache inside the writable data dir."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "geogrid.json"
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src python -m pytest tests/test_geogrid.py tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yey/boats/simulator/config.py src/yey/boats/simulator/resources.py tests/test_config.py tests/test_geogrid.py
git commit -m "feat(config): boat geometry defaults + geogrid cache path"
```

---

### Task 4: Autorouter — tiered cost + A* + straight fast-path

**Files:**
- Create: `src/yey/boats/simulator/engine/autoroute.py`
- Test: `tests/test_autoroute.py`

**Interfaces:**
- Consumes: `GeoGrid` (uses `.depth_at`, `.sample`, `._cell_of`, `._corner`, `._cell`).
- Produces:
  - `@dataclass AutorouteConfig(hard_min_m=3.2, soft_min_m=5.0, prefer_m=10.0, penalty_necessary=25.0, penalty_tolerated=5.0, bbox_margin_deg=0.3, max_cells=8000, max_nodes=20000)`
  - `depth_penalty(depth_m: float, cfg: AutorouteConfig) -> float`
  - `autoroute_leg(grid, a: tuple[float,float], b: tuple[float,float], cfg: AutorouteConfig) -> list[tuple[float,float]]` (returns `[a, ...interior..., b]`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_autoroute.py
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from __future__ import annotations

from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]
from yey.boats.simulator.engine.autoroute import (  # type: ignore[import]
    AutorouteConfig, autoroute_leg, depth_penalty)


def _barrier_fetcher(points):
    """Deep water (-50 m) everywhere except a vertical land wall at
    lon in [13.00, 13.02) spanning lat [44.90, 45.10], leaving a gap south of
    lat 44.90 so a detour exists. Land => elevation +10 m."""
    out = []
    for lat, lon in points:
        if 13.00 <= lon < 13.02 and 44.90 <= lat <= 45.10:
            out.append(10.0)      # land barrier
        else:
            out.append(-50.0)     # deep water
    return out


def test_depth_penalty_bands():
    cfg = AutorouteConfig()
    assert depth_penalty(2.0, cfg) == float("inf")   # < hard_min
    assert depth_penalty(4.0, cfg) == 25.0           # 3.2-5
    assert depth_penalty(7.0, cfg) == 5.0            # 5-10
    assert depth_penalty(20.0, cfg) == 1.0           # >= prefer


def test_straight_leg_when_all_deep():
    g = GeoGrid(fetcher=lambda pts: [-50.0 for _ in pts], cell_deg=0.02)
    path = autoroute_leg(g, (45.0, 12.50), (45.0, 12.80), AutorouteConfig())
    assert path == [(45.0, 12.50), (45.0, 12.80)]    # no detour


def test_routes_around_land_barrier():
    g = GeoGrid(fetcher=_barrier_fetcher, cell_deg=0.02)
    a, b = (45.0, 12.95), (45.0, 13.10)              # straight line crosses the wall
    path = autoroute_leg(g, a, b, AutorouteConfig())
    assert path[0] == a and path[-1] == b
    assert len(path) > 2                              # detour inserted
    # every interior point is navigable (not on the land wall)
    for lat, lon in path:
        assert not g.is_land(lat, lon)


def test_fallback_to_straight_on_node_cap():
    g = GeoGrid(fetcher=_barrier_fetcher, cell_deg=0.02)
    cfg = AutorouteConfig(max_nodes=1)               # force the cap
    a, b = (45.0, 12.95), (45.0, 13.10)
    path = autoroute_leg(g, a, b, cfg)
    assert path == [a, b]                             # logged + straight fallback
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python -m pytest tests/test_autoroute.py -q`
Expected: FAIL — `ModuleNotFoundError: ...autoroute`.

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src python -m pytest tests/test_autoroute.py -q`
Expected: PASS (4 tests). `ruff check src/yey/boats/simulator/engine/autoroute.py` clean.

- [ ] **Step 5: Commit**

```bash
git add src/yey/boats/simulator/engine/autoroute.py tests/test_autoroute.py
git commit -m "feat(autoroute): tiered-cost A* navigable leg routing"
```

---

### Task 5: Expand the route's legs through the autorouter

**Files:**
- Modify: `src/yey/boats/simulator/engine/route.py` (add `autoroute_legs`)
- Test: `tests/test_autoroute.py` (extend)

**Interfaces:**
- Consumes: `autoroute_leg`, `AutorouteConfig`, `GeoGrid`, `Route.waypoints` (each has `.lat`, `.lon`, `.name`), `Route.from_waypoint_dicts`.
- Produces: `Route.autoroute_legs(grid: GeoGrid, cfg: AutorouteConfig) -> int` — rebuilds `self.waypoints` as the navigable polyline (planner waypoints preserved as vertices; interior points inserted as synthetic waypoints). Returns the number of inserted interior points.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_autoroute.py
from yey.boats.simulator.engine.route import Route, Waypoint  # type: ignore[import]


def _two_wp_route(a, b):
    r = Route()
    r.waypoints = [Waypoint(name="A", lat=a[0], lon=a[1], berth_heading=0.0),
                   Waypoint(name="B", lat=b[0], lon=b[1], berth_heading=0.0)]
    return r


def test_autoroute_legs_inserts_interior_points_around_land():
    g = GeoGrid(fetcher=_barrier_fetcher, cell_deg=0.02)
    r = _two_wp_route((45.0, 12.95), (45.0, 13.10))
    inserted = r.autoroute_legs(g, AutorouteConfig())
    assert inserted >= 1
    names = [w.name for w in r.waypoints]
    assert names[0] == "A" and names[-1] == "B"          # endpoints preserved
    for w in r.waypoints:
        assert not g.is_land(w.lat, w.lon)               # all navigable
```

Check `Waypoint`'s real field names first: `grep -n "class Waypoint" -A8 src/yey/boats/simulator/engine/route.py`. If the constructor differs (e.g. no `berth_heading` default), adjust the test's `Waypoint(...)` call to match the actual dataclass.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python -m pytest tests/test_autoroute.py::test_autoroute_legs_inserts_interior_points_around_land -q`
Expected: FAIL — `Route` has no `autoroute_legs`.

- [ ] **Step 3: Implement**

Add to `route.py` inside `class Route` (import autoroute lazily inside the method to avoid a circular import, since `autoroute.py` imports from `route.py`):

```python
    def autoroute_legs(self, grid, cfg) -> int:
        """Replace each straight planner leg with a navigable polyline that
        avoids land/shallow water. Planner waypoints are preserved as vertices;
        interior points are inserted as synthetic ('auto') waypoints. Returns
        the count of inserted interior points."""
        from yey.boats.simulator.engine.autoroute import autoroute_leg
        if len(self.waypoints) < 2:
            return 0
        planner = list(self.waypoints)
        out: list = [planner[0]]
        inserted = 0
        for i in range(len(planner) - 1):
            a, b = planner[i], planner[i + 1]
            leg = autoroute_leg(grid, (a.lat, a.lon), (b.lat, b.lon), cfg)
            for lat, lon in leg[1:-1]:                   # interior points only
                out.append(Waypoint(name=f"auto-{i}-{inserted}",
                                     lat=lat, lon=lon, berth_heading=0.0))
                inserted += 1
            out.append(b)                                # keep planner endpoint
        self.waypoints = out
        return inserted
```

If `Waypoint` has required fields beyond `name/lat/lon/berth_heading`, fill them with sensible defaults matching the dataclass (inspect with the grep from Step 1).

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src python -m pytest tests/test_autoroute.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/yey/boats/simulator/engine/route.py tests/test_autoroute.py
git commit -m "feat(route): autoroute_legs expands planner legs into navigable polylines"
```

---

### Task 6: Wire the grid into navigator, engine, and runner

**Files:**
- Modify: `src/yey/boats/simulator/engine/navigator.py:94-99,210-214`
- Modify: `src/yey/boats/simulator/engine/engine.py:43-50`
- Modify: `src/yey/boats/simulator/engine/runner.py:55-150`
- Test: `tests/test_navigator_depth.py` (new, small)

**Interfaces:**
- Consumes: `GeoGrid`, `AutorouteConfig`, `resources.geogrid_cache_path`, `Settings.boat_draft_m`.
- Produces: `Navigator(polars, schedule, grid)` (3rd arg is now a grid with `.depth_at`); `Engine(route, polars, data_source, ais_source, start_state=..., grid=...)`. `NavState.depth_m` now carries **depth below surface** `D`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_navigator_depth.py
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from __future__ import annotations

from yey.boats.simulator.engine.navigator import Navigator  # type: ignore[import]
from yey.boats.simulator.engine.schedule import Schedule  # type: ignore[import]


class _FakeGrid:
    def depth_at(self, lat, lon):
        return 123.0


def test_navigator_reads_depth_from_grid():
    nav = Navigator(polars=None, schedule=Schedule(), grid=_FakeGrid())
    assert nav._depth_at(45.0, 13.0) == 123.0
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python -m pytest tests/test_navigator_depth.py -q`
Expected: FAIL — `Navigator.__init__` still expects `depth_profile`; keyword `grid` unknown.

- [ ] **Step 3: Implement**

In `navigator.py`, change the constructor and `_depth_at`:

```python
    def __init__(self, polars: Polars, schedule: Schedule, grid) -> None:
        self._polars   = polars
        self._schedule = schedule
        self._grid     = grid           # object exposing depth_at(lat,lon) -> D (m)
```

```python
    def _depth_at(self, lat: float, lon: float) -> float:
        return self._grid.depth_at(lat, lon)   # depth below surface (m)
```

In `engine.py:43-50`, thread the grid through:

```python
    def __init__(self, route: Any, polars: Any, data_source: Any, ais_source: Any,
                 start_state: Any, grid: Any) -> None:
        self.route = route
        self.polars = polars
        self._data = data_source
        self._ais = ais_source
        self.sched = Schedule()
        self.nav = Navigator(polars, self.sched, grid)
```

(Keep the rest of `Engine.__init__` unchanged. `start_state` becomes positional-or-keyword as before; add `grid` as a required arg.)

In `runner.py`, replace the depth-profile load + Engine construction. After `route` is loaded and before `engine = Engine(...)`:

```python
    from yey.boats.simulator.engine.geogrid import GeoGrid
    from yey.boats.simulator.engine.autoroute import AutorouteConfig

    grid = GeoGrid(cache_path=resources.geogrid_cache_path(settings.data_dir))
    route_cfg = AutorouteConfig(hard_min_m=settings.boat_draft_m + 1.0)
    try:
        inserted = route.autoroute_legs(grid, route_cfg)
        print(f"[sim] autoroute inserted {inserted} navigable waypoints", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[sim] autoroute failed (using planner legs): {exc!r}", flush=True)
```

Delete the old lines:
```python
    print("[sim] fetching depth profile (may take ~30s first run)...", flush=True)
    route.load_depth_profile(resources.depth_cache_path(settings.data_dir))
```

Change the Engine construction to pass the grid:
```python
    engine = Engine(route, polars, data_source, ais_source,
                    start_state=start_state, grid=grid)
```

Add `grid.fetch_loop()` to the always-on task list (so per-tick depth misses fill in the background). Change:
```python
    tasks = [drive(), ais_source.start(), grid.fetch_loop()]
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src python -m pytest tests/test_navigator_depth.py tests/test_engine.py -q`
Expected: PASS. If `tests/test_engine.py` constructs `Engine(...)` or `Navigator(...)` directly, update those call sites to pass a fake grid (`grid=_FakeGrid()` / a `GeoGrid(fetcher=lambda pts:[-20.0 for _ in pts])`) — this is expected fallout of the signature change, not a test break to ignore.

- [ ] **Step 5: Commit**

```bash
git add src/yey/boats/simulator/engine/navigator.py src/yey/boats/simulator/engine/engine.py src/yey/boats/simulator/engine/runner.py tests/test_navigator_depth.py tests/test_engine.py
git commit -m "feat(engine): depth from GeoGrid + autoroute at load + background fetch"
```

---

### Task 7: Depth-semantics fix in the SignalK writer

**Files:**
- Modify: `src/yey/boats/simulator/engine/signalk_writer.py` (the depth emission block + constants)
- Test: `tests/test_screen_value_emission.py` (extend)

**Interfaces:**
- Consumes: `NavState.depth_m` (now depth below surface `D`).
- Produces: emitted `environment.depth.belowKeel = max(0, D - DRAFT_M)`, `environment.depth.belowTransducer = max(0, D - TRANSDUCER_DEPTH_M)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_screen_value_emission.py
def test_depth_emissions_derived_from_depth_below_surface():
    # D below surface = 12 m, draft 2.2, transducer 0.6
    p = _paths(_delta(nav=_nav(depth_m=12.0)))
    assert p["environment.depth.belowKeel"] == pytest.approx(12.0 - 2.2)
    assert p["environment.depth.belowTransducer"] == pytest.approx(12.0 - 0.6)


def test_depth_emissions_clamped_non_negative():
    # Shallow mooring: D = 1.0 m < draft -> belowKeel clamps to 0.
    p = _paths(_delta(nav=_nav(depth_m=1.0)))
    assert p["environment.depth.belowKeel"] == 0.0
    assert p["environment.depth.belowTransducer"] == pytest.approx(max(0.0, 1.0 - 0.6))
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python -m pytest tests/test_screen_value_emission.py -q`
Expected: FAIL — current code emits `belowKeel = D` and `belowTransducer = D + 1.5`.

- [ ] **Step 3: Implement**

In `signalk_writer.py`, replace the `KEEL_TO_TRANSDUCER_M` constant block with draft/transducer constants:

```python
# Boat vertical geometry (Beneteau O45): keel bottom 2.2 m below the
# waterline, depth transducer ~0.6 m below it. GEBCO gives depth below the
# surface D; the two reported depths derive from it.
DRAFT_M = 2.2
TRANSDUCER_DEPTH_M = 0.6
```

Replace the two emission lines (currently `belowKeel = nav.depth_m` and `belowTransducer = nav.depth_m + KEEL_TO_TRANSDUCER_M` and the water-temp line stays):

```python
        # Depth — nav.depth_m is depth below surface (D), from the GeoGrid.
        _v("environment.depth.belowKeel",       max(0.0, nav.depth_m - DRAFT_M)),
        _v("environment.depth.belowTransducer", max(0.0, nav.depth_m - TRANSDUCER_DEPTH_M)),
```

Update the existing `test_depth_below_transducer_offset_from_keel` test (Task-0 era) if present so it reflects the new derivation, and remove any remaining reference to `KEEL_TO_TRANSDUCER_M` (including its import in the test module).

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src python -m pytest tests/test_screen_value_emission.py -q`
Expected: PASS. `ruff check` clean (no unused `KEEL_TO_TRANSDUCER_M`).

- [ ] **Step 5: Commit**

```bash
git add src/yey/boats/simulator/engine/signalk_writer.py tests/test_screen_value_emission.py
git commit -m "fix(signalk): derive belowKeel/belowTransducer from depth-below-surface"
```

---

### Task 8: Real-GEBCO record-once fixture + integration test

**Files:**
- Create: `tests/fixtures/__init__.py` (empty), `tests/conftest.py` (fixture helper if not present — else extend)
- Create: `tests/test_geogrid_real.py`
- Create (generated, committed): `tests/fixtures/geogrid_hvar.json`

**Interfaces:**
- Consumes: `GeoGrid`, `autoroute_leg`, `AutorouteConfig`, real OpenTopoData (only when refreshing the fixture).

- [ ] **Step 1: Write the integration test (skips cleanly without the fixture)**

```python
# tests/test_geogrid_real.py
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Integration test against REAL GEBCO bathymetry, replayed from a committed
tile cache. Download the fixture once with:

    YEYBOATS_REFRESH_GEOGRID_FIXTURE=1 PYTHONPATH=src \
      python -m pytest tests/test_geogrid_real.py -q

Thereafter it runs fully offline from tests/fixtures/geogrid_hvar.json.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.geogrid import GeoGrid, _opentopo_fetch  # type: ignore[import]
from yey.boats.simulator.engine.autoroute import (  # type: ignore[import]
    AutorouteConfig, autoroute_leg)

FIXTURE = Path(__file__).parent / "fixtures" / "geogrid_hvar.json"

# Around the island of Hvar (Croatia): deep channel water to the south,
# the island landmass in the middle.
DEEP_WATER = (43.05, 16.45)     # open Adriatic, south of Hvar
ON_ISLAND  = (43.17, 16.60)     # Hvar landmass
WEST_PT    = (43.12, 16.35)     # west of the island, in water
EAST_PT    = (43.12, 16.80)     # east of the island, in water


def _grid() -> GeoGrid:
    refresh = os.environ.get("YEYBOATS_REFRESH_GEOGRID_FIXTURE") == "1"
    if not FIXTURE.exists() and not refresh:
        pytest.skip("geogrid fixture absent; set YEYBOATS_REFRESH_GEOGRID_FIXTURE=1 to record")
    fetcher = _opentopo_fetch if refresh else _no_net
    return GeoGrid(cache_path=FIXTURE, fetcher=fetcher, cell_deg=0.02)


def _no_net(points):
    raise AssertionError("offline test attempted a network fetch; fixture incomplete")


def test_real_depth_is_plausible_in_open_water():
    g = _grid()
    g.sample([DEEP_WATER])
    g.save()
    assert g.depth_at(*DEEP_WATER) > 20.0      # genuinely deep, not 0


def test_real_land_classified_on_island():
    g = _grid()
    g.sample([ON_ISLAND])
    g.save()
    assert g.is_land(*ON_ISLAND) is True


def test_real_autoroute_goes_around_island():
    g = _grid()
    path = autoroute_leg(g, WEST_PT, EAST_PT, AutorouteConfig())
    g.save()
    assert path[0] == WEST_PT and path[-1] == EAST_PT
    for lat, lon in path:
        assert not g.is_land(lat, lon)         # never crosses Hvar
```

- [ ] **Step 2: Record the fixture once (online)**

Run:
```bash
mkdir -p tests/fixtures && touch tests/fixtures/__init__.py
YEYBOATS_REFRESH_GEOGRID_FIXTURE=1 PYTHONPATH=src python -m pytest tests/test_geogrid_real.py -q
```
Expected: PASS, and `tests/fixtures/geogrid_hvar.json` now exists (the `sample()` + `save()` calls and the autoroute bbox pre-sample populate it). If a test asserts and the geometry constants don't match reality (e.g. `ON_ISLAND` lands in water), nudge the coordinates using a quick GEBCO check:
`curl -s "https://api.opentopodata.org/v1/gebco2020?locations=43.17,16.60"` (negative elevation = water; pick a clearly positive point for `ON_ISLAND`).

- [ ] **Step 3: Verify it now runs offline**

Run: `PYTHONPATH=src python -m pytest tests/test_geogrid_real.py -q`
Expected: PASS with no network (the `_no_net` fetcher is used; if it raises, the bbox pre-sample needs more cells recorded — re-run Step 2, which records the full autoroute bbox).

- [ ] **Step 4: Full suite green**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS (web-API tests needing `pytest-aiohttp` may error if that plugin is absent locally — unrelated to this work; confirm no NEW failures in geogrid/autoroute/navigator/writer modules).

- [ ] **Step 5: Commit (including the recorded fixture)**

```bash
git add tests/test_geogrid_real.py tests/fixtures/__init__.py tests/fixtures/geogrid_hvar.json tests/conftest.py
git commit -m "test(geogrid): record-once real-GEBCO fixture + autoroute-around-island integration"
```

---

## Self-Review

**Spec coverage:**
- GeoGrid lazy sampler + non-blocking depth + background fetch → Tasks 1, 2, 6. ✓
- Persistence in sim-data volume (`geogrid.json`) → Tasks 2, 3, 6. ✓
- Tiered depth-cost A*, straight fast-path, bbox+node-cap fallback → Task 4. ✓
- Auto-insert navigable legs between planner waypoints → Task 5, run at load in Task 6. ✓
- Depth-at-current-location into navigator → Task 6. ✓
- belowKeel/belowTransducer from depth-below-surface → Task 7. ✓
- Config (cell size, draft, cache path, thresholds via `AutorouteConfig`) → Tasks 3, 4. ✓
- Error handling (offline/fallback, A* blowup, no clamp on reported depth) → Tasks 1, 4. ✓
- Testing: synthetic pure-logic + record-once real-GEBCO replay → Tasks 1,2,4,5 + Task 8. ✓
- Out of scope (nav-state/lights) → not planned, correct. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Two steps instruct verifying the real `Waypoint` dataclass fields before use — that is a guard against drift, not a placeholder (the code given matches the fields seen at planning time: `name, lat, lon, berth_heading`).

**Type consistency:** `GeoGrid.depth_at/elevation_at/is_land/sample/save/fetch_loop/_cell_of/_corner/_cell` used consistently across Tasks 1–8. `AutorouteConfig` field names (`hard_min_m`, `soft_min_m`, `prefer_m`, `penalty_necessary`, `penalty_tolerated`, `bbox_margin_deg`, `max_cells`, `max_nodes`) consistent in Tasks 4–6. `autoroute_leg(grid, a, b, cfg)` and `Route.autoroute_legs(grid, cfg)` signatures consistent. `Navigator(polars, schedule, grid)` and `Engine(..., grid=...)` consistent in Task 6. `NavState.depth_m` = depth-below-surface used by Task 7.

## Risks / notes for the implementer
- `haversine_nm` and `great_circle_bearing` already exist in `route.py`; `autoroute.py` reuses `haversine_nm`. Do not re-implement.
- `Engine(...)` and `Navigator(...)` signature changes will ripple into any existing test that constructs them directly — update those call sites (expected, not optional).
- OpenTopoData public API has a ~1000 req/day quota; the recorded fixture and the `sim-data` cache keep live usage low. If the lab hits limits, self-hosting OpenTopoData is a later config change, not part of this plan.
