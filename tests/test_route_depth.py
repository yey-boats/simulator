# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from yey.boats.simulator.engine import route as route_mod  # type: ignore[import]
from yey.boats.simulator.engine.route import Route  # type: ignore[import]
from yey.boats.simulator import resources  # type: ignore[import]


def _load_route():
    return Route.load(resources.route_kmz(), resources.marinas_json())


def test_depth_profile_degrades_on_fetch_failure(monkeypatch, tmp_path):
    r = _load_route()

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(route_mod, "_fetch_depth_profile", boom)
    cache = tmp_path / "depth_profile.json"
    r.load_depth_profile(cache)            # must NOT raise
    assert r._depth_profile == []          # noqa: S101  degraded to empty
    assert not cache.exists()              # noqa: S101  no cache written on failure
    assert r.depth_at(45.0, 13.0) == 50.0  # noqa: S101  default depth fallback
