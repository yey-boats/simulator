"""Pure route I/O helpers: GeoJSON <-> waypoint dicts, and validation.

A waypoint dict is {"name": str, "lat": float, "lon": float}. GeoJSON uses
[lon, lat] order (RFC 7946); waypoint dicts keep lat/lon explicit.
"""
from __future__ import annotations

from typing import Any


class WaypointError(ValueError):
    """Raised when waypoint data is structurally invalid."""


def validate_waypoints(wps: list[dict]) -> list[dict]:
    if not isinstance(wps, list) or len(wps) < 2:
        raise WaypointError("route needs at least 2 waypoints")
    out = []
    for i, w in enumerate(wps):
        try:
            lat = float(w["lat"])
            lon = float(w["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WaypointError(f"waypoint {i}: missing/invalid lat/lon") from exc
        if not (-90.0 <= lat <= 90.0):
            raise WaypointError(f"waypoint {i}: lat {lat} out of range")
        if not (-180.0 <= lon <= 180.0):
            raise WaypointError(f"waypoint {i}: lon {lon} out of range")
        out.append({"name": str(w.get("name") or f"WP{i+1}"), "lat": lat, "lon": lon})
    return out


def waypoints_from_geojson(gj: dict[str, Any]) -> list[dict]:
    t = gj.get("type")
    feats = gj.get("features") if t == "FeatureCollection" else [gj] if t == "Feature" else None
    if feats is None:
        raise WaypointError("unsupported GeoJSON: expected Feature/FeatureCollection")
    wps: list[dict] = []
    for f in feats:
        geom = f.get("geometry") or {}
        props = f.get("properties") or {}
        if geom.get("type") == "LineString":
            names = props.get("waypoints") or []
            for i, (lon, lat) in enumerate(geom.get("coordinates", [])):
                nm = names[i].get("name") if i < len(names) and isinstance(names[i], dict) else None
                wps.append({"name": nm or f"WP{i+1}", "lat": float(lat), "lon": float(lon)})
        elif geom.get("type") == "Point":
            lon, lat = geom["coordinates"][0], geom["coordinates"][1]
            wps.append({"name": props.get("name") or f"WP{len(wps)+1}",
                        "lat": float(lat), "lon": float(lon)})
    if not wps:
        raise WaypointError("no LineString/Point geometry found in GeoJSON")
    return wps


def waypoints_to_geojson(wps: list[dict], name: str = "Route") -> dict:
    return {"type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[w["lon"], w["lat"]] for w in wps]},
            "properties": {"name": name,
                           "waypoints": [{"name": w["name"]} for w in wps]}}
