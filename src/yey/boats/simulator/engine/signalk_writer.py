# signalk/sim/modules/signalk_writer.py
from __future__ import annotations
import asyncio
import json
import math
import urllib.request
from datetime import datetime, timezone
from typing import Any
import websockets  # type: ignore[import]
from yey.boats.simulator.engine.navigator import NavState, engine_rpm, engine_fuel_L_h  # type: ignore[import]
from yey.boats.simulator.engine.electrical import ElecState  # type: ignore[import]
from yey.boats.simulator.engine.systems import SystemsState  # type: ignore[import]
from yey.boats.simulator.engine.lights import LightsState  # type: ignore[import]
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]
from yey.boats.simulator.engine.weather import WeatherPoint  # type: ignore[import]

SELF_MMSI    = "235177007"
MS_TO_KTS    = 1.94384
BATTERY_WH_J = 14400 * 3600   # 1200 Ah × 12 V, in joules

# ──────────────────────────────────────────────────────────────────────────────
# SignalK metadata — sent once at startup via PUT to /api/vessels/self/{path}/meta
# Manufacturer "Rusty Boats"; model names are affectionate fictions.
# ──────────────────────────────────────────────────────────────────────────────
_RB = "Rusty Boats"

_METADATA: dict[str, dict] = {
    # ── Navigation ── RB-SKYHOOK-3000: 10 Hz GPS chartplotter ────────────
    "navigation.position": {
        "description": "GPS lat/lon fix", "units": "deg", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-SKYHOOK-3000"},
    },
    "navigation.speedOverGround": {
        "description": "GPS speed over ground", "units": "m/s", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-SKYHOOK-3000"},
    },
    "navigation.courseOverGroundTrue": {
        "description": "GPS course over ground (true)", "units": "rad", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-SKYHOOK-3000"},
    },
    "navigation.headingTrue": {
        "description": "Fluxgate compass heading, true north", "units": "rad", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-POINTY-END-200"},
    },
    "navigation.speedThroughWater": {
        "description": "Paddlewheel speed through water", "units": "m/s", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-PADDLEWHEEL-PRO"},
    },
    "navigation.attitude.roll": {
        "description": "IMU heel angle, +stbd down", "units": "rad", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-HEELY-FEELY"},
    },
    "navigation.log": {
        "description": "Cumulative trip odometer", "units": "m", "timeout": 10,
        "source": {"manufacturer": _RB, "model": "RB-PADDLEWHEEL-PRO"},
    },
    "navigation.state": {
        "description": "Voyage state: motored/sailing/moored/bora_hold", "timeout": 10,
        "source": {"manufacturer": _RB, "model": "RB-SKYHOOK-3000"},
    },
    # ── Wind ── RB-WINDY-MC-WINDFACE: triaxial masthead unit ─────────────
    "environment.wind.angleApparent": {
        "description": "Apparent wind angle, +stbd", "units": "rad", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-WINDY-MC-WINDFACE"},
    },
    "environment.wind.speedApparent": {
        "description": "Apparent wind speed", "units": "m/s", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-WINDY-MC-WINDFACE"},
    },
    "environment.wind.angleTrueWater": {
        "description": "True wind angle over water, +stbd", "units": "rad", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-WINDY-MC-WINDFACE"},
    },
    "environment.wind.speedTrue": {
        "description": "True wind speed over water", "units": "m/s", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-WINDY-MC-WINDFACE"},
    },
    # ── Performance ── RB-POLAR-BEAR: polar-table performance computer ───
    "performance.velocityMadeGood": {
        "description": "VMG toward/away from true wind (polar-derived)", "units": "m/s", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-POLAR-BEAR"},
    },
    "performance.polarSpeed": {
        "description": "Expected boat speed from polar at current TWA/TWS", "units": "m/s", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-POLAR-BEAR"},
    },
    "performance.polarSpeedRatio": {
        "description": "Actual STW / polar speed (1.0 = on the polar)", "units": "ratio", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-POLAR-BEAR"},
    },
    "performance.targetAngle": {
        "description": "VMG-optimal TWA for current TWS, current tack side", "units": "rad", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-POLAR-BEAR"},
    },
    "performance.beatAngle": {
        "description": "Optimal upwind TWA for current TWS", "units": "rad", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-POLAR-BEAR"},
    },
    "performance.gybeAngle": {
        "description": "Optimal downwind TWA for current TWS", "units": "rad", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-POLAR-BEAR"},
    },
    # ── Depth ── RB-DEPTHY-DEEP: 200 kHz single-beam depth sounder ───────
    "environment.depth.belowKeel": {
        "description": "Water depth below keel", "units": "m", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-DEPTHY-DEEP"},
    },
    # ── Meteo/swell ── RB-CLOUD-WHISPERER: Open-Meteo forecast, 1 h cache
    "environment.water.swell.height": {
        "description": "Significant wave height (Open-Meteo forecast)", "units": "m", "timeout": 3600,
        "source": {"manufacturer": _RB, "model": "RB-CLOUD-WHISPERER"},
    },
    "environment.water.swell.period": {
        "description": "Dominant wave period (forecast)", "units": "s", "timeout": 3600,
        "source": {"manufacturer": _RB, "model": "RB-CLOUD-WHISPERER"},
    },
    "environment.water.swell.direction": {
        "description": "Swell direction, met convention (forecast)", "units": "rad", "timeout": 3600,
        "source": {"manufacturer": _RB, "model": "RB-CLOUD-WHISPERER"},
    },
    "environment.outside.temperature": {
        "description": "Air temp at 2 m (Open-Meteo forecast)", "units": "K", "timeout": 3600,
        "source": {"manufacturer": _RB, "model": "RB-CLOUD-WHISPERER"},
    },
    "environment.outside.pressure": {
        "description": "Sea-level air pressure (forecast)", "units": "Pa", "timeout": 3600,
        "source": {"manufacturer": _RB, "model": "RB-CLOUD-WHISPERER"},
    },
    "environment.outside.humidity": {
        "description": "Relative humidity 0–1 (forecast)", "units": "ratio", "timeout": 3600,
        "source": {"manufacturer": _RB, "model": "RB-CLOUD-WHISPERER"},
    },
    # ── Temperatures ── RB-THERMO-INATOR: 1-Wire sensor bus ──────────────
    "propulsion.main.coolantTemperature": {
        "description": "Volvo D4-55 coolant temp", "units": "K", "timeout": 10,
        "source": {"manufacturer": _RB, "model": "RB-THERMO-INATOR"},
    },
    "propulsion.genset.coolantTemperature": {
        "description": "Genset coolant temp", "units": "K", "timeout": 10,
        "source": {"manufacturer": _RB, "model": "RB-THERMO-INATOR"},
    },
    "environment.inside.waterHeater.temperature": {
        "description": "Calorifier water temp", "units": "K", "timeout": 30,
        "source": {"manufacturer": _RB, "model": "RB-THERMO-INATOR"},
    },
    "environment.inside.saloon.temperature": {
        "description": "Saloon air temp", "units": "K", "timeout": 30,
        "source": {"manufacturer": _RB, "model": "RB-THERMO-INATOR"},
    },
    "environment.inside.cabin.forwardDouble.temperature": {
        "description": "Forward double cabin air temp", "units": "K", "timeout": 30,
        "source": {"manufacturer": _RB, "model": "RB-THERMO-INATOR"},
    },
    "environment.inside.cabin.portAft.temperature": {
        "description": "Port aft cabin air temp", "units": "K", "timeout": 30,
        "source": {"manufacturer": _RB, "model": "RB-THERMO-INATOR"},
    },
    "environment.inside.cabin.starboardAft.temperature": {
        "description": "Stbd aft cabin air temp", "units": "K", "timeout": 30,
        "source": {"manufacturer": _RB, "model": "RB-THERMO-INATOR"},
    },
    # ── Battery ── RB-JUICE-GAUGE-LFP: 1200 Ah LiFePO4 shunt monitor ─────
    "electrical.batteries.house.voltage": {
        "description": "House bank voltage (1200 Ah LiFePO4)", "units": "V", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-JUICE-GAUGE-LFP"},
    },
    "electrical.batteries.house.current": {
        "description": "House bank current, +charging −load", "units": "A", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-JUICE-GAUGE-LFP"},
    },
    "electrical.batteries.house.stateOfCharge": {
        "description": "House bank SOC 0–1", "units": "ratio", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-JUICE-GAUGE-LFP"},
    },
    "electrical.batteries.house.temperature": {
        "description": "Battery bank temperature", "units": "K", "timeout": 30,
        "source": {"manufacturer": _RB, "model": "RB-JUICE-GAUGE-LFP"},
    },
    "electrical.batteries.house.capacity.nominal": {
        "description": "Nominal capacity (14 400 Wh)", "units": "J", "timeout": 86400,
        "source": {"manufacturer": _RB, "model": "RB-JUICE-GAUGE-LFP"},
    },
    "electrical.batteries.house.capacity.remaining": {
        "description": "Estimated remaining energy", "units": "J", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-JUICE-GAUGE-LFP"},
    },
    # ── Solar ── RB-SUNSHINE-HARVESTER: 40 A MPPT controller ─────────────
    "electrical.solar.1.power": {
        "description": "Solar array output power", "units": "W", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SUNSHINE-HARVESTER"},
    },
    "electrical.solar.1.current": {
        "description": "Solar MPPT output current", "units": "A", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SUNSHINE-HARVESTER"},
    },
    "electrical.solar.1.voltage": {
        "description": "Solar MPPT output voltage", "units": "V", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SUNSHINE-HARVESTER"},
    },
    # ── Alternator ── RB-ALTERNATOR-PRO: 120 A engine alternator shunt ───
    "electrical.alternators.1.power": {
        "description": "Engine alternator charging power", "units": "W", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-ALTERNATOR-PRO"},
    },
    # ── Genset ── RB-NOISY-BOX-5KVA: diesel genset charger ───────────────
    "electrical.chargers.genset.power": {
        "description": "Genset charging power", "units": "W", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-NOISY-BOX-5KVA"},
    },
    # ── Inverter ── RB-WALL-WART-3000: DC-AC inverter/charger ────────────
    "electrical.inverter.1.state": {
        "description": "Inverter state: invert/charge/off/passthrough", "timeout": 10,
        "source": {"manufacturer": _RB, "model": "RB-WALL-WART-3000"},
    },
    "electrical.inverter.1.dc.power": {
        "description": "Total DC bus load power", "units": "W", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-WALL-WART-3000"},
    },
    "electrical.inverter.1.ac.power": {
        "description": "Total AC appliance load power", "units": "W", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-WALL-WART-3000"},
    },
    # ── Nav lights ── RB-SWITCH-A-ROO: NMEA-2000 switch panel ────────────
    "electrical.switches.navLights.state": {
        "description": "COLREGS nav lights master (true = any nav light on)", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SWITCH-A-ROO"},
    },
    "electrical.switches.portLight.state": {
        "description": "Port red nav light (COLREGS Rule 21, 112.5° arc)", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SWITCH-A-ROO"},
    },
    "electrical.switches.starboardLight.state": {
        "description": "Stbd green nav light (COLREGS Rule 21, 112.5° arc)", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SWITCH-A-ROO"},
    },
    "electrical.switches.sternLight.state": {
        "description": "Stern white light (COLREGS Rule 21, 135° arc)", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SWITCH-A-ROO"},
    },
    "electrical.switches.mastheadLight.state": {
        "description": "Masthead steaming light, motor only (COLREGS Rule 23, 225° arc)", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SWITCH-A-ROO"},
    },
    "electrical.switches.steeringLight.state": {
        "description": "Alias for mastheadLight (steaming light)", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SWITCH-A-ROO"},
    },
    "electrical.switches.anchorLight.state": {
        "description": "All-round white anchor light (COLREGS Rule 30)", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SWITCH-A-ROO"},
    },
    "electrical.switches.deckLight.state": {
        "description": "Deck floodlight, moored/night only; random exponential timer", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SWITCH-A-ROO"},
    },
    # ── Cabin dimmers ── RB-DIMMER-DELUXE: 4-zone PWM LED dimmer ─────────
    "electrical.switches.saloonLight.state": {
        "description": "Saloon overhead LED on/off", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-DIMMER-DELUXE"},
    },
    "electrical.switches.saloonLight.dimmer": {
        "description": "Saloon LED brightness 0–1 (0 = off)", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-DIMMER-DELUXE"},
    },
    "electrical.switches.forwardCabinLight.state": {
        "description": "Forward double cabin LED on/off", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-DIMMER-DELUXE"},
    },
    "electrical.switches.forwardCabinLight.dimmer": {
        "description": "Forward cabin LED brightness 0–1", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-DIMMER-DELUXE"},
    },
    "electrical.switches.portAftCabinLight.state": {
        "description": "Port aft cabin LED on/off", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-DIMMER-DELUXE"},
    },
    "electrical.switches.portAftCabinLight.dimmer": {
        "description": "Port aft cabin LED brightness 0–1", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-DIMMER-DELUXE"},
    },
    "electrical.switches.stbdAftCabinLight.state": {
        "description": "Stbd aft cabin LED on/off", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-DIMMER-DELUXE"},
    },
    "electrical.switches.stbdAftCabinLight.dimmer": {
        "description": "Stbd aft cabin LED brightness 0–1", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-DIMMER-DELUXE"},
    },
    "electrical.switches.instrumentLight.dimmer": {
        "description": "Chart table backlight brightness 0–1", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-DIMMER-DELUXE"},
    },
    # ── Pumps ── RB-SOGGY-SENSOR: bilge float + water pressure switch ─────
    "electrical.switches.bilgePump.state": {
        "description": "Bilge pump; auto-on when float switch triggers", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SOGGY-SENSOR"},
    },
    "electrical.switches.waterPump.state": {
        "description": "Pressurised fresh water pump; on when tap demand detected", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-SOGGY-SENSOR"},
    },
    # ── Propulsion ── RB-VROOM-METER: Volvo D4-55 CAN-bus gauge ──────────
    "propulsion.main.state": {
        "description": "Main engine state: started / stopped", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-VROOM-METER"},
    },
    "propulsion.main.revolutions": {
        "description": "Engine shaft speed in Hz (RPM÷60). Cruise 2200 RPM ≈ 36.7 Hz, max 3000 RPM = 50 Hz",
        "units": "Hz", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-VROOM-METER"},
    },
    "propulsion.genset.state": {
        "description": "Genset state: starting / running / stopped", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-NOISY-BOX-5KVA"},
    },
    "propulsion.genset.revolutions": {
        "description": "Genset shaft speed in Hz (50 Hz at 3000 RPM)", "units": "Hz", "timeout": 3,
        "source": {"manufacturer": _RB, "model": "RB-NOISY-BOX-5KVA"},
    },
    # ── Tanks ── RB-SLOSH-O-METER: capacitive fill sensors ───────────────
    "tanks.freshWater.0.currentLevel": {
        "description": "Forward fresh water tank, fill ratio 0–1", "units": "ratio", "timeout": 60,
        "source": {"manufacturer": _RB, "model": "RB-SLOSH-O-METER"},
    },
    "tanks.freshWater.1.currentLevel": {
        "description": "Aft fresh water tank, fill ratio 0–1", "units": "ratio", "timeout": 60,
        "source": {"manufacturer": _RB, "model": "RB-SLOSH-O-METER"},
    },
    "tanks.fuel.0.currentLevel": {
        "description": "Stbd diesel tank, fill ratio 0–1", "units": "ratio", "timeout": 60,
        "source": {"manufacturer": _RB, "model": "RB-SLOSH-O-METER"},
    },
    "tanks.fuel.1.currentLevel": {
        "description": "Port diesel tank, fill ratio 0–1", "units": "ratio", "timeout": 60,
        "source": {"manufacturer": _RB, "model": "RB-SLOSH-O-METER"},
    },
    "tanks.blackWater.0.currentLevel": {
        "description": "Forward holding tank, fill ratio 0–1", "units": "ratio", "timeout": 60,
        "source": {"manufacturer": _RB, "model": "RB-SLOSH-O-METER"},
    },
    "tanks.blackWater.1.currentLevel": {
        "description": "Mid holding tank, fill ratio 0–1", "units": "ratio", "timeout": 60,
        "source": {"manufacturer": _RB, "model": "RB-SLOSH-O-METER"},
    },
    "tanks.blackWater.2.currentLevel": {
        "description": "Aft holding tank, fill ratio 0–1", "units": "ratio", "timeout": 60,
        "source": {"manufacturer": _RB, "model": "RB-SLOSH-O-METER"},
    },
    # ── Fuel flow ── RB-FUEL-FLOW-PRO: turbine in-line flow meters ────────
    "propulsion.fuel.0.consumption": {
        "description": "Main engine fuel flow (m³/s). At cruise: ~1.39e-6 m³/s (5 L/h)",
        "units": "m3/s", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-FUEL-FLOW-PRO"},
    },
    "propulsion.fuel.1.consumption": {
        "description": "Genset fuel flow (m³/s). Running: ~5.56e-7 m³/s (2 L/h)",
        "units": "m3/s", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-FUEL-FLOW-PRO"},
    },
    # ── Course / next waypoint ── now owned by the SignalK Course API +
    # @signalk/course-provider once the route is activated (see put_active_route).
    # The sim no longer hand-publishes navigation.courseGreatCircle.* to avoid a
    # second $source conflicting with the server-computed values.
    # ── Autopilot ── RB-OTTO-PILOT: simulated autopilot ──────────────────────
    "steering.autopilot.state": {
        "description": "Autopilot mode: standby/auto/wind/route", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-OTTO-PILOT"},
    },
    "steering.autopilot.target.headingMagnetic": {
        "description": "Autopilot target heading", "units": "rad", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-OTTO-PILOT"},
    },
    "steering.autopilot.target.windAngleApparent": {
        "description": "Autopilot target wind angle (wind mode)", "units": "rad", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-OTTO-PILOT"},
    },
    "steering.rudderAngle": {
        "description": "Rudder angle, + to starboard", "units": "rad", "timeout": 5,
        "source": {"manufacturer": _RB, "model": "RB-OTTO-PILOT"},
    },
}

