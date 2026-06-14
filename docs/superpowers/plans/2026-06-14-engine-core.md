# Phase C Engine Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the simulator into a hexagonal architecture — a deterministic, I/O-isolated `Engine.tick(now) -> TelemetrySnapshot` that pulls all external data through injected async ports (`DataSource`, `AISSource`), with AIS folded into the frame, plus a real `SignalKDataSource`; the runner becomes a thin driver owning only the clock, cadence, sinks, and SignalK side-tasks.

**Architecture:** Big-bang extraction. The verbatim physics body moves from `runner.sim_loop` into `Engine.tick`; weather/AIS come from injected ports; the driver constructs ports + engine, runs the 1 Hz loop, and publishes snapshots. The engine never reads the wall clock, opens a socket, or calls a sink. Engine unit tests (fake ports + injected clock) and the stdout smoke are the regression gate.

**Tech Stack:** Python 3.12 async, structural `Protocol` ports, pytest + pytest-asyncio. Repo `yey-boats-simulator`, branch `feat/engine-core`.

---

## Conventions (every task)

- Work in `/Users/borissorochkin/code/embedded/yey.boats-simulator` on branch `feat/engine-core`; venv `.venv`; tests via `.venv/bin/pytest`.
- **Lint hook:** in TEST files put `# noqa: S101` on every `assert` and `# type: ignore[import]` on local-package imports (incl. `pytest`). Keep non-test code ruff-clean; reuse the module-level `# ruff: noqa: T201,BLE001,S110` header pattern where prints/broad-excepts are intentional (as in the existing engine modules).
- **Commit discipline:** every task ends with a commit; then run `git log --oneline -1` to capture the SHA.
- Spec: `docs/superpowers/specs/2026-06-14-engine-core-design.md`.

---

## Task 1: AisContact model + snapshot field

**Files:**
- Modify: `src/yey/boats/simulator/engine/snapshot.py`
- Test: `tests/test_ais_contact.py`

- [ ] **Step 1: Write the failing test** — `tests/test_ais_contact.py`:

```python
from yey.boats.simulator.engine.snapshot import AisContact, TelemetrySnapshot  # type: ignore[import]


def test_ais_contact_fields():
    c = AisContact(mmsi="247100111", lat=45.1, lon=13.2, cog_deg=90.0,
                   sog_kts=11.0, name="MV Adriatic Star", ship_type=70)
    assert c.mmsi == "247100111"  # noqa: S101
    assert c.ship_type == 70  # noqa: S101


def test_snapshot_ais_contacts_defaults_empty():
    from datetime import datetime, timezone
    snap = TelemetrySnapshot(
        nav=object(), elec=object(), sys=object(), lights=object(), wx=object(),
        state=object(), utc_now=datetime.now(timezone.utc), temps={},
        next_wp=None, route_href="", point_index=0)
    assert snap.ais_contacts == []  # noqa: S101
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_ais_contact.py -q`
Expected: FAIL — `ImportError: cannot import name 'AisContact'`.

- [ ] **Step 3: Implement** — in `src/yey/boats/simulator/engine/snapshot.py`, add the `AisContact` dataclass above `TelemetrySnapshot`, and add the `ais_contacts` field at the END of `TelemetrySnapshot` (after `distance_to_next_nm`). Add `field` to the dataclasses import.

```python
from dataclasses import dataclass, field
```

```python
@dataclass
class AisContact:
    mmsi: str
    lat: float
    lon: float
    cog_deg: float
    sog_kts: float
    name: str
    ship_type: int
```

Add as the last field of `TelemetrySnapshot`:
```python
    ais_contacts: list[AisContact] = field(default_factory=list)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_ais_contact.py -q`
Expected: PASS.

- [ ] **Step 5: Run full suite + commit**

```bash
.venv/bin/pytest -q
git add -A && git commit -m "feat: AisContact model + ais_contacts on TelemetrySnapshot"
git log --oneline -1
```

---

## Task 2: Widen DataSource port + add AISSource port

**Files:**
- Modify: `src/yey/boats/simulator/ports/__init__.py`
- Test: `tests/test_ports_phase_c.py`

- [ ] **Step 1: Write the failing test** — `tests/test_ports_phase_c.py`:

```python
from yey.boats.simulator.ports import DataSource, AISSource  # type: ignore[import]


class _DS:
    async def get_weather(self, lat, lon, now): ...
    async def twd_shift_next_6h(self, lat, lon, now): ...
    async def mean_tws_next_6h(self, lat, lon, now): ...


class _AIS:
    async def start(self): ...
    def get_contacts(self, lat, lon): return []


def test_datasource_structural():
    assert isinstance(_DS(), DataSource)  # noqa: S101


def test_aissource_structural():
    assert isinstance(_AIS(), AISSource)  # noqa: S101
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_ports_phase_c.py -q`
Expected: FAIL — `ImportError: cannot import name 'AISSource'`.

- [ ] **Step 3: Implement** — in `src/yey/boats/simulator/ports/__init__.py`, REPLACE the existing `DataSource` Protocol with the widened one and ADD `AISSource`. Add `AisContact` to the snapshot import line.

```python
from yey.boats.simulator.engine.snapshot import AisContact, TelemetrySnapshot  # type: ignore[import]
```

```python
@runtime_checkable
class DataSource(Protocol):
    async def get_weather(self, lat: float, lon: float, now: Any) -> Any: ...
    async def twd_shift_next_6h(self, lat: float, lon: float, now: Any) -> float: ...
    async def mean_tws_next_6h(self, lat: float, lon: float, now: Any) -> float: ...


@runtime_checkable
class AISSource(Protocol):
    async def start(self) -> None:
        """Long-running; maintains a live in-range contact set."""

    def get_contacts(self, lat: float, lon: float) -> list[AisContact]:
        """Synchronous snapshot of current in-range contacts."""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_ports_phase_c.py -q`
Expected: PASS.

- [ ] **Step 5: Run full suite + commit**

```bash
.venv/bin/pytest -q
git add -A && git commit -m "feat: widen DataSource port (weather + lookaheads); add AISSource port"
git log --oneline -1
```

---

## Task 3: OpenMeteoDataSource

**Files:**
- Create: `src/yey/boats/simulator/sources/open_meteo.py`
- Test: `tests/test_open_meteo_source.py`

- [ ] **Step 1: Write the failing test** — `tests/test_open_meteo_source.py`:

