# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
import math
from datetime import datetime, timezone

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.route import great_circle_bearing, haversine_nm  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import AisContact, TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.sinks.signalk import SignalKSink  # type: ignore[import]


class FakeWriter:
    def __init__(self):
        self.deltas = []
        self.closest_approaches = []

    async def connect(self, u, p): self.connected = (u, p)

    async def send_vessel_delta(self, nav, elec, sys_, lights, wx, state,
                                utc_now, temps, next_wp=None, route_href="",
                                point_index=0, polars=None, autopilot=None,
                                closest_approach=None, current=None, prev_wp=None):
        self.deltas.append((nav, point_index, next_wp))
        self.closest_approaches.append(closest_approach)

    async def enqueue_ais(self, mmsi, lat, lon, cog_deg, sog_kts, name, ship_type): ...
    async def advance_active_point(self, steps=1): ...
    async def close(self): self.closed = True


def _nav(lat=45.0, lon=13.0):
    return NavState(lat=lat, lon=lon, hdg_deg=90, cog_deg=90, sog_kts=5,
                    stw_kts=5, twa_deg=40, tws_kts=12, twd_deg=130,
                    awa_deg=30, aws_kts=15, heel_deg=8, depth_m=20.0)


def _snap(nav=None, contacts=None, point_index=3):
    return TelemetrySnapshot(
        nav=nav or _nav(), elec=object(), sys=object(), lights=object(), wx=object(),
        state=SimState.SAILING, utc_now=datetime.now(timezone.utc), temps={},
        next_wp=("Pula", 44.87, 13.84), route_href="/r", point_index=point_index,
        polars=None, autopilot=None, ais_contacts=contacts or [])


@pytest.mark.asyncio
async def test_signalk_sink_publishes_via_writer():
    fake = FakeWriter()
    sink = SignalKSink(writer=fake)
    await sink.publish(_snap())
    assert sink.name == "signalk"  # noqa: S101
    assert fake.deltas and fake.deltas[0][1] == 3  # noqa: S101
    assert fake.deltas[0][2][0] == "Pula"  # noqa: S101


@pytest.mark.asyncio
async def test_sink_forwards_closest_approach_for_nearest_contact():
    """SignalKSink.publish() computes closest_approach from the NEAREST contact."""
    own_lat, own_lon = 45.0, 13.0
    nav = _nav(lat=own_lat, lon=own_lon)
    # far contact (>1 degree away)
    far = AisContact(mmsi="123456789", lat=46.0, lon=13.0,
                     cog_deg=270.0, sog_kts=8.0, name="Far Ship", ship_type=70)
    # near contact (~0.05 degree away)
    near = AisContact(mmsi="987654321", lat=45.05, lon=13.0,
                      cog_deg=180.0, sog_kts=5.0, name="Near Ship", ship_type=36)

    fake = FakeWriter()
    sink = SignalKSink(writer=fake)
    await sink.publish(_snap(nav=nav, contacts=[far, near]))

    assert len(fake.closest_approaches) == 1  # noqa: S101
    ca = fake.closest_approaches[0]
    assert ca is not None, "closest_approach must be non-None when contacts present"  # noqa: S101

    bearing_rad, dist_m = ca
    expected_bearing_rad = math.radians(
        great_circle_bearing(own_lat, own_lon, near.lat, near.lon))
    expected_dist_m = haversine_nm(own_lat, own_lon, near.lat, near.lon) * 1852

    assert abs(bearing_rad - expected_bearing_rad) < 1e-9, (  # noqa: S101
        f"bearing mismatch: {bearing_rad} != {expected_bearing_rad}")
    assert abs(dist_m - expected_dist_m) < 1e-3, (  # noqa: S101
        f"distance mismatch: {dist_m} != {expected_dist_m}")


@pytest.mark.asyncio
async def test_sink_closest_approach_none_without_contacts():
    """SignalKSink.publish() passes closest_approach=None when no AIS contacts."""
    fake = FakeWriter()
    sink = SignalKSink(writer=fake)
    await sink.publish(_snap(contacts=[]))

    assert len(fake.closest_approaches) == 1  # noqa: S101
    assert fake.closest_approaches[0] is None, (  # noqa: S101
        "closest_approach must be None when no contacts")
