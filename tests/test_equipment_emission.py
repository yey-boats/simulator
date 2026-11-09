# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Demo-boat equipment: magnetic compass, AIS transponder, VHF/DSC, radar,
fridge/freezer monitor and shore-power inlet.

Each device must (a) carry Rusty Boats metadata (manufacturer/model/description)
and (b) publish at least one live value path, otherwise the navigator's
list_instruments (signalk_meta.instruments(): groups /meta `source` by
manufacturer+model over the LIVE leaf paths) never shows it.
"""
from __future__ import annotations

import math
from datetime import datetime, UTC
from unittest.mock import MagicMock

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.autopilot import Autopilot  # type: ignore[import]
from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.signalk_writer import (  # type: ignore[import]
    SELF_MMSI, _build_vessel_delta, _magnetic_variation_deg, _metadata_items,
)
from yey.boats.simulator.engine.snapshot import AisContact, TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.sinks.signalk import SignalKSink  # type: ignore[import]

NEW_DEVICES = (
    "RB-NORTH-ISH-9",       # magnetic compass
    "RB-SHOUTY-BOX-B",      # AIS transponder
    "RB-CHATTY-CATHY-25",   # VHF / DSC
    "RB-BLIP-O-MATIC-4G",   # radar
    "RB-CHILLY-WILLY",      # fridge / freezer
    "RB-UMBILICAL-16",      # shore power
)
NM = 1852.0


def _nav(lat=44.7, lon=13.1, hdg=90.0, sog=6.0):
    return NavState(lat=lat, lon=lon, hdg_deg=hdg, cog_deg=hdg + 3, sog_kts=sog,
                    stw_kts=sog, twa_deg=50, tws_kts=12, twd_deg=hdg + 50,
                    awa_deg=35, aws_kts=15, heel_deg=8, depth_m=30.0)


def _elec(loads=None):
    e = MagicMock()
    e.loads = loads if loads is not None else {"fridge": 60.0, "vhf": 5.0}
    e.voltage, e.current_a, e.soc = 13.6, 5.0, 0.9
    e.solar_w, e.alternator_w, e.genset_w, e.net_w = 100.0, 0.0, 0.0, 0.0
    e.inverter_state, e.genset_state, e.genset_rpm = "standby", "off", 0.0
    return e


def _sys():
    s = MagicMock()
    s.bilge_pump = s.water_pump = False
    for a in ("fw_tank_0", "fw_tank_1", "fuel_tank_0", "fuel_tank_1",
              "bw_tank_0", "bw_tank_1", "bw_tank_2"):
        setattr(s, a, 0.5)
    return s


def _lights():
    li = MagicMock()
    for a in ("port_light", "starboard_light", "stern_light",
              "masthead_light", "anchor_light", "deck_light"):
        setattr(li, a, False)
    for a in ("saloon_dimmer", "forward_cabin_dimmer", "port_aft_cabin_dimmer",
              "stbd_aft_cabin_dimmer", "instrument_dimmer"):
        setattr(li, a, 0.0)
    return li


def _wx():
    w = MagicMock()
    w.wave_height_m, w.wave_period_s, w.wave_dir_deg = 1.0, 6.0, 120.0
    w.temp_c, w.pressure_pa, w.humidity, w.gust_ms = 20.0, 101500.0, 0.6, 9.0
    return w


_TEMPS = {"engine_k": 350.0, "genset_k": 300.0, "boiler_k": 340.0, "saloon_k": 295.0,
          "fwd_cabin_k": 293.0, "port_aft_k": 292.0, "stbd_aft_k": 292.0}
_NOW = datetime(2026, 7, 1, 10, 0, 30, tzinfo=UTC)


def _paths(state=SimState.SAILING, nav=None, elec=None, **kw):
    d = _build_vessel_delta(nav or _nav(), elec or _elec(), _sys(), _lights(), _wx(),
                            state, _NOW, _TEMPS, **kw)
    return {v["path"]: v["value"] for v in d["updates"][0]["values"]}


def _instruments(published: dict) -> dict:
    """Mirror of navigator signalk_meta.instruments(): live paths with meta,
    grouped by (manufacturer, model)."""
    out: dict = {}
    for path, meta in _metadata_items(["fridge", "vhf"]):
        if path not in published:
            continue
        src = meta["source"]
        slot = out.setdefault((src["manufacturer"], src["model"]),
                              {"measures": [], "paths": []})
        slot["paths"].append(path)
        slot["measures"].append(meta["description"])
    return out


# ── inventory / metadata ────────────────────────────────────────────────────

@pytest.mark.parametrize("model", NEW_DEVICES)
def test_new_device_has_metadata_and_live_paths(model):
    items = [(p, m) for p, m in _metadata_items() if m["source"]["model"] == model]
    assert items, f"{model} missing from _METADATA"  # noqa: S101
    published = _paths()
    for path, meta in items:
        assert meta["source"]["manufacturer"] == "Rusty Boats"  # noqa: S101
        assert meta.get("description")  # noqa: S101
        assert path in published, f"{model}: {path} has metadata but is never published"  # noqa: S101


@pytest.mark.parametrize("state", list(SimState))
def test_new_devices_listed_as_instruments_in_every_state(state):
    inv = _instruments(_paths(state=state))
    for model in NEW_DEVICES:
        assert ("Rusty Boats", model) in inv, f"{model} not listed in {state}"  # noqa: S101
        assert inv[("Rusty Boats", model)]["paths"]  # noqa: S101


def test_published_leaf_count_stays_under_navigator_ceiling():
    # signalk_meta._leaf_paths walks at most SK_METADATA_MAX_PATHS (default 300)
    # leaves; leave plenty of headroom for SignalK's own course/notification paths.
    loads = dict.fromkeys(("navigation", "fridge", "cabinLights", "navLights",
                           "anchorLight", "steeringLight", "cooker", "boiler",
                           "kettle", "coffeemaker", "vhf"), 1.0)
    p = _paths(elec=_elec(loads), ais_target_ranges_m=[1000.0])
    assert len(p) < 220  # noqa: S101


# ── compass ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("hdg", [0.0, 45.0, 90.0, 181.0, 270.0, 359.5])
def test_compass_is_consistent_with_true_heading(hdg):
    p = _paths(nav=_nav(hdg=hdg))
    true = p["navigation.headingTrue"]
    mag = p["navigation.headingMagnetic"]
    var = p["navigation.magneticVariation"]
    dev = p["navigation.magneticDeviation"]
    comp = p["navigation.headingCompass"]

    def wrap(a):
        return (a + math.pi) % (2 * math.pi) - math.pi

    assert abs(wrap(mag + var - true)) < 1e-9  # noqa: S101  true = magnetic + variation
    assert abs(wrap(comp + dev - mag)) < 1e-9  # noqa: S101  magnetic = compass + deviation
    assert abs(math.degrees(dev)) <= 2.5  # noqa: S101
    assert 0.0 <= mag < 2 * math.pi and 0.0 <= comp < 2 * math.pi  # noqa: S101


def test_variation_plausible_across_adriatic():
    for lat, lon in ((45.4, 12.3), (44.7, 13.1), (43.5, 16.4), (39.6, 19.9)):
        assert 3.0 <= _magnetic_variation_deg(lat, lon) <= 6.5  # noqa: S101


def test_autopilot_magnetic_target_uses_variation():
    ap = Autopilot()
    ap.apply("set_heading", 120.0, current_heading_deg=120.0, twd_deg=200)
    p = _paths(nav=_nav(hdg=120.0), autopilot=ap)
    var = p["navigation.magneticVariation"]
    assert p["steering.autopilot.target.headingTrue"] == pytest.approx(math.radians(120.0))  # noqa: S101
    assert p["steering.autopilot.target.headingMagnetic"] == pytest.approx(  # noqa: S101
        math.radians(120.0) - var)


# ── AIS / VHF / radar ───────────────────────────────────────────────────────

@pytest.mark.parametrize("state,sog,status,interval", [
    (SimState.SAILING, 6.0, "under way sailing", 30.0),
    (SimState.MOTORED, 7.0, "under way using engine", 30.0),
    (SimState.MOTORED, 15.0, "under way using engine", 15.0),
    (SimState.MOORED, 0.0, "at anchor", 180.0),
    (SimState.BORA_HOLD, 0.0, "at anchor", 180.0),
])
def test_ais_own_ship_status(state, sog, status, interval):
    p = _paths(state=state, nav=_nav(sog=sog))
    assert p["sensors.ais.class"] == "B"  # noqa: S101
    assert p["sensors.ais.transmitting"] is True  # noqa: S101
    assert p["sensors.ais.navigationalStatus"] == status  # noqa: S101
    assert p["sensors.ais.reportingInterval"] == interval  # noqa: S101


def test_ais_and_radar_target_counts():
    ranges = [0.4 * NM, 2.0 * NM, 9.0 * NM, 40.0 * NM]
    p = _paths(ais_target_ranges_m=ranges)
    assert p["sensors.ais.targetsTracked"] == 3  # noqa: S101  (40 nM is out of reception)
    assert p["sensors.radar.state"] == "transmit"  # noqa: S101
    assert p["sensors.radar.range"] == pytest.approx(0.75 * NM)  # noqa: S101
    assert p["sensors.radar.targetsTracked"] == 1  # noqa: S101


def test_radar_default_range_and_standby_at_anchor():
    assert _paths()["sensors.radar.range"] == pytest.approx(3.0 * NM)  # noqa: S101
    p = _paths(state=SimState.MOORED, nav=_nav(sog=0.0), ais_target_ranges_m=[500.0])
    assert p["sensors.radar.state"] == "standby"  # noqa: S101
    assert p["sensors.radar.targetsTracked"] == 0  # noqa: S101


def test_vhf_dsc_values():
    p = _paths()
    assert p["communication.vhf.channel"] == 16  # noqa: S101
    assert p["communication.vhf.transmitPower"] == "high"  # noqa: S101
    assert p["communication.vhf.transmitting"] is False  # noqa: S101
    assert p["communication.dsc.mmsi"] == SELF_MMSI  # noqa: S101
    assert p["communication.dsc.positionAvailable"] is True  # noqa: S101
    tx = _paths(elec=_elec({"vhf": 25.0}), gnss_quality="no GNSS")
    assert tx["communication.vhf.transmitting"] is True  # noqa: S101
    assert tx["communication.dsc.positionAvailable"] is False  # noqa: S101
    assert _paths(state=SimState.MOORED)["communication.vhf.transmitPower"] == "low"  # noqa: S101


# ── fridge / shore power ────────────────────────────────────────────────────

@pytest.mark.parametrize("fridge_w", [0.0, 60.0])
def test_fridge_and_freezer_temperatures_plausible(fridge_w):
    p = _paths(elec=_elec({"fridge": fridge_w}))
    assert 2.0 <= p["environment.inside.refrigerator.temperature"] - 273.15 <= 7.0  # noqa: S101
    assert -21.0 <= p["environment.inside.freezer.temperature"] - 273.15 <= -16.0  # noqa: S101


def test_shore_power_unplugged_at_sea_and_at_anchor():
    for state in SimState:
        p = _paths(state=state)
        assert p["electrical.shorePower.connected"] is False  # noqa: S101
        assert p["electrical.shorePower.voltage"] == 0.0  # noqa: S101


# ── sink wiring ─────────────────────────────────────────────────────────────

class _Writer:
    def __init__(self):
        self.kwargs: dict = {}

    async def connect(self, u, p): ...
    async def send_vessel_delta(self, *a, **kw): self.kwargs = kw
    async def enqueue_ais(self, *a, **kw): ...
    async def advance_active_point(self, steps=1): ...
    async def close(self): ...


async def test_sink_forwards_ais_target_ranges():
    w = _Writer()
    sink = SignalKSink(writer=w)
    contacts = [AisContact("111111111", 44.7 + 1 / 60, 13.1, 0.0, 5.0, "A", 36)]
    snap = TelemetrySnapshot(nav=_nav(), elec=_elec(), sys=_sys(), lights=_lights(),
                             wx=_wx(), state=SimState.SAILING, utc_now=_NOW,
                             temps=_TEMPS, next_wp=None, route_href="", point_index=0,
                             ais_contacts=contacts)
    await sink.publish(snap)
    (rng,) = w.kwargs["ais_target_ranges_m"]
    assert rng == pytest.approx(NM, rel=0.01)  # noqa: S101  1' of latitude = 1 nM
