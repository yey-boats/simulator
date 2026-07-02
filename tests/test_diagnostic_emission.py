# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Phase-3 diagnostic signals flow through the writer's published-path set.

Verifies that the new paths are emitted when _build_vessel_delta receives the
kwargs, and are OMITTED by default (None) — exactly like propulsion.main.runTime
— so existing call sites/tests are unaffected.
"""
from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import MagicMock

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.signalk_writer import _build_vessel_delta  # type: ignore[import]

_DIAG_PATHS = (
    "propulsion.main.oilPressure",
    "propulsion.main.exhaustTemperature",
    "electrical.batteries.starter.voltage",
    "electrical.batteries.starter.stateOfCharge",
    "electrical.batteries.starter.current",
    "navigation.gnss.satellites",
    "navigation.gnss.horizontalDilution",
    "navigation.gnss.methodQuality",
    "navigation.gnss.antennaAltitude",
    "navigation.rateOfTurn",
)


def _nav(lat=45.0, lon=13.0):
    return NavState(lat=lat, lon=lon, hdg_deg=90, cog_deg=90, sog_kts=5,
                    stw_kts=5, twa_deg=40, tws_kts=12, twd_deg=130,
                    awa_deg=30, aws_kts=15, heel_deg=8, depth_m=20.0)


def _stub_elec():
    e = MagicMock()
    e.loads = {}
    e.voltage = 12.8
    e.current_a = 5.0
    e.soc = 0.9
    e.solar_w = 100.0
    e.alternator_w = 0.0
    e.genset_w = 0.0
    e.net_w = 0.0
    e.inverter_state = "invert"
    e.genset_state = "stopped"
    e.genset_rpm = 0.0
    return e


def _stub_sys():
    s = MagicMock()
    s.bilge_pump = False
    s.water_pump = False
    for attr in ("fw_tank_0", "fw_tank_1", "fuel_tank_0", "fuel_tank_1",
                 "bw_tank_0", "bw_tank_1", "bw_tank_2"):
        setattr(s, attr, 0.5)
    return s


def _stub_lights():
    l = MagicMock()  # noqa: E741
    for attr in ("port_light", "starboard_light", "stern_light",
                 "masthead_light", "anchor_light", "deck_light"):
        setattr(l, attr, False)
    for attr in ("saloon_dimmer", "forward_cabin_dimmer",
                 "port_aft_cabin_dimmer", "stbd_aft_cabin_dimmer", "instrument_dimmer"):
        setattr(l, attr, 0.0)
    return l


def _stub_wx():
    w = MagicMock()
    w.wave_height_m = 1.0
    w.wave_period_s = 8.0
    w.wave_dir_deg = 270.0
    w.temp_c = 20.0
    w.pressure_pa = 101325.0
    w.humidity = 0.65
    w.gust_ms = 7.0
    return w


def _stub_temps():
    return {"engine_k": 350.0, "genset_k": 300.0, "boiler_k": 340.0,
            "saloon_k": 295.0, "fwd_cabin_k": 293.0,
            "port_aft_k": 292.0, "stbd_aft_k": 292.0, "exhaust_k": 400.0}


def _delta(**kw):
    return _build_vessel_delta(
        _nav(), _stub_elec(), _stub_sys(), _stub_lights(), _stub_wx(),
        SimState.MOTORED, datetime(2025, 6, 18, 12, 0, tzinfo=UTC),
        _stub_temps(), **kw)


def _paths(delta):
    return {v["path"]: v["value"] for v in delta["updates"][0]["values"]}


def test_diagnostic_paths_absent_by_default():
    p = _paths(_delta())
    for path in _DIAG_PATHS:
        assert path not in p, f"{path} should be omitted when not supplied"  # noqa: S101


def test_diagnostic_paths_present_with_values():
    p = _paths(_delta(
        oil_pressure_pa=450_000.0, exhaust_temp_k=453.15,
        starter_voltage=12.7, starter_soc=0.95, starter_current_a=-180.0,
        gnss_satellites=11, gnss_hdop=0.9, gnss_quality="GNSS Fix",
        gnss_antenna_altitude_m=2.0, rate_of_turn_rad_s=0.05))
    for path in _DIAG_PATHS:
        assert path in p, f"missing {path}"  # noqa: S101
    assert p["propulsion.main.oilPressure"] == pytest.approx(450_000.0)  # noqa: S101
    assert p["navigation.gnss.satellites"] == 11  # noqa: S101
    assert p["navigation.gnss.methodQuality"] == "GNSS Fix"  # noqa: S101


def test_gps_jitter_overrides_published_position():
    p = _paths(_delta(gnss_position_jitter_deg=(0.001, -0.002)))
    pos = p["navigation.position"]
    assert pos["latitude"] == pytest.approx(45.0 + 0.001)  # noqa: S101
    assert pos["longitude"] == pytest.approx(13.0 - 0.002)  # noqa: S101
