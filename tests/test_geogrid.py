# tests/test_geogrid.py
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from __future__ import annotations

from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]


def _flat_fetcher(elev_m):
    """Fetcher that returns a constant elevation for every requested point."""
    def f(points):
        return [elev_m for _ in points]
    return f


def test_depth_at_uses_fetched_elevation_via_sample():
    g = GeoGrid(fetcher=_flat_fetcher(-30.0), cell_deg=0.02)
    g.sample([(45.0, 13.0)])              # one cell now cached at elev -30
    assert g.depth_at(45.0, 13.0) == 30.0  # depth = -elev
    assert g.is_land(45.0, 13.0) is False


def test_depth_at_miss_returns_fallback_and_queues_without_network():
    calls = {"n": 0}
    def counting(points):
        calls["n"] += 1
        return [-5.0 for _ in points]
    g = GeoGrid(fetcher=counting, cell_deg=0.02, fallback_depth_m=50.0)
    # No sample() yet -> depth_at must NOT call the fetcher (non-blocking).
    assert g.depth_at(10.0, 10.0) == 50.0
    assert calls["n"] == 0
    assert g._cell_of(10.0, 10.0) in g._misses


def test_land_classification_positive_elevation():
    g = GeoGrid(fetcher=_flat_fetcher(12.0), cell_deg=0.02)
    g.sample([(45.5, 13.5)])
    assert g.is_land(45.5, 13.5) is True
    assert g.depth_at(45.5, 13.5) == 0.0   # land => depth clamped to 0
