# ruff: noqa: T201,BLE001
"""AISStream source — relays live AIS traffic from the AISStream WebSocket feed."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import websockets  # type: ignore[import]

from yey.boats.simulator.engine.ais_relay import (  # type: ignore[import]
    AIS_WS_URL, SELF_MMSI, _bbox_for, _parse_ais_message)
from yey.boats.simulator.engine.route import haversine_nm  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import AisContact  # type: ignore[import]

_RANGE_NM = 20.0


class AISStreamSource:
    def __init__(self, get_pos: Callable[[], tuple[float, float]], api_key: str = "") -> None:
        self._get_pos = get_pos
        self._api_key = api_key
        self._contacts: dict[str, AisContact] = {}

    def get_contacts(self, lat: float, lon: float) -> list[AisContact]:
        return [c for c in self._contacts.values()
                if haversine_nm(lat, lon, c.lat, c.lon) < _RANGE_NM]

    async def start(self) -> None:
        if not self._api_key:
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
        sub = json.dumps({"APIKey": self._api_key, "BoundingBoxes": [_bbox_for(lat, lon)]})
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
