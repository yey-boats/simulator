# Navigable geo-grid + land/depth autorouting + realistic depth

**Date:** 2026-06-20
**Status:** Design (approved in brainstorming; pending spec review)
**Scope:** Spec 1 of a planned series. This spec covers the geo-data
**foundation**, **land/depth-aware autorouting**, and **realistic
depth-at-current-location**. Location-driven navigation state and COLREGS
lights are deferred to a follow-up spec (Spec 2) that builds on the grid.

## Motivation

The simulator's depth model samples GEBCO only *along the route legs* and
returns the nearest sampled point's value via nearest-neighbour. When the
boat is off the route (e.g. a resumed run far south of the Adriatic
waypoints), the nearest sample is a distant coastal point, so
`environment.depth.belowKeel` reads `0` even in deep open water.

The route is a fixed 8-point waypoint list (`adriatic.kmz`: Venice → Pula →
… → Corfu). Straight legs between waypoints take no account of land or
shallow water — there is **no coastline/land dataset at all** today.

We want depth that reflects the **actual bathymetry under the boat**, and
routing that **avoids land and shallow water** using the same map data.

## Key insight

GEBCO 2020 elevation gives **both** quantities from one dataset:

- `elevation < 0` → water, `depth_below_surface = -elevation`
- `elevation ≥ 0` → land (impassable)

So a single lazily-sampled GEBCO grid serves depth lookup **and** routing
navigability. No separate coastline polygon dataset is required for "basic"
autorouting.

## Architecture

Two new modules plus targeted edits to existing engine files.

```
OpenTopoData gebco2020 ──(lazy batch ≤1 req/s, cached)──> GeoGrid (DATA_DIR/geogrid.json)
   ├─ depth_at(boat pos)     [per tick, non-blocking] ─> NavState.depth_below_surface ─> writer
   └─ sample()/navigable     [route compute, off-tick] ─> Autorouter A* ─> expanded Route waypoints
```

### Component: `engine/geogrid.py` — `GeoGrid`

A lazy, persistent GEBCO sampler. One clear purpose: map any `(lat, lon)` to
a depth/elevation, fetching and caching GEBCO cells on demand.

- **Quantization:** integer cell indices at `CELL_DEG = 0.02` (~2 km).
  `cell(lat,lon) = (round(lat/CELL), round(lon/CELL))`. Cache is
  `dict[(ilat,ilon) -> elevation_m]` (store elevation so land ≥ 0 is
  representable).
- **`depth_at(lat, lon) -> float`** — called per tick, **never does
  network**. Bilinear interpolation over the four surrounding cached cell
  centres → `depth = max(0.0, -elev)`. On a miss: return the nearest cached
  value, else a fallback (`FALLBACK_DEPTH_M = 50.0`), and enqueue the missing
  cell(s) for background fetch.
- **`elevation_at` / `is_land` / `navigable_depth_penalty`** — derived
  helpers (see Autorouter cost model).
- **`sample(points) -> list[float]`** — **synchronous** batched fetch of
  uncached cells via OpenTopoData (`≤100` locations/request, `≥1.1 s`
  spacing — reuse the existing `_fetch_depth_profile` HTTP pattern). Caches
  results. Used by the autorouter, which runs off the tick loop.
- **`async fetch_loop()`** — drains the per-tick miss queue at `≤1` batch/s,
  populates the cache, and persists to `DATA_DIR/geogrid.json` periodically
  and on shutdown. Started by the runner as a concurrent task.
- **Persistence:** load cache from `DATA_DIR/geogrid.json` at startup; the
  `sim-data` Docker volume makes it survive restarts.

Dataset: OpenTopoData `gebco2020` (already used by the route profile).

### Component: `engine/autoroute.py` — `autoroute_leg(grid, A, B, cfg)`

Computes a navigable polyline between two waypoints.

- **Fast path:** sample points along the straight A→B line; if **every**
  point has `depth ≥ PREFER_DEPTH_M`, return `[A, B]` (no search).
