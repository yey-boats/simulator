# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
import json
from datetime import datetime, timezone

from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.sinks.stdout_json import StdoutJsonSink  # type: ignore[import]


class _Elec:
    soc = 0.8; solar_w = 120.0  # noqa: E702


class _Sys:
    fw_tank_0 = 0.5; bw_tank_0 = 0.1  # noqa: E702


class _Wx:
    pass


async def test_stdout_sink_emits_json(capsys):
    nav = NavState(lat=45.0, lon=13.0, hdg_deg=90, cog_deg=91, sog_kts=5.2,
                   stw_kts=5.0, twa_deg=40, tws_kts=12, twd_deg=130,
                   awa_deg=30, aws_kts=15, heel_deg=8, depth_m=20.0)
    nav.log_nm = 12.345
    snap = TelemetrySnapshot(
        nav=nav, elec=_Elec(), sys=_Sys(), lights=object(), wx=_Wx(),
        state=SimState.SAILING, utc_now=datetime.now(timezone.utc), temps={},
        next_wp=("Pula", 44.87, 13.84), route_href="", point_index=0,
        distance_to_next_nm=7.3)
    sink = StdoutJsonSink()
    await sink.open()
    await sink.publish(snap)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads(line)
    assert rec["lat"] == 45.0  # noqa: S101
    assert rec["state"] == "sailing"  # noqa: S101
    assert rec["wp_next"] == "Pula"  # noqa: S101
    assert rec["dist_nm"] == 7.3  # noqa: S101
    await sink.close()
