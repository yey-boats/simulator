# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Gap 2: navigation.closestApproach.* emitted on the SELF vessel delta.

Tests verify:
  (a) Given an own position and 2+ AisContacts, the self delta includes
      navigation.closestApproach.bearingTrue and .distance pointing at the
      NEAREST contact, matching values from great_circle_bearing/haversine_nm.
  (b) With no contacts, neither path appears.
"""
import math

from yey.boats.simulator.engine.route import great_circle_bearing, haversine_nm
from yey.boats.simulator.engine.signalk_writer import _build_vessel_delta
from yey.boats.simulator.engine.snapshot import AisContact

# ---------------------------------------------------------------------------
# Minimal stubs for the parts of _build_vessel_delta we don't care about
# ---------------------------------------------------------------------------
from datetime import datetime, UTC
from unittest.mock import MagicMock

from yey.boats.simulator.engine.navigator import NavState
from yey.boats.simulator.engine.schedule import SimState


def _nav(lat: float = 45.0, lon: float = 13.0):
    return NavState(
        lat=lat, lon=lon, hdg_deg=90, cog_deg=90,
        sog_kts=5, stw_kts=5, twa_deg=40, tws_kts=12,
        twd_deg=130, awa_deg=30, aws_kts=15, heel_deg=8, depth_m=20.0,
    )


def _stub_elec():
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
    return w


def _stub_temps():
    return {
        "engine_k": 350.0, "genset_k": 300.0, "boiler_k": 340.0,
        "saloon_k": 295.0, "fwd_cabin_k": 293.0,
        "port_aft_k": 292.0, "stbd_aft_k": 292.0,
    }


def _paths_from_delta(delta: dict) -> dict:
    values = delta["updates"][0]["values"]
    return {v["path"]: v["value"] for v in values}


# Own vessel position
OWN_LAT = 45.0
OWN_LON = 13.0

# Two AIS contacts; contact A is farther, contact B is nearer
_CONTACT_A = AisContact(mmsi="123456789", lat=46.0, lon=13.0,
                        cog_deg=270.0, sog_kts=8.0, name="Far Ship", ship_type=70)
_CONTACT_B = AisContact(mmsi="987654321", lat=45.05, lon=13.0,
                        cog_deg=180.0, sog_kts=5.0, name="Near Ship", ship_type=36)


def _build(contacts):
    nav = _nav(OWN_LAT, OWN_LON)
    closest = None
    if contacts:
        nearest = min(contacts, key=lambda c: haversine_nm(nav.lat, nav.lon, c.lat, c.lon))
        bearing_rad = math.radians(great_circle_bearing(nav.lat, nav.lon, nearest.lat, nearest.lon))
        dist_m = haversine_nm(nav.lat, nav.lon, nearest.lat, nearest.lon) * 1852
        closest = (bearing_rad, dist_m)
    return _build_vessel_delta(
        nav, _stub_elec(), _stub_sys(), _stub_lights(),
        _stub_wx(), SimState.MOTORED,
        datetime.now(UTC), _stub_temps(),
        closest_approach=closest,
    )


def test_closest_approach_present_with_contacts():
    """Nearest contact bearing/distance appear in self delta."""
    delta = _build([_CONTACT_A, _CONTACT_B])
    p = _paths_from_delta(delta)

    assert "navigation.closestApproach.bearingTrue" in p, (
        "missing navigation.closestApproach.bearingTrue")
    assert "navigation.closestApproach.distance" in p, (
        "missing navigation.closestApproach.distance")

    # Contact B is nearer; verify values match the helper functions
    expected_bearing_deg = great_circle_bearing(OWN_LAT, OWN_LON,
                                                _CONTACT_B.lat, _CONTACT_B.lon)
    expected_dist_nm = haversine_nm(OWN_LAT, OWN_LON,
                                    _CONTACT_B.lat, _CONTACT_B.lon)

    assert abs(p["navigation.closestApproach.bearingTrue"]
               - math.radians(expected_bearing_deg)) < 1e-9
    assert abs(p["navigation.closestApproach.distance"]
               - expected_dist_nm * 1852) < 1e-3


def test_closest_approach_absent_without_contacts():
    """When there are no AIS contacts, neither path should appear."""
    delta = _build([])
    p = _paths_from_delta(delta)

    assert "navigation.closestApproach.bearingTrue" not in p
    assert "navigation.closestApproach.distance" not in p
