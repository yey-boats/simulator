# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from datetime import datetime, timedelta, UTC

import pytest  # type: ignore[import]

from yey.boats.simulator import resources  # type: ignore[import]
from yey.boats.simulator.engine.engine import Engine, EngineCommandSink  # type: ignore[import]
from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]
from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.polars import Polars  # type: ignore[import]
from yey.boats.simulator.engine.route import Route  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
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
    polars = Polars.load(resources.polar_csv())
    start = NavState(lat=route.current.lat, lon=route.current.lon,
                     hdg_deg=route.current.berth_heading, cog_deg=0, sog_kts=0,
                     stw_kts=0, twa_deg=0, tws_kts=0, twd_deg=0, awa_deg=0,
                     aws_kts=0, heel_deg=0, depth_m=10.0)
    grid = GeoGrid(fetcher=lambda pts: [-10.0 for _ in pts])
    return Engine(route, polars, FakeData(), FakeAIS(), start_state=start, grid=grid)


@pytest.mark.asyncio
async def test_tick_returns_snapshot_with_contacts():
    eng = _engine()
    now = datetime(2026, 6, 14, 10, 0, 0, tzinfo=UTC)
    snap = await eng.tick(now)
    assert isinstance(snap, TelemetrySnapshot)  # noqa: S101
    assert snap.utc_now == now  # noqa: S101
    assert len(snap.ais_contacts) == 1  # noqa: S101
    assert snap.ais_contacts[0].mmsi == "111"  # noqa: S101


@pytest.mark.asyncio
async def test_submitted_command_reaches_autopilot():
    eng = _engine()
    eng.submit_command("disengage", None)
    now = datetime(2026, 6, 14, 10, 0, 0, tzinfo=UTC)
    await eng.tick(now)
    assert eng.autopilot.state.mode != "route"  # noqa: S101


@pytest.mark.asyncio
async def test_command_sink_shim_enqueues():
    eng = _engine()
    shim = EngineCommandSink(eng)
    shim.apply("set_heading", 123.0, current_heading_deg=90.0, twd_deg=200.0)
    assert eng._cmd_queue == [("set_heading", 123.0)]  # noqa: S101


@pytest.mark.asyncio
async def test_tick_emits_diagnostic_signal_fields():
    eng = _engine()
    now = datetime(2026, 6, 14, 10, 0, 0, tzinfo=UTC)
    snap = await eng.tick(now)
    # All Phase-3 diagnostic fields are populated every tick.
    assert snap.oil_pressure_pa is not None  # noqa: S101
    assert snap.exhaust_temp_k is not None  # noqa: S101
    assert snap.starter_voltage is not None  # noqa: S101
    assert snap.gnss_satellites is not None  # noqa: S101
    assert snap.gnss_quality == "GNSS Fix"  # healthy by default  # noqa: S101
    assert snap.rate_of_turn_rad_s is not None  # noqa: S101


@pytest.mark.asyncio
async def test_set_and_clear_fault_command_toggles_faultstate():
    eng = _engine()
    # set_fault / clear_fault mutate the shared FaultState directly (not the AP).
    eng.submit_command("set_fault", "gps_degraded")
    assert eng.faults.is_active("gps_degraded")  # noqa: S101
    assert eng._cmd_queue == []  # not forwarded to autopilot  # noqa: S101
    now = datetime(2026, 6, 14, 10, 0, 0, tzinfo=UTC)
    snap = await eng.tick(now)
    assert snap.gnss_quality == "no GNSS"  # noqa: S101
    assert snap.gnss_position_jitter_deg is not None  # noqa: S101

    eng.submit_command("clear_fault", "gps_degraded")
    assert not eng.faults.is_active("gps_degraded")  # noqa: S101
    snap2 = await eng.tick(now)
    assert snap2.gnss_quality == "GNSS Fix"  # noqa: S101


@pytest.mark.asyncio
async def test_moored_boat_does_not_report_sog_from_polar_or_current():
    """Issue #8: while SimState.MOORED, navigation.speedOverGround was reading
    ~5 kn because the navigator fell through to the sailing polar-speed +
    current-drift path. Tick several minutes at a time well outside the
    sailing window (so the schedule stays MOORED regardless of wind) and
    assert SOG/STW stay near zero and the boat does not leave the berth."""
    eng = _engine()
    assert eng.sched.state.value == "moored"  # noqa: S101
    lat0, lon0 = eng.nav_state.lat, eng.nav_state.lon
    # 22:00 UTC -> 00:00 local (Adriatic, UTC+2): outside the 07:00-18:00
    # sailing window, so Schedule.try_depart keeps the boat MOORED every tick
    # no matter what the (randomised) wind sample is.
    now = datetime(2026, 11, 8, 22, 0, 0, tzinfo=UTC)
    for i in range(180):
        snap = await eng.tick(now + timedelta(seconds=i))
    assert eng.sched.state.value == "moored"  # noqa: S101
    assert snap.nav.sog_kts < 0.2  # noqa: S101
    assert snap.nav.stw_kts < 0.2  # noqa: S101
    assert abs(snap.nav.lat - lat0) < 1e-6  # noqa: S101
    assert abs(snap.nav.lon - lon0) < 1e-6  # noqa: S101


def _open_water_route(eng, legs_nm=6.0):
    """Replace the route with open-water waypoints (marina="", as autoroute
    legs and random passages produce) starting at the boat's position."""
    from yey.boats.simulator.engine.route import Waypoint, dead_reckon
    w0 = eng.route.current
    wps = [w0]
    lat, lon = eng.nav_state.lat, eng.nav_state.lon
    for i in range(1, 4):
        lat, lon = dead_reckon(lat, lon, legs_nm, 200.0, 3600.0)
        wps.append(Waypoint(name=f"open{i}", lat=lat, lon=lon, marina="", berth_heading=0.0,
                            refill_water=False, refill_fuel=False, pump_out_bw=False))
    eng.route.waypoints = wps
    eng.route.current_index = 0
    return wps


@pytest.mark.asyncio
async def test_night_arrival_at_open_water_waypoint_keeps_the_boat_moving():
    """Review of #12: reaching an open-water waypoint outside the sailing
    window must not moor the boat (it would freeze mid-sea until 07:00)."""
    eng = _engine()
    wps = _open_water_route(eng)
    eng.sched.state = SimState.SAILING
    eng.autopilot.apply("set_mode", "route", current_heading_deg=eng.nav_state.hdg_deg, twd_deg=0.0)
    # Put the boat right on top of open1 at night.
    eng.nav_state.lat, eng.nav_state.lon = wps[1].lat, wps[1].lon
    now = datetime(2026, 11, 8, 22, 0, 0, tzinfo=UTC)
    snap = await eng.tick(now)
    assert eng.route.current.name == "open1"  # noqa: S101  (arrived, advanced)
    assert snap.state != SimState.MOORED  # noqa: S101
    assert eng.sched.state != SimState.MOORED  # noqa: S101


@pytest.mark.asyncio
async def test_night_arrival_at_a_marina_moors():
    eng = _engine()
    wps = _open_water_route(eng)
    wps[1].marina = "ACI Test"
    eng.sched.state = SimState.SAILING
    eng.autopilot.apply("set_mode", "route", current_heading_deg=eng.nav_state.hdg_deg, twd_deg=0.0)
    eng.nav_state.lat, eng.nav_state.lon = wps[1].lat, wps[1].lon
    await eng.tick(datetime(2026, 11, 8, 22, 0, 0, tzinfo=UTC))
    assert eng.route.current.name == "open1"  # noqa: S101
    assert eng.sched.state == SimState.MOORED  # noqa: S101
