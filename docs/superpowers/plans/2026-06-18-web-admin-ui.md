# Simulator Web Admin UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a web admin embedded in `yey-boats-sim` to edit SignalK connection, AISStream key, sink/weather/failover/data-dir, and the route (list + upload + map), with changes applied live (in-process pipeline restart preserving boat position).

**Architecture:** Python backend = a config-file layer + a `SimController` supervisor (runs the engine/sink pipeline as a cancellable task, rebuilds it on change) + an `aiohttp` JSON API on the engine's event loop. Frontend = a React+Tailwind+Vite SPA built into the Python package and served by the same server; visual design produced via the frontend-design skill.

**Tech Stack:** Python 3.12, asyncio, aiohttp (new), hatchling; React 18 + TypeScript + Vite + Tailwind + react-leaflet. Tests: pytest (+ pytest-asyncio), aiohttp test client; Vite build check.

**Spec:** `docs/superpowers/specs/2026-06-18-web-admin-ui-design.md`

---

## File Structure

Backend (under `src/yey/boats/simulator/`):
- `config.py` — **modify**: add file persistence + `config-file` precedence layer.
- `engine/route.py` — **modify**: waypoint dict round-trip + JSON persistence helpers.
- `routeio.py` — **create**: pure parsers (`waypoints_from_geojson`, `waypoints_to_geojson`, validation). KMZ parse stays in `route.py`.
- `control.py` — **create**: `SimController` supervisor (owns Settings+Route, runs/rebuilds the pipeline, exposes `status()`/`apply_config()`/`apply_route()`).
- `web/__init__.py`, `web/server.py`, `web/api.py` — **create**: aiohttp app, route handlers, static serving, token middleware.
- `web/static/` — **create (build output)**: the built SPA (git-ignored source; shipped in wheel).
- `cli.py` / `engine/runner.py` — **modify**: `--web*` flags; `runner.run()` delegates to `SimController`.

Frontend (repo root `frontend/`):
- `frontend/package.json`, `vite.config.ts`, `tailwind.config.js`, `index.html`, `tsconfig.json`
- `frontend/src/api.ts` (client+types), `frontend/src/main.tsx`, `frontend/src/App.tsx`
- `frontend/src/tabs/ConfigTab.tsx`, `RouteTab.tsx`, `StatusStrip.tsx`, `RouteMap.tsx`

Packaging: `pyproject.toml` (package-data), `Dockerfile` (node stage), `.github/workflows/ci.yml` (frontend build).

Test command (backend): `.venv/bin/pytest -q` ; lint `.venv/bin/ruff check src tests`.

---

# Phase A — Backend

## Task A1: Config-file persistence + precedence

**Files:**
- Modify: `src/yey/boats/simulator/config.py`
- Test: `tests/test_config_file.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_file.py`:

```python
import json
from pathlib import Path

from yey.boats.simulator.config import Settings


def test_save_and_load_roundtrip(tmp_path: Path):
    s = Settings(signalk_host="boat.local", signalk_port=3001,
                 aisstream_api_key="KEY123", sink="stdout")
    p = tmp_path / "config.json"
    s.save(p)
    loaded = Settings.from_file(p)
    assert loaded.signalk_host == "boat.local"
    assert loaded.signalk_port == 3001
    assert loaded.aisstream_api_key == "KEY123"
    assert loaded.sink == "stdout"


def test_from_file_missing_returns_defaults(tmp_path: Path):
    s = Settings.from_file(tmp_path / "nope.json")
    assert s.signalk_host == "localhost"
    assert s.signalk_port == 3000


def test_precedence_cli_over_env_over_file(tmp_path: Path, monkeypatch):
    p = tmp_path / "config.json"
    Settings(signalk_host="from-file", signalk_port=3002).save(p)
    monkeypatch.setenv("SIGNALK_HOST", "from-env")
    # file provides port 3002; env overrides host; cli override wins for username
    s = Settings.from_env(config_path=p, username_override=None,
                          **{"signalk_username": "from-cli"})
    assert s.signalk_host == "from-env"      # env beats file
    assert s.signalk_port == 3002            # file beats default
    assert s.signalk_username == "from-cli"  # cli beats all


def test_save_is_json_with_known_keys(tmp_path: Path):
    p = tmp_path / "config.json"
    Settings().save(p)
    data = json.loads(p.read_text())
    assert set(data) >= {"signalk_host", "signalk_port", "signalk_username",
                         "signalk_password", "aisstream_api_key", "sink",
                         "weather_source", "failover", "data_dir"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config_file.py -q`
Expected: FAIL — `Settings` has no `save` / `from_file`.

- [ ] **Step 3: Implement file persistence in `config.py`**

Add these methods to the `Settings` dataclass and extend `from_env`. Insert after the existing `from_env`:

```python
    _PERSIST_KEYS = ("signalk_host", "signalk_port", "signalk_username",
                     "signalk_password", "aisstream_api_key", "sink",
                     "weather_source", "failover", "data_dir")

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self._PERSIST_KEYS}
        d["data_dir"] = str(self.data_dir)
        return d

    def save(self, path) -> None:
        import json
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def from_file(cls, path) -> "Settings":
        import json
        from pathlib import Path
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text())
        if "data_dir" in raw:
            raw["data_dir"] = Path(raw["data_dir"]).resolve()
        known = {k: raw[k] for k in cls._PERSIST_KEYS if k in raw}
        return cls(**known)
```

Then change `from_env` so the file layer sits **below env** and CLI overrides win. Replace the body of `from_env` with:

```python
    @classmethod
    def from_env(cls, *, config_path=None, **overrides: object) -> "Settings":
        # precedence (low -> high): defaults < file < env < cli(overrides)
        base = cls.from_file(config_path) if config_path is not None else cls()
        env_map = {
            "signalk_host": os.environ.get("SIGNALK_HOST"),
            "signalk_port": (int(os.environ["SIGNALK_PORT"]) if "SIGNALK_PORT" in os.environ else None),
            "signalk_username": os.environ.get("SIGNALK_USERNAME"),
            "signalk_password": os.environ.get("SIGNALK_PASSWORD"),
            "aisstream_api_key": (os.environ.get("AISSTREAM_API_KEY", "").strip() or None),
            "sink": os.environ.get("SINK"),
            "weather_source": os.environ.get("WEATHER_SOURCE"),
            "failover": (os.environ["SINK_FAILOVER"] not in ("0", "false", "False")
                         if "SINK_FAILOVER" in os.environ else None),
            "data_dir": (Path(os.environ["DATA_DIR"]).resolve() if "DATA_DIR" in os.environ else None),
        }
        for k, v in env_map.items():
            if v is not None:
                setattr(base, k, v)
        for k, v in overrides.items():
            if v is not None and hasattr(base, k):
                setattr(base, k, v)
        return base
```