# Known electrical loads (name → human label) for dynamic metadata generation
_LOAD_LABELS: dict[str, str] = {
    "fridge":       "Compressor fridge",
    "watermaker":   "Watermaker (RO desalinator)",
    "nav":          "Navigation electronics",
    "instruments":  "Instruments (MFD + sensors)",
    "lighting":     "Interior LED lighting",
    "wifi":         "WiFi router and network gear",
    "cooker":       "AC induction cooker",
    "boiler":       "Calorifier immersion heater",
    "kettle":       "Electric kettle",
    "coffeemaker":  "Coffee maker",
    "hvac":         "Air conditioning unit",
    "bilge_pump":   "Bilge pump motor",
    "water_pump":   "Fresh water pressure pump",
}


def _metadata_items(extra_load_names: list[str] | None = None) -> list[tuple[str, dict]]:
    """Full metadata list: static paths + dynamic electrical-load paths."""
    items: list[tuple[str, dict]] = list(_METADATA.items())
    for name in (extra_load_names or []):
        label = _LOAD_LABELS.get(name, name.replace("_", " ").title())
        items.append((
            f"electrical.loads.{name}.power",
            {"description": f"{label} power draw", "units": "W", "timeout": 5,
             "source": {"manufacturer": _RB, "model": "RB-WALL-WART-3000"}},
        ))
        items.append((
            f"electrical.loads.{name}.state",
            {"description": f"{label} on/off", "timeout": 5,
             "source": {"manufacturer": _RB, "model": "RB-WALL-WART-3000"}},
        ))
    return items


