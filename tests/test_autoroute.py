# tests/test_autoroute.py
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from __future__ import annotations

from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]
from yey.boats.simulator.engine.autoroute import (  # type: ignore[import]
    AutorouteConfig, autoroute_leg, depth_penalty)


def _barrier_fetcher(points):
    """Deep water (-50 m) everywhere except a vertical land wall at
    lon in [13.00, 13.02) spanning lat [44.90, 45.10], leaving a gap south of
    lat 44.90 so a detour exists. Land => elevation +10 m."""
    out = []
    for lat, lon in points:
        if 13.00 <= lon < 13.02 and 44.90 <= lat <= 45.10:
            out.append(10.0)      # land barrier
        else:
            out.append(-50.0)     # deep water
    return out


def test_depth_penalty_bands():
    cfg = AutorouteConfig()
    assert depth_penalty(2.0, cfg) == float("inf")   # < hard_min
    assert depth_penalty(4.0, cfg) == 25.0           # 3.2-5
    assert depth_penalty(7.0, cfg) == 5.0            # 5-10
    assert depth_penalty(20.0, cfg) == 1.0           # >= prefer


def test_straight_leg_when_all_deep():
    g = GeoGrid(fetcher=lambda pts: [-50.0 for _ in pts], cell_deg=0.02)
    path = autoroute_leg(g, (45.0, 12.50), (45.0, 12.80), AutorouteConfig())
    assert path == [(45.0, 12.50), (45.0, 12.80)]    # no detour


def test_routes_around_land_barrier():
    g = GeoGrid(fetcher=_barrier_fetcher, cell_deg=0.02)
    a, b = (45.0, 12.95), (45.0, 13.10)              # straight line crosses the wall
    path = autoroute_leg(g, a, b, AutorouteConfig())
    assert path[0] == a and path[-1] == b
    assert len(path) > 2                              # detour inserted
    # every interior point is navigable (not on the land wall)
    for lat, lon in path:
        assert not g.is_land(lat, lon)


def test_fallback_to_straight_on_node_cap():
    g = GeoGrid(fetcher=_barrier_fetcher, cell_deg=0.02)
    cfg = AutorouteConfig(max_nodes=1)               # force the cap
    a, b = (45.0, 12.95), (45.0, 13.10)
    path = autoroute_leg(g, a, b, cfg)
    assert path == [a, b]                             # logged + straight fallback