(Drop the now-unused `_env` helper if nothing else uses it; keep it if other modules import it — grep first.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config_file.py -q`
Expected: PASS (4 tests).
Then run the FULL suite — `cli.py` calls `Settings.from_env(**overrides)`; the new signature still accepts that (config_path defaults None). Run: `.venv/bin/pytest -q` — all green.

- [ ] **Step 5: Commit**

```bash
git add src/yey/boats/simulator/config.py tests/test_config_file.py
git commit -m "feat(config): persist Settings to config.json; file precedence below env"
```

---

## Task A2: Route ⇄ waypoints + GeoJSON parsing + JSON persistence

**Files:**
- Create: `src/yey/boats/simulator/routeio.py`
- Modify: `src/yey/boats/simulator/engine/route.py` (add `to_waypoint_dicts`, `from_waypoint_dicts`, `save_json`, `load_json`)
- Test: `tests/test_routeio.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_routeio.py`:

```python
import json
from pathlib import Path

import pytest

from yey.boats.simulator.routeio import (
    waypoints_from_geojson, validate_waypoints, WaypointError,
)
from yey.boats.simulator.engine.route import Route


def test_geojson_linestring_to_waypoints():
    gj = {"type": "Feature",
          "geometry": {"type": "LineString",
                       "coordinates": [[13.5, 45.4], [14.2, 44.9]]},
          "properties": {"waypoints": [{"name": "A"}, {"name": "B"}]}}
    wps = waypoints_from_geojson(gj)
    assert wps == [{"name": "A", "lat": 45.4, "lon": 13.5},
                   {"name": "B", "lat": 44.9, "lon": 14.2}]


def test_geojson_point_features_to_waypoints():
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [13.5, 45.4]},
         "properties": {"name": "Start"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [14.2, 44.9]},
         "properties": {"name": "End"}}]}
    wps = waypoints_from_geojson(gj)
    assert [w["name"] for w in wps] == ["Start", "End"]
    assert wps[0]["lat"] == 45.4 and wps[0]["lon"] == 13.5


def test_validate_rejects_too_few():
    with pytest.raises(WaypointError):
        validate_waypoints([{"name": "only", "lat": 45.0, "lon": 13.0}])


def test_validate_rejects_bad_coords():
    with pytest.raises(WaypointError):
        validate_waypoints([{"name": "a", "lat": 91.0, "lon": 13.0},
                            {"name": "b", "lat": 45.0, "lon": 13.0}])


def test_route_json_roundtrip(tmp_path: Path):
    wps = [{"name": "A", "lat": 45.4, "lon": 13.5},
           {"name": "B", "lat": 44.9, "lon": 14.2}]
    r = Route.from_waypoint_dicts(wps)
    p = tmp_path / "route.json"
    r.save_json(p)
    r2 = Route.load_json(p)
    assert r2.to_waypoint_dicts() == wps
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_routeio.py -q`
Expected: FAIL — `routeio` module missing.

- [ ] **Step 3: Implement `routeio.py`**

Create `src/yey/boats/simulator/routeio.py`:

```python
"""Pure route I/O helpers: GeoJSON <-> waypoint dicts, and validation.

A waypoint dict is {"name": str, "lat": float, "lon": float}. GeoJSON uses
[lon, lat] order (RFC 7946); waypoint dicts keep lat/lon explicit.
"""
from __future__ import annotations

from typing import Any


class WaypointError(ValueError):
    """Raised when waypoint data is structurally invalid."""


