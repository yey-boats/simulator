# signalk/sim/modules/route.py
from __future__ import annotations
import json
import math
import sys
import zipfile
import pathlib
from dataclasses import dataclass, field
import httpx  # type: ignore[import]

R_NM = 3440.065  # Earth radius in nautical miles


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lon2 - lon1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return 2 * R_NM * math.asin(math.sqrt(a))


def great_circle_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from (lat1,lon1) to (lat2,lon2) in degrees [0, 360)."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δλ = math.radians(lon2 - lon1)
    x = math.sin(Δλ) * math.cos(φ2)
    y = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(Δλ)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def dead_reckon(lat: float, lon: float, sog_kts: float,
                cog_deg: float, dt_s: float = 1.0):
    """Advance position by sog_kts for dt_s seconds on cog_deg. Returns (lat, lon)."""
    dist_nm = sog_kts * dt_s / 3600
    dist_rad = dist_nm / R_NM
    φ1 = math.radians(lat)
    λ1 = math.radians(lon)
    tc = math.radians(cog_deg)
    φ2 = math.asin(math.sin(φ1) * math.cos(dist_rad) +
                   math.cos(φ1) * math.sin(dist_rad) * math.cos(tc))
    λ2 = λ1 + math.atan2(math.sin(tc) * math.sin(dist_rad) * math.cos(φ1),
                          math.cos(dist_rad) - math.sin(φ1) * math.sin(φ2))
    return math.degrees(φ2), math.degrees(λ2)


@dataclass
class Waypoint:
    name: str
    lat: float
    lon: float
    marina: str
    berth_heading: float
    refill_water: bool
    refill_fuel: bool
    pump_out_bw: bool