- **Search:** otherwise weighted **A\*** over 8-connected grid cells:
  - **Cost** to enter a cell = great-circle distance between cell centres ×
    `depth_penalty(depth)`.
  - **Heuristic** = haversine to goal × base penalty (admissible:
    min penalty is 1.0).
  - **Navigability is tiered** (see below); cells below the hard floor are
    not neighbours.
  - **Bounded:** search constrained to the A–B bounding box inflated by
    `BBOX_MARGIN_DEG` (default `0.3`), with a node-expansion cap
    (`MAX_NODES`, default `20000`). On cap or no-path → return `[A, B]`
    straight leg **and log a warning** (never silent).
  - Lazily materialise cell depths via `grid.sample()` on the search
    frontier (batched).
- **Output:** simplify the cell path (collinear / Douglas–Peucker pruning)
  to a minimal interior waypoint list; return `[A, …interior…, B]`.

#### Tiered depth-cost model

Boat draft `BOAT_DRAFT_M = 2.2`. Thresholds (all config-overridable):

| Band | Depth below surface | A* treatment |
|---|---|---|
| Impassable | `< HARD_MIN = draft + 1.0 = 3.2 m` | not traversable |
| Necessary-only | `3.2 m ≤ d < SOFT_MIN = 5.0 m` | penalty `×25` |
| Tolerated | `5.0 m ≤ d < PREFER = 10.0 m` | penalty `×5` |
| Preferred | `d ≥ 10.0 m` | penalty `×1` |

This makes A* hug ≥10 m water, dip into 5–10 m only when it meaningfully
shortens the path, and use 3.2–5 m water only to connect coastal endpoints
(e.g. marina approaches) when there is no deeper alternative. It never routes
shallower than `draft + 1 m`.

### Integration into the route + engine

- **`engine/route.py`**: new `autoroute_legs(grid, cfg)` walks the planner's
  waypoint list; each consecutive pair → `autoroute_leg`, concatenated into
  the effective navigable polyline. The original planner waypoints are kept
  separate (endpoints are never moved). The expanded route is persisted with
  the existing `route.json` so reboots don't recompute.
- **`engine/navigator.py`**: `Navigator.__init__` takes the `GeoGrid`
  (replacing the static `depth_profile` list). `_depth_at(lat,lon)` →
  `grid.depth_at(lat,lon)`. Returns **depth below surface** `D` (renamed
  intent; non-blocking).
- **`engine/runner.py`**: build the `GeoGrid`, start `fetch_loop()` as a
  concurrent task, run `autoroute_legs` once after route load.

### Depth-semantics fix (consistency with the prior emission change)

GEBCO yields **depth below surface `D`**. Make that the source of truth and
derive both emissions consistently (replacing the current
`belowKeel = nav.depth_m` / `belowTransducer = belowKeel + 1.5`):

- `belowKeel = max(0, D − DRAFT_M)` (`DRAFT_M = 2.2`)
- `belowTransducer = max(0, D − TRANSDUCER_DEPTH_M)` (`TRANSDUCER_DEPTH_M ≈ 0.6`)

The `~1.6 m` gap matches the shipped `1.5 m` constant, so this is a
consistency cleanup, not a behavioural reversal. Both constants live in
config. `NavState.depth_m` becomes "depth below surface"; `signalk_writer`
computes the two emitted depths from it.

## Configuration (new `Settings` fields, all defaulted)

- `geogrid_cell_deg = 0.02`
- `geogrid_cache = DATA_DIR/geogrid.json`
- `boat_draft_m = 2.2`, `transducer_depth_m = 0.6`
- `route_hard_min_depth_m = 3.2` (draft + 1; derived default)
- `route_soft_min_depth_m = 5.0`, `route_prefer_depth_m = 10.0`
- `route_penalty_necessary = 25.0`, `route_penalty_tolerated = 5.0`
- `autoroute_bbox_margin_deg = 0.3`, `autoroute_max_nodes = 20000`
- `geogrid_fallback_depth_m = 50.0`