def validate_waypoints(wps: list[dict]) -> list[dict]:
    if not isinstance(wps, list) or len(wps) < 2:
        raise WaypointError("route needs at least 2 waypoints")
    out = []
    for i, w in enumerate(wps):
        try:
            lat = float(w["lat"]); lon = float(w["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WaypointError(f"waypoint {i}: missing/invalid lat/lon") from exc
        if not (-90.0 <= lat <= 90.0):
            raise WaypointError(f"waypoint {i}: lat {lat} out of range")
        if not (-180.0 <= lon <= 180.0):
            raise WaypointError(f"waypoint {i}: lon {lon} out of range")
        out.append({"name": str(w.get("name") or f"WP{i+1}"), "lat": lat, "lon": lon})
    return out


def waypoints_from_geojson(gj: dict[str, Any]) -> list[dict]:
    t = gj.get("type")
    feats = gj.get("features") if t == "FeatureCollection" else [gj] if t == "Feature" else None
    if feats is None:
        raise WaypointError("unsupported GeoJSON: expected Feature/FeatureCollection")
    wps: list[dict] = []
    for f in feats:
        geom = f.get("geometry") or {}
        props = f.get("properties") or {}
        if geom.get("type") == "LineString":
            names = props.get("waypoints") or []
            for i, (lon, lat) in enumerate(geom.get("coordinates", [])):
                nm = names[i].get("name") if i < len(names) and isinstance(names[i], dict) else None
                wps.append({"name": nm or f"WP{i+1}", "lat": float(lat), "lon": float(lon)})
        elif geom.get("type") == "Point":
            lon, lat = geom["coordinates"][0], geom["coordinates"][1]
            wps.append({"name": props.get("name") or f"WP{len(wps)+1}",
                        "lat": float(lat), "lon": float(lon)})
    if not wps:
        raise WaypointError("no LineString/Point geometry found in GeoJSON")
    return wps


def waypoints_to_geojson(wps: list[dict], name: str = "Route") -> dict:
    return {"type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[w["lon"], w["lat"]] for w in wps]},
            "properties": {"name": name,
                           "waypoints": [{"name": w["name"]} for w in wps]}}
```

- [ ] **Step 4: Implement Route helpers in `engine/route.py`**

Read the `Waypoint` dataclass and `Route` class first. Add these methods to `Route` (a `Waypoint` has at least `name`, `lat`, `lon`; pass through the other fields with sensible defaults — check the dataclass and fill required fields, e.g. `berth_heading=0.0` if present):

```python
    def to_waypoint_dicts(self) -> list[dict]:
        return [{"name": w.name, "lat": w.lat, "lon": w.lon} for w in self.waypoints]

    @classmethod
    def from_waypoint_dicts(cls, wps: list[dict]) -> "Route":
        from yey.boats.simulator.routeio import validate_waypoints
        valid = validate_waypoints(wps)
        objs = [Waypoint(name=w["name"], lat=w["lat"], lon=w["lon"]) for w in valid]
        return cls(waypoints=objs)

    def save_json(self, path) -> None:
        import json
        from pathlib import Path
        Path(path).write_text(json.dumps(self.to_waypoint_dicts(), indent=2))

    @classmethod
    def load_json(cls, path) -> "Route":
        import json
        from pathlib import Path
        return cls.from_waypoint_dicts(json.loads(Path(path).read_text()))
```

If `Waypoint.__init__` requires fields beyond name/lat/lon (e.g. `berth_heading`), supply defaults in `from_waypoint_dicts` so construction succeeds; mirror what `Route.load` does when building waypoints.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_routeio.py -q`
Expected: PASS (5 tests). Then `.venv/bin/pytest -q` — full suite green.

- [ ] **Step 6: Commit**

```bash
git add src/yey/boats/simulator/routeio.py src/yey/boats/simulator/engine/route.py tests/test_routeio.py
git commit -m "feat(route): waypoint-dict/GeoJSON parsing, validation, JSON persistence"
```

---

## Task A3: `SimController` supervisor (live-apply)

**Files:**
- Create: `src/yey/boats/simulator/control.py`
- Test: `tests/test_control.py`

The controller owns the live `Settings`+`Route`, runs the pipeline as a cancellable task, and rebuilds it on apply while preserving the last position. To keep it unit-testable, the controller takes a **pipeline factory** `async def pipeline(settings, route, start_pos) -> None` (the real one is `runner`'s; tests inject a fake).

- [ ] **Step 1: Write the failing test**

Create `tests/test_control.py`:

```python
import asyncio
import pytest

from yey.boats.simulator.config import Settings
from yey.boats.simulator.control import SimController


@pytest.mark.asyncio
async def test_apply_config_rebuilds_pipeline(tmp_path):
    runs = []           # (settings.signalk_host, start_pos)
    started = asyncio.Event()

    async def fake_pipeline(settings, route, start_pos, report_pos):
        runs.append((settings.signalk_host, start_pos))
        report_pos((45.0, 13.0))   # controller records last position
        started.set()
        await asyncio.sleep(3600)  # runs until cancelled

    c = SimController(Settings(signalk_host="a"), route=None,
                      data_dir=tmp_path, pipeline=fake_pipeline)
    task = asyncio.create_task(c.run_forever())
    await asyncio.wait_for(started.wait(), 1)
    assert runs[0][0] == "a"
    assert runs[0][1] is None

    started.clear()
    await c.apply_config({"signalk_host": "b"})
    await asyncio.wait_for(started.wait(), 1)
    assert runs[1][0] == "b"             # rebuilt with new host
    assert runs[1][1] == (45.0, 13.0)    # position preserved across rebuild
    assert (tmp_path / "config.json").exists()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_status_reports_position(tmp_path):
    async def fake_pipeline(settings, route, start_pos, report_pos):
        report_pos((1.0, 2.0))
        await asyncio.sleep(3600)
    c = SimController(Settings(), route=None, data_dir=tmp_path, pipeline=fake_pipeline)
    task = asyncio.create_task(c.run_forever())
    await asyncio.sleep(0.05)
    st = c.status()
    assert st["position"] == {"lat": 1.0, "lon": 2.0}
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_control.py -q`
Expected: FAIL — `control` module missing.

- [ ] **Step 3: Implement `control.py`**

```python
"""SimController: owns live Settings+Route and (re)runs the engine pipeline.

Live-apply = cancel the running pipeline task and start a new one with the new
settings/route, seeding it with the last reported position so the boat does not
jump back to the route origin.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

PipelineFn = Callable[..., Awaitable[None]]


class SimController:
    def __init__(self, settings, route, data_dir, pipeline: PipelineFn):
        self._settings = settings
        self._route = route
        self._data_dir = Path(data_dir)
        self._pipeline = pipeline
        self._task: Optional[asyncio.Task] = None
        self._last_pos: Optional[tuple[float, float]] = None
        self._restart = asyncio.Event()
        self._last_error: Optional[str] = None

    # --- introspection ---------------------------------------------------
    @property
    def settings(self):
        return self._settings

    @property
    def route(self):
        return self._route

    def status(self) -> dict:
        pos = ({"lat": self._last_pos[0], "lon": self._last_pos[1]}
               if self._last_pos else None)
        return {
            "running": self._task is not None and not self._task.done(),
            "sink": self._settings.sink,
            "weather_source": self._settings.weather_source,
            "signalk": f"{self._settings.signalk_host}:{self._settings.signalk_port}",
            "position": pos,
            "last_error": self._last_error,
        }

    def _report_pos(self, pos: tuple[float, float]) -> None:
        self._last_pos = pos

    # --- supervisor loop -------------------------------------------------
    async def run_forever(self) -> None:
        while True:
            self._restart.clear()
            self._task = asyncio.create_task(self._run_once())
            restart_wait = asyncio.create_task(self._restart.wait())
            done, _ = await asyncio.wait(
                {self._task, restart_wait}, return_when=asyncio.FIRST_COMPLETED)
            restart_wait.cancel()
            if self._task in done:           # pipeline exited on its own (error)
                exc = self._task.exception()
                if exc is not None:
                    self._last_error = repr(exc)
                await asyncio.sleep(1.0)      # brief backoff, then relaunch
            else:                            # restart requested
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

    async def _run_once(self) -> None:
        await self._pipeline(self._settings, self._route,
                             self._last_pos, self._report_pos)

    # --- live-apply ------------------------------------------------------
    async def apply_config(self, changes: dict[str, Any]) -> None:
        for k, v in changes.items():
            if v is not None and hasattr(self._settings, k):
                setattr(self._settings, k, v)
        self._settings.save(self._data_dir / "config.json")
        self._restart.set()

    async def apply_route(self, route) -> None:
        self._route = route
        if route is not None:
            route.save_json(self._data_dir / "route.json")
        self._restart.set()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_control.py -q`
Expected: PASS (2 tests). Then `.venv/bin/pytest -q` — full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/yey/boats/simulator/control.py tests/test_control.py
git commit -m "feat(control): SimController supervisor with live-apply + position carry-over"
```

---

## Task A4: Web API (aiohttp) — config / route / status / import

**Files:**
- Create: `src/yey/boats/simulator/web/__init__.py` (empty), `src/yey/boats/simulator/web/api.py`
- Modify: `pyproject.toml` (add `aiohttp>=3.9` to dependencies)
- Test: `tests/test_web_api.py`

- [ ] **Step 1: Add aiohttp dependency + install**

Edit `pyproject.toml` `dependencies` to add `"aiohttp>=3.9",`. Then:
Run: `.venv/bin/pip install -e ".[dev]"`
Expected: aiohttp installed.

- [ ] **Step 2: Write the failing test**

Create `tests/test_web_api.py`:

```python
import pytest
from aiohttp import web

from yey.boats.simulator.config import Settings
from yey.boats.simulator.control import SimController
from yey.boats.simulator.web.api import make_app


class _Ctl(SimController):
    def __init__(self, tmp_path):
        async def noop(*a):  # pragma: no cover
            import asyncio; await asyncio.sleep(3600)
        super().__init__(Settings(aisstream_api_key="SECRET"), route=None,
                         data_dir=tmp_path, pipeline=noop)
        self.applied = []
    async def apply_config(self, changes):
        self.applied.append(changes)
        await super().apply_config(changes)


@pytest.fixture
def client_ctl(tmp_path, aiohttp_client, loop):
    ctl = _Ctl(tmp_path)
    app = make_app(ctl, token=None)
    return loop.run_until_complete(aiohttp_client(app)), ctl


async def test_get_config_masks_secrets(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    r = await cli.get("/api/config")
    body = await r.json()
    assert r.status == 200
    assert "signalk_password" not in body
    assert "aisstream_api_key" not in body
    assert body["aisstream_api_key_set"] is True
    assert body["signalk_host"] == "localhost"


async def test_put_config_applies_and_keeps_empty_secret(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    r = await cli.put("/api/config", json={"signalk_host": "boat", "aisstream_api_key": ""})
    assert r.status == 200
    assert ctl.settings.signalk_host == "boat"
    assert ctl.settings.aisstream_api_key == "SECRET"   # empty => unchanged


async def test_put_config_rejects_bad_port(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    r = await cli.put("/api/config", json={"signalk_port": 99999})
    assert r.status == 400
    body = await r.json()
    assert "signalk_port" in body["errors"]


async def test_route_put_and_get(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    wps = [{"name": "A", "lat": 45.0, "lon": 13.0},
           {"name": "B", "lat": 44.0, "lon": 14.0}]
    r = await cli.put("/api/route", json={"waypoints": wps})
    assert r.status == 200
    g = await (await cli.get("/api/route")).json()
    assert g["waypoints"] == wps


async def test_route_put_rejects_one_point(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    r = await cli.put("/api/route", json={"waypoints": [{"name": "x", "lat": 1, "lon": 2}]})
    assert r.status == 400


async def test_status(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    r = await cli.get("/api/status")
    assert r.status == 200
    assert "position" in await r.json()


async def test_token_required_when_set(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token="t0p"))
    assert (await cli.get("/api/config")).status == 401
    ok = await cli.get("/api/config", headers={"X-Sim-Token": "t0p"})
    assert ok.status == 200
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_web_api.py -q`
Expected: FAIL — `web.api` / `make_app` missing.

- [ ] **Step 4: Implement `web/api.py`**

```python
"""aiohttp JSON API for the simulator web admin.

Secrets are write-only: GET masks them as <field>_set booleans; PUT with an
empty string leaves the stored secret unchanged.
"""
from __future__ import annotations

from aiohttp import web

from yey.boats.simulator.engine.route import Route
from yey.boats.simulator.routeio import WaypointError, validate_waypoints

_SECRET_FIELDS = ("signalk_password", "aisstream_api_key")
_SINKS = ("signalk", "stdout", "nmea0183", "nmea2000")
_WEATHER = ("openmeteo", "signalk")


def _config_public(settings) -> dict:
    return {
        "signalk_host": settings.signalk_host,
        "signalk_port": settings.signalk_port,
        "signalk_username": settings.signalk_username,
        "signalk_password_set": bool(settings.signalk_password),
        "aisstream_api_key_set": bool(settings.aisstream_api_key),
        "sink": settings.sink,
        "weather_source": settings.weather_source,
        "failover": settings.failover,
        "data_dir": str(settings.data_dir),
    }


def _validate_config(payload: dict) -> tuple[dict, dict]:
    changes, errors = {}, {}
    if "signalk_host" in payload:
        if not str(payload["signalk_host"]).strip():
            errors["signalk_host"] = "must not be empty"
        else:
            changes["signalk_host"] = str(payload["signalk_host"]).strip()
    if "signalk_port" in payload:
        try:
            port = int(payload["signalk_port"])
            if not (1 <= port <= 65535):
                raise ValueError
            changes["signalk_port"] = port
        except (TypeError, ValueError):
            errors["signalk_port"] = "must be 1..65535"
    for k in ("signalk_username", "data_dir"):
        if k in payload and str(payload[k]).strip():
            changes[k] = str(payload[k]).strip()
    if "sink" in payload:
        if payload["sink"] in _SINKS:
            changes["sink"] = payload["sink"]
        else:
            errors["sink"] = f"must be one of {_SINKS}"
    if "weather_source" in payload:
        if payload["weather_source"] in _WEATHER:
            changes["weather_source"] = payload["weather_source"]
        else:
            errors["weather_source"] = f"must be one of {_WEATHER}"
    if "failover" in payload:
        changes["failover"] = bool(payload["failover"])
    for k in _SECRET_FIELDS:        # empty string => leave unchanged (skip)
        if k in payload and str(payload[k]) != "":
            changes[k] = str(payload[k])
    return changes, errors


def make_app(controller, token: str | None) -> web.Application:
    app = web.Application()

    @web.middleware
    async def auth(request, handler):
        if token is not None and request.path.startswith("/api/"):
            if request.headers.get("X-Sim-Token") != token:
                return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    app.middlewares.append(auth)

    async def get_config(request):
        return web.json_response(_config_public(controller.settings))

    async def put_config(request):
        payload = await request.json()
        changes, errors = _validate_config(payload)
        if errors:
            return web.json_response({"errors": errors}, status=400)
        await controller.apply_config(changes)
        return web.json_response(_config_public(controller.settings))

    async def get_route(request):
        r = controller.route
        wps = r.to_waypoint_dicts() if r is not None else []
        idx = getattr(r, "current_index", 0) if r is not None else 0
        return web.json_response({"waypoints": wps, "current_index": idx})

    async def put_route(request):
        payload = await request.json()
        try:
            valid = validate_waypoints(payload.get("waypoints", []))
        except WaypointError as exc:
            return web.json_response({"errors": {"waypoints": str(exc)}}, status=400)
        await controller.apply_route(Route.from_waypoint_dicts(valid))
        return web.json_response({"waypoints": valid})

    async def import_route(request):
        from yey.boats.simulator.routeio import waypoints_from_geojson
        reader = await request.multipart()
        field = await reader.next()
        raw = await field.read()
        name = (field.filename or "").lower()
        try:
            if name.endswith(".kmz"):
                import io, pathlib, tempfile
                with tempfile.NamedTemporaryFile(suffix=".kmz", delete=False) as fh:
                    fh.write(raw); tmp = pathlib.Path(fh.name)
                wps = Route.load(tmp, None).to_waypoint_dicts()
            else:
                import json
                wps = waypoints_from_geojson(json.loads(raw.decode()))
            wps = validate_waypoints(wps)
        except (WaypointError, Exception) as exc:  # noqa: BLE001
            return web.json_response({"errors": {"file": str(exc)}}, status=400)
        return web.json_response({"waypoints": wps})

    async def get_status(request):
        return web.json_response(controller.status())

    app.router.add_get("/api/config", get_config)
    app.router.add_put("/api/config", put_config)
    app.router.add_get("/api/route", get_route)
    app.router.add_put("/api/route", put_route)
    app.router.add_post("/api/route/import", import_route)
    app.router.add_get("/api/status", get_status)
    return app
```

Note: `Route.load(tmp, None)` is used for KMZ import; if `Route.load` requires a marinas path, pass `resources.marinas_json()` instead of `None` (check the signature — Task A2 read it). Adjust the import handler accordingly.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_web_api.py -q`
Expected: PASS (8 tests). Then `.venv/bin/pytest -q` and `.venv/bin/ruff check src tests`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/yey/boats/simulator/web/ tests/test_web_api.py
git commit -m "feat(web): aiohttp config/route/status/import API with secret masking + token"
```

---

## Task A5: Static serving + server wiring + CLI flags + runner pipeline

**Files:**
- Create: `src/yey/boats/simulator/web/server.py`
- Modify: `src/yey/boats/simulator/cli.py`, `src/yey/boats/simulator/engine/runner.py`
- Test: `tests/test_web_server.py`, extend `tests/` for CLI flags

- [ ] **Step 1: Write the failing test (static fallback + flag parsing)**

Create `tests/test_web_server.py`:

```python
from pathlib import Path

import pytest

from yey.boats.simulator.config import Settings
from yey.boats.simulator.control import SimController
from yey.boats.simulator.web.server import make_full_app, web_settings_from
from yey.boats.simulator.cli import build_settings


def _ctl(tmp_path):
    async def noop(*a):
        import asyncio; await asyncio.sleep(3600)
    return SimController(Settings(), route=None, data_dir=tmp_path, pipeline=noop)


async def test_spa_fallback_serves_index(aiohttp_client, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>sim</title>")
    cli = await aiohttp_client(make_full_app(_ctl(tmp_path), token=None, static_dir=static))
    r = await cli.get("/")
    assert r.status == 200 and "sim" in await r.text()
    deep = await cli.get("/route")          # client-side route -> index fallback
    assert deep.status == 200


async def test_api_still_works_with_static(aiohttp_client, tmp_path):
    static = tmp_path / "static"; static.mkdir()
    (static / "index.html").write_text("x")
    cli = await aiohttp_client(make_full_app(_ctl(tmp_path), token=None, static_dir=static))
    assert (await cli.get("/api/status")).status == 200


def test_web_flags_default_on_loopback():
    ws = web_settings_from(build_settings([]))
    assert ws.enabled is True
    assert ws.host == "127.0.0.1"
    assert ws.port == 8080


def test_web_flags_disable_and_override():
    ws = web_settings_from(build_settings(["--no-web"]))
    assert ws.enabled is False
    ws2 = web_settings_from(build_settings(["--web-port", "9000", "--web-host", "0.0.0.0"]))
    assert ws2.port == 9000 and ws2.host == "0.0.0.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_web_server.py -q`
Expected: FAIL — `web.server` / new CLI flags missing.

- [ ] **Step 3: Implement `web/server.py`**

```python
"""Static SPA serving + a WebSettings holder. Wraps the JSON API from web.api."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from aiohttp import web

from yey.boats.simulator.web.api import make_app


@dataclass
class WebSettings:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080
    token: str | None = None


def web_settings_from(args) -> WebSettings:
    """Build WebSettings from argparse Namespace (see cli.build_settings)."""
    enabled = (not getattr(args, "no_web", False)) and \
        os.environ.get("SIM_WEB_ENABLED", "1") not in ("0", "false", "False")
    host = getattr(args, "web_host", None) or os.environ.get("SIM_WEB_HOST", "127.0.0.1")
    port = getattr(args, "web_port", None) or int(os.environ.get("SIM_WEB_PORT", "8080"))
    token = getattr(args, "web_token", None) or os.environ.get("SIM_WEB_TOKEN") or None
    return WebSettings(enabled=enabled, host=host, port=int(port), token=token)


def default_static_dir() -> Path:
    return Path(__file__).parent / "static"


def make_full_app(controller, token, static_dir: Path) -> web.Application:
    app = make_app(controller, token=token)

    async def index(request):
        return web.FileResponse(static_dir / "index.html")

    # serve built assets, with SPA fallback to index.html for non-/api/ paths
    if (static_dir / "assets").exists():
        app.router.add_static("/assets/", static_dir / "assets")
    app.router.add_get("/", index)

    async def spa_fallback(request):
        if request.path.startswith("/api/"):
            return web.json_response({"error": "not found"}, status=404)
        return web.FileResponse(static_dir / "index.html")

    app.router.add_route("GET", "/{tail:.*}", spa_fallback)
    return app


async def start_web(controller, ws: WebSettings, static_dir: Path | None = None):
    static_dir = static_dir or default_static_dir()
    app = make_full_app(controller, ws.token, static_dir)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, ws.host, ws.port)
    await site.start()
    print(f"[web] admin UI at http://{ws.host}:{ws.port}", flush=True)  # noqa: T201
    return runner
```

- [ ] **Step 4: Add CLI flags in `cli.py`**

In `build_settings`'s parser add:

```python
    p.add_argument("--web-host", default=None)
    p.add_argument("--web-port", type=int, default=None)
    p.add_argument("--web-token", default=None)
    p.add_argument("--no-web", action="store_true", help="disable the web admin UI")
```

Keep `build_settings` returning `Settings` as today, BUT also expose the parsed args. Refactor: split parsing so both Settings and the raw args are available. Change `build_settings` to parse into `args`, build overrides, and **return `Settings`** as before (so existing tests pass), and add a second function:

```python
def parse_args(argv: list[str] | None = None):
    p = _build_parser()
    return p.parse_args(argv)
```

Extract the `ArgumentParser` construction into `_build_parser()` and have both `build_settings` and `parse_args` use it. `web_settings_from` consumes the args Namespace; tests call `build_settings([...])` for Settings and `parse_args` (via `web_settings_from(build_settings(...))` — adjust `web_settings_from` to accept the Namespace; simplest: make `build_settings` attach the namespace, or have `main` call `parse_args` then pass to both). For the tests above, `web_settings_from(build_settings([]))` is used — so make `build_settings` return the Namespace-bearing Settings OR change the test to `web_settings_from(parse_args([]))`. **Decision:** change the plan's tests to use `parse_args`: in `tests/test_web_server.py` replace `build_settings(...)` with `parse_args(...)` for the web-flag tests, and `web_settings_from(parse_args([]))`. Update those three test lines accordingly before implementing.

- [ ] **Step 5: Wire the runner into the controller pipeline + start web in `main`**

Refactor `engine/runner.py`: extract the body of `run(settings)` from "build route/sinks/engine" through `await asyncio.gather(*tasks)` into:

```python
async def pipeline(settings, route, start_pos, report_pos):
    # identical to today's run(), except:
    #  - if `route` is None: load Route.load(...) as today; else use the passed route
    #  - if `start_pos` is not None: use it as (start_lat, start_lon) instead of get_self_position()
    #  - replace the local get_pos()/engine_ref with calls to report_pos((lat, lon)) each tick
    ...
```

Concretely: where today it computes `start_lat,start_lon` from `writer.get_self_position()`, prefer `start_pos` when provided. In `drive()`, after `snap = await engine.tick(now)`, call `report_pos((engine.nav_state.lat, engine.nav_state.lon))`. Keep `route = route or Route.load(resources.route_kmz(), resources.marinas_json())`; load depth profile on it once.

Then rewrite `run(settings)` to use the controller + web server:

```python
async def run(settings: Settings) -> None:
    route = Route.load(resources.route_kmz(), resources.marinas_json())
    route_json = settings.data_dir / "route.json"
    if route_json.exists():
        route = Route.load_json(route_json)
    from yey.boats.simulator.control import SimController
    controller = SimController(settings, route, settings.data_dir, pipeline)
    runner_handle = None
    from yey.boats.simulator.cli import parse_args  # only for env-less default
    # web settings provided by main(); see below
    tasks = [controller.run_forever()]
    await asyncio.gather(*tasks)
```

Update `cli.main` to build web settings and start the server alongside the controller:

```python
def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = build_settings(argv)   # Settings honoring config.json too: see note
    from yey.boats.simulator.engine.runner import run_with_web
    asyncio.run(run_with_web(settings, args))
```

Add `run_with_web(settings, args)` to `runner.py` that: builds the controller, and if `web_settings_from(args).enabled`, calls `start_web(controller, ws)` before `await controller.run_forever()`.

**config.json wiring:** in `build_settings`, pass `config_path=Path(data_dir)/"config.json"` to `Settings.from_env` so persisted config loads on start. Compute `data_dir` from args/env first (it already is), then `Settings.from_env(config_path=<data_dir>/"config.json", **overrides)`.

- [ ] **Step 6: Run tests + full suite + lint**

Run: `.venv/bin/pytest -q` (all green, incl. new web-server tests) and `.venv/bin/ruff check src tests`.

- [ ] **Step 7: Manual smoke (stdout sink, web on)**

Run: `.venv/bin/yey-boats-sim --sink stdout --no-failover --web-port 8080 &` then `curl -s localhost:8080/api/status` → JSON; `curl -s localhost:8080/api/config` → masked config. Kill the process.

- [ ] **Step 8: Commit**

```bash
git add src/yey/boats/simulator/web/server.py src/yey/boats/simulator/cli.py src/yey/boats/simulator/engine/runner.py tests/test_web_server.py
git commit -m "feat(web): static SPA serving, --web flags, runner pipeline via SimController"
```

---

# Phase B — Frontend (React + Tailwind + Vite)

> **Visual + interaction design for Tasks B3–B5 is produced via the frontend-design skill.** These tasks specify the API contract, component responsibilities, state, and acceptance — the implementer invokes frontend-design to generate the polished, distinctive UI (not generic AI styling). Tasks B1–B2 are concrete scaffolding.

## Task B1: Vite + React + TS + Tailwind scaffold

**Files:** Create `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tailwind.config.js`, `frontend/postcss.config.js`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/index.css`, `frontend/.gitignore`

- [ ] **Step 1: Create the scaffold files**

`frontend/package.json`:
```json
{
  "name": "yey-boats-sim-web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-leaflet": "^4.2.1",
    "leaflet": "^1.9.4"
  },
  "devDependencies": {
    "@types/leaflet": "^1.9.12",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.19",
    "postcss": "^8.4.39",
    "tailwindcss": "^3.4.6",
    "typescript": "^5.5.3",
    "vite": "^5.3.4"
  }
}
```

`frontend/vite.config.ts` — build into the Python package and proxy /api in dev:
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("../src/yey/boats/simulator/web/static", import.meta.url)),
    emptyOutDir: true,
  },
  server: { proxy: { "/api": "http://127.0.0.1:8080" } },
});
```

`frontend/tailwind.config.js`:
```js
export default { content: ["./index.html", "./src/**/*.{ts,tsx}"], theme: { extend: {} }, plugins: [] };
```

`frontend/postcss.config.js`:
```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020", "useDefineForClassFields": true, "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext", "skipLibCheck": true, "moduleResolution": "bundler",
    "resolveJsonModule": true, "isolatedModules": true, "noEmit": true, "jsx": "react-jsx",
    "strict": true, "noUnusedLocals": true, "noUnusedParameters": true
  },
  "include": ["src"]
}
```

`frontend/index.html`:
```html
<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Boat Simulator — Admin</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
```

`frontend/src/index.css`:
```css
@tailwind base; @tailwind components; @tailwind utilities;
@import "leaflet/dist/leaflet.css";
```

`frontend/src/main.tsx`:
```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import App from "./App";
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
```

`frontend/.gitignore`:
```
node_modules
```
(Note: the build output `src/yey/boats/simulator/web/static/` should also be git-ignored — add it to the repo root `.gitignore`.)

- [ ] **Step 2: Install + verify a minimal build**

Add a temporary `frontend/src/App.tsx` returning `<div>hello</div>`. Then:
Run: `cd frontend && npm install && npm run build`
Expected: build succeeds; `src/yey/boats/simulator/web/static/index.html` produced.

- [ ] **Step 3: Commit**

```bash
git add frontend/ .gitignore
git commit -m "build(web): Vite + React + TS + Tailwind scaffold building into the package"
```

## Task B2: API client + types

**Files:** Create `frontend/src/api.ts`

- [ ] **Step 1: Implement the typed client**

```ts
export type Config = {
  signalk_host: string; signalk_port: number; signalk_username: string;
  signalk_password_set: boolean; aisstream_api_key_set: boolean;
  sink: string; weather_source: string; failover: boolean; data_dir: string;
};
export type Waypoint = { name: string; lat: number; lon: number };
export type Status = {
  running: boolean; sink: string; weather_source: string; signalk: string;
  position: { lat: number; lon: number } | null; last_error: string | null;
};

const token = () => localStorage.getItem("sim_token") || "";
const headers = () => {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token()) h["X-Sim-Token"] = token();
  return h;
};
async function j("GET", path) ... // see below

async function req(method: string, path: string, body?: unknown) {
  const r = await fetch(path, { method, headers: headers(),
    body: body === undefined ? undefined : JSON.stringify(body) });
  if (!r.ok) throw await r.json().catch(() => ({ error: r.statusText }));
  return r.json();
}

export const api = {
  getConfig: (): Promise<Config> => req("GET", "/api/config"),
  putConfig: (c: Partial<Config> & { signalk_password?: string; aisstream_api_key?: string }) =>
    req("PUT", "/api/config", c) as Promise<Config>,
  getRoute: (): Promise<{ waypoints: Waypoint[]; current_index: number }> => req("GET", "/api/route"),
  putRoute: (waypoints: Waypoint[]) => req("PUT", "/api/route", { waypoints }),
  getStatus: (): Promise<Status> => req("GET", "/api/status"),
  importRoute: async (file: File): Promise<{ waypoints: Waypoint[] }> => {
    const fd = new FormData(); fd.append("file", file);
    const h: Record<string, string> = {}; if (token()) h["X-Sim-Token"] = token();
    const r = await fetch("/api/route/import", { method: "POST", body: fd, headers: h });
    if (!r.ok) throw await r.json().catch(() => ({ error: r.statusText }));
    return r.json();
  },
};
```

(Remove the stray `async function j(...)` placeholder line; it is illustrative — the real export is `req` + `api`.)

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc -b`
Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat(web): typed API client (config/route/status/import)"
```

## Task B3: App shell + tabs + status strip (frontend-design)

**Files:** Create `frontend/src/App.tsx`, `frontend/src/tabs/StatusStrip.tsx`

- [ ] **Step 1: Invoke frontend-design** for the overall app shell: a top **status strip** (connection state, SignalK target, active sink, boat position — polls `api.getStatus()` every 1500 ms; green/amber/red dot for running/last_error) and a **tab switcher** for Connection / Route / Status. Provide the design these constraints: dark, instrument-panel aesthetic appropriate to a marine MFD tool; Tailwind only; no extra UI libs.
- [ ] **Step 2: Implement** `App.tsx` (tab state + renders `<ConfigTab/>`, `<RouteTab/>`, and a Status panel) and `StatusStrip.tsx` (the polling indicator). Use `api` from Task B2.
- [ ] **Step 3: Acceptance** — `cd frontend && npm run build` succeeds; loading the app against a running sim shows the live status strip updating and tab navigation works (manual). Commit:
```bash
git add frontend/src/App.tsx frontend/src/tabs/StatusStrip.tsx
git commit -m "feat(web): app shell, tab switcher, live status strip"
```

## Task B4: Connection / Config tab (frontend-design)

**Files:** Create `frontend/src/tabs/ConfigTab.tsx`

- [ ] **Step 1: Invoke frontend-design** for a config form: fields for SignalK host/port/username/password, AISStream API key, sink (select from signalk/stdout/nmea0183/nmea2000), weather_source (openmeteo/signalk), failover (toggle), data_dir. Secrets render as "Set / Not set" with an "Update" affordance (empty submit = unchanged). A Save button posts the diff.
- [ ] **Step 2: Implement** — load via `api.getConfig()`; submit changed fields via `api.putConfig()`; render server `errors` map inline (400 response); on success, show a "applied (sim restarting)" toast and refresh status. Empty secret fields are omitted from the PUT body.
- [ ] **Step 3: Acceptance** — build succeeds; editing host + saving calls PUT and the status strip reflects the new SignalK target after live-apply (manual). Commit:
```bash
git add frontend/src/tabs/ConfigTab.tsx
git commit -m "feat(web): connection/config tab with masked secrets + inline validation"
```

## Task B5: Route tab — list + upload + map (frontend-design)

**Files:** Create `frontend/src/tabs/RouteTab.tsx`, `frontend/src/tabs/RouteMap.tsx`

- [ ] **Step 1: Invoke frontend-design** for the route editor. One waypoint model (`Waypoint[]`) shared by three sub-modes selectable via a segmented control: **List** (editable rows name/lat/lon, add/remove/reorder via up/down), **Upload** (file input → `api.importRoute(file)` → preview → "Replace" applies to the list), **Map** (`RouteMap.tsx`: react-leaflet `MapContainer` + OSM `TileLayer`, a `Polyline` through waypoints, draggable `Marker`s, click-on-map to append, click-marker to remove). A single **Save route** button persists via `api.putRoute(waypoints)`.
- [ ] **Step 2: Implement** `RouteMap.tsx` (leaflet glue: markers/polyline two-way bound to the `waypoints` prop + `onChange`) and `RouteTab.tsx` (mode switch, shared state, save). Fix the known leaflet marker-icon asset issue by setting `L.Icon.Default` image URLs (import from `leaflet/dist/images`) or a small `divIcon`.
- [ ] **Step 3: Acceptance** — build succeeds; can add/edit/reorder rows, import a sample GeoJSON, drag a marker on the map, and Save (PUT /api/route returns 200); the boat re-routes live (manual). Commit:
```bash
git add frontend/src/tabs/RouteTab.tsx frontend/src/tabs/RouteMap.tsx
git commit -m "feat(web): route tab — list + file-import + leaflet map editor"
```

---

# Phase C — Packaging, Docker, CI

## Task C1: Ship the built SPA in the wheel

**Files:** Modify `pyproject.toml`, repo-root `.gitignore`

- [ ] **Step 1:** Add to `.gitignore`: `src/yey/boats/simulator/web/static/`.
- [ ] **Step 2:** In `pyproject.toml`, force-include the built static dir so it ships even though git-ignored:
```toml
[tool.hatch.build.targets.wheel.force-include]
"src/yey/boats/simulator/web/static" = "yey/boats/simulator/web/static"
```
- [ ] **Step 3:** Verify: `cd frontend && npm run build && cd .. && .venv/bin/python -m build --wheel` then `unzip -l dist/*.whl | grep web/static/index.html` shows the file.
- [ ] **Step 4: Commit**
```bash
git add pyproject.toml .gitignore
git commit -m "build: ship built web SPA in the wheel via hatch force-include"
```

## Task C2: Dockerfile node build stage

**Files:** Modify `Dockerfile`, `.dockerignore`

- [ ] **Step 1:** Add a node stage before the python build and copy its output in. New `Dockerfile`:
```dockerfile
# syntax=docker/dockerfile:1
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build   # writes to /src/yey/.../web/static via vite outDir? No — see note

FROM python:3.12-slim AS build
WORKDIR /build
RUN pip install --no-cache-dir build hatchling
COPY . .
# bring in the built SPA from the web stage
COPY --from=web /src/yey/boats/simulator/web/static ./src/yey/boats/simulator/web/static
RUN python -m build --wheel --outdir /dist

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 SINK=signalk DATA_DIR=/data SIM_WEB_HOST=0.0.0.0
RUN useradd -u 1000 -m sim && mkdir -p /data && chown sim:sim /data
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
USER sim
EXPOSE 8080
VOLUME ["/data"]
ENTRYPOINT ["yey-boats-sim"]
```
**Note on the web stage output path:** vite's `outDir` points outside `/web` (`../src/...`), which won't exist in the node stage. For Docker, set the build to emit into `/web/dist` and copy from there. Add an env-overridable outDir: in `vite.config.ts`, `outDir: process.env.VITE_OUT_DIR || fileURLToPath(new URL("../src/yey/boats/simulator/web/static", import.meta.url))`. In the Dockerfile web stage, `RUN VITE_OUT_DIR=/web/dist npm run build` and `COPY --from=web /web/dist ./src/yey/boats/simulator/web/static`. Update the stage accordingly.
- [ ] **Step 2:** Ensure `.dockerignore` does not exclude `frontend/`; do exclude `frontend/node_modules` and `src/yey/boats/simulator/web/static` (rebuilt in-image).
- [ ] **Step 3:** Verify: `docker build -t sim:web .` succeeds and `docker run --rm sim:web --sink stdout --no-failover --no-web` prints ticks.
- [ ] **Step 4: Commit**
```bash
git add Dockerfile .dockerignore frontend/vite.config.ts
git commit -m "build(docker): node stage builds SPA into the image"
```

## Task C3: CI frontend build

**Files:** Modify `.github/workflows/ci.yml`

- [ ] **Step 1:** In the `test` job, before `python -m build --wheel`, build the SPA so the wheel includes it:
```yaml
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: npm install
        working-directory: frontend
      - run: npm run build
        working-directory: frontend
```
Place these steps after `pytest -q` and before the `pip install build && python -m build --wheel` step. (The existing `docker-smoke` and `publish-image` jobs already build the image, which now includes the node stage — no change needed there beyond the Dockerfile.)
- [ ] **Step 2:** Verify locally the YAML is valid (`python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"`).
- [ ] **Step 3: Commit**
```bash
git add .github/workflows/ci.yml
git commit -m "ci: build the web SPA before packaging the wheel"
```

---

## Self-Review

**Spec coverage:**
- Config-file layer + precedence (CLI>env>file>defaults) → A1. ✓
- Secret masking on read / write-only → A4 (`_config_public`, `_validate_config`). ✓
- SignalK connection + AISStream key + sink/weather/failover/data-dir editing → A4 + B4. ✓
- Route: list + upload(KMZ/GeoJSON) + map → A2 (parse/persist), A4 (`/api/route*`), B5. ✓
- Live-apply via in-process pipeline restart + position carry-over → A3 + A5 (`report_pos`, `start_pos`). ✓
- aiohttp on the engine loop → A4/A5 (`start_web`, `AppRunner`). ✓
- `/api/status` polled → A4 + B3. ✓
- Exposure: default loopback:8080, `--no-web`/`--web-*`/env, optional token → A5 + A4 (auth mw). ✓
- React+Tailwind+Vite, three tabs, map via react-leaflet → B1–B5. ✓
- Packaging: hatch force-include, Dockerfile node stage, CI build → C1–C3. ✓
- Testing: config/route/api/control pytest + Vite build check → A1–A5 tests, C3. ✓

**Placeholder scan:** `frontend/src/api.ts` Task B2 contains an intentionally-flagged stray illustrative line (`async function j(...)`) with a note to remove it — the real exports are `req`+`api`. The `pipeline`/`run_with_web` refactor in A5 references today's `run()` body explicitly (extract-and-adapt, with the three concrete deltas named). No other placeholders.

**Type consistency:** waypoint dict shape `{name,lat,lon}` consistent across A2/A4/B2. `report_pos`/`start_pos` controller↔pipeline signature consistent (A3 fake + A5 real both `(settings, route, start_pos, report_pos)`). `WebSettings`/`web_settings_from` used in A5 tests + `main`. `make_app(controller, token)` (A4) wrapped by `make_full_app(controller, token, static_dir)` (A5). Config public keys (`*_set` booleans) consistent A4↔B2 `Config` type.

**Note for executor:** B3–B5 invoke the **frontend-design** skill for the actual component UI; the steps fix the API contract + acceptance, not the visual code. A5 Step 4 asks you to adjust three test lines in `tests/test_web_server.py` to use `parse_args` — do that edit as part of A5 before implementing.
