# tests/test_geogrid.py
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest  # type: ignore[import]

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


def _plane_fetcher(points):
    # elevation varies with lon so bilinear interpolation is observable:
    # elev = -10 - 1000*lon  (deeper as lon grows)
    return [-10.0 - 1000.0 * lon for _lat, lon in points]


def test_bilinear_interpolation_between_cells():
    g = GeoGrid(fetcher=_plane_fetcher, cell_deg=0.02)
    # cache the four corners around (45.01, 13.01)
    g.sample([(45.00, 13.00), (45.00, 13.02), (45.02, 13.00), (45.02, 13.02)])
    d = g.depth_at(45.01, 13.01)
    # exact plane => interpolated depth equals the plane value at that point
    assert d == pytest.approx(10.0 + 1000.0 * 13.01, rel=1e-6)


def test_persistence_round_trip(tmp_path: Path):
    p = tmp_path / "geogrid.json"
    g1 = GeoGrid(cache_path=p, fetcher=lambda pts: [-42.0 for _ in pts], cell_deg=0.02)
    g1.sample([(45.0, 13.0)])
    g1.save()
    g2 = GeoGrid(cache_path=p, fetcher=lambda pts: [0.0 for _ in pts], cell_deg=0.02)
    assert g2.depth_at(45.0, 13.0) == 42.0  # loaded from disk, no fetch


@pytest.mark.asyncio
async def test_fetch_loop_drains_misses():
    g = GeoGrid(fetcher=lambda pts: [-20.0 for _ in pts], cell_deg=0.02)
    g.depth_at(45.0, 13.0)                  # miss -> queued
    assert g._misses
    task = asyncio.create_task(g.fetch_loop(interval=0.01))
    for _ in range(50):
        if not g._misses:
            break
        await asyncio.sleep(0.02)
    task.cancel()
    assert not g._misses
    assert g.depth_at(45.0, 13.0) == 20.0


def test_geogrid_cache_path(tmp_path):
    from yey.boats.simulator import resources  # type: ignore[import]
    p = resources.geogrid_cache_path(tmp_path)
    assert p == tmp_path / "geogrid.json"
    assert tmp_path.exists()
