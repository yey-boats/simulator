# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Phase-3 diagnostic-signal models + fault injection.

Covers, per the plan:
  - FaultState seeding (env + runtime) and clear-by-default.
  - Each model's nominal range.
  - Each fault makes its signal deviate when active and recover when cleared.
  - A raw_water_blocked integration check: exhaust AND coolant rise at steady RPM.
"""
from __future__ import annotations

import math

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.diagnostics import (  # type: ignore[import]
    Gnss, StarterBattery, oil_pressure_pa, rate_of_turn_rad_s)
from yey.boats.simulator.engine.faults import KNOWN_FAULTS, FaultState  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.temperatures import (  # type: ignore[import]
    COOLANT_OVERHEAT_T, ThermalModel)


# ── FaultState ───────────────────────────────────────────────────────────────

def test_faultstate_clear_by_default():
    fs = FaultState(seed=[])
    for fid in KNOWN_FAULTS:
        assert not fs.is_active(fid)  # noqa: S101
        assert fs.severity(fid) == 0.0  # noqa: S101
    assert fs.active_ids() == []  # noqa: S101


def test_faultstate_seed_from_env(monkeypatch):
    monkeypatch.setenv("SIM_FAULTS", "raw_water_blocked, alternator_belt")
    fs = FaultState()
    assert fs.is_active("raw_water_blocked")  # noqa: S101
    assert fs.is_active("alternator_belt")  # noqa: S101
    assert not fs.is_active("gps_degraded")  # noqa: S101


def test_faultstate_runtime_toggle_and_clear():
    fs = FaultState(seed=[])
    fs.set("low_oil_pressure")
    assert fs.is_active("low_oil_pressure")  # noqa: S101
    assert fs.severity("low_oil_pressure") == pytest.approx(1.0)  # noqa: S101
    fs.set("low_oil_pressure", severity=0.4)
    assert fs.severity("low_oil_pressure") == pytest.approx(0.4)  # noqa: S101
    fs.clear("low_oil_pressure")
    assert not fs.is_active("low_oil_pressure")  # noqa: S101
    assert fs.severity("low_oil_pressure") == 0.0  # noqa: S101


# ── Oil pressure ─────────────────────────────────────────────────────────────

def test_oil_pressure_nominal_range():
    assert oil_pressure_pa(0.0, engine_on=False) == 0.0  # stopped  # noqa: S101
    idle = oil_pressure_pa(0.0, engine_on=True)
    cruise = oil_pressure_pa(1.0, engine_on=True)
    assert 230_000 < idle < 270_000  # ~250 kPa idle  # noqa: S101
    assert 430_000 < cruise < 470_000  # ~450 kPa cruise  # noqa: S101
    assert cruise > idle  # noqa: S101


def test_oil_pressure_low_oil_fault_drops_and_recovers():
    nominal = oil_pressure_pa(0.5, engine_on=True, fault_severity=0.0)
    faulted = oil_pressure_pa(0.5, engine_on=True, fault_severity=1.0)
    assert faulted < nominal * 0.2  # deep drop into alarm territory  # noqa: S101
    recovered = oil_pressure_pa(0.5, engine_on=True, fault_severity=0.0)
    assert recovered == pytest.approx(nominal)  # noqa: S101


# ── Exhaust + coolant (raw_water_blocked) ────────────────────────────────────

def _warm_engine(tm: ThermalModel, seconds: int, cooling_fault: float = 0.0,
                 rpm_frac: float = 0.5) -> None:
    for _ in range(seconds):
        tm.tick(1.0, SimState.MOTORED, rpm_frac=rpm_frac, cooling_fault=cooling_fault)


def test_exhaust_nominal_warmup_and_load():
    tm = ThermalModel(ambient_c=20.0)
    _warm_engine(tm, 600, rpm_frac=0.5)
    ex = tm.exhaust_k
    # Wet exhaust, raw-water cooled: well below dry exhaust-gas temps.
    assert (80 + 273.15) < ex < (250 + 273.15)  # noqa: S101


def test_raw_water_blocked_exhaust_and_coolant_rise_at_steady_rpm():
    """Integration fixture: with the raw-water blocked, BOTH the wet exhaust and
    the engine coolant climb past their nominal setpoints at steady RPM — the
    engine-overheat discriminator the P2 diagnostic looks for."""
    healthy = ThermalModel(ambient_c=20.0)
    faulted = ThermalModel(ambient_c=20.0)
    _warm_engine(healthy, 600, cooling_fault=0.0, rpm_frac=0.5)
    _warm_engine(faulted, 600, cooling_fault=1.0, rpm_frac=0.5)

    assert faulted.exhaust_k > healthy.exhaust_k + 50  # exhaust spikes  # noqa: S101
    assert faulted.engine_k > healthy.engine_k + 5  # coolant climbs past 90 °C  # noqa: S101
    assert faulted.engine_k > (95 + 273.15)  # into boil-warning range  # noqa: S101
    assert faulted.engine_k <= (COOLANT_OVERHEAT_T + 273.16)  # bounded  # noqa: S101


def test_cooling_fault_recovers_when_cleared():
    tm = ThermalModel(ambient_c=20.0)
    _warm_engine(tm, 600, cooling_fault=1.0, rpm_frac=0.5)
    hot = tm.engine_k
    # Clear the fault; coolant relaxes back toward the 90 °C setpoint.
    for _ in range(600):
        tm.tick(1.0, SimState.MOTORED, rpm_frac=0.5, cooling_fault=0.0)
    assert tm.engine_k < hot  # noqa: S101
    assert tm.engine_k == pytest.approx(90 + 273.15, abs=1.0)  # noqa: S101


# ── Starter battery (weak_starter) ───────────────────────────────────────────

def test_starter_nominal_float_and_crank_dip():
    sb = StarterBattery()
    # Engine off: rested float ~12.7 V, no current.
    v, _soc, a = sb.tick(1.0, engine_on=False)
    assert 12.4 < v < 12.9  # noqa: S101
    assert a == pytest.approx(0.0)  # noqa: S101
    # Engine just started -> crank dip + heavy discharge.
    v_crank, _soc, a_crank = sb.tick(1.0, engine_on=True)
    assert v_crank < 11.0  # noqa: S101
    assert a_crank < -100.0  # noqa: S101


def test_weak_starter_deeper_dip_than_healthy():
    healthy = StarterBattery()
    weak = StarterBattery()
    healthy.tick(1.0, engine_on=False)
    weak.tick(1.0, engine_on=False)
    vh, _s, _a = healthy.tick(1.0, engine_on=True, weak_severity=0.0)
    vw, _s2, aw = weak.tick(1.0, engine_on=True, weak_severity=1.0)
    assert vw < vh  # deeper dip  # noqa: S101
    assert aw < -100.0  # noqa: S101


def test_weak_starter_recovers_when_cleared():
    sb = StarterBattery()
    sb.tick(1.0, engine_on=False, weak_severity=1.0)
    # fault cleared mid-run -> after the crank, float voltage is healthy again.
    sb.tick(1.0, engine_on=True, weak_severity=0.0)  # crank
    # run out the recharge phase
    for _ in range(200):
        v, _soc, _a = sb.tick(1.0, engine_on=True, weak_severity=0.0)
    assert v > 13.5  # charging voltage, no weak penalty  # noqa: S101


# ── GNSS (gps_degraded) ──────────────────────────────────────────────────────

def test_gnss_nominal_range():
    g = Gnss(seed=42)
    for _ in range(50):
        s = g.tick(degraded_severity=0.0)
        assert 4 <= s["satellites"] <= 13  # noqa: S101
        assert 0.5 <= s["horizontalDilution"] <= 1.6  # noqa: S101
        assert s["methodQuality"] == "GNSS Fix"  # noqa: S101
        assert s["antennaAltitude"] == pytest.approx(2.0)  # noqa: S101


def test_gps_degraded_drops_sats_raises_hdop_and_recovers():
    g = Gnss(seed=7)
    deg = g.tick(degraded_severity=1.0)
    assert deg["satellites"] <= 4  # noqa: S101
    assert deg["horizontalDilution"] > 5.0  # noqa: S101
    assert deg["methodQuality"] == "no GNSS"  # noqa: S101
    # Position jitter is substantial.
    lat_j, lon_j = deg["position_jitter_deg"]
    assert abs(lat_j) > 0 or abs(lon_j) > 0  # noqa: S101
    # Cleared -> back to a valid fix.
    nom = g.tick(degraded_severity=0.0)
    assert nom["methodQuality"] == "GNSS Fix"  # noqa: S101
    assert nom["satellites"] >= 4  # noqa: S101


# ── Rate of turn ─────────────────────────────────────────────────────────────

def test_rate_of_turn_from_heading_delta():
    # +10° in 1 s -> +10°/s to starboard.
    assert rate_of_turn_rad_s(100.0, 110.0, 1.0) == pytest.approx(math.radians(10.0))  # noqa: S101
    # Wrap across 360: 350 -> 10 is +20° (starboard), not −340°.
    assert rate_of_turn_rad_s(350.0, 10.0, 1.0) == pytest.approx(math.radians(20.0))  # noqa: S101
    # Port turn is negative.
    assert rate_of_turn_rad_s(10.0, 350.0, 1.0) == pytest.approx(math.radians(-20.0))  # noqa: S101
    assert rate_of_turn_rad_s(100.0, 100.0, 1.0) == 0.0  # noqa: S101
