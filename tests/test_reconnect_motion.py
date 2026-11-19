# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Regressions for #20: one live engine, fresh reconnect data, smooth sailing."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_engine import _engine
from yey.boats.simulator.config import Settings
from yey.boats.simulator.control import SimController
from yey.boats.simulator.engine import signalk_writer as sw
from yey.boats.simulator.engine.navigator import (
    MAX_SPEED_CHANGE_KTS_S,
    MAX_TURN_RATE_DEG_S,
)
from yey.boats.simulator.engine.schedule import Schedule, SimState


@pytest.mark.asyncio
async def test_supervisor_cancel_retires_engine_and_restart_waiter(tmp_path):
    live = set()
    started = asyncio.Event()

    async def pipeline(settings, route, start_pos, report_status):
        marker = object()
        live.add(marker)
        report_status((45.0, 13.0), True)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            # Teardown can await: the supervisor must join it before returning.
            await asyncio.sleep(0)
            live.remove(marker)

    controller = SimController(Settings(), None, tmp_path, pipeline)
    task = asyncio.create_task(controller.run_forever())
    await asyncio.wait_for(started.wait(), 1)
    for _ in range(3):
        started.clear()
        await controller.apply_config({})
        await asyncio.wait_for(started.wait(), 1)
        assert len(live) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not live
    assert not controller.status()['running']
    assert not controller.status()['connected']


class Socket:
    def __init__(self, hello_error=None):
        self.closed = False
        self.hello_error = hello_error

    async def recv(self):
        if self.hello_error:
            raise self.hello_error
        return 'hello'

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_reconnect_closes_old_socket_and_discards_outage_backlog(monkeypatch):
    old, new = Socket(), Socket()
    writer = sw.SignalKWriter('localhost', 3000)
    writer._ws = old
    writer._token = 'test-token'
    writer._queue.put_nowait('old-position')

    async def connect(uri):
        assert old.closed
        return new

    monkeypatch.setattr(sw.websockets, 'connect', connect)
    await writer._reconnect_ws()
    assert writer._ws is new
    assert writer._queue.empty()
    await writer.close()
    assert new.closed
    assert writer._ws is None


@pytest.mark.asyncio
async def test_cancel_during_reconnect_hello_closes_candidate(monkeypatch):
    candidate = Socket(asyncio.CancelledError())
    writer = sw.SignalKWriter('localhost', 3000)

    async def connect(uri):
        return candidate

    monkeypatch.setattr(sw.websockets, 'connect', connect)
    with pytest.raises(asyncio.CancelledError):
        await writer._reconnect_ws()
    assert candidate.closed
    assert writer._ws is None


def test_propulsion_switch_has_a_deadband():
    schedule = Schedule()
    schedule.state = SimState.SAILING
    assert schedule.update_sailing_state(1.7) == SimState.MOTORED
    for speed in [1.9, 2.1, 1.85, 2.0]:
        assert schedule.update_sailing_state(speed) == SimState.MOTORED
    assert schedule.update_sailing_state(2.3) == SimState.SAILING
    for speed in [2.1, 1.9, 2.0]:
        assert schedule.update_sailing_state(speed) == SimState.SAILING


