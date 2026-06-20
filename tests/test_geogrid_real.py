# tests/test_geogrid_real.py
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Integration test against REAL GEBCO bathymetry, replayed from a committed
tile cache. Download the fixture once with:

    YEYBOATS_REFRESH_GEOGRID_FIXTURE=1 PYTHONPATH=src \
      python -m pytest tests/test_geogrid_real.py -q

Thereafter it runs fully offline from tests/fixtures/geogrid_hvar.json.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.geogrid import GeoGrid, _opentopo_fetch  # type: ignore[import]
from yey.boats.simulator.engine.autoroute import (  # type: ignore[import]
    AutorouteConfig, autoroute_leg)

FIXTURE = Path(__file__).parent / "fixtures" / "geogrid_hvar.json"

# Around the island of Hvar (Croatia): deep channel water to the south,
# the island landmass in the middle.
DEEP_WATER = (43.05, 16.45)     # open Adriatic, south of Hvar
ON_ISLAND  = (43.17, 16.60)     # Hvar landmass
WEST_PT    = (43.12, 16.35)     # west of the island, in water
EAST_PT    = (43.12, 16.80)     # east of the island, in water


def _grid() -> GeoGrid:
    refresh = os.environ.get("YEYBOATS_REFRESH_GEOGRID_FIXTURE") == "1"
    if not FIXTURE.exists() and not refresh:
        pytest.skip("geogrid fixture absent; set YEYBOATS_REFRESH_GEOGRID_FIXTURE=1 to record")
    fetcher = _opentopo_fetch if refresh else _no_net
    return GeoGrid(cache_path=FIXTURE, fetcher=fetcher, cell_deg=0.02)


def _no_net(points):
    raise AssertionError("offline test attempted a network fetch; fixture incomplete")


def test_real_depth_is_plausible_in_open_water():
    g = _grid()
    g.sample([DEEP_WATER])
    g.save()
    assert g.depth_at(*DEEP_WATER) > 20.0      # genuinely deep, not 0


def test_real_land_classified_on_island():
    g = _grid()
    g.sample([ON_ISLAND])
    g.save()
    assert g.is_land(*ON_ISLAND) is True


def test_real_autoroute_goes_around_island():
    g = _grid()
    # Tighter bbox to stay within ~400 cells and avoid API rate-limit during recording
    cfg = AutorouteConfig(bbox_margin_deg=0.1)
    path = autoroute_leg(g, WEST_PT, EAST_PT, cfg)
    g.save()
    assert path[0] == WEST_PT and path[-1] == EAST_PT
    for lat, lon in path:
        assert not g.is_land(lat, lon)         # never crosses Hvar
