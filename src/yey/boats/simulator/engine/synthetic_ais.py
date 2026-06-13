# signalk/sim/modules/synthetic_ais.py
# ruff: noqa: T201,S311
"""Synthetic AIS traffic — injects a few moving vessels around own ship into
SignalK so the assistant's traffic / CPA-TCPA / proximity features have data to
work with when there's no real AISSTREAM feed. Purely local: it only writes to
SignalK via the same writer the sim uses (no external API)."""
from __future__ import annotations
import asyncio
import math
import random
from collections.abc import Callable

from yey.boats.simulator.engine.route import haversine_nm  # type: ignore[import]
from yey.boats.simulator.engine.signalk_writer import SignalKWriter  # type: ignore[import]

# AIS ship-type codes: 70 cargo, 36 sailing, 30 fishing, 60 passenger.
_FLEET = [
    {"mmsi": "247100111", "name": "MV Adriatic Star", "type": 70, "sog": 11.0},
    {"mmsi": "238200222", "name": "SY Bora",          "type": 36, "sog": 6.0},
    {"mmsi": "201300333", "name": "FV Riba",          "type": 30, "sog": 4.5},
    {"mmsi": "247400444", "name": "HSC Liburnija",    "type": 60, "sog": 23.0},
]
_RESPAWN_NM = 18.0


def _offset(lat: float, lon: float, bearing_deg: float, dist_nm: float) -> tuple[float, float]:
    b = math.radians(bearing_deg)
    nlat = lat + (dist_nm * math.cos(b)) / 60.0
    nlon = lon + (dist_nm * math.sin(b)) / (60.0 * math.cos(math.radians(lat)))
    return nlat, nlon


class SyntheticTraffic:
    def __init__(self, writer: SignalKWriter,
                 get_pos: Callable[[], tuple[float, float]], dt: float = 3.0) -> None:
        self._writer = writer
        self._get_pos = get_pos
        self._dt = dt
        self._vessels: list[dict] = []

    def _spawn(self, spec: dict, olat: float, olon: float, converging: bool) -> dict:
        brg = random.uniform(0, 360)
        dist = random.uniform(4.0, 9.0)
        lat, lon = _offset(olat, olon, brg, dist)
        if converging:                      # steer roughly back toward own ship
            cog = (brg + 180 + random.uniform(-25, 25)) % 360
        else:
            cog = random.uniform(0, 360)
        return {"mmsi": spec["mmsi"], "name": spec["name"], "type": spec["type"],
                "lat": lat, "lon": lon, "cog": cog,
                "sog": spec["sog"] * random.uniform(0.8, 1.1)}

    async def run(self) -> None:
        olat, olon = self._get_pos()
        for i, spec in enumerate(_FLEET):
            self._vessels.append(self._spawn(spec, olat, olon, converging=(i == 0)))
        print(f"[synth-ais] generating {len(self._vessels)} synthetic vessels (no AISSTREAM key)")
        while True:
            olat, olon = self._get_pos()
            for v in self._vessels:
                d = v["sog"] * (self._dt / 3600.0)        # nm advanced this tick
                v["lat"], v["lon"] = _offset(v["lat"], v["lon"], v["cog"], d)
                if haversine_nm(olat, olon, v["lat"], v["lon"]) > _RESPAWN_NM:
                    v.update(self._spawn(v, olat, olon, converging=True))
                try:
                    await self._writer.enqueue_ais(
                        v["mmsi"], v["lat"], v["lon"], v["cog"], v["sog"],
                        v["name"], v["type"])
                except Exception as exc:  # noqa: BLE001
                    print(f"[synth-ais] enqueue failed: {exc!r}")
            await asyncio.sleep(self._dt)