```python
import pytest

from yey.boats.simulator.sources.open_meteo import OpenMeteoDataSource  # type: ignore[import]


class FakeFetcher:
    async def get(self, lat, lon, now): return ("wx", lat, lon)
    async def twd_shift_next_6h(self, lat, lon, now): return 12.0
    async def mean_tws_next_6h(self, lat, lon, now): return 9.0


@pytest.mark.asyncio
async def test_forwards_to_fetcher():
    src = OpenMeteoDataSource(fetcher=FakeFetcher())
    assert await src.get_weather(45.0, 13.0, "now") == ("wx", 45.0, 13.0)  # noqa: S101
    assert await src.twd_shift_next_6h(45.0, 13.0, "now") == 12.0  # noqa: S101
    assert await src.mean_tws_next_6h(45.0, 13.0, "now") == 9.0  # noqa: S101
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_open_meteo_source.py -q`
Expected: FAIL — `ModuleNotFoundError: ...sources.open_meteo`.

- [ ] **Step 3: Implement** — `src/yey/boats/simulator/sources/open_meteo.py`:

```python
"""DataSource backed by Open-Meteo (wraps the existing WeatherFetcher)."""
from __future__ import annotations

from typing import Any

from yey.boats.simulator.engine.weather import WeatherFetcher  # type: ignore[import]


class OpenMeteoDataSource:
    def __init__(self, fetcher: Any = None) -> None:
        self._fetcher = fetcher if fetcher is not None else WeatherFetcher()

    async def get_weather(self, lat: float, lon: float, now: Any) -> Any:
        return await self._fetcher.get(lat, lon, now)

    async def twd_shift_next_6h(self, lat: float, lon: float, now: Any) -> float:
        return await self._fetcher.twd_shift_next_6h(lat, lon, now)

    async def mean_tws_next_6h(self, lat: float, lon: float, now: Any) -> float:
        return await self._fetcher.mean_tws_next_6h(lat, lon, now)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_open_meteo_source.py -q`
Expected: PASS.

- [ ] **Step 5: Run full suite + commit**

```bash
.venv/bin/pytest -q
git add -A && git commit -m "feat: OpenMeteoDataSource (wraps WeatherFetcher as a DataSource port)"
git log --oneline -1
```

---

## Task 4: SignalKDataSource

Reads current weather from a SignalK server's `environment.*` paths and builds a `WeatherPoint`; forecasts are neutral (SignalK has none); degrades on failure. `WeatherPoint` (engine/weather.py) requires keyword fields including `tws_ms, twd_deg, gust_ms, cloud_cover, wave_height_m, wave_period_s, wave_dir_deg, temp_c, pressure_pa, humidity` (see `DEFAULT_WEATHER`).

**Files:**
- Create: `src/yey/boats/simulator/sources/signalk_weather.py`
- Test: `tests/test_signalk_weather_source.py`

- [ ] **Step 1: Write the failing test** — `tests/test_signalk_weather_source.py`:

```python
import pytest

from yey.boats.simulator.sources.signalk_weather import SignalKDataSource  # type: ignore[import]


@pytest.mark.asyncio
async def test_builds_weatherpoint_from_sk_env(monkeypatch):
    src = SignalKDataSource(host="h", port=3000)

    async def fake_read(path):  # SI units as SignalK serves them
        return {
            "environment.wind.speedTrue": 5.0,          # m/s
            "environment.wind.directionTrue": 3.665,     # rad (~210 deg)
            "environment.outside.temperature": 291.15,   # K (=18 C)
        }.get(path)

    monkeypatch.setattr(src, "_read_path", fake_read)
    wx = await src.get_weather(45.0, 13.0, "now")
    tws, twd = wx.sample()
    assert round(tws, 1) == round(5.0 * 1.94384, 1)  # noqa: S101  m/s -> kts
    assert round(twd) == 210  # noqa: S101
    assert round(wx.temp_c) == 18  # noqa: S101


@pytest.mark.asyncio
async def test_forecasts_are_neutral(monkeypatch):
    src = SignalKDataSource(host="h", port=3000)

    async def fake_read(path):
        return 6.0 if path == "environment.wind.speedTrue" else None

    monkeypatch.setattr(src, "_read_path", fake_read)
    assert await src.twd_shift_next_6h(45.0, 13.0, "now") == 0.0  # noqa: S101
    mean = await src.mean_tws_next_6h(45.0, 13.0, "now")
    assert round(mean, 1) == round(6.0 * 1.94384, 1)  # noqa: S101  current TWS in kts


@pytest.mark.asyncio
async def test_degrades_on_read_failure(monkeypatch):
    src = SignalKDataSource(host="h", port=3000)

    async def boom(path):
        raise RuntimeError("sk down")

    monkeypatch.setattr(src, "_read_path", boom)
    wx = await src.get_weather(45.0, 13.0, "now")  # must not raise
    assert wx is not None  # noqa: S101
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_signalk_weather_source.py -q`
Expected: FAIL — `ModuleNotFoundError: ...sources.signalk_weather`.

- [ ] **Step 3: Implement** — `src/yey/boats/simulator/sources/signalk_weather.py`:

