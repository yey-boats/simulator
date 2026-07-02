# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# signalk/sim/modules/electrical.py
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import datetime
from yey.boats.simulator.engine.schedule import SimState

BATTERY_WH      = 14400.0   # 1200 Ah × 12 V
ADRIATIC_OFFSET = 2         # UTC+2 CEST


def solar_elevation_deg(lat: float, lon: float, utc_now: datetime) -> float:
    doy   = utc_now.timetuple().tm_yday
    ha    = (utc_now.hour + utc_now.minute / 60 + lon / 15 - 12) * 15
    dec   = 23.45 * math.sin(math.radians(360 / 365 * (doy - 81)))
    el    = math.degrees(math.asin(
        math.sin(math.radians(lat)) * math.sin(math.radians(dec)) +
        math.cos(math.radians(lat)) * math.cos(math.radians(dec)) *
        math.cos(math.radians(ha))
    ))
    return el


@dataclass
class ElecState:
    soc: float
    voltage: float
    current_a: float
    solar_w: float
    alternator_w: float
    genset_w: float
    inverter_state: str
    genset_state: str
    genset_rpm: float
    loads: dict[str, float]
    net_w: float

    @property
    def capacity_remaining_wh(self) -> float:
        return self.soc * BATTERY_WH


class Electrical:
    def __init__(self, initial_soc: float = 0.85) -> None:
        self._soc            = initial_soc
        self._genset_state   = "off"
        self._genset_timer   = 0.0
        self._fridge_on      = True
        self._fridge_timer   = 0.0

    # ── main tick ────────────────────────────────────────────────────────────
    def tick(self, dt_s: float, sim_state: SimState,
             lat: float, lon: float, cloud_cover: float,
             utc_now: datetime) -> ElecState:
        local_frac = self._local_hour_frac(utc_now)
        is_night   = not self._is_sailing_daylight(utc_now, lat, lon)

        loads = self._compute_loads(sim_state, local_frac, is_night, dt_s)
        solar_w = self._solar_power(lat, lon, cloud_cover, utc_now)
        alt_w   = 1500.0 if sim_state == SimState.MOTORED else 0.0
        gen_w   = self._step_genset(dt_s)
        net_w   = solar_w + alt_w + gen_w - sum(loads.values())

        self._soc = min(1.0, max(0.0,
            self._soc + (net_w * dt_s / 3600) / BATTERY_WH))

        voltage  = 13.0 + 0.9 * self._soc
        current  = net_w / voltage if voltage else 0.0
        inv_state = "inverting" if any(
            loads.get(k, 0) > 0 for k in ("cooker", "boiler", "kettle", "coffeemaker")
        ) else "standby"

        return ElecState(
            soc=self._soc, voltage=voltage, current_a=current,
            solar_w=solar_w, alternator_w=alt_w,
            genset_w=gen_w if gen_w > 0 else 0.0,
            inverter_state=inv_state,
            genset_state=self._genset_state,
            genset_rpm=50.0 if self._genset_state == "running" else 0.0,
            loads=loads, net_w=net_w,
        )

    # ── solar ─────────────────────────────────────────────────────────────────
    def _solar_power(self, lat: float, lon: float,
                     cloud_cover: float, utc_now: datetime) -> float:
        el = solar_elevation_deg(lat, lon, utc_now)
        if el <= 0:
            return 0.0
        return 500.0 * math.sin(math.radians(el)) * (1 - 0.8 * cloud_cover)

    # ── genset state machine ──────────────────────────────────────────────────
    def _step_genset(self, dt_s: float) -> float:
        self._genset_timer += dt_s
        if self._genset_state == "off":
            if self._soc < 0.50:
                self._genset_state = "starting"
                self._genset_timer = 0.0
            return 0.0
        if self._genset_state == "starting":
            if self._genset_timer >= 30:
                self._genset_state = "running"
            return 0.0
        if self._genset_state == "running":
            if self._soc >= 0.80:
                self._genset_state = "cooling"
                self._genset_timer = 0.0
            return 4000.0
        if self._genset_state == "cooling":
            if self._genset_timer >= 120:
                self._genset_state = "off"
            return 0.0
        return 0.0

    # ── loads ─────────────────────────────────────────────────────────────────
    def _compute_loads(self, sim_state: SimState,
                       local_frac: float, is_night: bool,
                       dt_s: float = 1.0) -> dict[str, float]:
        def in_window(*windows) -> bool:
            return any(a <= local_frac < b for a, b in windows)

        self._fridge_timer += dt_s
        if self._fridge_timer >= 120:
            self._fridge_on = not self._fridge_on
            self._fridge_timer = 0

        underway = sim_state in (SimState.SAILING, SimState.MOTORED)
        return {
            "navigation": 100.0 if underway else 0.0,
            "fridge":     60.0 if self._fridge_on else 0.0,
            "cabinLights":40.0 if is_night else 10.0,
            "navLights":  50.0 if (underway and is_night) else 0.0,
            "anchorLight":15.0 if (sim_state == SimState.MOORED and is_night) else 0.0,
            "steeringLight": 25.0 if (sim_state == SimState.MOTORED and is_night) else 0.0,
            "cooker":     3000.0 if in_window((7,8),(12,13),(19,20)) else 0.0,
            "boiler":     1500.0 * 0.6 if in_window((6.5,7.5),(19.5,20.5)) else 0.0,
            "kettle":     2000.0 if any(
                abs(local_frac - h) < (5/60) for h in (7.0, 10.0, 15.0, 19.0)
            ) else 0.0,
            "coffeemaker":1000.0 if in_window((7.083,7.333),(9.917,10.083)) else 0.0,
            "vhf":        25.0 if (int(local_frac * 120) % 60 == 0) else 5.0,
        }

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _local_hour_frac(utc_now: datetime) -> float:
        return (utc_now.hour + ADRIATIC_OFFSET + utc_now.minute / 60) % 24

    @staticmethod
    def _is_sailing_daylight(utc_now: datetime, lat: float, lon: float) -> bool:
        return solar_elevation_deg(lat, lon, utc_now) > 0
