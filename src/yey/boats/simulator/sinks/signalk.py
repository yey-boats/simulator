# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""SignalK telemetry sink: adapts TelemetrySnapshot to the existing
SignalKWriter. open() connects; publish() forwards the snapshot fields to
send_vessel_delta. close() tears down the connection.

The runner reads `.writer` to launch flush_loop()/metadata_loop() and to feed
AIS — those are SignalK-transport concerns owned by the writer, not the engine.
Position-resume and route-resource registration are performed by the runner via
`.writer`, NOT in this sink's open() — open() only calls connect().
"""
from __future__ import annotations

import contextlib
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
            dist_nm = haversine_nm(nav.lat, nav.lon, nearest.lat, nearest.lon)
            closest_approach = (bearing_rad, dist_nm * 1852)

        # Convert modelled current fields to SI for the wire format:
        # set: degrees → radians (direction water flows toward, true)
        # drift: knots → m/s
        current = (
            math.radians(snapshot.current_set_deg),
            snapshot.current_drift_kts * 0.514444,
        )

        await self.writer.send_vessel_delta(
            snapshot.nav, snapshot.elec, snapshot.sys, snapshot.lights,
            snapshot.wx, snapshot.state, snapshot.utc_now, snapshot.temps,
            next_wp=snapshot.next_wp, route_href=snapshot.route_href,
            point_index=snapshot.point_index, polars=snapshot.polars,
            autopilot=snapshot.autopilot, closest_approach=closest_approach,
            current=current, prev_wp=snapshot.prev_wp,
            engine_run_s=snapshot.engine_run_s,
            oil_pressure_pa=snapshot.oil_pressure_pa,
            exhaust_temp_k=snapshot.exhaust_temp_k,
            starter_voltage=snapshot.starter_voltage,
            starter_soc=snapshot.starter_soc,
            starter_current_a=snapshot.starter_current_a,
            gnss_satellites=snapshot.gnss_satellites,
            gnss_hdop=snapshot.gnss_hdop,
            gnss_quality=snapshot.gnss_quality,
            gnss_antenna_altitude_m=snapshot.gnss_antenna_altitude_m,
            gnss_position_jitter_deg=snapshot.gnss_position_jitter_deg,
            rate_of_turn_rad_s=snapshot.rate_of_turn_rad_s)
        for c in snapshot.ais_contacts:
            await self.writer.enqueue_ais(c.mmsi, c.lat, c.lon, c.cog_deg,
                                          c.sog_kts, c.name, c.ship_type)
        if self._last_point_index is not None and snapshot.point_index != self._last_point_index:
            steps = snapshot.point_index - self._last_point_index
            with contextlib.suppress(Exception):  # noqa: BLE001,S110
                await self.writer.advance_active_point(steps if steps > 0 else 1)
        self._last_point_index = snapshot.point_index

    async def close(self) -> None:
        await self.writer.close()
