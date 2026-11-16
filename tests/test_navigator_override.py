# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from yey.boats.simulator import resources  # type: ignore[import]
from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]
from yey.boats.simulator.engine.navigator import (  # type: ignore[import]
    MAX_TURN_RATE_DEG_S, Navigator, NavState)
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.polars import Polars  # type: ignore[import]
from yey.boats.simulator.engine.schedule import Schedule  # type: ignore[import]

POLAR = resources.polar_csv()


def _nav():
    grid = GeoGrid(fetcher=lambda pts: [-10.0 for _ in pts])
    return Navigator(Polars.load(POLAR), Schedule(), grid)


def _state(hdg=90.0):
    return NavState(lat=43.5, lon=16.4, hdg_deg=hdg, cog_deg=hdg,
                    sog_kts=5, stw_kts=5, twa_deg=60, tws_kts=12, twd_deg=200,
                    awa_deg=60, aws_kts=14, heel_deg=5, depth_m=20.0)


def test_route_heading_motored_is_wp_bearing():
    nav = _nav()
    hdg = nav.route_heading(_state(), wp_bearing=137.0, tws_kts=12, twd_deg=200,
                            sim_state=SimState.MOTORED)
    assert hdg == 137.0  # noqa: S101


# The heading is now turn-rate limited (a tack/turn slews over a few seconds
# instead of snapping in one tick), so the target heading is reached over
# several ticks; assert on the converged value.
def _converge(nav, st, *args, **kw):
    out = st
    for _ in range(60):
        out = nav.tick(out, *args, **kw)
    return out


def test_tick_motored_without_override_matches_route_heading():
    nav = _nav()
    out = _converge(nav, _state(), 137.0, 12, 200, SimState.MOTORED)
    assert abs(out.hdg_deg - 137.0) < 1e-6  # noqa: S101


def test_tick_override_forces_heading_when_motored():
    nav = _nav()
    out = _converge(nav, _state(), 137.0, 12, 200, SimState.MOTORED, heading_override=42.0)
    assert abs(out.hdg_deg - 42.0) < 1e-6  # noqa: S101


def test_tick_override_forces_heading_when_sailing():
    nav = _nav()
    out = _converge(nav, _state(), 137.0, 12, 200, SimState.SAILING, heading_override=250.0)
    assert abs(out.hdg_deg - 250.0) < 1e-6  # noqa: S101
    assert out.stw_kts >= 0.0  # noqa: S101  # speed derived from polar at the forced heading


def test_tick_heading_is_turn_rate_limited():
    """A large commanded change must not snap in one tick (fixes the ~115 deg
    HDG jump on tacks)."""
    nav = _nav()
    out = nav.tick(_state(hdg=90.0), 137.0, 12, 200, SimState.MOTORED, heading_override=250.0)
    moved = abs(((out.hdg_deg - 90.0 + 180) % 360) - 180)
    assert 0 < moved <= MAX_TURN_RATE_DEG_S + 1e-6  # noqa: S101  # one turn-rate step (dt=1s)


# ── issue #8: moored/bora_hold must not report polar/current-driven SOG ────

def test_route_heading_moored_holds_current_heading():
    """Moored: route_heading must not steer toward the waypoint (that caused
    the boat to slowly turn onto a sailing heading while still at the berth)."""
    nav = _nav()
    st = _state(hdg=210.0)
    hdg = nav.route_heading(st, wp_bearing=90.0, tws_kts=12, twd_deg=200,
                            sim_state=SimState.MOORED)
    assert hdg == st.hdg_deg  # noqa: S101


def test_route_heading_bora_hold_holds_current_heading():
    """BORA_HOLD is also "held at the berth" (grouped with MOORED everywhere
    else in the engine: schedule.update_sailing_state, lights, try_depart)."""
    nav = _nav()
    st = _state(hdg=15.0)
    hdg = nav.route_heading(st, wp_bearing=270.0, tws_kts=30, twd_deg=40,
                            sim_state=SimState.BORA_HOLD)
    assert hdg == st.hdg_deg  # noqa: S101


def test_tick_moored_keeps_sog_stw_near_zero_and_position_fixed():
    """Reproduces issue #8: moored was reporting ~5 kn SOG because tick()
    fell through to the polar-speed + current-drift branch used for sailing.
    Run several minutes of ticks with real wind and confirm SOG/STW settle
    near zero and the berth position does not drift."""
    nav = _nav()
    st = _state(hdg=180.0)
    lat0, lon0 = st.lat, st.lon
    for _ in range(120):
        st = nav.tick(st, 90.0, 12, 200, SimState.MOORED)
    assert st.sog_kts < 0.2  # noqa: S101
    assert st.stw_kts < 0.2  # noqa: S101
    assert abs(st.lat - lat0) < 1e-9  # noqa: S101
    assert abs(st.lon - lon0) < 1e-9  # noqa: S101


def test_tick_bora_hold_keeps_sog_stw_near_zero_and_position_fixed():
    """Same as above for BORA_HOLD, with a strong Bora-strength wind — the
    state that should most tempt the old polar-speed fallback into a large
    bogus SOG."""
    nav = _nav()
    st = _state(hdg=180.0)
    lat0, lon0 = st.lat, st.lon
    for _ in range(120):
        st = nav.tick(st, 90.0, 30, 40, SimState.BORA_HOLD)
    assert st.sog_kts < 0.2  # noqa: S101
    assert st.stw_kts < 0.2  # noqa: S101
    assert abs(st.lat - lat0) < 1e-9  # noqa: S101
    assert abs(st.lon - lon0) < 1e-9  # noqa: S101