def _ts(utc_now: datetime) -> str:
    return utc_now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _v(path: str, value: Any) -> dict:
    return {"path": path, "value": value}


def _autopilot_values(ap: Any, hdg_deg: float) -> list[dict]:
    """SignalK delta values for the autopilot from its current state."""
    s = ap.state
    state_label = s.mode if s.engaged else "standby"
    out = [
        _v("steering.autopilot.state", state_label),
        _v("steering.rudderAngle", math.radians(s.rudder_deg)),
    ]
    if s.mode == "wind" and s.target_wind_angle_deg is not None:
        out.append(_v("steering.autopilot.target.windAngleApparent",
                      math.radians(s.target_wind_angle_deg)))
    target_hdg = s.target_heading_deg if s.target_heading_deg is not None else hdg_deg
    target_rad = math.radians(target_hdg)
    out.append(_v("steering.autopilot.target.headingMagnetic", target_rad))
    # No magnetic variation model — true heading == magnetic heading in this sim.
    out.append(_v("steering.autopilot.target.headingTrue", target_rad))
    return out


def _build_vessel_delta(nav: NavState, elec: ElecState, sys_: SystemsState,
                         lights: LightsState, wx: WeatherPoint, state: SimState,
                         utc_now: datetime, temps: dict,
                         next_wp: tuple[str, float, float] | None = None,
                         route_href: str = "", point_index: int = 0,
                         polars: Any = None, autopilot: Any = None,
                         closest_approach: tuple[float, float] | None = None) -> dict:
    ts = _ts(utc_now)
    engine_on = state == SimState.MOTORED
    genset_on = elec.genset_state == "running"

    # Volvo D4-55 propulsion: derive RPM and fuel from actual STW
    eng_rps  = engine_rpm(nav.stw_kts) / 60.0 if engine_on else 0.0
    fuel_L_h = engine_fuel_L_h(nav.stw_kts) if engine_on else 0.0

    load_entries = list(elec.loads.items())

    values = [
        # Navigation
        _v("navigation.position", {"latitude": nav.lat, "longitude": nav.lon}),
        _v("navigation.speedOverGround",      nav.sog_kts * 0.514444),
        _v("navigation.courseOverGroundTrue", math.radians(nav.cog_deg)),
        _v("navigation.headingTrue",          math.radians(nav.hdg_deg)),
        _v("navigation.speedThroughWater",    nav.stw_kts * 0.514444),
        _v("navigation.attitude.roll",        math.radians(nav.heel_deg)),
        _v("navigation.log",                  nav.log_nm * 1852),
        _v("navigation.state",                state.value),
        # Wind
        _v("environment.wind.angleApparent",  math.radians(nav.awa_deg)),
        _v("environment.wind.speedApparent",  nav.aws_kts * 0.514444),
        _v("environment.wind.angleTrueWater", math.radians(nav.twa_deg)),
        _v("environment.wind.speedTrue",      nav.tws_kts * 0.514444),
        # Environment
        _v("environment.depth.belowKeel",       nav.depth_m),
        _v("environment.water.swell.height",    wx.wave_height_m),
        _v("environment.water.swell.period",    wx.wave_period_s),
        _v("environment.water.swell.direction", math.radians(wx.wave_dir_deg)),
        _v("environment.outside.temperature",   wx.temp_c + 273.15),
        _v("environment.outside.pressure",      wx.pressure_pa),
        _v("environment.outside.humidity",      wx.humidity),
        # Temperatures
        _v("propulsion.main.coolantTemperature",         temps["engine_k"]),
        _v("propulsion.genset.coolantTemperature",       temps["genset_k"]),
        _v("environment.inside.waterHeater.temperature", temps["boiler_k"]),
        _v("environment.inside.saloon.temperature",      temps["saloon_k"]),
        _v("environment.inside.cabin.forwardDouble.temperature", temps["fwd_cabin_k"]),
        _v("environment.inside.cabin.portAft.temperature",       temps["port_aft_k"]),
        _v("environment.inside.cabin.starboardAft.temperature",  temps["stbd_aft_k"]),
        # Battery
        _v("electrical.batteries.house.voltage",            elec.voltage),
        _v("electrical.batteries.house.current",            elec.current_a),
        _v("electrical.batteries.house.stateOfCharge",      elec.soc),
        _v("electrical.batteries.house.temperature",        wx.temp_c + 2 + 273.15),
        _v("electrical.batteries.house.capacity.nominal",   BATTERY_WH_J),
        _v("electrical.batteries.house.capacity.remaining", elec.soc * BATTERY_WH_J),
        # Solar
        _v("electrical.solar.1.power",   elec.solar_w),
        _v("electrical.solar.1.current", elec.solar_w / max(elec.voltage, 1)),
        _v("electrical.solar.1.voltage", elec.voltage),
        # Alternator / genset / inverter
        _v("electrical.alternators.1.power",   elec.alternator_w),
        _v("electrical.chargers.genset.power", elec.genset_w),
        _v("electrical.inverter.1.state",      elec.inverter_state),
        _v("electrical.inverter.1.dc.power",   sum(elec.loads.values())),
        _v("electrical.inverter.1.ac.power",   sum(
            elec.loads.get(k, 0) for k in ("cooker", "boiler", "kettle", "coffeemaker"))),
        # Navigation lights (COLREGS)
        _v("electrical.switches.navLights.state",      lights.port_light or lights.starboard_light),
        _v("electrical.switches.portLight.state",      lights.port_light),
        _v("electrical.switches.starboardLight.state", lights.starboard_light),
        _v("electrical.switches.sternLight.state",     lights.stern_light),
        _v("electrical.switches.mastheadLight.state",  lights.masthead_light),
        _v("electrical.switches.steeringLight.state",  lights.masthead_light),  # alias
        _v("electrical.switches.anchorLight.state",    lights.anchor_light),
        # Additional lights
        _v("electrical.switches.deckLight.state",      lights.deck_light),
        # Cabin dimmers
        _v("electrical.switches.saloonLight.state",          lights.saloon_dimmer > 0),
        _v("electrical.switches.saloonLight.dimmer",         lights.saloon_dimmer),
        _v("electrical.switches.forwardCabinLight.state",    lights.forward_cabin_dimmer > 0),
        _v("electrical.switches.forwardCabinLight.dimmer",   lights.forward_cabin_dimmer),
        _v("electrical.switches.portAftCabinLight.state",    lights.port_aft_cabin_dimmer > 0),
        _v("electrical.switches.portAftCabinLight.dimmer",   lights.port_aft_cabin_dimmer),
        _v("electrical.switches.stbdAftCabinLight.state",    lights.stbd_aft_cabin_dimmer > 0),
        _v("electrical.switches.stbdAftCabinLight.dimmer",   lights.stbd_aft_cabin_dimmer),
        _v("electrical.switches.instrumentLight.dimmer",     lights.instrument_dimmer),
        # Pumps
        _v("electrical.switches.bilgePump.state",  sys_.bilge_pump),
        _v("electrical.switches.waterPump.state",  sys_.water_pump),
        # Propulsion — RPM and fuel derived from Volvo D4-55 model in navigator.py
        _v("propulsion.main.state",       "started" if engine_on else "stopped"),
        _v("propulsion.main.revolutions", eng_rps),
        _v("propulsion.genset.state",     elec.genset_state),
        _v("propulsion.genset.revolutions", elec.genset_rpm),
        # Tanks (0–1 fraction)
        _v("tanks.freshWater.0.currentLevel",  sys_.fw_tank_0),
        _v("tanks.freshWater.1.currentLevel",  sys_.fw_tank_1),
        _v("tanks.fuel.0.currentLevel",        sys_.fuel_tank_0),
        _v("tanks.fuel.1.currentLevel",        sys_.fuel_tank_1),
        _v("tanks.blackWater.0.currentLevel",  sys_.bw_tank_0),
        _v("tanks.blackWater.1.currentLevel",  sys_.bw_tank_1),
        _v("tanks.blackWater.2.currentLevel",  sys_.bw_tank_2),
        # Fuel consumption (L/h → L/s → m³/s: ÷3600÷1000)
        _v("propulsion.fuel.0.consumption", fuel_L_h / 3600 / 1000 if engine_on else 0.0),
        _v("propulsion.fuel.1.consumption", (2.0 / 3600 / 1000) if genset_on else 0.0),
    ]

    # Loads — built outside the list literal to avoid walrus-operator issues
    for k, vv in load_entries:
        values.append(_v(f"electrical.loads.{k}.power", vv))
    for k, vv in load_entries:
        values.append(_v(f"electrical.loads.{k}.state", "on" if vv > 0 else "off"))

    # Course — next/previous waypoint, distance/bearing and crossTrackError are
    # now published by the SignalK Course API + @signalk/course-provider once the
    # route is activated (writer.put_active_route). The sim no longer hand-publishes
    # navigation.courseGreatCircle.* here. (next_wp/route_href/point_index params
    # are retained for call-site compatibility but unused.)

    # Performance — derived from the sim polar at the CURRENT true wind. Emitted
    # in SI (speeds m/s, angles radians) so the bundle's native reader
    # (sailing/polars.py::_read_native_performance) can report source="signalk".
    #   polarSpeed       = polar boat speed at (current TWS, |TWA|)         m/s
    #   velocityMadeGood = actual STW * cos(TWA); +upwind / −downwind       m/s
    #   beatAngle/gybeAngle = polar VMG-optimal upwind/downwind TWAs        rad
    #   targetAngle      = beat (|TWA|<90) else gybe, on the current tack   rad
    #   polarSpeedRatio  = actual STW / polarSpeed (guarded)               ratio
    if polars is not None:
        abs_twa = abs(nav.twa_deg)
        polar_speed_kts = polars.polar_speed(nav.tws_kts, abs_twa)
        beat_deg, gybe_deg = polars.beat_gybe_angles(nav.tws_kts)
        vmg_kts = nav.stw_kts * math.cos(math.radians(nav.twa_deg))
        target_deg = beat_deg if abs_twa < 90 else gybe_deg
        # Sign target/beat/gybe to the current tack (TWA sign) so it points to
        # the same side the boat is on (SignalK convention: +stbd, −port).
        tack_sign = -1.0 if nav.twa_deg < 0 else 1.0
        values.append(_v("performance.velocityMadeGood", vmg_kts * 0.514444))
        values.append(_v("performance.polarSpeed",       polar_speed_kts * 0.514444))
        values.append(_v("performance.targetAngle",      math.radians(target_deg) * tack_sign))
        values.append(_v("performance.beatAngle",        math.radians(beat_deg) * tack_sign))
        values.append(_v("performance.gybeAngle",        math.radians(gybe_deg) * tack_sign))
        if polar_speed_kts > 1e-6:
            values.append(_v("performance.polarSpeedRatio",
                             nav.stw_kts / polar_speed_kts))

    if autopilot is not None:
        values.extend(_autopilot_values(autopilot, nav.hdg_deg))

    # navigation.closestApproach.* — sim convention (no SK standard).
    # Bearing (radians, true) and distance (metres) to the nearest AIS contact.
    # Omitted entirely when there are no contacts.
    if closest_approach is not None:
        bearing_rad, dist_m = closest_approach
        values.append(_v("navigation.closestApproach.bearingTrue", bearing_rad))
        values.append(_v("navigation.closestApproach.distance",    dist_m))

    return {
        "context": "vessels.self",
        "updates": [{"$source": "simulator.py", "timestamp": ts, "values": values}],
    }