```python
"""DataSource backed by a SignalK server's live environment readings.

Use case: drive the sim's physics from a real boat's instrument data. SignalK
serves SI units (m/s, radians, kelvin) and has no forecast, so the 6 h lookahead
methods return neutral values. All reads degrade to DEFAULT_WEATHER/neutral and
never raise into the engine.
"""
from __future__ import annotations

import math
from typing import Any

import httpx  # type: ignore[import]

from yey.boats.simulator.engine.weather import DEFAULT_WEATHER, WeatherPoint  # type: ignore[import]

_MS_TO_KTS = 1.94384


class SignalKDataSource:
    def __init__(self, host: str = "localhost", port: int = 3000) -> None:
        self._host = host
        self._port = port

    async def _read_path(self, path: str) -> Any:
        """Read a single SignalK self value (SI units), or None on absence/error."""
        dotted = path.replace(".", "/")
        url = f"http://{self._host}:{self._port}/signalk/v1/api/vessels/self/{dotted}"
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=6)
            r.raise_for_status()
            data = r.json()
        if isinstance(data, dict):
            return data.get("value", data)
        return data

    async def _current_tws_kts(self) -> float:
        ms = await self._read_path("environment.wind.speedTrue")
        return float(ms) * _MS_TO_KTS if ms is not None else DEFAULT_WEATHER.sample()[0]

    async def get_weather(self, lat: float, lon: float, now: Any) -> WeatherPoint:
        try:
            speed = await self._read_path("environment.wind.speedTrue")
            direction = await self._read_path("environment.wind.directionTrue")
            temp_k = await self._read_path("environment.outside.temperature")
        except Exception:  # noqa: BLE001
            return DEFAULT_WEATHER
        tws_ms = float(speed) if speed is not None else DEFAULT_WEATHER.tws_ms
        twd_deg = math.degrees(float(direction)) % 360 if direction is not None else DEFAULT_WEATHER.twd_deg
        temp_c = (float(temp_k) - 273.15) if temp_k is not None else DEFAULT_WEATHER.temp_c
        return WeatherPoint(
            tws_ms=tws_ms, twd_deg=twd_deg, gust_ms=tws_ms * 1.3,
            cloud_cover=DEFAULT_WEATHER.cloud_cover,
            wave_height_m=DEFAULT_WEATHER.wave_height_m,
            wave_period_s=DEFAULT_WEATHER.wave_period_s,
            wave_dir_deg=twd_deg, temp_c=temp_c,
            pressure_pa=DEFAULT_WEATHER.pressure_pa, humidity=DEFAULT_WEATHER.humidity)

    async def twd_shift_next_6h(self, lat: float, lon: float, now: Any) -> float:
        return 0.0  # no forecast from SignalK

    async def mean_tws_next_6h(self, lat: float, lon: float, now: Any) -> float:
        try:
            return await self._current_tws_kts()
        except Exception:  # noqa: BLE001
            return DEFAULT_WEATHER.sample()[0]
```

Note: confirm `WeatherPoint`'s exact field names/defaults by reading `engine/weather.py` lines 30–62; the constructor call above must match `DEFAULT_WEATHER`'s kwargs exactly. If a field name differs, correct the call and the `DEFAULT_WEATHER.<field>` references to match.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_signalk_weather_source.py -q`
Expected: PASS.

- [ ] **Step 5: Run full suite + commit**

```bash
.venv/bin/pytest -q
git add -A && git commit -m "feat: SignalKDataSource (weather from SK env paths; neutral forecasts; degrades)"
git log --oneline -1
```

---

## Task 5: AIS sources (synthetic + AISStream)

Refactor `synthetic_ais`/`ais_relay` logic into `AISSource` adapters that maintain contacts and answer `get_contacts(lat, lon) -> list[AisContact]` instead of writing to the SK writer. Reuse the pure helpers from the existing modules (`_offset`, `_FLEET`, `_RESPAWN_NM` from synthetic; `_parse_ais_message`, `_bbox_for`, `_within_20nm`, `SELF_MMSI` from relay).

**Files:**
- Create: `src/yey/boats/simulator/sources/ais.py`
- Test: `tests/test_ais_sources.py`

- [ ] **Step 1: Write the failing test** — `tests/test_ais_sources.py`:

```python
from yey.boats.simulator.engine.snapshot import AisContact  # type: ignore[import]
from yey.boats.simulator.sources.ais import SyntheticAISSource, AISStreamSource  # type: ignore[import]


def test_synthetic_get_contacts_returns_contacts():
    src = SyntheticAISSource(get_pos=lambda: (45.0, 13.0))
    src.seed(45.0, 13.0)                       # spawn fleet around own ship
    contacts = src.get_contacts(45.0, 13.0)
    assert len(contacts) >= 1  # noqa: S101
    assert all(isinstance(c, AisContact) for c in contacts)  # noqa: S101
    assert all(c.mmsi for c in contacts)  # noqa: S101


def test_synthetic_advance_moves_vessels():
    src = SyntheticAISSource(get_pos=lambda: (45.0, 13.0))
    src.seed(45.0, 13.0)
    before = src.get_contacts(45.0, 13.0)[0]
    for _ in range(50):
        src.advance(45.0, 13.0)
    after = src.get_contacts(45.0, 13.0)[0]
    assert (before.lat, before.lon) != (after.lat, after.lon)  # noqa: S101


def test_aisstream_get_contacts_filters_range():
    src = AISStreamSource(get_pos=lambda: (45.0, 13.0))
    # near (within 20 nm) and far contact pre-seeded into the map
    src._contacts = {
        "111": AisContact("111", 45.05, 13.05, 90.0, 10.0, "Near", 70),
        "222": AisContact("222", 48.0, 16.0, 90.0, 10.0, "Far", 70),
    }
    out = src.get_contacts(45.0, 13.0)
    mmsis = {c.mmsi for c in out}
    assert "111" in mmsis  # noqa: S101
    assert "222" not in mmsis  # noqa: S101
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_ais_sources.py -q`
Expected: FAIL — `ModuleNotFoundError: ...sources.ais`.

- [ ] **Step 3: Implement** — `src/yey/boats/simulator/sources/ais.py`:

```python
# ruff: noqa: T201,S311,BLE001
"""AISSource adapters: maintain a live in-range contact set and answer
get_contacts(lat, lon). Synthetic generates local traffic; AISStream relays a
real feed. Neither writes to SignalK — the engine folds contacts into the frame.
"""
from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Callable

import websockets  # type: ignore[import]

from yey.boats.simulator.engine.ais_relay import (  # type: ignore[import]
    AIS_WS_URL, SELF_MMSI, _bbox_for, _parse_ais_message)
from yey.boats.simulator.engine.route import haversine_nm  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import AisContact  # type: ignore[import]
from yey.boats.simulator.engine.synthetic_ais import (  # type: ignore[import]
    _FLEET, _RESPAWN_NM, _offset)

_RANGE_NM = 20.0


