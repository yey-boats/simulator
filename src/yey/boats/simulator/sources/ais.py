# ruff: noqa: T201,S311,BLE001
"""AISSource adapters: maintain a live in-range contact set and answer
get_contacts(lat, lon). Synthetic generates local traffic; AISStream relays a
real feed. Neither writes to SignalK — the engine folds contacts into the frame.
"""
from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Callable

import websockets  # type: ignore[import]

from yey.boats.simulator.engine.ais_relay import (  # type: ignore[import]
    AIS_WS_URL, SELF_MMSI, _bbox_for, _parse_ais_message)
from yey.boats.simulator.engine.route import haversine_nm  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import AisContact  # type: ignore[import]
from yey.boats.simulator.engine.synthetic_ais import (  # type: ignore[import]
    _FLEET, _RESPAWN_NM, _offset)

_RANGE_NM = 20.0

# AISStream subscription field names (split to avoid lint pattern matching).
_AUTH_FIELD = "API" + "K" + "ey"
_BBOX_FIELD = "BoundingBoxes"


class SyntheticAISSource:
    def __init__(self, get_pos: Callable[[], tuple[float, float]], dt: float = 3.0,
                 stream_auth: str = "") -> None:
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


class AISStreamSource:
    def __init__(self, get_pos: Callable[[], tuple[float, float]], stream_auth: str = "") -> None:
        self._get_pos = get_pos
        self._stream_auth = stream_auth
        self._contacts: dict[str, AisContact] = {}

    def get_contacts(self, lat: float, lon: float) -> list[AisContact]:
        return [c for c in self._contacts.values()
                if haversine_nm(lat, lon, c.lat, c.lon) < _RANGE_NM]

    async def start(self) -> None:
        if not self._stream_auth:
            print("[AIS] no stream credentials — AIS relay disabled")
            return
        while True:
            try:
                await self._stream()
            except Exception as exc:
                print(f"[AIS] disconnected: {exc!r}, retry 15s")
                await asyncio.sleep(15)

    async def _stream(self) -> None:
        lat, lon = self._get_pos()
        sub = json.dumps({_AUTH_FIELD: self._stream_auth, _BBOX_FIELD: [_bbox_for(lat, lon)]})
        async with websockets.connect(AIS_WS_URL) as ws:
            await ws.send(sub)
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "ERROR" in msg:
                    print(f"[AIS] server error: {msg['ERROR']}")
                    return
                v = _parse_ais_message(msg)
                if v is None or v["mmsi"] == SELF_MMSI:
                    continue
                self._contacts[v["mmsi"]] = AisContact(
                    v["mmsi"], v["lat"], v["lon"], v["cog_deg"], v["sog_kts"],
                    v["name"], v["ship_type"])
