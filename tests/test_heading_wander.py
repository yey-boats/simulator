# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Helm realism: holding a course must yaw a few degrees and work the rudder.

A real vessel never holds a dead-flat heading with a zero rudder — it wanders a
few degrees around the target while the helm corrects continuously. These tests
pin that behaviour so the firmware display shows a live HDG and a working rudder
instead of frozen values.
"""
from datetime import datetime, timedelta, timezone

import pytest  # type: ignore[import]

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
from yey.boats.simulator.engine.weather import DEFAULT_WEATHER  # type: ignore[import]


class _FakeData:
    async def get_weather(self, lat, lon, now):  # noqa: D401
        return DEFAULT_WEATHER

    async def twd_shift_next_6h(self, lat, lon, now):
        return 0.0

    async def mean_tws_next_6h(self, lat, lon, now):
        return DEFAULT_WEATHER.sample()[0]


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
