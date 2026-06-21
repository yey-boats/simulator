# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Tests for random-passage generation (engine/passage.py)."""
from __future__ import annotations

import random

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.autoroute import AutorouteConfig  # type: ignore[import]
from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]
from yey.boats.simulator.engine.passage import (  # type: ignore[import]
    DEST_MIN_DEPTH_M, destination_point, make_passage)
from yey.boats.simulator.engine.route import (  # type: ignore[import]
    great_circle_bearing, haversine_nm)


def test_destination_point_distance_and_bearing():
    # 50 nm due east of (43,16)
    dlat, dlon = destination_point(43.0, 16.0, 90.0, 50.0)
    assert haversine_nm(43.0, 16.0, dlat, dlon) == pytest.approx(50.0, abs=0.3)  # noqa: S101
    assert great_circle_bearing(43.0, 16.0, dlat, dlon) == pytest.approx(90.0, abs=2.0)  # noqa: S101


def test_make_passage_open_water_in_range():
    g = GeoGrid(fetcher=lambda pts: [-50.0 for _ in pts], cell_deg=0.02)
    wps = make_passage(43.0, 16.0, g, AutorouteConfig(), 40.0, 60.0,
                       rng=random.Random(1))
    assert wps is not None  # noqa: S101
    assert wps[0].name == "PASSAGE-START"  # noqa: S101
    assert wps[-1].name.startswith("DEST-")  # noqa: S101
    d = haversine_nm(43.0, 16.0, wps[-1].lat, wps[-1].lon)
    assert 40.0 <= d <= 60.0, f"passage length {d:.1f} nm out of range"  # noqa: S101
    for w in wps:                                  # whole passage is navigable
        assert g.depth_at(w.lat, w.lon) >= AutorouteConfig().hard_min_m  # noqa: S101


def test_make_passage_none_when_all_land():
    g = GeoGrid(fetcher=lambda pts: [10.0 for _ in pts], cell_deg=0.02)  # all land
    wps = make_passage(43.0, 16.0, g, AutorouteConfig(), 40.0, 60.0,
                       rng=random.Random(1), tries=12)
    assert wps is None  # noqa: S101


def test_make_passage_avoids_land_destination_and_path():
    # Land wall east of lon 16.3; deep water elsewhere.
    def fetcher(points):
        return [10.0 if lon > 16.3 else -50.0 for _lat, lon in points]

    g = GeoGrid(fetcher=fetcher, cell_deg=0.02)
    wps = make_passage(43.0, 16.0, g, AutorouteConfig(), 40.0, 60.0,
                       rng=random.Random(7))
    assert wps is not None  # noqa: S101
    for w in wps:                                  # nothing on the land wall
        assert not g.is_land(w.lat, w.lon)  # noqa: S101
    assert g.depth_at(wps[-1].lat, wps[-1].lon) >= DEST_MIN_DEPTH_M  # noqa: S101