def _build_meta_delta(path: str, meta: dict, utc_now: datetime) -> dict:
    """A SignalK delta that sets a path's metadata (units/description/source...).
    SignalK ingests meta via deltas (updates[].meta), not REST PUT to /meta."""
    return {
        "context": "vessels.self",
        "updates": [{
            "$source": "simulator.py",
            "timestamp": _ts(utc_now),
            "meta": [{"path": path, "value": meta}],
        }],
    }


def _build_ais_delta(mmsi: str, lat: float, lon: float,
                     cog_deg: float, sog_kts: float,
                     name: str, ship_type: int) -> dict:
    return {
        "context": f"vessels.urn:mrn:imo:mmsi:{mmsi}",
        "updates": [{
            "$source": "ais_relay",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "values": [
                _v("navigation.position", {"latitude": lat, "longitude": lon}),
                _v("navigation.courseOverGroundTrue", math.radians(cog_deg)),
                _v("navigation.speedOverGround",      sog_kts * 0.514444),
                # AIS targets without a transmitted true heading conventionally
                # fall back to COG as the heading approximation.
                _v("navigation.headingTrue", math.radians(cog_deg)),
                # Standard SignalK vessel name (top-level field).
                _v("name", name),
                # Standard SignalK ship type (design.aisShipType shape).
                _v("design.aisShipType", {"id": ship_type}),
                # Legacy kdcube fields retained for back-compat.
                _v("kdcube.ais.name", name),
                _v("kdcube.ais.shipType", {"id": ship_type}),
            ],
        }],
    }


