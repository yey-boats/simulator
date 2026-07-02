# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Tests for the firmware-screen values the sim now publishes:

  - environment.depth.belowTransducer (= depth-below-surface minus transducer depth, clamped ≥ 0)
  - environment.depth.belowKeel (= depth-below-surface minus draft, clamped ≥ 0)
  - environment.water.temperature (Kelvin, plausible-range clamped)
  - navigation.courseRhumbline.{nextPoint.distance, nextPoint.bearingTrue,
    bearingTrackTrue, crossTrackError} — legacy v1 legs computed from route state

These are consumed by the firmware (signalk_parser / widget_data_resolver) but
were previously unpopulated: depth/water-temp not modelled, course legs only
published under the v2 Course API (navigation.course.calcValues.*) which the
firmware does not subscribe to.
"""
from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import MagicMock

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.signalk_writer import (  # type: ignore[import]
    _build_vessel_delta)
from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.sinks.signalk import SignalKSink  # type: ignore[import]

# ---------------------------------------------------------------------------
# Shared stubs (mirror tests/test_current_emission.py)
# ---------------------------------------------------------------------------

def _nav(lat: float = 45.0, lon: float = 13.0, depth_m: float = 20.0) -> NavState:
    return NavState(
        lat=lat, lon=lon, hdg_deg=90, cog_deg=90,
        sog_kts=5, stw_kts=5, twa_deg=40, tws_kts=12,
        twd_deg=130, awa_deg=30, aws_kts=15, heel_deg=8, depth_m=depth_m,
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


def _stub_wx(temp_c: float = 20.0) -> MagicMock:
    w = MagicMock()
    w.wave_height_m = 1.0
    w.wave_period_s = 8.0
    w.wave_dir_deg = 270.0
    w.temp_c = temp_c
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


def _delta(*, nav: NavState | None = None, wx_temp_c: float = 20.0,
           next_wp=None, prev_wp=None) -> dict:
    return _build_vessel_delta(
        nav or _nav(), _stub_elec(), _stub_sys(), _stub_lights(),
        _stub_wx(wx_temp_c), SimState.SAILING,
        datetime(2025, 6, 18, 12, 0, 0, tzinfo=UTC),
        _stub_temps(), next_wp=next_wp, prev_wp=prev_wp,
    )


# ---------------------------------------------------------------------------
# Depth below transducer
# ---------------------------------------------------------------------------

def test_depth_emissions_derived_from_depth_below_surface():
    # D below surface = 12 m, draft 2.2, transducer 0.6
    p = _paths(_delta(nav=_nav(depth_m=12.0)))
    assert p["environment.depth.belowKeel"] == pytest.approx(12.0 - 2.2)  # noqa: S101
    assert p["environment.depth.belowTransducer"] == pytest.approx(12.0 - 0.6)  # noqa: S101


def test_depth_emissions_clamped_non_negative():
    # Shallow mooring: D = 1.0 m < draft -> belowKeel clamps to 0.
    p = _paths(_delta(nav=_nav(depth_m=1.0)))
    assert p["environment.depth.belowKeel"] == 0.0  # noqa: S101
    assert p["environment.depth.belowTransducer"] == pytest.approx(max(0.0, 1.0 - 0.6))  # noqa: S101


# ---------------------------------------------------------------------------
# Sea water temperature
# ---------------------------------------------------------------------------

def test_water_temperature_kelvin_in_range():
    p = _paths(_delta(wx_temp_c=20.0))
    assert "environment.water.temperature" in p  # noqa: S101
    # 20 °C air → 18.5 °C water → Kelvin.
    assert p["environment.water.temperature"] == pytest.approx(18.5 + 273.15)  # noqa: S101


@pytest.mark.parametrize("air_c,expect_c", [(-5.0, 10.0), (40.0, 28.0), (15.0, 13.5)])
def test_water_temperature_clamped(air_c, expect_c):
    p = _paths(_delta(wx_temp_c=air_c))
    assert p["environment.water.temperature"] == pytest.approx(expect_c + 273.15)  # noqa: S101


# ---------------------------------------------------------------------------
# Course rhumbline legs
# ---------------------------------------------------------------------------

_RHUMB = (
    "navigation.courseRhumbline.nextPoint.distance",
    "navigation.courseRhumbline.nextPoint.bearingTrue",
    "navigation.courseRhumbline.bearingTrackTrue",
    "navigation.courseRhumbline.crossTrackError",
)


def test_course_legs_absent_without_next_wp():
    p = _paths(_delta(next_wp=None, prev_wp=None))
    for path in _RHUMB:
        assert path not in p, f"{path} should be absent when no waypoint is active"  # noqa: S101


def test_course_legs_present_and_si_units():
    # Leg due north: prev → next at same lon, higher lat. Boat sits on the leg.
    prev = ("A", 45.00, 13.00)
    nxt = ("B", 45.10, 13.00)
    p = _paths(_delta(nav=_nav(lat=45.05, lon=13.00), next_wp=nxt, prev_wp=prev))
    for path in _RHUMB:
        assert path in p, f"missing {path}"  # noqa: S101
    # Distance to B (~0.05° of latitude ≈ 5.56 km) in metres, positive.
    assert p["navigation.courseRhumbline.nextPoint.distance"] > 5000  # noqa: S101
    # Leg bearing is due north (~0 rad); on-track XTE ~0.
    assert p["navigation.courseRhumbline.bearingTrackTrue"] == pytest.approx(0.0, abs=1e-3)  # noqa: S101
    assert p["navigation.courseRhumbline.crossTrackError"] == pytest.approx(0.0, abs=1.0)  # noqa: S101


def test_cross_track_sign_starboard_positive():
    """SignalK convention: + XTE = vessel to starboard (right) of the leg."""
    prev = ("A", 45.00, 13.00)
    nxt = ("B", 45.10, 13.00)  # leg heads due north
    # East of a northbound leg = starboard = positive.
    east = _paths(_delta(nav=_nav(lat=45.05, lon=13.02), next_wp=nxt, prev_wp=prev))
    assert east["navigation.courseRhumbline.crossTrackError"] > 0  # noqa: S101
    # West of a northbound leg = port = negative.
    west = _paths(_delta(nav=_nav(lat=45.05, lon=12.98), next_wp=nxt, prev_wp=prev))
    assert west["navigation.courseRhumbline.crossTrackError"] < 0  # noqa: S101


def test_course_degrades_to_btw_without_prev_wp():
    """No distinct leg origin → CTS == BTW and XTE == 0 (steer direct to WP)."""
    nxt = ("B", 45.10, 13.05)
    p = _paths(_delta(nav=_nav(lat=45.00, lon=13.00), next_wp=nxt, prev_wp=None))
    assert p["navigation.courseRhumbline.bearingTrackTrue"] == pytest.approx(  # noqa: S101
        p["navigation.courseRhumbline.nextPoint.bearingTrue"])
    assert p["navigation.courseRhumbline.crossTrackError"] == 0.0  # noqa: S101


# ---------------------------------------------------------------------------
# Sink forwards prev_wp
# ---------------------------------------------------------------------------

class _FakeWriter:
    def __init__(self):
        self.calls: list = []

    async def connect(self, u, p): ...

    async def send_vessel_delta(self, nav, elec, sys_, lights, wx, state,
                                utc_now, temps, next_wp=None, route_href="",
                                point_index=0, polars=None, autopilot=None,
                                closest_approach=None, current=None, prev_wp=None,
                                engine_run_s=None, **kwargs):
        self.calls.append({"next_wp": next_wp, "prev_wp": prev_wp})

    async def enqueue_ais(self, *a, **kw): ...
    async def advance_active_point(self, steps=1): ...
    async def close(self): ...


@pytest.mark.asyncio
async def test_sink_forwards_prev_wp():
    fake = _FakeWriter()
    sink = SignalKSink(writer=fake)
    snap = TelemetrySnapshot(
        nav=_nav(), elec=object(), sys=object(), lights=object(), wx=object(),
        state=SimState.SAILING, utc_now=datetime.now(UTC), temps={},
        next_wp=("B", 45.1, 13.0), prev_wp=("A", 45.0, 13.0),
        route_href="/r", point_index=1, polars=None, autopilot=None,
        ais_contacts=[],
    )
    await sink.publish(snap)
    assert len(fake.calls) == 1  # noqa: S101
    assert fake.calls[0]["prev_wp"] == ("A", 45.0, 13.0)  # noqa: S101
    assert fake.calls[0]["next_wp"] == ("B", 45.1, 13.0)  # noqa: S101
