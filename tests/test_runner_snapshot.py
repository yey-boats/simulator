from datetime import datetime, timezone

from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.runner import build_snapshot  # type: ignore[import]


class _Elec: soc = 0.8; solar_w = 100.0
class _Sys: fw_tank_0 = 0.4; bw_tank_0 = 0.2
class _Wx: pass


def test_build_snapshot_populates_fields():
    nav = NavState(lat=45.0, lon=13.0, hdg_deg=90, cog_deg=90, sog_kts=5,
                   stw_kts=5, twa_deg=40, tws_kts=12, twd_deg=130,
                   awa_deg=30, aws_kts=15, heel_deg=8, depth_m=20.0)
    snap = build_snapshot(
        nav=nav, elec=_Elec(), sys_=_Sys(), lights=object(), wx=_Wx(),
        state=SimState.SAILING, now=datetime.now(timezone.utc), temps={},
        next_wp=("Pula", 44.87, 13.84), route_href="/r", point_index=2,
        polars=None, autopilot=None, distance_to_next_nm=4.2)
    assert snap.point_index == 2  # noqa: S101
    assert snap.distance_to_next_nm == 4.2  # noqa: S101
    assert snap.next_wp[0] == "Pula"  # noqa: S101