@pytest.mark.asyncio
async def test_upwind_leg_finishes_tack_without_motor_sail_hunting(monkeypatch):
    engine = _engine()
    engine.sched.state = SimState.SAILING
    engine.nav_state.hdg_deg = 280
    engine.nav_state.twa_deg = 0
    engine.nav_state.stw_kts = 5
    # An upwind waypoint with sufficient wind: sailing is viable after the tack,
    # even while the present heading points directly into the no-go zone.
    monkeypatch.setattr(engine.route, 'bearing_to_next', lambda *_: 280.0)
    monkeypatch.setattr(engine.route, 'distance_to_next', lambda *_: 100.0)
    monkeypatch.setattr(type(engine._data), 'get_weather', fixed_weather)
    from yey.boats.simulator.engine.weather import WeatherPoint
    monkeypatch.setattr(WeatherPoint, 'sample', lambda _: (12.0, 280.0))
    now = datetime(2026, 6, 14, 10, tzinfo=UTC)
    headings, speeds, states = [], [], []
    for i in range(90):
        snap = await engine.tick(now + timedelta(seconds=i))
        headings.append(snap.nav.hdg_deg)
        speeds.append(snap.nav.stw_kts)
        states.append(snap.state)
    assert set(states) == {SimState.SAILING}
    turns = [abs((b - a + 180) % 360 - 180)
             for a, b in zip(headings, headings[1:], strict=False)]
    assert max(turns) <= MAX_TURN_RATE_DEG_S + 1e-9
    changes = [abs(b - a) for a, b in zip(speeds, speeds[1:], strict=False)]
    assert max(changes) <= MAX_SPEED_CHANGE_KTS_S + 1e-9
    assert abs((headings[-1] - 280 + 180) % 360 - 180) > 30


async def fixed_weather(*args):
    from yey.boats.simulator.engine.weather import DEFAULT_WEATHER
    return DEFAULT_WEATHER


@pytest.mark.asyncio
async def test_pipeline_cancel_closes_sink_after_driver_stops(monkeypatch, tmp_path):
    from tests.test_engine import FakeData
    from yey.boats.simulator import resources
    from yey.boats.simulator.engine import runner
    from yey.boats.simulator.engine.geogrid import GeoGrid
    from yey.boats.simulator.engine.route import Route

    started = asyncio.Event()
    route = Route.load(resources.route_kmz(), resources.marinas_json())

    class Chain:
        active = None
        closed = False

        async def open(self):
            pass

        async def publish(self, snapshot):
            assert not self.closed

        async def close(self):
            self.closed = True

    chain = Chain()

    async def wait_forever(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(runner, 'build_sink_chain', lambda _: chain)
    monkeypatch.setattr(runner, 'build_data_source', lambda _: FakeData())
    monkeypatch.setattr(GeoGrid, 'fetch_loop', wait_forever)
    cached = [Route._wp_full_dict(w) for w in route.waypoints]
    monkeypatch.setattr(Route, 'load_expanded_waypoints', lambda *_: cached)
    monkeypatch.delenv('RANDOM_PASSAGES', raising=False)
    task = asyncio.create_task(runner.pipeline(
        Settings(data_dir=tmp_path), route, (43.5, 16.4), lambda *_: started.set()))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert chain.closed


async def test_manual_heading_into_the_wind_motors_instead_of_sitting_in_irons(monkeypatch):
    """#23 (regression from #21): the motor/sail decision used the route course while
    the autopilot held a manual heading. Autopilot holds 280 into 12 kn from 280 while
    the route leg (190) is sailable: the boat must motor on 280, not sit SAILING at
    STW 0 until the route resumes (or forever with RESUME_ROUTE_AFTER_S=0)."""
    engine = _engine()
    engine.sched.state = SimState.SAILING
    engine.nav_state.hdg_deg = 280
    engine.nav_state.stw_kts = 0
    monkeypatch.setattr(engine.route, 'bearing_to_next', lambda *_: 190.0)
    monkeypatch.setattr(engine.route, 'distance_to_next', lambda *_: 100.0)
    monkeypatch.setattr(type(engine._data), 'get_weather', fixed_weather)
    from yey.boats.simulator.engine.weather import WeatherPoint
    monkeypatch.setattr(WeatherPoint, 'sample', lambda _: (12.0, 280.0))
    engine.submit_command("set_heading", 280.0)
    now = datetime(2026, 6, 14, 10, tzinfo=UTC)
    for i in range(240):
        snap = await engine.tick(now + timedelta(seconds=i))
    assert engine.autopilot.state.mode == "auto"
    assert abs((snap.nav.hdg_deg - 280 + 180) % 360 - 180) < 15, "holds the manual heading"
    assert snap.state == SimState.MOTORED, snap.state
    assert snap.nav.stw_kts > 3.0, snap.nav.stw_kts
