# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from datetime import datetime, timezone
from pathlib import Path

import pytest  # type: ignore[import]

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
    route.load_depth_profile(resources.depth_cache_path(Path("/tmp/yey-eng-test")))  # noqa: S108
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
    assert snap.utc_now == now  # noqa: S101
    assert len(snap.ais_contacts) == 1  # noqa: S101
    assert snap.ais_contacts[0].mmsi == "111"  # noqa: S101


@pytest.mark.asyncio
async def test_submitted_command_reaches_autopilot():
    eng = _engine()
    eng.submit_command("disengage", None)
    now = datetime(2026, 6, 14, 10, 0, 0, tzinfo=timezone.utc)
    await eng.tick(now)
    assert eng.autopilot.state.mode != "route"  # noqa: S101


@pytest.mark.asyncio
async def test_command_sink_shim_enqueues():
    eng = _engine()
    shim = EngineCommandSink(eng)
    shim.apply("set_heading", 123.0, current_heading_deg=90.0, twd_deg=200.0)
    assert eng._cmd_queue == [("set_heading", 123.0)]  # noqa: S101
