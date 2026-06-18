# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Output-only sink: prints one JSON telemetry record per tick to stdout.

Mirrors the legacy simulator_stub.py record shape so existing consumers and
local verification keep working without a SignalK server.
"""
from __future__ import annotations

import json
import sys

from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]


class StdoutJsonSink:
    name = "stdout"

    async def open(self) -> None:
        return None

    async def publish(self, snapshot: TelemetrySnapshot) -> None:
        nav = snapshot.nav
        elec = snapshot.elec
        sys_ = snapshot.sys
        state = snapshot.state
        rec = {
            "t": snapshot.utc_now.isoformat(),
            "state": getattr(state, "value", str(state)),
            "lat": round(nav.lat, 6), "lon": round(nav.lon, 6),
            "sog": round(nav.sog_kts, 2), "cog": round(nav.cog_deg, 1),
            "hdg": round(nav.hdg_deg, 1), "stw": round(nav.stw_kts, 2),
            "tws": round(nav.tws_kts, 1), "twd": round(nav.twd_deg, 1),
            "twa": round(nav.twa_deg, 1),
            "aws": round(nav.aws_kts, 1), "awa": round(nav.awa_deg, 1),
            "heel": round(nav.heel_deg, 1), "depth": round(nav.depth_m, 1),
            "log": round(getattr(nav, "log_nm", 0.0), 3),
            "soc": round(elec.soc, 3),
            "solar_w": round(elec.solar_w, 1),
            "fw0": round(sys_.fw_tank_0, 3),
            "bw0": round(sys_.bw_tank_0, 3),
            "wp_next": snapshot.next_wp[0] if snapshot.next_wp else None,
            "dist_nm": round(snapshot.distance_to_next_nm, 1),
            "ais": len(snapshot.ais_contacts),
        }
        sys.stdout.write(json.dumps(rec) + "\n")
        sys.stdout.flush()

    async def close(self) -> None:
        return None
