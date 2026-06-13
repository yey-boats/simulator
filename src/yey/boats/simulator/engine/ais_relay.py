# signalk/sim/modules/ais_relay.py
# ruff: noqa: T201
from __future__ import annotations
import asyncio
import json
import os
from collections.abc import Callable
import websockets  # type: ignore[import]
from yey.boats.simulator.engine.route import haversine_nm  # type: ignore[import]
from yey.boats.simulator.engine.signalk_writer import SignalKWriter  # type: ignore[import]

SELF_MMSI     = "235177007"
BBOX_DEG      = 0.34      # ≈ 20 nm
AIS_WS_URL    = "wss://stream.aisstream.io/v0/stream"
RESUB_DIST_NM = 5.0
IDLE_RESUB_S  = 30.0     # re-center bbox after this much silence (open-water gap)

# Position-bearing AIS message types (exact names from AISStream v0 schema).
# Wrong names → server drops the connection with no close frame.
_FILTER_TYPES = ["PositionReport",
                 "StandardClassBCsPositionReport",
                 "ExtendedClassBCsPositionReport"]


def _bbox_for(lat: float, lon: float) -> list:
    return [
        [lat - BBOX_DEG, lon - BBOX_DEG],
        [lat + BBOX_DEG, lon + BBOX_DEG],
    ]


def _within_20nm(self_lat: float, self_lon: float,
                 target_lat: float, target_lon: float) -> bool:
    return haversine_nm(self_lat, self_lon, target_lat, target_lon) < 20.0


def _parse_ais_message(msg: dict) -> dict | None:
    """Extract vessel info from AISStream message. Returns None to skip."""
    meta = msg.get("MetaData", {})
    mmsi = str(meta.get("MMSI", ""))
    if mmsi == SELF_MMSI:
        return None

    msg_body = msg.get("Message", {})
    report = (msg_body.get("PositionReport")
              or msg_body.get("StandardClassBCsPositionReport")
              or msg_body.get("ExtendedClassBCsPositionReport"))
    if not report:
        return None

    lat = report.get("Latitude", 0.0)
    lon = report.get("Longitude", 0.0)
    if abs(lat) > 90 or abs(lon) > 180:   # AISStream 91/181 = no-fix sentinel
        return None

    return {
        "mmsi":      mmsi,
        "lat":       lat,
        "lon":       lon,
        "cog_deg":   report.get("Cog", 0.0),
        "sog_kts":   report.get("Sog", 0.0),
        "name":      meta.get("ShipName", "").strip(),
        "ship_type": meta.get("ShipType", 0),
    }


class AISRelay:
    def __init__(self, writer: SignalKWriter,
                 get_position: Callable[[], tuple[float, float]]) -> None:
        self._writer      = writer
        self._get_pos     = get_position
        self._api_key     = os.environ.get("AISSTREAM_API_KEY", "").strip()
        self._last_sub_lat = 0.0
        self._last_sub_lon = 0.0
        self._running     = False

    async def run(self) -> None:
        if not self._api_key:
            print("[AIS] AISSTREAM_API_KEY not set — AIS relay disabled")
            return
        self._running = True
        while self._running:
            try:
                await self._connect_and_stream()
            except Exception as exc:
                print(f"[AIS] disconnected: {exc!r}, retrying in 15s")
                await asyncio.sleep(15)

    async def stop(self) -> None:
        self._running = False

    async def _connect_and_stream(self) -> None:
        lat, lon = self._get_pos()
        self._last_sub_lat, self._last_sub_lon = lat, lon
        sub_msg = json.dumps({
            "APIKey":        self._api_key,
            "BoundingBoxes": [_bbox_for(lat, lon)],
        })
        print(f"[AIS] connecting, bbox centre ({lat:.3f}, {lon:.3f})")
        async with websockets.connect(AIS_WS_URL) as ws:
            await ws.send(sub_msg)
            # Read first frame with timeout — AISStream sends {"ERROR":"..."} on bad
            # subscription then closes without a WS close frame (ConnectionClosedError).
            try:
                first_raw = await asyncio.wait_for(ws.recv(), timeout=8.0)
                first_msg = json.loads(first_raw)
                if "ERROR" in first_msg:
                    print(f"[AIS] server error: {first_msg['ERROR']}")
                    return
                print("[AIS] subscribed, first frame OK")
                pending = [first_raw]
            except asyncio.TimeoutError:
                print("[AIS] subscribed (no initial server frame within 8 s)")
                pending = []

            rx = 0
            queued = list(pending)   # first frame, if any, drained before polling

            # Poll the socket with a timeout instead of blocking on `async for`.
            # In empty water no frames arrive, so a blocking read would never let
            # us re-center the bbox — the subscription would stay pinned to a
            # region the boat already left and relay nothing. On idle we check
            # movement and reconnect with a fresh bbox.
            while self._running:
                if queued:
                    raw = queued.pop(0)
                else:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=IDLE_RESUB_S)
                    except asyncio.TimeoutError:
                        cur_lat, cur_lon = self._get_pos()
                        if haversine_nm(cur_lat, cur_lon, self._last_sub_lat,
                                        self._last_sub_lon) > RESUB_DIST_NM:
                            print("[AIS] idle + moved >5 nm, resubscribing")
                            return  # reconnect with new bbox
                        continue

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # AISStream sends a plain error dict on bad API key / bad request
                if "ERROR" in msg:
                    print(f"[AIS] server error: {msg['ERROR']}")
                    return

                vessel = _parse_ais_message(msg)
                if vessel is None:
                    continue

                cur_lat, cur_lon = self._get_pos()
                if not _within_20nm(cur_lat, cur_lon, vessel["lat"], vessel["lon"]):
                    continue

                rx += 1
                if rx == 1 or rx % 100 == 0:
                    print(f"[AIS] {rx} targets relayed (latest: {vessel['name'] or vessel['mmsi']})")

                await self._writer.enqueue_ais(
                    vessel["mmsi"], vessel["lat"], vessel["lon"],
                    vessel["cog_deg"], vessel["sog_kts"],
                    vessel["name"], vessel["ship_type"],
                )

                # Resubscribe if boat moved > 5 nm from last subscription centre
                if haversine_nm(cur_lat, cur_lon,
                                self._last_sub_lat, self._last_sub_lon) > RESUB_DIST_NM:
                    print("[AIS] moved >5 nm, resubscribing")
                    return  # reconnect with new bbox
