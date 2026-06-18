# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# signalk/sim/modules/temperatures.py
from __future__ import annotations
import math
from datetime import datetime
from yey.boats.simulator.engine.schedule import SimState

ADRIATIC_UTC_OFFSET = 2

# Operating temperatures (°C)
ENGINE_T_OPERATING  = 90.0
GENSET_T_OPERATING  = 85.0
BOILER_T_TARGET     = 65.0

# Thermal rates (°C/s)
ENGINE_WARMUP_RATE   = 0.15    # ~10 min to operating temp
ENGINE_COOLDOWN_RATE = 0.03
GENSET_WARMUP_RATE   = 0.12
GENSET_COOLDOWN_RATE = 0.025
BOILER_HEAT_RATE     = 0.08    # 1500W into ~30L water
BOILER_COOL_RATE     = 0.0008  # well-insulated


def cabin_temp_k(outside_c: float, utc_now: datetime,
                 solar_gain: float = 0.5) -> float:
    """Return cabin air temperature in Kelvin.
    solar_gain: 0 (no sun) to 1 (full sun, south-facing port).
    Peaks at 14:00 local.
    """
    local_h = (utc_now.hour + ADRIATIC_UTC_OFFSET) % 24
    angle = math.pi * (local_h - 6) / 12
    solar_bonus = solar_gain * 9.0 * max(0.0, math.sin(angle))
    temp_c = outside_c + 3.0 + solar_bonus
    return temp_c + 273.15


class ThermalModel:
    def __init__(self, ambient_c: float = 22.0) -> None:
        self._ambient_k = ambient_c + 273.15
        self._engine_k  = self._ambient_k
        self._genset_k  = self._ambient_k
        self._boiler_k  = self._ambient_k

    @property
    def engine_k(self) -> float:  return self._engine_k
    @property
    def genset_k(self) -> float:  return self._genset_k
    @property
    def boiler_k(self) -> float:  return self._boiler_k

    def update_ambient(self, ambient_c: float) -> None:
        self._ambient_k = ambient_c + 273.15

    def tick(self, dt_s: float, sim_state: SimState,
             genset_running: bool = False,
             boiler_active: bool = False) -> None:
        engine_on = sim_state == SimState.MOTORED

        # Engine
        if engine_on:
            target = ENGINE_T_OPERATING + 273.15
            self._engine_k = min(target, self._engine_k + ENGINE_WARMUP_RATE * dt_s)
        else:
            self._engine_k = max(self._ambient_k,
                                 self._engine_k - ENGINE_COOLDOWN_RATE * dt_s)

        # Genset
        if genset_running:
            target = GENSET_T_OPERATING + 273.15
            self._genset_k = min(target,
                                 self._genset_k + GENSET_WARMUP_RATE * dt_s)
        else:
            self._genset_k = max(self._ambient_k,
                                 self._genset_k - GENSET_COOLDOWN_RATE * dt_s)

        # Boiler
        if boiler_active:
            target = BOILER_T_TARGET + 273.15
            self._boiler_k = min(target,
                                 self._boiler_k + BOILER_HEAT_RATE * dt_s)
        else:
            self._boiler_k = max(self._ambient_k,
                                 self._boiler_k - BOILER_COOL_RATE * dt_s)

    def cabin_temps(self, outside_c: float, utc_now: datetime) -> dict:
        """Return all cabin and equipment temperatures in Kelvin."""
        return {
            "saloon_k":    cabin_temp_k(outside_c, utc_now, solar_gain=0.3),
            "fwd_cabin_k": cabin_temp_k(outside_c, utc_now, solar_gain=0.5),
            "port_aft_k":  cabin_temp_k(outside_c, utc_now, solar_gain=0.4),
            "stbd_aft_k":  cabin_temp_k(outside_c, utc_now, solar_gain=0.4),
            "engine_k":    self._engine_k,
            "genset_k":    self._genset_k,
            "boiler_k":    self._boiler_k,
        }
