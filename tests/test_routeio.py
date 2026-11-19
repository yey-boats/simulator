# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from pathlib import Path

import pytest

from yey.boats.simulator.routeio import (
    waypoints_from_geojson, validate_waypoints, WaypointError,
)
from yey.boats.simulator.engine.route import Route


def test_geojson_linestring_to_waypoints():
    gj = {"type": "Feature",
          "geometry": {"type": "LineString",
                       "coordinates": [[13.5, 45.4], [14.2, 44.9]]},
          "properties": {"waypoints": [{"name": "A"}, {"name": "B"}]}}
    wps = waypoints_from_geojson(gj)
    assert wps == [{"name": "A", "lat": 45.4, "lon": 13.5},
                   {"name": "B", "lat": 44.9, "lon": 14.2}]


def test_geojson_point_features_to_waypoints():
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [13.5, 45.4]},
         "properties": {"name": "Start"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [14.2, 44.9]},
         "properties": {"name": "End"}}]}
    wps = waypoints_from_geojson(gj)
    assert [w["name"] for w in wps] == ["Start", "End"]
    assert wps[0]["lat"] == 45.4 and wps[0]["lon"] == 13.5


def test_validate_rejects_too_few():
    with pytest.raises(WaypointError):
        validate_waypoints([{"name": "only", "lat": 45.0, "lon": 13.0}])


def test_validate_rejects_bad_coords():
    with pytest.raises(WaypointError):
        validate_waypoints([{"name": "a", "lat": 91.0, "lon": 13.0},
                            {"name": "b", "lat": 45.0, "lon": 13.0}])


def test_route_json_roundtrip(tmp_path: Path):
    wps = [{"name": "A", "lat": 45.4, "lon": 13.5},
           {"name": "B", "lat": 44.9, "lon": 14.2}]
    r = Route.from_waypoint_dicts(wps)
    p = tmp_path / "route.json"
    r.save_json(p)
    r2 = Route.load_json(p)
    assert [(d["name"], d["lat"], d["lon"]) for d in r2.to_waypoint_dicts()] == \
        [(d["name"], d["lat"], d["lon"]) for d in wps]
    # idempotent: a second save/load changes nothing (the default marina stop sticks)
    r2.save_json(p)
    assert Route.load_json(p).to_waypoint_dicts() == r2.to_waypoint_dicts()


# #22: a route saved through the web admin (to_waypoint_dicts -> PUT /api/route ->
# validate_waypoints -> from_waypoint_dicts -> save_json/load_json) must keep its
# marina stops, or the boat never moors again (only marina waypoints moor, #12).

def _marina_route():
    return Route.load(__import__("yey.boats.simulator.resources",
                                 fromlist=["x"]).route_kmz(),
                      __import__("yey.boats.simulator.resources",
                                 fromlist=["x"]).marinas_json())


def test_web_admin_save_keeps_marina_stops(tmp_path: Path):
    r = _marina_route()
    before = [(w.name, w.marina, w.berth_heading, w.refill_water, w.refill_fuel, w.pump_out_bw)
              for w in r.waypoints]
    assert any(m for _, m, *_ in before), "fixture route has marina stops"
    # the web admin round trip: GET -> PUT (validated) -> persisted -> reloaded
    saved = Route.from_waypoint_dicts(validate_waypoints(r.to_waypoint_dicts()))
    p = tmp_path / "route.json"
    saved.save_json(p)
    after = [(w.name, w.marina, w.berth_heading, w.refill_water, w.refill_fuel, w.pump_out_bw)
             for w in Route.load_json(p).waypoints]
    assert after == before


def test_marina_metadata_validated():
    wps = validate_waypoints([
        {"name": "A", "lat": 45.4, "lon": 13.5, "marina": "ACI X", "berth_heading": "270",
         "refill_water": 1, "refill_fuel": 0, "pump_out_bw": True},
        {"name": "B", "lat": 44.9, "lon": 14.2},
    ])
    assert wps[0]["marina"] == "ACI X" and wps[0]["berth_heading"] == 270.0
    assert wps[0]["refill_water"] is True and wps[0]["refill_fuel"] is False
    assert "marina" not in wps[1] or wps[1]["marina"] == ""
    with pytest.raises(WaypointError):
        validate_waypoints([{"name": "A", "lat": 45.4, "lon": 13.5, "marina": "M",
                             "berth_heading": "x"},
                            {"name": "B", "lat": 44.9, "lon": 14.2}])


def test_route_without_marina_info_moors_somewhere():
    """An uploaded route with no marina info (GeoJSON, a plain list) gets marina
    metadata from the bundled marinas by waypoint name, and if still none is a marina
    stop, its last waypoint moors (the pre-#12 behaviour at least once per loop)."""
    named = Route.from_waypoint_dicts([
        {"name": "Venice (Porto Lido)", "lat": 45.4317, "lon": 12.3405},
        {"name": "Somewhere", "lat": 45.0, "lon": 13.0},
    ])
    assert named.waypoints[0].marina == "ACI Venezia"
    assert named.waypoints[0].refill_water is True
    plain = Route.from_waypoint_dicts([
        {"name": "A", "lat": 45.4, "lon": 13.5},
        {"name": "B", "lat": 44.9, "lon": 14.2},
    ])
    assert [bool(w.marina) for w in plain.waypoints] == [False, True]
