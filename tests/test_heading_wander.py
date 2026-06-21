# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Helm realism: holding a course must yaw a few degrees and work the rudder.

A real vessel never holds a dead-flat heading with a zero rudder — it wanders a
few degrees around the target while the helm corrects continuously. These tests
pin that behaviour so the firmware display shows a live HDG and a working rudder
instead of frozen values.
"""
from datetime import datetime, timedelta, timezone

import pytest  # type: ignore[import]

import math

from yey.boats.simulator import resources  # type: ignore[import]
from yey.boats.simulator.engine.autopilot import (  # type: ignore[import]
    Autopilot,
    WANDER_AMP1_DEG,
    WANDER_AMP2_DEG,
    WANDER_RIPPLE_DEG,
)
from yey.boats.simulator.engine.engine import Engine  # type: ignore[import]
from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]
from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.polars import Polars  # type: ignore[import]
from yey.boats.simulator.engine.route import Route  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.signalk_writer import _build_vessel_delta  # type: ignore[import]
from yey.boats.simulator.engine.weather import DEFAULT_WEATHER, WeatherPoint  # type: ignore[import]


def _emitted_paths(snap) -> dict:
    """Serialize a TelemetrySnapshot exactly as the SignalK sink does and return
    a path->value map. This is what the firmware actually receives — asserting on
    it (rather than on ``snap.nav.hdg_deg``) is what closes the live-lab gap where
    the engine wandered internally but the wire heading was frozen at the AP target."""
    delta = _build_vessel_delta(
        snap.nav, snap.elec, snap.sys, snap.lights, snap.wx, snap.state,
        snap.utc_now, snap.temps, next_wp=snap.next_wp, route_href=snap.route_href,
        point_index=snap.point_index, polars=snap.polars, autopilot=snap.autopilot)
    return {v["path"]: v["value"] for v in delta["updates"][0]["values"]}

# Dead-calm weather: with no wind the boat motors a dead-straight leg (no
# tacking, no sampled-wind jitter), which is exactly the "long straight route
# leg" the live lab scenario sits on. Used by the route-following test so the
# only heading movement is the helm wander we want to assert on.
_CALM = WeatherPoint(tws_ms=0.0, twd_deg=0.0, gust_ms=0.0, cloud_cover=0.2,
                     wave_height_m=0.0, wave_period_s=0.0, wave_dir_deg=0.0,
                     temp_c=20.0, pressure_pa=101325.0, humidity=0.6)


class _FakeData:
    async def get_weather(self, lat, lon, now):  # noqa: D401
        return DEFAULT_WEATHER

    async def twd_shift_next_6h(self, lat, lon, now):
        return 0.0

    async def mean_tws_next_6h(self, lat, lon, now):
        return DEFAULT_WEATHER.sample()[0]


class _CalmData(_FakeData):
    async def get_weather(self, lat, lon, now):  # noqa: D401
        return _CALM

    async def mean_tws_next_6h(self, lat, lon, now):
        return 0.0


class _FakeAIS:
    async def start(self): ...

    def get_contacts(self, lat, lon):
        return []


def _engine():
    route = Route.load(resources.route_kmz(), resources.marinas_json())
    polars = Polars.load(resources.polar_csv())
    start = NavState(lat=route.current.lat, lon=route.current.lon,
                     hdg_deg=route.current.berth_heading, cog_deg=0, sog_kts=0,
                     stw_kts=0, twa_deg=0, tws_kts=0, twd_deg=0, awa_deg=0,
                     aws_kts=0, heel_deg=0, depth_m=10.0)
    grid = GeoGrid(fetcher=lambda pts: [-10.0 for _ in pts])
    return Engine(route, polars, _FakeData(), _FakeAIS(), start_state=start, grid=grid)


# ── unit-level: the wander/rudder primitives ────────────────────────────────

def test_steer_wanders_around_commanded_but_stays_bounded():
    ap = Autopilot()
    target = 120.0
    bound = WANDER_AMP1_DEG + WANDER_AMP2_DEG + WANDER_RIPPLE_DEG + 1e-6
    headings = [ap.steer(target, dt_s=1.0) for _ in range(40)]
    # Not constant: the helm yaws around the target.
    assert max(headings) - min(headings) > 1.0
    # But every sample stays within the analytic wander envelope of the target.
    for h in headings:
        offset = ((h - target + 180) % 360) - 180
        assert abs(offset) <= bound


def test_steer_is_deterministic():
    a, b = Autopilot(), Autopilot()
    seq_a = [a.steer(90.0) for _ in range(20)]
    seq_b = [b.steer(90.0) for _ in range(20)]
    assert seq_a == seq_b  # no RNG — reproducible


def test_steer_tracks_commanded_course_change():
    """The wander is an OFFSET; a real turn must move the held heading with it."""
    ap = Autopilot()
    bound = WANDER_AMP1_DEG + WANDER_AMP2_DEG + WANDER_RIPPLE_DEG + 1e-6
    held_low = ap.steer(10.0)
    # advance the same phase clock, then command a 200° turn
    for _ in range(5):
        ap.steer(10.0)
    held_high = ap.steer(210.0)
    # held heading near the new command, not the old one
    assert abs((((held_high - 210.0) + 180) % 360) - 180) <= bound
    assert abs(((held_high - held_low + 180) % 360) - 180) > 150


# ── integration: engine holding a course under autopilot ────────────────────

@pytest.mark.asyncio
async def test_holding_course_heading_wanders_and_rudder_works():
    eng = _engine()
    # Hold a fixed heading under autopilot ("auto" engaged).
    eng.submit_command("set_heading", 100.0)
    now = datetime(2026, 6, 14, 10, 0, 0, tzinfo=timezone.utc)

    # Heading is turn-rate limited, so first let it slew from the start heading
    # onto the commanded course; then measure the steady-state wander.
    for i in range(40):
        await eng.tick(now + timedelta(seconds=i))
    now = now + timedelta(seconds=40)

    headings = []
    rudders = []
    for i in range(60):
        snap = await eng.tick(now + timedelta(seconds=i))
        headings.append(snap.nav.hdg_deg)
        rudders.append(eng.autopilot.state.rudder_deg)

    # (a) Heading is NOT constant, but wanders within a sane band (a few degrees).
    spread = max(headings) - min(headings)
    assert spread > 0.5, f"heading appears frozen (spread={spread:.3f}deg)"
    assert spread < 20.0, f"heading wander is unrealistically large ({spread:.3f}deg)"

    # (b) Rudder is actively working (non-zero) and bounded to a realistic max.
    assert any(abs(r) > 0.2 for r in rudders), "rudder never moves while holding"
    assert all(abs(r) <= Autopilot.MAX_RUDDER_DEG for r in rudders), "rudder exceeded max"


@pytest.mark.asyncio
async def test_route_following_leg_heading_wanders_and_rudder_works():
    """Route-following (NOT autopilot-hold) must also yaw + work the rudder.

    The live lab scenario follows a multi-leg route. In that mode the heading
    comes from the leg bearing, not an AP target heading, so it used to emit a
    dead-flat ``navigation.headingTrue`` and an exactly-zero ``steering.rudderAngle``
    on a long straight leg (the firmware HDG read "stuck"). The wander/rudder
    realism must ride on the *final emitted* heading in route mode too — the
    offset rides on top of the leg bearing, so real course changes between legs
    are still preserved exactly.
    """
    eng = _engine()
    # Dead-calm wind so the boat motors a dead-straight leg (the commanded leg
    # heading is constant) — isolates the helm wander as the only heading motion.
    eng._data = _CalmData()
    # No autopilot command: default state is engaged in ROUTE mode. Pin the
    # underway state so the boat is actively steering a leg (not still moored).
    eng.sched.state = SimState.MOTORED
    assert eng.autopilot.state.mode == "route", "fixture must follow the route"
    now = datetime(2026, 6, 14, 10, 0, 0, tzinfo=timezone.utc)

    # Heading is turn-rate limited: settle onto the leg bearing first, then
    # measure the steady-state wander.
    for i in range(40):
        await eng.tick(now + timedelta(seconds=i))
        eng.sched.state = SimState.MOTORED
    now = now + timedelta(seconds=40)

    headings = []
    rudders = []
    commanded = []
    for i in range(60):
        snap = await eng.tick(now + timedelta(seconds=i))
        # Re-pin MOTORED: update_sailing_state would otherwise be a no-op here
        # (no wind → no sailing), but keep it explicit so the leg stays straight.
        eng.sched.state = SimState.MOTORED
        headings.append(snap.nav.hdg_deg)
        rudders.append(eng.autopilot.state.rudder_deg)
        # The commanded (pre-wander) leg heading the helm is trying to hold.
        commanded.append(eng.nav.route_heading(
            eng.nav_state, eng.route.bearing_to_next(eng.nav_state.lat, eng.nav_state.lon),
            0.0, 0.0, eng.sched.state))

    # (a) Emitted heading is NOT frozen on the leg — it wanders a few degrees.
    spread = max(headings) - min(headings)
    assert spread > 0.5, f"route-leg heading appears frozen (spread={spread:.3f}deg)"
    assert spread < 20.0, f"route-leg heading wander is unrealistically large ({spread:.3f}deg)"

    # (b) Rudder is non-zero (helm correcting the wander) and bounded.
    assert any(abs(r) > 0.2 for r in rudders), "rudder never moves while following a route"
    assert all(abs(r) <= Autopilot.MAX_RUDDER_DEG for r in rudders), "rudder exceeded max"
    # It is not pinned at exactly zero for the whole leg (the original bug).
    assert any(r != 0.0 for r in rudders), "rudder stayed exactly zero on the route leg"

    # (c) The wander is an OFFSET on the leg bearing, not a replacement: each
    # emitted heading stays within the analytic wander envelope of the
    # commanded leg heading, so real course changes between legs are preserved.
    bound = WANDER_AMP1_DEG + WANDER_AMP2_DEG + WANDER_RIPPLE_DEG + 1e-6
    for emitted, cmd in zip(headings, commanded):
        offset = ((emitted - cmd + 180) % 360) - 180
        assert abs(offset) <= bound, (
            f"emitted heading {emitted:.3f} strayed beyond the wander envelope "
            f"of leg bearing {cmd:.3f} (offset {offset:.3f}deg)")


# ── regression: the WIRE values (post-serialization), not just snap.nav ──────

@pytest.mark.asyncio
async def test_emitted_heading_wanders_and_rudder_nonzero_in_auto_hold():
    """Live-lab reproduction: AUTO hold must wander + work the rudder ON THE WIRE.

    The lab observed ``navigation.headingTrue`` frozen at EXACTLY the autopilot
    target (0.6513 rad) with ``steering.rudderAngle`` == 0, while position/SOG
    kept advancing — i.e. the per-tick wander was not reaching the *serialized*
    delta. Every other heading-wander test asserts on ``snap.nav.hdg_deg`` (the
    in-engine value); none serialized through the writer, so a regression that
    broke override→wire propagation would pass them all. This test runs the full
    engine tick AND serializes through ``_build_vessel_delta`` (exactly what
    ``SignalKSink.publish`` sends), then asserts on the emitted radian values.
    """
    eng = _engine()
    # Reproduce the live config: autopilot in AUTO holding 0.6513 rad (≈37.32°).
    target_rad = 0.6513
    eng.submit_command("set_heading", math.degrees(target_rad))
    now = datetime(2026, 6, 14, 10, 0, 0, tzinfo=timezone.utc)

    # Heading is turn-rate limited: settle onto the AP target first, then measure
    # the steady-state wander on the wire.
    for i in range(40):
        await eng.tick(now + timedelta(seconds=i))
    now = now + timedelta(seconds=40)

    emitted_hdg_rad = []
    emitted_rudder_rad = []
    for i in range(60):
        snap = await eng.tick(now + timedelta(seconds=i))
        assert eng.autopilot.state.mode == "auto"  # fixture really is holding
        p = _emitted_paths(snap)
        emitted_hdg_rad.append(p["navigation.headingTrue"])
        emitted_rudder_rad.append(p["steering.rudderAngle"])

    # (a) The EMITTED heading is never frozen at exactly the AP target — the wander
    # offset reaches the wire. (The original live bug: every sample == target.)
    assert not all(abs(h - target_rad) < 1e-9 for h in emitted_hdg_rad), (
        "emitted navigation.headingTrue frozen at the AP target — wander not "
        "reaching the serialized delta")
    spread_deg = math.degrees(max(emitted_hdg_rad) - min(emitted_hdg_rad))
    assert spread_deg > 0.5, f"emitted heading appears frozen (spread={spread_deg:.3f}deg)"
    assert spread_deg < 20.0, f"emitted heading wander unrealistically large ({spread_deg:.3f}deg)"

    # (b) The EMITTED rudder is not pinned at exactly zero — the helm is working.
    assert any(abs(r) > 1e-6 for r in emitted_rudder_rad), (
        "emitted steering.rudderAngle stayed exactly zero — rudder frozen on the wire")
    assert any(abs(r) > math.radians(0.2) for r in emitted_rudder_rad), (
        "emitted rudder never moves meaningfully while holding")
    assert all(abs(r) <= math.radians(Autopilot.MAX_RUDDER_DEG) for r in emitted_rudder_rad), (
        "emitted rudder exceeded the physical maximum")