class SignalKWriter:
    def __init__(self, host: str, port: int) -> None:
        self._host  = host
        self._port  = port
        self._ws    = None
        self._token: str | None = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=60)  # ~60s buffer

    async def connect(self, username: str, password: str) -> None:
        req = urllib.request.Request(
            f"http://{self._host}:{self._port}/signalk/v1/auth/login",
            data=json.dumps({"username": username, "password": password}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
            self._token = json.loads(r.read())["token"]
        uri = (f"ws://{self._host}:{self._port}/signalk/v1/stream"
               f"?subscribe=none&token={self._token}")
        self._ws = await websockets.connect(uri)
        await self._ws.recv()  # consume hello

    @property
    def token(self) -> str | None:
        return self._token

    async def get_self_position(self) -> tuple[float, float] | None:
        """Read navigation.position from SK so the sim can resume where it left
        off after a restart. Returns (lat, lon), or None if SK has no position
        yet (fresh server) or the read fails — caller then starts at the origin."""
        import httpx  # type: ignore[import]

        url = (f"http://{self._host}:{self._port}"
               f"/signalk/v1/api/vessels/self/navigation/position")
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url, headers={"Authorization": f"JWT {self._token}"}, timeout=8)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            print(f"[writer] position read failed (fresh start): {exc!r}", flush=True)  # noqa: T201
            return None
        val = data.get("value", data) if isinstance(data, dict) else None
        if not isinstance(val, dict):
            return None
        lat, lon = val.get("latitude"), val.get("longitude")
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)

    async def send_vessel_delta(self, nav: NavState, elec: ElecState,
                                 sys_: SystemsState, lights: LightsState,
                                 wx: WeatherPoint, state: SimState,
                                 utc_now: datetime, temps: dict,
                                 next_wp: tuple[str, float, float] | None = None,
                                 route_href: str = "", point_index: int = 0,
                                 polars: Any = None, autopilot: Any = None,
                                 closest_approach: tuple[float, float] | None = None) -> None:
        delta = _build_vessel_delta(nav, elec, sys_, lights, wx, state, utc_now, temps,
                                    next_wp, route_href, point_index, polars, autopilot,
                                    closest_approach)
        try:
            self._queue.put_nowait(json.dumps(delta))
        except asyncio.QueueFull:
            pass  # drop on full: sim_loop must never block on the queue

    async def enqueue_ais(self, mmsi: str, lat: float, lon: float,
                           cog_deg: float, sog_kts: float,
                           name: str, ship_type: int) -> None:
        delta = _build_ais_delta(mmsi, lat, lon, cog_deg, sog_kts, name, ship_type)
        if not self._queue.full():
            await self._queue.put(json.dumps(delta))

    async def _reconnect_ws(self, label: str = "reconnected") -> None:
        """Re-establish the WebSocket connection using the stored token."""
        self._ws = None
        while True:
            try:
                uri = (f"ws://{self._host}:{self._port}/signalk/v1/stream"
                       f"?subscribe=none&token={self._token}")
                self._ws = await websockets.connect(uri)
                await self._ws.recv()  # consume hello
                print(f"[writer] WS {label}", flush=True)  # noqa: T201
                return
            except Exception as exc:
                print(f"[writer] WS connect failed: {exc!r}, retrying in 5s", flush=True)  # noqa: T201
                await asyncio.sleep(5)

    async def flush_loop(self) -> None:
        """Run forever — drain queue and send to SK WS, reconnecting on drop."""
        while True:
            msg = await self._queue.get()
            if self._ws is None:
                continue  # drop message, reconnect already in progress
            try:
                await self._ws.send(msg)
            except Exception as exc:
                print(f"[writer] WS send failed: {exc!r}, reconnecting…", flush=True)  # noqa: T201
                await self._reconnect_ws(label="reconnected")

    def _meta_url(self, path: str) -> str:
        return (f"http://{self._host}:{self._port}/signalk/v1/api"
                f"/vessels/self/{path.replace('.', '/')}/meta")

    async def send_all_metadata(self, extra_load_names: list[str] | None = None) -> None:
        """One-shot: PUT SignalK metadata for every published path. Best-effort.

        NOTE: on the embedded board, blasting ~90 PUTs at once (even at low
        concurrency) can stall SK's Node.js event loop and drop the WebSocket.
        Prefer metadata_loop() for the running sim; this stays for tooling."""
        import httpx  # type: ignore[import]

        items = _metadata_items(extra_load_names)
        sem = asyncio.Semaphore(2)
        headers = {"Authorization": f"JWT {self._token}"}

        async def _put(client: Any, path: str, meta: dict) -> None:
            async with sem:
                try:
                    await client.put(self._meta_url(path), json=meta, headers=headers, timeout=5)
                except Exception as exc:
                    print(f"[writer] meta PUT {path}: {exc!r}", flush=True)  # noqa: T201

        async with httpx.AsyncClient() as client:
            await asyncio.gather(*(_put(client, p, m) for p, m in items))

    async def metadata_loop(self, extra_load_names: list[str] | None = None,
                            interval: float = 2.0) -> None:
        """Trickle metadata in the background: enqueue ONE meta delta every
        `interval` seconds, cycling through all paths forever.

        Goes through the same queue/WebSocket as the data deltas (only flush_loop
        owns the socket), so it's gentle — one tiny update at a time, never a
        burst — and self-healing: it keeps re-asserting metadata, so a SignalK
        restart is recovered within one cycle. Run as a concurrent task."""
        items = _metadata_items(extra_load_names)
        if not items:
            return
        print(f"[writer] metadata trickle: {len(items)} records, 1 per {interval:g}s (delta)", flush=True)  # noqa: T201
        i = 0
        while True:
            path, meta = items[i % len(items)]
            i += 1
            delta = _build_meta_delta(path, meta, datetime.now(timezone.utc))
            try:
                self._queue.put_nowait(json.dumps(delta))
            except asyncio.QueueFull:
                pass  # never block; the value deltas take priority
            await asyncio.sleep(interval)

    async def put_route_resource(self, route_uuid: str, geojson: dict) -> None:
        # Resources API is v2 in signalk-server 2.x; the v1 path falls through to
        # the generic data-PUT handler ("input is missing a value").
        import httpx  # type: ignore[import]
        async with httpx.AsyncClient() as client:
            r = await client.put(
                f"http://{self._host}:{self._port}/signalk/v2/api/resources/routes/{route_uuid}",
                json=geojson,
                headers={"Authorization": f"JWT {self._token}"},
                timeout=10,
            )
            if r.status_code >= 300:
                print(f"[writer] put_route_resource {r.status_code}: {r.text[:200]}", flush=True)  # noqa: T201

    async def put_active_route(self, route_uuid: str,
                                waypoint_index: int) -> None:
        """Activate a route via the v2 Course API. The Course API + the enabled
        @signalk/course-provider plugin then compute navigation.course.* incl.
        calcValues.crossTrackError from vessel position vs the active leg."""
        import httpx  # type: ignore[import]
        async with httpx.AsyncClient() as client:
            await client.put(
                f"http://{self._host}:{self._port}"
                f"/signalk/v2/api/vessels/self/navigation/course/activeRoute",
                json={"href": f"/resources/routes/{route_uuid}",
                      "pointIndex": waypoint_index},
                headers={"Authorization": f"JWT {self._token}"},
                timeout=10,
            )

    async def advance_active_point(self, steps: int = 1) -> None:
        """Advance the active route's current leg by `steps` (v2 Course API)."""
        import httpx  # type: ignore[import]
        async with httpx.AsyncClient() as client:
            await client.put(
                f"http://{self._host}:{self._port}"
                f"/signalk/v2/api/vessels/self/navigation/course/activeRoute/nextPoint",
                json={"value": steps},
                headers={"Authorization": f"JWT {self._token}"},
                timeout=10,
            )

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