class SyntheticAISSource:
    def __init__(self, get_pos: Callable[[], tuple[float, float]], dt: float = 3.0,
                 api_key: str = "") -> None:
        self._get_pos = get_pos
        self._dt = dt
        self._vessels: list[dict] = []

    def _spawn(self, spec: dict, olat: float, olon: float, converging: bool) -> dict:
        brg = random.uniform(0, 360)
        dist = random.uniform(4.0, 9.0)
        lat, lon = _offset(olat, olon, brg, dist)
        cog = (brg + 180 + random.uniform(-25, 25)) % 360 if converging else random.uniform(0, 360)
        return {"mmsi": spec["mmsi"], "name": spec["name"], "type": spec["type"],
                "lat": lat, "lon": lon, "cog": cog,
                "sog": spec["sog"] * random.uniform(0.8, 1.1)}

    def seed(self, olat: float, olon: float) -> None:
        self._vessels = [self._spawn(spec, olat, olon, converging=(i == 0))
                         for i, spec in enumerate(_FLEET)]

    def advance(self, olat: float, olon: float) -> None:
        for v in self._vessels:
            d = v["sog"] * (self._dt / 3600.0)
            v["lat"], v["lon"] = _offset(v["lat"], v["lon"], v["cog"], d)
            if haversine_nm(olat, olon, v["lat"], v["lon"]) > _RESPAWN_NM:
                v.update(self._spawn(v, olat, olon, converging=True))

    def get_contacts(self, lat: float, lon: float) -> list[AisContact]:
        return [AisContact(v["mmsi"], v["lat"], v["lon"], v["cog"], v["sog"],
                           v["name"], v["type"]) for v in self._vessels]

    async def start(self) -> None:
        olat, olon = self._get_pos()
        self.seed(olat, olon)
        print(f"[synth-ais] generating {len(self._vessels)} synthetic vessels")
        while True:
            olat, olon = self._get_pos()
            self.advance(olat, olon)
            await asyncio.sleep(self._dt)


class AISStreamSource:
    def __init__(self, get_pos: Callable[[], tuple[float, float]], api_key: str = "") -> None:
        self._get_pos = get_pos
        self._api_key = api_key
        self._contacts: dict[str, AisContact] = {}

    def get_contacts(self, lat: float, lon: float) -> list[AisContact]:
        return [c for c in self._contacts.values()
                if haversine_nm(lat, lon, c.lat, c.lon) < _RANGE_NM]

    async def start(self) -> None:
        if not self._api_key:
            print("[AIS] AISSTREAM_API_KEY not set — AIS relay disabled")
            return
        while True:
            try:
                await self._stream()
            except Exception as exc:
                print(f"[AIS] disconnected: {exc!r}, retry 15s")
                await asyncio.sleep(15)

    async def _stream(self) -> None:
        lat, lon = self._get_pos()
        sub = json.dumps({"APIKey": self._api_key, "BoundingBoxes": [_bbox_for(lat, lon)]})
        async with websockets.connect(AIS_WS_URL) as ws:
            await ws.send(sub)
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "ERROR" in msg:
                    print(f"[AIS] server error: {msg['ERROR']}")
                    return
                v = _parse_ais_message(msg)
                if v is None or v["mmsi"] == SELF_MMSI:
                    continue
                self._contacts[v["mmsi"]] = AisContact(
                    v["mmsi"], v["lat"], v["lon"], v["cog_deg"], v["sog_kts"],
                    v["name"], v["ship_type"])
```

Note: confirm the helper names `_offset`, `_FLEET`, `_RESPAWN_NM` exist in `synthetic_ais.py` and `_parse_ais_message`, `_bbox_for`, `AIS_WS_URL`, `SELF_MMSI` exist in `ais_relay.py` (they do — see those modules). If any is named differently, fix the import.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_ais_sources.py -q`
Expected: PASS.

- [ ] **Step 5: Run full suite + commit**

```bash
.venv/bin/pytest -q
git add -A && git commit -m "feat: AIS sources (synthetic + AISStream) maintaining contacts for the frame"
git log --oneline -1
```

---

## Task 6: Sinks emit AIS contacts (+ SignalKSink route-point advance)

`SignalKSink.publish` emits one `enqueue_ais` per contact, and advances the SignalK active route point when `snapshot.point_index` increments (replacing the old in-loop `advance_active_point` call). `StdoutJsonSink` adds an `"ais"` count.

**Files:**
- Modify: `src/yey/boats/simulator/sinks/signalk.py`
- Modify: `src/yey/boats/simulator/sinks/stdout_json.py`
- Test: `tests/test_sink_ais.py`

- [ ] **Step 1: Write the failing test** — `tests/test_sink_ais.py`:

