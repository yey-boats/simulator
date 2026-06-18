from datetime import datetime, timezone

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.sinks.signalk import SignalKSink  # type: ignore[import]


class FakeWriter:
    def __init__(self): self.deltas = []
    async def connect(self, u, p): self.connected = (u, p)
    async def send_vessel_delta(self, nav, elec, sys_, lights, wx, state,
                                utc_now, temps, next_wp=None, route_href="",
                                point_index=0, polars=None, autopilot=None,
                                closest_approach=None):
        self.deltas.append((nav, point_index, next_wp))  # noqa: S101
    async def close(self): self.closed = True


@pytest.mark.asyncio
async def test_signalk_sink_publishes_via_writer():
    fake = FakeWriter()
    sink = SignalKSink(writer=fake)
    nav = NavState(lat=45.0, lon=13.0, hdg_deg=90, cog_deg=90, sog_kts=5,
                   stw_kts=5, twa_deg=40, tws_kts=12, twd_deg=130,
                   awa_deg=30, aws_kts=15, heel_deg=8, depth_m=20.0)
    snap = TelemetrySnapshot(
        nav=nav, elec=object(), sys=object(), lights=object(), wx=object(),
        state=SimState.SAILING, utc_now=datetime.now(timezone.utc), temps={},
        next_wp=("Pula", 44.87, 13.84), route_href="/r", point_index=3,
        polars=None, autopilot=None)
    await sink.publish(snap)
    assert sink.name == "signalk"  # noqa: S101
    assert fake.deltas and fake.deltas[0][1] == 3  # noqa: S101
    assert fake.deltas[0][2][0] == "Pula"  # noqa: S101
