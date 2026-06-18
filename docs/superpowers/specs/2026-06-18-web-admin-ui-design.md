# Simulator Web Admin UI — Design

**Status:** Approved (design) — ready for implementation plan
**Date:** 2026-06-18
**Repo:** `yey-boats/simulator`

## Goal

A web admin embedded in the `yey-boats-sim` process for editing the simulator's
runtime configuration and route, with changes **applied live** to the running
sim (no OS process / container restart). React + Tailwind SPA served by a small
embedded async server. Config and route persist to files so edits survive
restarts.

Editable surface:
- **SignalK connection** — host, port, username, password
- **API key** — `aisstream_api_key`
- **Other config** — `sink` (signalk/stdout/nmea0183/nmea2000), `weather_source`
  (openmeteo/signalk), `failover`, `data_dir`
- **Route** — ordered waypoints (`name`, `lat`, `lon`)

Non-goals: user accounts, a full telemetry dashboard (status is a small
read-only strip), editing physics/polar/depth models, multi-vessel config.

## Architecture (Python)

Three small, independently-testable units plus the SPA.

### Config-file layer
- Persist settings to `config.json` in `data_dir`.
- New precedence: **CLI > env > config-file > defaults** (today it is
  CLI > env > defaults; the file slots in below env).
- `Settings.from_file(path)` / `Settings.save(path)`; `Settings.from_env` gains a
  file-merge step. Secrets (`signalk_password`, `aisstream_api_key`) are
  persisted but **never returned** by the read API — GET responses mask them as a
  boolean `"<field>_set"` and the field is write-only (empty string on PUT = leave
  unchanged; explicit value = overwrite).

### Supervisor (live-apply)
- `engine/runner.py` becomes a **supervisor**: it owns the current `Settings` +
  `Route` and runs the engine/sink pipeline as a **cancellable asyncio task**.
- An `asyncio.Event` (or single-slot queue) is the change signal. The web API
  mutates the in-memory `Settings`/`Route`, persists to disk, then sets the event.
- On signal the supervisor **cancels the running pipeline task and rebuilds it**
  from the new settings (new sink/source/engine), then resumes. This is the
  "live-apply" mechanism — an in-process pipeline restart (~1 s blip), not an OS
  restart; far simpler than hot-swapping live sockets and indistinguishable to the
  operator.
- **Position continuity:** the supervisor seeds the rebuilt `Engine` with the last
  observed `NavState` (lat/lon/heading) so the boat does not teleport to the route
  origin across a live-apply. If no prior state (first run), start at the route
  origin as today.

### Web server
- `aiohttp` server run as a task on the **same asyncio event loop** as the engine
  (no second event loop; cleaner than uvicorn-in-thread). Started by the
  supervisor when the web admin is enabled.
- Serves the built SPA static assets and the JSON API below.

## API surface

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/config` | Current settings, secrets masked (`signalk_password_set`, `aisstream_api_key_set` booleans). |
| PUT | `/api/config` | Validate, persist to `config.json`, signal live-apply. Empty secret fields leave the stored secret unchanged. |
| GET | `/api/route` | `{ waypoints: [{name, lat, lon}], current_index }`. |
| PUT | `/api/route` | Replace waypoints, persist (`route.json`), signal live-apply. |
| POST | `/api/route/import` | Multipart upload of a KMZ or GeoJSON; parse → waypoints; return parsed list (does not auto-save — UI confirms then PUTs). |
| GET | `/api/status` | Polled (~1.5 s): `{ connected, sink, weather_source, position:{lat,lon}\|null, tick, last_error\|null }`. |

Validation: host non-empty; port 1–65535; `sink`/`weather_source` from their
enums; waypoints lat ∈ [-90,90], lon ∈ [-180,180], ≥ 2 points. Invalid PUTs
return 400 with a field-level error map; the live pipeline is **not** disturbed on
a rejected change.

### Route persistence & seeding
- Route persists to `route.json` in `data_dir` (`[{name, lat, lon}]`).
- Load precedence on start: `route.json` if present, else the **bundled KMZ**
  (today's behavior) seeds it.
- KMZ parsing reuses the existing `Route.load` KML path; GeoJSON parsing is added
  (LineString / list of Point features → waypoints).

## Frontend (React + Tailwind + Vite)

Single SPA, three tabs + a persistent status strip:
- **Connection / Config** — form for SignalK host/port/user/pass, AISStream key
  (masked, "set/unset" + overwrite), sink, weather source, failover, data-dir.
  Save button → `PUT /api/config`; inline validation mirrors server rules.
- **Route** — all three editing modes over one waypoint model:
  1. **List editor** — table of rows (name/lat/lon), add / remove / reorder.
  2. **File upload** — drop a KMZ/GeoJSON → `POST /api/route/import` → preview →
     confirm replaces the list.
  3. **Map editor** — `react-leaflet` + OSM tiles; click to add, drag to move,
     click-to-delete; two-way bound to the same waypoint list.
  Save → `PUT /api/route`.
- **Status strip** — connection state, active sink, boat position, tick count;
  polls `/api/status`.

The visual + interaction design (layout, color, typography, component polish) is
produced via the **frontend-design** skill during implementation so it is
distinctive, not generic-AI. Tailwind for styling; no component-library lock-in
beyond react-leaflet.

## Build & packaging

- Frontend source in `frontend/` (Vite). Build output goes into the Python
  package at `src/yey/boats/simulator/web/static/` so **hatchling ships it in the
  wheel** (declare as package data / force-include).
- The server serves `web/static/` (SPA `index.html` fallback for client routes).
- **Dockerfile** gains a `node` build stage: build the SPA, copy `dist` into the
  python build context before `python -m build`. CI (`ci.yml`) builds the frontend
  in the wheel + image jobs; add a frontend `npm ci && npm run build` step.

## Exposure & security

- Web admin **enabled by default at `127.0.0.1:8080`**. Flags: `--web-host`,
  `--web-port`, `--no-web`; env `SIM_WEB_HOST` / `SIM_WEB_PORT` / `SIM_WEB_ENABLED`.
- No auth by default (localhost lab tool). Optional `--web-token` (env
  `SIM_WEB_TOKEN`): when set, the API requires a matching `X-Sim-Token` header and
  the SPA prompts for it once. For remote use, recommend an SSH tunnel.
- Secrets are never returned by GET; the bind default is loopback so a missing
  token does not expose secrets on the network.

## Testing

- **Python (pytest):**
  - config-file round-trip + precedence (CLI > env > file > defaults); secret
    masking on read; empty-secret-keeps-existing on write.
  - route parsing: KMZ and GeoJSON → waypoints; validation rejects bad coords /
    < 2 points.
  - API handlers via `aiohttp` test client: GET/PUT config + route, import,
    status; 400 on invalid input without disturbing the pipeline.
  - supervisor: a config/route change signal rebuilds the pipeline and preserves
    the last `NavState`.
- **Frontend:** Vite production build must succeed in CI (build check). Optional
  Playwright smoke (load app, edit a field, save, see status) — not gating.

## Risks / notes

- Larger than the original "keep it simple" ask; simplicity is preserved via
  clean unit boundaries (config-file / supervisor / server / SPA), not fewer
  features.
- `react-leaflet` + OSM tiles fetch map tiles at runtime (network needed for the
  map editor; list + upload modes work offline). Accepted.
- Live-apply via pipeline restart resets in-flight sink connections briefly; the
  status strip surfaces reconnection so the blip is visible, not silent.