```python
import json
from datetime import datetime, timezone

import pytest

from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import AisContact, TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.sinks.signalk import SignalKSink  # type: ignore[import]
from yey.boats.simulator.sinks.stdout_json import StdoutJsonSink  # type: ignore[import]


class _Nav(NavState):
    pass


def _nav():
    return NavState(lat=45.0, lon=13.0, hdg_deg=90, cog_deg=90, sog_kts=5, stw_kts=5,
                    twa_deg=40, tws_kts=12, twd_deg=130, awa_deg=30, aws_kts=15,
                    heel_deg=8, depth_m=20.0)


def _snap(point_index=0, contacts=None):
    return TelemetrySnapshot(
        nav=_nav(), elec=object(), sys=object(), lights=object(), wx=object(),
        state=SimState.SAILING, utc_now=datetime.now(timezone.utc), temps={},
        next_wp=("Pula", 44.87, 13.84), route_href="/r", point_index=point_index,
        ais_contacts=contacts or [])


class FakeWriter:
    def __init__(self): self.ais = []; self.advances = 0
    async def connect(self, u, p): ...
    async def send_vessel_delta(self, *a, **k): ...
    async def enqueue_ais(self, mmsi, lat, lon, cog_deg, sog_kts, name, ship_type):
        self.ais.append(mmsi)
    async def advance_active_point(self, steps=1): self.advances += steps
    async def close(self): ...


@pytest.mark.asyncio
async def test_signalk_sink_emits_contacts_and_advances_on_index_change():
    w = FakeWriter()
    sink = SignalKSink(writer=w)
    c = [AisContact("111", 45.1, 13.1, 90.0, 10.0, "X", 70)]
    await sink.publish(_snap(point_index=2, contacts=c))
    assert w.ais == ["111"]  # noqa: S101
    assert w.advances == 0  # noqa: S101  first publish: no prior index
    await sink.publish(_snap(point_index=3, contacts=c))
    assert w.advances == 1  # noqa: S101  index 2 -> 3


@pytest.mark.asyncio
async def test_stdout_sink_includes_ais_count(capsys):
    sink = StdoutJsonSink()
    c = [AisContact("111", 45.1, 13.1, 90.0, 10.0, "X", 70)]
    await sink.publish(_snap(contacts=c))

    class _E: soc = 0.8; solar_w = 1.0
    # publish needs elec/sys attrs; rebuild with concrete stand-ins
    snap = _snap(contacts=c)
    snap.elec = type("E", (), {"soc": 0.8, "solar_w": 1.0})()
    snap.sys = type("S", (), {"fw_tank_0": 0.4, "bw_tank_0": 0.2})()
    snap.nav.log_nm = 1.0
    await sink.publish(snap)
    rec = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rec["ais"] == 1  # noqa: S101
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_sink_ais.py -q`
Expected: FAIL — `AttributeError`/assertion (sink doesn't emit contacts yet).

- [ ] **Step 3: Implement SignalKSink** — in `src/yey/boats/simulator/sinks/signalk.py`:
  - add `self._last_point_index: int | None = None` in `__init__`.
  - in `publish`, AFTER the `send_vessel_delta(...)` call, add contact emission + route-point advance:

```python
        for c in snapshot.ais_contacts:
            await self.writer.enqueue_ais(c.mmsi, c.lat, c.lon, c.cog_deg,
                                          c.sog_kts, c.name, c.ship_type)
        if self._last_point_index is not None and snapshot.point_index != self._last_point_index:
            steps = (snapshot.point_index - self._last_point_index) % 1_000_000
            try:
                await self.writer.advance_active_point(steps if steps > 0 else 1)
            except Exception:  # noqa: BLE001
                pass
        self._last_point_index = snapshot.point_index
```

  If `signalk.py` has no broad-except lint header, add `# ruff: noqa: BLE001` as the module's second line, or keep the inline `# noqa: BLE001` shown.

- [ ] **Step 4: Implement StdoutJsonSink** — in `src/yey/boats/simulator/sinks/stdout_json.py`, add to the `rec` dict (before the closing brace):

```python
            "ais": len(snapshot.ais_contacts),
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_sink_ais.py -q`
Expected: PASS.

- [ ] **Step 6: Run full suite + commit**

```bash
.venv/bin/pytest -q
git add -A && git commit -m "feat: sinks emit AIS contacts from the frame; SK advances route point on index change"
git log --oneline -1
```

---

## Task 7: weather_source config setting

**Files:**
- Modify: `src/yey/boats/simulator/config.py`
- Test: `tests/test_config_weather_source.py`

- [ ] **Step 1: Write the failing test** — `tests/test_config_weather_source.py`:

```python
from yey.boats.simulator.config import Settings  # type: ignore[import]


def test_weather_source_default(monkeypatch):
    monkeypatch.delenv("WEATHER_SOURCE", raising=False)
    assert Settings.from_env().weather_source == "openmeteo"  # noqa: S101


def test_weather_source_env(monkeypatch):
    monkeypatch.setenv("WEATHER_SOURCE", "signalk")
    assert Settings.from_env().weather_source == "signalk"  # noqa: S101
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_config_weather_source.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'weather_source'`.

- [ ] **Step 3: Implement** — in `src/yey/boats/simulator/config.py`:
  - add the field to the dataclass (after `sink`): `weather_source: str = "openmeteo"  # openmeteo | signalk`
  - in `from_env`, add to the `cls(...)` kwargs: `weather_source=_env("WEATHER_SOURCE", "openmeteo"),`

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_config_weather_source.py -q`
Expected: PASS.

- [ ] **Step 5: Run full suite + commit**

```bash
.venv/bin/pytest -q
git add -A && git commit -m "feat: WEATHER_SOURCE config (openmeteo | signalk)"
git log --oneline -1
```

---

## Task 8: Engine

The deterministic, I/O-isolated core. Holds the physics modules + injected `DataSource`/`AISSource` + a command queue; `async tick(now)` runs the verbatim physics body (from `runner.sim_loop`, lines 119–205) with weather/AIS via ports and returns a `TelemetrySnapshot`. Includes a `submit_command(action, arg)` + an `EngineCommandSink` shim so the existing `SignalKCommandSource`/`CommandHandler` (and their tests) are untouched. The standalone `build_snapshot` helper is removed (the engine builds the frame).

**Files:**
- Create: `src/yey/boats/simulator/engine/engine.py`
- Test: `tests/test_engine.py`
- (Task 9 removes `build_snapshot` + `tests/test_runner_snapshot.py`.)

- [ ] **Step 1: Write the failing test** — `tests/test_engine.py`:

```python
from datetime import datetime, timezone

import pytest

from yey.boats.simulator import resources  # type: ignore[import]
from yey.boats.simulator.engine.engine import Engine, EngineCommandSink  # type: ignore[import]
from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.polars import Polars  # type: ignore[import]
from yey.boats.simulator.engine.route import Route  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import AisContact, TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.engine.weather import DEFAULT_WEATHER  # type: ignore[import]


class FakeData:
    async def get_weather(self, lat, lon, now): return DEFAULT_WEATHER
    async def twd_shift_next_6h(self, lat, lon, now): return 0.0
    async def mean_tws_next_6h(self, lat, lon, now): return DEFAULT_WEATHER.sample()[0]


class FakeAIS:
    async def start(self): ...
    def get_contacts(self, lat, lon):
        return [AisContact("111", lat + 0.01, lon + 0.01, 90.0, 10.0, "X", 70)]


def _engine():
    route = Route.load(resources.route_kmz(), resources.marinas_json())
    route.load_depth_profile(resources.depth_cache_path(__import__("pathlib").Path("/tmp/yey-eng-test")))
    polars = Polars.load(resources.polar_csv())
    start = NavState(lat=route.current.lat, lon=route.current.lon,
                     hdg_deg=route.current.berth_heading, cog_deg=0, sog_kts=0,
                     stw_kts=0, twa_deg=0, tws_kts=0, twd_deg=0, awa_deg=0,
                     aws_kts=0, heel_deg=0, depth_m=10.0)
    return Engine(route, polars, FakeData(), FakeAIS(), start_state=start)


@pytest.mark.asyncio
async def test_tick_returns_snapshot_with_contacts():
    eng = _engine()
    now = datetime(2026, 6, 14, 10, 0, 0, tzinfo=timezone.utc)
    snap = await eng.tick(now)
    assert isinstance(snap, TelemetrySnapshot)  # noqa: S101
    assert snap.utc_now == now  # noqa: S101  injected clock used verbatim
    assert len(snap.ais_contacts) == 1  # noqa: S101
    assert snap.ais_contacts[0].mmsi == "111"  # noqa: S101


@pytest.mark.asyncio
async def test_submitted_command_reaches_autopilot():
    eng = _engine()
    eng.submit_command("engage", None)
    now = datetime(2026, 6, 14, 10, 0, 0, tzinfo=timezone.utc)
    await eng.tick(now)
    assert eng.autopilot.state.mode != "route"  # noqa: S101  engage left route mode


@pytest.mark.asyncio
async def test_command_sink_shim_enqueues():
    eng = _engine()
    shim = EngineCommandSink(eng)
    shim.apply("set_heading", 123.0, current_heading_deg=90.0, twd_deg=200.0)
    assert eng._cmd_queue == [("set_heading", 123.0)]  # noqa: S101
```

Note: `test_submitted_command_reaches_autopilot` assumes `autopilot.apply("engage", None, ...)` changes `autopilot.state.mode` away from `"route"`. Confirm the engage semantics by reading `engine/autopilot.py`; if `engage` keeps mode `"route"`, pick a command/assert that demonstrably changes autopilot state (e.g. `("standby", None)` → mode `"standby"`), matching the real autopilot API. Adjust the assert to the real behavior.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: ...engine.engine`.

- [ ] **Step 3: Implement** — `src/yey/boats/simulator/engine/engine.py`. Transcribe the physics body from `runner.sim_loop` verbatim (only the substitutions noted in the spec). The non-transcription pieces (`submit_command`, command drain, AIS, snapshot return) are shown in full.

```python
# yey/boats/simulator/engine/engine.py
# ruff: noqa: T201,BLE001,S110
"""Deterministic, I/O-isolated simulation engine.

Holds the physics modules + injected DataSource/AISSource + a command queue.
tick(now) runs one 1 Hz step using the injected clock and ports, and returns a
TelemetrySnapshot (vessel state + AIS contacts). No wall-clock reads, no sockets,
no sink calls — those belong to the driver.
"""
from __future__ import annotations

from typing import Any

from yey.boats.simulator.engine.autopilot import Autopilot  # type: ignore[import]
from yey.boats.simulator.engine.electrical import Electrical, solar_elevation_deg  # type: ignore[import]
from yey.boats.simulator.engine.lights import LightsModel  # type: ignore[import]
from yey.boats.simulator.engine.navigator import Navigator, NavState, engine_fuel_L_h  # type: ignore[import]
from yey.boats.simulator.engine.performance import polar_efficiency  # type: ignore[import]
from yey.boats.simulator.engine.schedule import Schedule, SimState  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.engine.systems import Systems  # type: ignore[import]
from yey.boats.simulator.engine.temperatures import ThermalModel  # type: ignore[import]
from yey.boats.simulator.engine.weather import DEFAULT_WEATHER  # type: ignore[import]

ROUTE_UUID = "ad1a7c00-0b0a-4d1a-8c0a-000000000001"


class EngineCommandSink:
    """Autopilot-shaped shim handed to SignalKCommandSource/CommandHandler so they
    stay unchanged; .apply() enqueues onto the engine instead of mutating an AP."""

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine

    def apply(self, action: str, arg: Any, current_heading_deg: float | None = None,
              twd_deg: float | None = None) -> None:
        self._engine.submit_command(action, arg)


class Engine:
    def __init__(self, route: Any, polars: Any, data_source: Any, ais_source: Any,
                 *, start_state: NavState) -> None:
        self.route = route
        self.polars = polars
        self._data = data_source
        self._ais = ais_source
        self.sched = Schedule()
        self.nav = Navigator(polars, self.sched, route._depth_profile)
        self.elec = Electrical(initial_soc=0.85)
        self.sys_ = Systems()
        self.lights = LightsModel()
        self.thermal = ThermalModel()
        self.autopilot = Autopilot()
        self.nav_state = start_state
        self._cmd_queue: list[tuple[str, Any]] = []
        self._last_wx = DEFAULT_WEATHER
        self._last_twd = 0.0

    def submit_command(self, action: str, arg: Any) -> None:
        self._cmd_queue.append((action, arg))

    async def tick(self, now: Any) -> TelemetrySnapshot:
        try:
            wx = await self._data.get_weather(self.nav_state.lat, self.nav_state.lon, now)
        except Exception as exc:
            print(f"[engine] weather error (using last known): {exc!r}", flush=True)
            wx = self._last_wx
        if wx is None:
            wx = self._last_wx
        self._last_wx = wx
        tws, twd = wx.sample()
        self._last_twd = twd

        while self._cmd_queue:
            action, arg = self._cmd_queue.pop(0)
            self.autopilot.apply(action, arg,
                                 current_heading_deg=self.nav_state.hdg_deg, twd_deg=twd)

        if (self.autopilot.state.mode == "route"
                and self.route.distance_to_next(self.nav_state.lat, self.nav_state.lon) < 0.3):
            wp_meta = self.route.current
            self.sched.on_waypoint_arrival()
            self.route.advance()
            self.sys_.on_marina_arrival(wp_meta.refill_water, wp_meta.refill_fuel,
                                        wp_meta.pump_out_bw)
            print(f"[engine] arrived {wp_meta.name}, next {self.route.next_wp.name}", flush=True)

        if self.sched.lookahead_due:
            try:
                if await self._data.twd_shift_next_6h(self.nav_state.lat, self.nav_state.lon, now) > 15:
                    self.sched._tack_timer_s = 9999
            except Exception:
                pass
            self.sched.reset_lookahead()

        if self.sched.state in (SimState.MOORED, SimState.BORA_HOLD):
            try:
                mean_tws = await self._data.mean_tws_next_6h(self.nav_state.lat, self.nav_state.lon, now)
            except Exception:
                mean_tws = tws
            self.sched.try_depart(now, twd, mean_tws)

        wp_brg = self.route.bearing_to_next(self.nav_state.lat, self.nav_state.lon)
        stw_candidate = self.polars.boat_speed(tws, abs(self.nav_state.twa_deg))
        self.sched.update_sailing_state(stw_candidate)
        eff = polar_efficiency(wx.wave_height_m, tws)
        route_hdg = self.nav.route_heading(self.nav_state, wp_brg, tws, twd, self.sched.state)
        eff_hdg = self.autopilot.effective_heading(
            route_heading_deg=route_hdg, current_heading_deg=self.nav_state.hdg_deg, twd_deg=twd)
        prev_hdg = self.nav_state.hdg_deg
        self.nav_state = self.nav.tick(self.nav_state, wp_brg, tws, twd, self.sched.state,
                                       efficiency=eff, heading_override=eff_hdg)
        self.autopilot.update_rudder(prev_hdg, self.nav_state.hdg_deg)

        if self.sched.state == SimState.MOTORED:
            fuel_l = engine_fuel_L_h(self.nav_state.stw_kts) / 3600
        else:
            fuel_l = 0.0
        genset_running = self.elec._genset_state == "running"
        if genset_running:
            fuel_l += 2.0 / 3600

        elec_state = self.elec.tick(1.0, self.sched.state, self.nav_state.lat,
                                    self.nav_state.lon, wx.cloud_cover, now)
        sys_state = self.sys_.tick(1.0, self.sched.state, self.nav_state.tws_kts, now,
                                   fuel_l, False, False, False)
        is_night = solar_elevation_deg(self.nav_state.lat, self.nav_state.lon, now) < 0
        lights_state = self.lights.tick(1.0, self.sched.state, is_night, now)
        self.thermal.update_ambient(wx.temp_c)
        boiler_active = elec_state.loads.get("boiler", 0) > 0
        self.thermal.tick(1.0, self.sched.state, genset_running, boiler_active)
        temps = self.thermal.cabin_temps(wx.temp_c, now)

        contacts = self._ais.get_contacts(self.nav_state.lat, self.nav_state.lon)
        nwp = self.route.next_wp
        snap = TelemetrySnapshot(
            nav=self.nav_state, elec=elec_state, sys=sys_state, lights=lights_state,
            wx=wx, state=self.sched.state, utc_now=now, temps=temps,
            next_wp=(nwp.name, nwp.lat, nwp.lon),
            route_href=f"/resources/routes/{ROUTE_UUID}",
            point_index=self.route.current_index, polars=self.polars,
            autopilot=self.autopilot,
            distance_to_next_nm=self.route.distance_to_next(self.nav_state.lat, self.nav_state.lon),
            ais_contacts=contacts)
        self.sched.tick(1.0)
        return snap
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_engine.py -q`
Expected: PASS. (If a `now` that lands in an Adriatic sailing window triggers an immediate departure transition, the snapshot still returns — the assertions only check the frame shape, contacts, and command application.)

- [ ] **Step 5: Run full suite + commit**

```bash
.venv/bin/pytest -q
git add -A && git commit -m "feat: deterministic I/O-isolated Engine.tick via injected ports + command queue"
git log --oneline -1
```

---

## Task 9: Driver swap (rewrite runner.py)

Rewrite `runner.run` to build ports + engine and drive them; the engine owns the physics. Remove `build_snapshot` and its now-obsolete test.

**Files:**
- Modify: `src/yey/boats/simulator/engine/runner.py`
- Delete: `tests/test_runner_snapshot.py` (build_snapshot is gone; engine.tick is covered by `tests/test_engine.py`)
- Test (driver wiring): `tests/test_driver_wiring.py`

- [ ] **Step 1: Write the failing test** — `tests/test_driver_wiring.py` (tests the pure helper that selects the weather source; the full loop is covered by the stdout smoke):

```python
from yey.boats.simulator.config import Settings  # type: ignore[import]
from yey.boats.simulator.engine.runner import build_data_source  # type: ignore[import]
from yey.boats.simulator.sources.open_meteo import OpenMeteoDataSource  # type: ignore[import]
from yey.boats.simulator.sources.signalk_weather import SignalKDataSource  # type: ignore[import]


def test_build_data_source_openmeteo():
    s = Settings(weather_source="openmeteo")
    assert isinstance(build_data_source(s), OpenMeteoDataSource)  # noqa: S101


def test_build_data_source_signalk():
    s = Settings(weather_source="signalk", signalk_host="h", signalk_port=3001)
    ds = build_data_source(s)
    assert isinstance(ds, SignalKDataSource)  # noqa: S101
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_driver_wiring.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_data_source'`.

- [ ] **Step 3: Rewrite `runner.py`.** Replace the entire file with the driver below. It keeps `_route_to_geojson`, drops `build_snapshot` and the physics loop (now in `Engine`), adds `build_data_source`, builds the AIS source, constructs the `Engine`, wires the command source through `EngineCommandSink`, and runs the cadence loop.

```python
# yey/boats/simulator/engine/runner.py
# ruff: noqa: T201,BLE001,S110
"""Driver: builds ports + Engine and runs the 1 Hz loop.

This is the ONLY place that reads the wall clock and calls sinks/transport. The
Engine owns the physics; the driver owns the clock, cadence, output SinkChain,
SignalK transport side-tasks, and command-source wiring.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from yey.boats.simulator import resources  # type: ignore[import]
from yey.boats.simulator.config import Settings  # type: ignore[import]
from yey.boats.simulator.engine.engine import Engine, EngineCommandSink  # type: ignore[import]
from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.polars import Polars  # type: ignore[import]
from yey.boats.simulator.engine.route import Route  # type: ignore[import]
from yey.boats.simulator.sinks.registry import build_sink_chain  # type: ignore[import]
from yey.boats.simulator.sinks.signalk import SignalKSink  # type: ignore[import]
from yey.boats.simulator.sources.ais import AISStreamSource, SyntheticAISSource  # type: ignore[import]
from yey.boats.simulator.sources.open_meteo import OpenMeteoDataSource  # type: ignore[import]
from yey.boats.simulator.sources.signalk_command import SignalKCommandSource  # type: ignore[import]
from yey.boats.simulator.sources.signalk_weather import SignalKDataSource  # type: ignore[import]

ROUTE_UUID = "ad1a7c00-0b0a-4d1a-8c0a-000000000001"
META_LOADS = ["fridge", "watermaker", "nav", "instruments", "lighting", "wifi",
              "cooker", "boiler", "kettle", "coffeemaker", "hvac",
              "bilge_pump", "water_pump"]


def build_data_source(settings: Settings):
    if settings.weather_source == "signalk":
        return SignalKDataSource(settings.signalk_host, settings.signalk_port)
    return OpenMeteoDataSource()


def _route_to_geojson(route: Route) -> dict:
    coords = [[wp.lon, wp.lat] for wp in route.waypoints]
    names = [wp.name for wp in route.waypoints]
    return {
        "name": "Adriatic Cruise",
        "description": "Venice -> Pula -> Zadar -> Split -> Hvar -> Korcula -> Dubrovnik -> Corfu",
        "feature": {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"waypoints": [{"name": n} for n in names]},
        },
    }


async def run(settings: Settings) -> None:
    route = Route.load(resources.route_kmz(), resources.marinas_json())
    print("[sim] fetching depth profile (may take ~30s first run)...", flush=True)
    route.load_depth_profile(resources.depth_cache_path(settings.data_dir))
    polars = Polars.load(resources.polar_csv())

    chain = build_sink_chain(settings)
    print(f"[sim] opening sink chain (primary={settings.sink})...", flush=True)
    await chain.open()
    sk_sink = chain.active if isinstance(chain.active, SignalKSink) else None
    writer = sk_sink.writer if sk_sink else None

    resume = await writer.get_self_position() if writer is not None else None
    if resume is not None:
        start_lat, start_lon = resume
        idx, _ = route.resync_from_position(start_lat, start_lon)
        start_hdg = route.bearing_to_next(start_lat, start_lon)
        print(f"[sim] resuming from ({start_lat:.4f}, {start_lon:.4f}) -> leg {idx}", flush=True)
    else:
        start_lat, start_lon = route.current.lat, route.current.lon
        start_hdg = route.current.berth_heading
        print(f"[sim] starting at origin {route.current.name}", flush=True)

    if writer is not None:
        try:
            await writer.put_route_resource(ROUTE_UUID, _route_to_geojson(route))
            await writer.put_active_route(ROUTE_UUID, (route.current_index + 1) % len(route.waypoints))
        except Exception as exc:
            print(f"[sim] route resource upload failed (non-fatal): {exc!r}", flush=True)

    start_state = NavState(lat=start_lat, lon=start_lon, hdg_deg=start_hdg,
                           cog_deg=start_hdg, sog_kts=0, stw_kts=0, twa_deg=0,
                           tws_kts=0, twd_deg=0, awa_deg=0, aws_kts=0,
                           heel_deg=0, depth_m=10.0)

    data_source = build_data_source(settings)
    get_pos = None  # set after engine exists

    if settings.aisstream_api_key:
        ais_source = AISStreamSource(get_pos=lambda: get_pos(), api_key=settings.aisstream_api_key)
    else:
        ais_source = SyntheticAISSource(get_pos=lambda: get_pos())

    engine = Engine(route, polars, data_source, ais_source, start_state=start_state)
    get_pos = lambda: (engine.nav_state.lat, engine.nav_state.lon)  # noqa: E731

    async def drive():
        while True:
            t0 = time.monotonic()
            now = datetime.now(timezone.utc)
            snap = await engine.tick(now)
            await chain.publish(snap)
            await asyncio.sleep(max(0, 1.0 - (time.monotonic() - t0)))

    tasks = [drive(), ais_source.start()]
    if writer is not None:
        cmd_src = SignalKCommandSource(
            settings.signalk_host, settings.signalk_port, writer.token,
            EngineCommandSink(engine), lambda: (0.0, 0.0))
        tasks += [writer.flush_loop(),
                  writer.metadata_loop(extra_load_names=META_LOADS, interval=2.0),
                  cmd_src.run()]

    await asyncio.gather(*tasks)
```

- [ ] **Step 4: Delete the obsolete snapshot test**

```bash
git rm tests/test_runner_snapshot.py
```

- [ ] **Step 5: Run the wiring test + verify the module imports + full suite**

```bash
.venv/bin/pytest tests/test_driver_wiring.py -q
.venv/bin/python -c "import yey.boats.simulator.engine.runner as r; print('import-ok', bool(r.run), bool(r.build_data_source))"
.venv/bin/pytest -q
.venv/bin/ruff check src tests
```
Expected: wiring test PASS; `import-ok True True`; full suite PASS; ruff clean. If the engine import surfaces a missing symbol, fix it against the real module APIs.

- [ ] **Step 6: End-to-end stdout smoke (the integration gate)**

```bash
cd /Users/borissorochkin/code/embedded/yey.boats-simulator
( .venv/bin/yey-boats-sim --sink stdout --no-failover --data-dir ./run-data 2>/tmp/eng-stderr.log & echo $! >/tmp/eng.pid ) ; sleep 60 ; kill "$(cat /tmp/eng.pid)" 2>/dev/null
echo "---- last json line ----"; tail -1 /tmp/eng-stderr.log 2>/dev/null; grep -m1 '"state"' /tmp/eng-stderr.log 2>/dev/null || true
```
Run the sim for ~60 s (first run spends ~30 s on the depth fetch). SUCCESS = at least one JSON line containing `"state"`, `"lat"`, and the new `"ais"` key. The stdout sink writes to stdout, not stderr — capture stdout instead if needed: redirect the run with `> /tmp/eng-out.log` and read that. Confirm the `ais` field appears and is an integer ≥ 0. If no network, note the depth/weather degradation (engine still ticks; `ais` present) — the unit tests are the binding gate.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: driver swap — runner builds ports+Engine and runs the cadence loop (Phase C core)"
git log --oneline -1
```

---

## Self-review notes (plan author)

- **Spec coverage:** ports widened + AISSource (Task 2); Engine.tick deterministic/clock-injected, no direct I/O (Task 8); DataSource via async ports inside tick (Task 8); OpenMeteo + real SignalKDataSource (Tasks 3,4); AIS folded into snapshot + sink emission (Tasks 1,5,6); driver owns clock/cadence/sinks/side-tasks/command wiring (Task 9); weather-source selectable (Tasks 7,9); route/depth at startup (Task 9). NMEA/serial out of scope (spec non-goals). Determinism = clock injected, RNG not seeded (synthetic AIS uses `random`, unchanged).
- **Placeholder scan:** the two "confirm against the real module API" notes (WeatherPoint kwargs in Task 4; autopilot `engage` semantics in Task 8) are verification instructions with concrete fallbacks, not unresolved design. The on-arrival `advance_active_point` was relocated to `SignalKSink` (Task 6) since the engine can't call the writer.
- **Type consistency:** `AisContact`/`ais_contacts` (Task 1) used identically in Tasks 2/5/6/8; `DataSource`/`AISSource` method names match across Tasks 2/3/4/5/8; `Engine(route, polars, data_source, ais_source, *, start_state)` + `submit_command`/`tick`/`autopilot`/`nav_state` used consistently in Tasks 8/9; `EngineCommandSink.apply(action, arg, current_heading_deg, twd_deg)` matches what `CommandHandler` calls; `build_data_source`/`weather_source` consistent across Tasks 7/9.
- **Big-bang risk:** Tasks 1–7 are additive and keep the suite green; Task 8 adds the engine without touching the runner; only Task 9 swaps the runner. The engine unit tests (Task 8) + the stdout smoke (Task 9) are the regression gate, as agreed.
