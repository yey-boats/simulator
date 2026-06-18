"""SignalK telemetry sink: adapts TelemetrySnapshot to the existing
SignalKWriter. open() connects; publish() forwards the snapshot fields to
send_vessel_delta. close() tears down the connection.

The runner reads `.writer` to launch flush_loop()/metadata_loop() and to feed
AIS — those are SignalK-transport concerns owned by the writer, not the engine.
Position-resume and route-resource registration are performed by the runner via
`.writer`, NOT in this sink's open() — open() only calls connect().
"""
from __future__ import annotations

import math
from typing import Any

from yey.boats.simulator.engine.route import great_circle_bearing, haversine_nm  # type: ignore[import]
from yey.boats.simulator.engine.signalk_writer import SignalKWriter  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]


class SignalKSink:
    name = "signalk"

    def __init__(self, host: str = "localhost", port: int = 3000,
                 username: str = "admin", password: str = "admin",  # noqa: S107
                 writer: Any = None) -> None:
        self._username = username
        self._password = password
        self.writer = writer if writer is not None else SignalKWriter(host, port)
        self._last_point_index: int | None = None

    async def open(self) -> None:
        await self.writer.connect(self._username, self._password)

    async def publish(self, snapshot: TelemetrySnapshot) -> None:
        # Compute nearest AIS contact bearing/distance for closestApproach paths.
        closest_approach: tuple[float, float] | None = None
        if snapshot.ais_contacts:
            nav = snapshot.nav
            nearest = min(
                snapshot.ais_contacts,
                key=lambda c: haversine_nm(nav.lat, nav.lon, c.lat, c.lon),
            )
            bearing_rad = math.radians(
                great_circle_bearing(nav.lat, nav.lon, nearest.lat, nearest.lon))
            dist_m = haversine_nm(nav.lat, nav.lon, nearest.lat, nearest.lon) * 1852
            closest_approach = (bearing_rad, dist_m)

        await self.writer.send_vessel_delta(
            snapshot.nav, snapshot.elec, snapshot.sys, snapshot.lights,
            snapshot.wx, snapshot.state, snapshot.utc_now, snapshot.temps,
            next_wp=snapshot.next_wp, route_href=snapshot.route_href,
            point_index=snapshot.point_index, polars=snapshot.polars,
            autopilot=snapshot.autopilot, closest_approach=closest_approach)
        for c in snapshot.ais_contacts:
            await self.writer.enqueue_ais(c.mmsi, c.lat, c.lon, c.cog_deg,
                                          c.sog_kts, c.name, c.ship_type)
        if self._last_point_index is not None and snapshot.point_index != self._last_point_index:
            steps = snapshot.point_index - self._last_point_index
            try:
                await self.writer.advance_active_point(steps if steps > 0 else 1)
            except Exception:  # noqa: BLE001,S110
                pass
        self._last_point_index = snapshot.point_index

    async def close(self) -> None:
        await self.writer.close()
