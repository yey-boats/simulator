from datetime import datetime, timezone

from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]


def test_snapshot_holds_tick_state():
    nav = NavState(lat=45.0, lon=13.0, hdg_deg=90, cog_deg=90, sog_kts=5,
                   stw_kts=5, twa_deg=40, tws_kts=12, twd_deg=130,
                   awa_deg=30, aws_kts=15, heel_deg=8, depth_m=20.0)
    snap = TelemetrySnapshot(
        nav=nav, elec=object(), sys=object(), lights=object(),
        wx=object(), state=object(), utc_now=datetime.now(timezone.utc),
        temps={}, next_wp=("Pula", 44.87, 13.84),
        route_href="/resources/routes/x", point_index=2,
        polars=None, autopilot=None,
    )
    assert snap.nav.lat == 45.0  # noqa: S101
    assert snap.next_wp[0] == "Pula"  # noqa: S101
    assert snap.point_index == 2  # noqa: S101
