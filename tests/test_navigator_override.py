# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from yey.boats.simulator import resources  # type: ignore[import]
from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]
from yey.boats.simulator.engine.navigator import Navigator, NavState  # type: ignore[import]
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


def test_tick_motored_without_override_matches_route_heading():
    nav = _nav()
    st = _state()
    out = nav.tick(st, 137.0, 12, 200, SimState.MOTORED)
    assert abs(out.hdg_deg - 137.0) < 1e-9  # noqa: S101


def test_tick_override_forces_heading_when_motored():
    nav = _nav()
    st = _state()
    out = nav.tick(st, 137.0, 12, 200, SimState.MOTORED, heading_override=42.0)
    assert abs(out.hdg_deg - 42.0) < 1e-9  # noqa: S101


def test_tick_override_forces_heading_when_sailing():
    nav = _nav()
    st = _state()
    out = nav.tick(st, 137.0, 12, 200, SimState.SAILING, heading_override=250.0)
    assert abs(out.hdg_deg - 250.0) < 1e-9  # noqa: S101
    assert out.stw_kts >= 0.0  # noqa: S101  # speed derived from polar at the forced heading
