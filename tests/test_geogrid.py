# tests/test_geogrid.py
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from __future__ import annotations

import asyncio
import contextlib
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


def test_sample_raises_on_short_fetch_result_and_leaves_cache_untouched():
    """SIM-1 regression: a partial fetcher response must not silently pair
    the wrong elevation with the wrong cell (bare zip() truncates instead of
    raising). strict=True must surface the mismatch and the cache must stay
    empty rather than being corrupted with misaligned values."""
    def short_fetcher(points):
        return [-30.0 for _ in points][:-1]  # one fewer than requested

    g = GeoGrid(fetcher=short_fetcher, cell_deg=0.02)
    with pytest.raises(ValueError):
        g.sample([(45.00, 13.00), (45.00, 13.02), (45.02, 13.00), (45.02, 13.02)])
    assert g._elev == {}  # nothing partially/incorrectly written


@pytest.mark.asyncio
async def test_fetch_loop_raises_on_short_fetch_result_leaves_misses_queued():
    """Same as above but via the background fetch_loop() path: the existing
    `except Exception` handler should catch the strict=True ValueError and
    degrade gracefully (log + retry) instead of writing misaligned data or
    calling save()."""
    def short_fetcher(points):
        return [-20.0 for _ in points][:-1]

    g = GeoGrid(fetcher=short_fetcher, cell_deg=0.02)
    g.depth_at(45.0, 13.0)  # miss -> queued
    assert g._misses
    pending_before = set(g._misses)

    task = asyncio.create_task(g.fetch_loop(interval=100.0))
    await asyncio.sleep(0.05)  # let one fetch attempt run and fail
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert g._elev == {}                       # no misaligned writes
    assert g._misses == pending_before          # still queued for retry


def test_opentopo_fetch_honors_env_url(monkeypatch):
    """GEOGRID_API_URL repoints the fetcher at a self-hosted server, and the
    public-only inter-batch sleep is skipped for a custom URL."""
    from yey.boats.simulator.engine import geogrid as gg

    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [{"elevation": -12.0}]}

    def fake_get(url, timeout=30):
        captured["url"] = url
        return _Resp()

    monkeypatch.setattr(gg.httpx, "get", fake_get)
    monkeypatch.setenv("GEOGRID_API_URL", "http://localhost:8089/v1/gebco2020")
    out = gg._opentopo_fetch([(43.0, 16.0)])
    assert out == [-12.0]
    assert captured["url"].startswith(
        "http://localhost:8089/v1/gebco2020?locations=43.00000,16.00000")
