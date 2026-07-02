# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
import json
import math
from datetime import datetime, UTC

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.signalk_writer import _build_ais_delta  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import AisContact, TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.sinks.signalk import SignalKSink  # type: ignore[import]
from yey.boats.simulator.sinks.stdout_json import StdoutJsonSink  # type: ignore[import]


def _nav():
    return NavState(lat=45.0, lon=13.0, hdg_deg=90, cog_deg=90, sog_kts=5, stw_kts=5,
                    twa_deg=40, tws_kts=12, twd_deg=130, awa_deg=30, aws_kts=15,
                    heel_deg=8, depth_m=20.0)


def _snap(point_index=0, contacts=None):
    return TelemetrySnapshot(
        nav=_nav(), elec=object(), sys=object(), lights=object(), wx=object(),
        state=SimState.SAILING, utc_now=datetime.now(UTC), temps={},
        next_wp=("Pula", 44.87, 13.84), route_href="/r", point_index=point_index,
        ais_contacts=contacts or [])


class FakeWriter:
    def __init__(self):
        self.ais = []
        self.advances = 0

    async def connect(self, u, p): ...
    async def send_vessel_delta(self, *a, **k): ...

    async def enqueue_ais(self, mmsi, lat, lon, cog_deg, sog_kts, name, ship_type):
        self.ais.append(mmsi)

    async def advance_active_point(self, steps=1):
        self.advances += steps

    async def close(self): ...


@pytest.mark.asyncio
async def test_signalk_sink_emits_contacts_and_advances_on_index_change():
    w = FakeWriter()
    sink = SignalKSink(writer=w)
    c = [AisContact("111", 45.1, 13.1, 90.0, 10.0, "X", 70)]
    await sink.publish(_snap(point_index=2, contacts=c))
    assert w.ais == ["111"]  # noqa: S101
    assert w.advances == 0  # noqa: S101
    await sink.publish(_snap(point_index=3, contacts=c))
    assert w.advances == 1  # noqa: S101


def test_ais_delta_includes_standard_fields():
    """Gap 3: AIS delta must include standard SK name/design.aisShipType/navigation.headingTrue."""
    delta = _build_ais_delta(
        mmsi="247100111", lat=45.1, lon=13.2,
        cog_deg=135.0, sog_kts=11.0,
        name="MV Adriatic Star", ship_type=70,
    )
    values = delta["updates"][0]["values"]
    by_path = {v["path"]: v["value"] for v in values}

    # Legacy kdcube.* fields must NOT be emitted — the sim injects only
    # proper standard SignalK fields now.
    assert "kdcube.ais.name" not in by_path
    assert "kdcube.ais.shipType" not in by_path
    assert not any(p.startswith("kdcube.") for p in by_path), "no kdcube.* keys allowed"

    # Standard fields
    assert by_path["name"] == "MV Adriatic Star", "standard 'name' field missing or wrong"
    assert by_path["design.aisShipType"] == {"id": 70}, "design.aisShipType missing or wrong"

    # navigation.headingTrue from COG (no transmitted heading — conventional fallback)
    expected_hdg_rad = math.radians(135.0)
    assert abs(by_path["navigation.headingTrue"] - expected_hdg_rad) < 1e-9, (
        "navigation.headingTrue missing or wrong")


@pytest.mark.asyncio
async def test_stdout_sink_includes_ais_count(capsys):
    sink = StdoutJsonSink()
    c = [AisContact("111", 45.1, 13.1, 90.0, 10.0, "X", 70)]
    snap = _snap(contacts=c)
    snap.elec = type("E", (), {"soc": 0.8, "solar_w": 1.0})()
    snap.sys = type("S", (), {"fw_tank_0": 0.4, "bw_tank_0": 0.2})()
    snap.nav.log_nm = 1.0
    await sink.publish(snap)
    rec = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rec["ais"] == 1  # noqa: S101
