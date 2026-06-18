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
    assert r2.to_waypoint_dicts() == wps
