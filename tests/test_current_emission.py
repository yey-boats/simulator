# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Tests for environment.current.* emission through _build_vessel_delta and
SignalKSink.publish().

(a) _build_vessel_delta: when current=(set_rad, drift_ms) is passed, the delta
    includes environment.current.setTrue and environment.current.drift with the
    exact values supplied.
(b) _build_vessel_delta: when current=None (default), neither path appears.
(c) SignalKSink.publish(): converts snapshot.current_set_deg / current_drift_kts
    to SI and forwards as current=(set_rad, drift_ms) to send_vessel_delta.
(d) SignalKSink.publish(): when snapshot fields are at default (0.0 / 0.0) but
    we treat them as "no data", verify the conversion formula is correct for a
    known non-zero snapshot value.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.signalk_writer import _build_vessel_delta  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.sinks.signalk import SignalKSink  # type: ignore[import]

# ---------------------------------------------------------------------------
# Shared stubs (mirrors test_closest_approach.py helpers)
# ---------------------------------------------------------------------------

def _nav(lat: float = 45.0, lon: float = 13.0) -> NavState:
    return NavState(
        lat=lat, lon=lon, hdg_deg=90, cog_deg=90,
        sog_kts=5, stw_kts=5, twa_deg=40, tws_kts=12,
        twd_deg=130, awa_deg=30, aws_kts=15, heel_deg=8, depth_m=20.0,
    )


def _stub_elec() -> MagicMock:
    e = MagicMock()
    e.loads = {}
    e.voltage = 12.8
    e.current_a = 5.0
    e.soc = 0.9
    e.solar_w = 100.0
    e.alternator_w = 0.0
    e.genset_w = 0.0
    e.inverter_state = "invert"
    e.genset_state = "stopped"
    e.genset_rpm = 0.0
    return e


def _stub_sys() -> MagicMock:
    s = MagicMock()
    s.bilge_pump = False
    s.water_pump = False
    for attr in ("fw_tank_0", "fw_tank_1", "fuel_tank_0", "fuel_tank_1",
                 "bw_tank_0", "bw_tank_1", "bw_tank_2"):
        setattr(s, attr, 0.5)
    return s


def _stub_lights() -> MagicMock:
    l = MagicMock()  # noqa: E741
    for attr in ("port_light", "starboard_light", "stern_light",
                 "masthead_light", "anchor_light", "deck_light"):
        setattr(l, attr, False)
    for attr in ("saloon_dimmer", "forward_cabin_dimmer",
                 "port_aft_cabin_dimmer", "stbd_aft_cabin_dimmer", "instrument_dimmer"):
        setattr(l, attr, 0.0)
    return l


def _stub_wx() -> MagicMock:
    w = MagicMock()
    w.wave_height_m = 1.0
    w.wave_period_s = 8.0
    w.wave_dir_deg = 270.0
    w.temp_c = 20.0
    w.pressure_pa = 101325.0
    w.humidity = 0.65
    return w


def _stub_temps() -> dict:
    return {
        "engine_k": 350.0, "genset_k": 300.0, "boiler_k": 340.0,
        "saloon_k": 295.0, "fwd_cabin_k": 293.0,
        "port_aft_k": 292.0, "stbd_aft_k": 292.0,
    }


def _paths(delta: dict) -> dict:
    return {v["path"]: v["value"] for v in delta["updates"][0]["values"]}


def _make_delta(current=None) -> dict:
    return _build_vessel_delta(
        _nav(), _stub_elec(), _stub_sys(), _stub_lights(),
        _stub_wx(), SimState.MOTORED,
        datetime(2025, 6, 18, 12, 0, 0, tzinfo=timezone.utc),
        _stub_temps(),
        current=current,
    )


# ---------------------------------------------------------------------------
# _build_vessel_delta tests
# ---------------------------------------------------------------------------