## Error handling / edge cases

- **Offline / API failure:** grid stays sparse; `depth_at` → nearest cached
  or `FALLBACK_DEPTH_M`; `autoroute_leg` → straight leg, logged. The tick
  loop never blocks or crashes.
- **OpenTopoData public quota (~1000 req/day):** 100 locations/request +
  permanent cache keeps one-time corridor cost small; warn as the quota is
  approached; document the self-host option.
- **A\* blowup:** bbox + node cap → straight-leg fallback + log.
- **~2 km cells** cannot resolve narrow channels / marina mouths → documented
  limitation of "basic" routing; legs may cut corners. Acceptable for the
  sim. Finer cells are a config change if needed later.
- **Genuinely shallow moorings (`< HARD_MIN`):** `depth_at` returns the real
  shallow value (no clamp). The navigability threshold is **routing-only**;
  it does not alter reported depth.

## Testing

Two layers: deterministic pure-logic tests that never touch the network, and
real-data integration tests that **download the needed GEBCO tiles once and
replay them from a committed cache** thereafter (record-once / replay).

### Layer 1 — pure logic, synthetic data (always offline)

- **`tests/test_geogrid.py`** — inject a fake fetcher backed by synthetic
  bathymetry `f(lat,lon)`: quantization, bilinear interpolation, land
  classification, miss-queue behaviour, JSON persistence round-trip,
  non-blocking `depth_at`.
- **`tests/test_autoroute.py`** — synthetic grid with a land/shoal barrier:
  path routes around and stays ≥ `HARD_MIN`; prefers deep water (penalty
  ordering); endpoints preserved; straight-leg shortcut when clear;
  fallback + log on node cap.
- **`tests/test_screen_value_emission.py`** (extend) — `belowKeel`/
  `belowTransducer` derived from `D` with offsets and `max(0, …)` clamps.

### Layer 2 — real GEBCO data, cached tiles (download once, then offline)

- A small **committed cache fixture** holds real GEBCO elevations for one
  bounded area containing a clear land/water boundary — e.g. a Croatian
  island with deep water around it. Same on-disk format as the live
  `geogrid.json`, stored at `tests/fixtures/geogrid_<area>.json` (a bounded
  ~2 km grid is a few hundred cells → small JSON).
- **Record-once mechanism:** a pytest fixture / helper points `GeoGrid` at
  the fixture path. If the fixture exists, the test runs **fully offline**
  from it. If it is missing **and** an opt-in marker is set
  (`YEYBOATS_REFRESH_GEOGRID_FIXTURE=1`), the helper fetches the needed cells
  **once** via the real OpenTopoData API and writes the fixture (to be
  committed). Default CI / local runs use the committed fixture and never hit
  the network; collection skips Layer 2 with a clear message if the fixture
  is absent and refresh is not requested.
- **Assertions on real data:** `depth_at` over open water returns plausible
  deep values (not `0`); a point on the island classifies as land; and
  `autoroute_leg` between two points on opposite sides of the island returns
  a path that stays ≥ `HARD_MIN` and goes **around** the land rather than
  through it.

This gives the autorouter and depth lookup coverage against genuine
bathymetry while keeping the suite hermetic and fast after the one-time
tile download.

## Files

- **New:** `engine/geogrid.py`, `engine/autoroute.py`,
  `tests/test_geogrid.py`, `tests/test_autoroute.py`
- **Modified:** `engine/navigator.py`, `engine/route.py`, `engine/engine.py`,
  `engine/runner.py`, `engine/signalk_writer.py`, `config.py`

## Out of scope (future specs)

- **Spec 2:** location-driven navigation state (add `ANCHORED`; derive
  moored/anchored/motoring/sailing from position + speed + engine + grid +
  marinas) and COLREGS lights driven by that state.
- Finer-than-2 km grids, self-hosted OpenTopoData, on-demand "route to
  destination" UI action, per-tick rerouting.
