# ruff: noqa: T201,S311
"""Synthetic AIS source — generates simulated vessel traffic around own position."""
from __future__ import annotations

import asyncio
import random
from collections.abc import Callable

from yey.boats.simulator.engine.route import haversine_nm  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import AisContact  # type: ignore[import]
from yey.boats.simulator.engine.synthetic_ais import (  # type: ignore[import]
    _FLEET, _RESPAWN_NM, _offset)


class SyntheticAISSource:
    def __init__(self, get_pos: Callable[[], tuple[float, float]], dt: float = 3.0) -> None:
        self._get_pos = get_pos
        self._dt = dt
        self._vessels: list[dict] = []

    def _spawn(self, spec: dict, olat: float, olon: float, converging: bool) -> dict:
        brg = random.uniform(0, 360)
        dist = random.uniform(4.0, 9.0)
        lat, lon = _offset(olat, olon, brg, dist)
        cog = (brg + 180 + random.uniform(-25, 25)) % 360 if converging else random.uniform(0, 360)
        return {"mmsi": spec["mmsi"], "name": spec["name"], "type": spec["type"],
                "lat": lat, "lon": lon, "cog": cog,
                "sog": spec["sog"] * random.uniform(0.8, 1.1)}

    def seed(self, olat: float, olon: float) -> None:
        self._vessels = [self._spawn(spec, olat, olon, converging=(i == 0))
                         for i, spec in enumerate(_FLEET)]

    def advance(self, olat: float, olon: float) -> None:
        for v in self._vessels:
            d = v["sog"] * (self._dt / 3600.0)
            v["lat"], v["lon"] = _offset(v["lat"], v["lon"], v["cog"], d)
            if haversine_nm(olat, olon, v["lat"], v["lon"]) > _RESPAWN_NM:
                v.update(self._spawn(v, olat, olon, converging=True))

    def get_contacts(self, lat: float, lon: float) -> list[AisContact]:
        return [AisContact(v["mmsi"], v["lat"], v["lon"], v["cog"], v["sog"],
                           v["name"], v["type"]) for v in self._vessels]

    async def start(self) -> None:
        olat, olon = self._get_pos()
        self.seed(olat, olon)
        print(f"[synth-ais] generating {len(self._vessels)} synthetic vessels")
        while True:
            olat, olon = self._get_pos()
            self.advance(olat, olon)
            await asyncio.sleep(self._dt)