def test_build_vessel_delta_current_present():
    """With current=(set_rad, drift_ms), delta includes both environment.current.* paths."""
    set_rad = math.radians(150.0)
    drift_ms = 0.4 * 0.514444
    delta = _make_delta(current=(set_rad, drift_ms))
    p = _paths(delta)

    assert "environment.current.setTrue" in p, "missing environment.current.setTrue"  # noqa: S101
    assert "environment.current.drift" in p, "missing environment.current.drift"  # noqa: S101
    assert abs(p["environment.current.setTrue"] - set_rad) < 1e-9  # noqa: S101
    assert abs(p["environment.current.drift"] - drift_ms) < 1e-9  # noqa: S101


def test_build_vessel_delta_current_absent_by_default():
    """Without current arg (None default), neither environment.current.* path appears."""
    delta = _make_delta(current=None)
    p = _paths(delta)

    assert "environment.current.setTrue" not in p, (  # noqa: S101
        "environment.current.setTrue should be absent when current=None")
    assert "environment.current.drift" not in p, (  # noqa: S101
        "environment.current.drift should be absent when current=None")


# ---------------------------------------------------------------------------
# SignalKSink.publish() tests via FakeWriter
# ---------------------------------------------------------------------------

class FakeWriter:
    """Minimal writer that captures the current kwarg passed to send_vessel_delta."""

    def __init__(self):
        self.current_calls: list = []

    async def connect(self, u, p): ...

    async def send_vessel_delta(self, nav, elec, sys_, lights, wx, state,
                                utc_now, temps, next_wp=None, route_href="",
                                point_index=0, polars=None, autopilot=None,
                                closest_approach=None, current=None, prev_wp=None,
                                engine_run_s=None, **kwargs):
        self.current_calls.append(current)

    async def enqueue_ais(self, *a, **kw): ...
    async def advance_active_point(self, steps=1): ...
    async def close(self): ...


def _snap(current_set_deg: float = 0.0, current_drift_kts: float = 0.0) -> TelemetrySnapshot:
    return TelemetrySnapshot(
        nav=_nav(), elec=object(), sys=object(), lights=object(), wx=object(),
        state=SimState.SAILING, utc_now=datetime.now(timezone.utc), temps={},
        next_wp=("Pula", 44.87, 13.84), route_href="/r", point_index=0,
        polars=None, autopilot=None, ais_contacts=[],
        current_set_deg=current_set_deg,
        current_drift_kts=current_drift_kts,
    )


@pytest.mark.asyncio
async def test_sink_emits_current_conversion():
    """SignalKSink.publish() converts set_deg→rad and drift_kts→m/s correctly."""
    set_deg = 150.0
    drift_kts = 0.4

    fake = FakeWriter()
    sink = SignalKSink(writer=fake)
    await sink.publish(_snap(current_set_deg=set_deg, current_drift_kts=drift_kts))

    assert len(fake.current_calls) == 1, "send_vessel_delta not called"  # noqa: S101
    result = fake.current_calls[0]
    assert result is not None, "current should be non-None for non-zero values"  # noqa: S101

    set_rad, drift_ms = result
    assert abs(set_rad - math.radians(set_deg)) < 1e-9, (  # noqa: S101
        f"set_rad={set_rad} expected {math.radians(set_deg)}")
    assert abs(drift_ms - drift_kts * 0.514444) < 1e-9, (  # noqa: S101
        f"drift_ms={drift_ms} expected {drift_kts * 0.514444}")


@pytest.mark.asyncio
async def test_sink_emits_current_zero_values():
    """SignalKSink.publish() still sends current tuple even when values are zero."""
    fake = FakeWriter()
    sink = SignalKSink(writer=fake)
    await sink.publish(_snap(current_set_deg=0.0, current_drift_kts=0.0))

    assert len(fake.current_calls) == 1  # noqa: S101
    result = fake.current_calls[0]
    # current is always emitted (never None) — snapshot always has set/drift fields
    assert result is not None  # noqa: S101
    set_rad, drift_ms = result
    assert set_rad == 0.0  # noqa: S101
    assert drift_ms == 0.0  # noqa: S101
