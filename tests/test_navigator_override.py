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
    return Navigator(Polars.load(POLAR), Schedule(), GeoGrid(fetcher=lambda pts: [-10.0 for _ in pts]))


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