@dataclass
class Route:
    waypoints: list[Waypoint]
    current_index: int = 0
    _depth_profile: list[dict] = field(default_factory=list, repr=False)

    @classmethod
    def load(cls, kmz_path: pathlib.Path, marinas_path: pathlib.Path) -> Route:
        marinas = {m["name"]: m for m in json.loads(marinas_path.read_text())}
        waypoints = []
        kml_text = _extract_kml(kmz_path)
        from lxml import etree  # type: ignore[import]
        ns = {"k": "http://www.opengis.net/kml/2.2"}
        root = etree.fromstring(kml_text.encode())
        for pm in root.findall(".//k:Placemark", ns):
            name = pm.findtext("k:name", namespaces=ns, default="").strip()
            coords = pm.findtext(".//k:coordinates", namespaces=ns, default="").strip()
            lon_s, lat_s, *_ = coords.split(",")
            m = marinas.get(name, {})
            waypoints.append(Waypoint(
                name=name, lat=float(lat_s), lon=float(lon_s),
                marina=m.get("marina", ""),
                berth_heading=m.get("berth_heading", 0.0),
                refill_water=m.get("refill_water", False),
                refill_fuel=m.get("refill_fuel", False),
                pump_out_bw=m.get("pump_out_bw", False),
            ))
        return cls(waypoints=waypoints)

    @property
    def current(self) -> Waypoint:
        return self.waypoints[self.current_index]

    @property
    def next_wp(self) -> Waypoint:
        return self.waypoints[(self.current_index + 1) % len(self.waypoints)]

    def advance(self) -> None:
        self.current_index = (self.current_index + 1) % len(self.waypoints)

    def bearing_to_next(self, lat: float, lon: float) -> float:
        wp = self.next_wp
        return great_circle_bearing(lat, lon, wp.lat, wp.lon)

    def distance_to_next(self, lat: float, lon: float) -> float:
        wp = self.next_wp
        return haversine_nm(lat, lon, wp.lat, wp.lon)

    def resync_from_position(self, lat: float, lon: float,
                             at_wp_nm: float = 0.5) -> tuple[int, float]:
        """Set current_index to match a resumed (lat, lon) — e.g. read from
        SignalK after a restart — so the boat continues from where it left off
        instead of jumping back to the route origin.

        If the position is essentially on top of a waypoint (within at_wp_nm),
        treat it as moored there (current_index = that waypoint, so the next
        target is the following one). Otherwise pick the leg i→i+1 the position
        lies on (minimises detour cost = d(pos,a)+d(pos,b)−leg(a,b), ≈0 on-leg)
        and set current_index = i, so next_wp is the waypoint ahead.

        Returns (current_index, distance_nm_to_nearest_waypoint)."""
        n = len(self.waypoints)
        near_i, near_d = min(
            ((i, haversine_nm(lat, lon, w.lat, w.lon))
             for i, w in enumerate(self.waypoints)),
            key=lambda t: t[1])
        if near_d <= at_wp_nm:
            self.current_index = near_i
            return near_i, near_d

        best_i, best_cost = 0, float("inf")
        for i in range(n):
            a, b = self.waypoints[i], self.waypoints[(i + 1) % n]
            leg = haversine_nm(a.lat, a.lon, b.lat, b.lon)
            cost = (haversine_nm(lat, lon, a.lat, a.lon)
                    + haversine_nm(lat, lon, b.lat, b.lon) - leg)
            if cost < best_cost:
                best_cost, best_i = cost, i
        self.current_index = best_i
        return best_i, near_d

    def load_depth_profile(self, cache_path: pathlib.Path,
                           samples_per_leg: int = 8) -> None:
        """Load depth profile from cache, or fetch from OpenTopoData and save.

        On a fetch/parse failure (e.g. offline or rate-limited first boot) the
        profile degrades to empty — depth_at() then returns a 50 m default —
        instead of crashing the simulator. No cache is written on failure, so a
        later run with connectivity can still populate it.
        """
        if cache_path.exists():
            self._depth_profile = json.loads(cache_path.read_text())
            return
        try:
            self._depth_profile = _fetch_depth_profile(self.waypoints, samples_per_leg)
        except Exception as exc:  # noqa: BLE001
            msg = (f"[route] depth profile fetch failed ({exc!r}); "
                   f"using default depth (50 m)")
            print(msg, file=sys.stderr, flush=True)  # noqa: T201
            self._depth_profile = []
            return
        cache_path.write_text(json.dumps(self._depth_profile, indent=2))

    def depth_at(self, lat: float, lon: float) -> float:
        """Interpolate depth (metres, positive = below surface) from profile."""
        if not self._depth_profile:
            return 50.0  # fallback
        best = min(self._depth_profile,
                   key=lambda p: haversine_nm(lat, lon, p["lat"], p["lon"]))
        return best["depth_m"]


def _extract_kml(kmz_path: pathlib.Path) -> str:
    with zipfile.ZipFile(kmz_path) as zf:
        kml_name = next((n for n in zf.namelist() if n.endswith(".kml")), None)
        if kml_name is None:
            raise ValueError(f"No .kml entry found in {kmz_path}")
        return zf.read(kml_name).decode("utf-8")


def _fetch_depth_profile(waypoints: list[Waypoint],
                         samples_per_leg: int) -> list[dict]:
    """Fetch GEBCO depths via OpenTopoData. Rate: ≤1 req/s, ≤100 locs/req."""
    import time
    points = []
    for i in range(len(waypoints)):
        a = waypoints[i]
        b = waypoints[(i + 1) % len(waypoints)]
        for k in range(samples_per_leg):
            α = k / samples_per_leg
            points.append((a.lat + α * (b.lat - a.lat),
                           a.lon + α * (b.lon - a.lon)))

    results = []
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        locs = "|".join(f"{lat:.5f},{lon:.5f}" for lat, lon in batch)
        url = f"https://api.opentopodata.org/v1/gebco2020?locations={locs}"
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        for pt, r in zip(batch, resp.json()["results"]):
            elev = r.get("elevation") or 0
            results.append({"lat": pt[0], "lon": pt[1],
                            "depth_m": max(0.0, -elev)})
        if i + batch_size < len(points):
            time.sleep(1.1)
    return results
