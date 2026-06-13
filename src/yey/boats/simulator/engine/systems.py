# signalk/sim/modules/systems.py
# ruff: noqa: E702
from __future__ import annotations
import random
from dataclasses import dataclass
from datetime import datetime
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]

ADRIATIC_OFFSET  = 2
FW_CAPACITY_L    = 400.0    # per tank
FUEL_CAPACITY_L  = 150.0    # per tank
BW_CAPACITY_L    = 60.0     # per tank
WATER_PUMP_LPM   = 14.0     # litres/minute
BW_DAILY_L       = 12.0     # total black water per day (4 L per tank)
BILGE_MEAN_S     = 18000.0  # mean seconds between bilge activations


@dataclass
class SystemsState:
    fw_tank_0: float;  fw_tank_1: float
    fuel_tank_0: float; fuel_tank_1: float
    bw_tank_0: float;  bw_tank_1: float;  bw_tank_2: float
    bilge_pump: bool;  water_pump: bool


# Water pump windows (local hours): list of (start, end) — 20 min total per day
_PUMP_WINDOWS: list[tuple[float, float]] = [
    (6.500, 6.567), (6.567, 6.633), (6.633, 6.700),
    (6.700, 6.767), (6.767, 6.833), (6.833, 6.900),   # 6 morning showers = 6 min
    (7.000, 7.033), (7.100, 7.133), (7.200, 7.233), (7.300, 7.333),  # breakfast = 2 min
    (12.000, 12.025), (12.100, 12.125), (12.200, 12.225),
    (12.300, 12.325), (12.400, 12.425), (12.500, 12.525),  # lunch = 3 min
    (19.000, 19.025), (19.100, 19.125), (19.200, 19.225),
    (19.300, 19.325), (19.400, 19.425), (19.500, 19.525),  # dinner = 3 min
    (19.533, 19.600), (19.600, 19.667), (19.667, 19.733),
    (19.733, 19.800), (19.800, 19.867), (19.867, 19.933),  # 6 evening showers = 6 min
]


class Systems:
    def __init__(self) -> None:
        self._fw0    = 1.0;  self._fw1   = 1.0
        self._fuel0  = 1.0;  self._fuel1 = 1.0
        self._bw0    = 0.0;  self._bw1   = 0.0;  self._bw2 = 0.0
        self._bilge_active = False
        self._bilge_timer  = 0.0
        self._bilge_on_s   = 0.0
        self._next_bilge   = random.expovariate(1 / BILGE_MEAN_S)  # noqa: S311
        self._active_fw_tank   = 0
        self._active_fuel_tank = 0
        self._marina_count = 0

    def tick(self, dt_s: float, sim_state: SimState, tws_kts: float,
             utc_now: datetime, fuel_consumed_l: float,
             refill_water: bool, refill_fuel: bool, pump_out_bw: bool) -> SystemsState:
        if refill_water or refill_fuel or pump_out_bw:
            self.on_marina_arrival(refill_water, refill_fuel, pump_out_bw)

        local_frac = (utc_now.hour + ADRIATIC_OFFSET + utc_now.minute / 60 +
                      utc_now.second / 3600) % 24

        water_pump_on = any(a <= local_frac < b for a, b in _PUMP_WINDOWS)
        if water_pump_on:
            drain_l = WATER_PUMP_LPM * dt_s / 60
            if self._active_fw_tank == 0:
                self._fw0 = max(0.0, self._fw0 - drain_l / FW_CAPACITY_L)
                if self._fw0 < 0.10:
                    self._active_fw_tank = 1
            else:
                self._fw1 = max(0.0, self._fw1 - drain_l / FW_CAPACITY_L)

        if fuel_consumed_l > 0:
            frac = fuel_consumed_l / FUEL_CAPACITY_L
            if self._active_fuel_tank == 0:
                self._fuel0 -= frac
                if self._fuel0 < 0.10:
                    self._active_fuel_tank = 1
            else:
                self._fuel1 = max(0.0, self._fuel1 - frac)

        bw_inc = BW_DAILY_L * dt_s / (86400 * 3)
        self._bw0 = min(1.0, self._bw0 + bw_inc / BW_CAPACITY_L)
        self._bw1 = min(1.0, self._bw1 + bw_inc / BW_CAPACITY_L)
        self._bw2 = min(1.0, self._bw2 + bw_inc / BW_CAPACITY_L)

        # bilge pump
        self._bilge_timer += dt_s
        mean_s = BILGE_MEAN_S / (2 if tws_kts > 20 else 1)
        if not self._bilge_active and self._bilge_timer >= self._next_bilge:
            self._bilge_active = True
            self._bilge_on_s   = 0.0
            self._bilge_timer  = 0.0
            self._next_bilge   = random.expovariate(1 / mean_s)  # noqa: S311
        if self._bilge_active:
            self._bilge_on_s += dt_s
            if self._bilge_on_s >= 45:
                self._bilge_active = False

        return SystemsState(
            fw_tank_0=max(0.0, self._fw0), fw_tank_1=max(0.0, self._fw1),
            fuel_tank_0=max(0.0, self._fuel0), fuel_tank_1=max(0.0, self._fuel1),
            bw_tank_0=self._bw0, bw_tank_1=self._bw1, bw_tank_2=self._bw2,
            bilge_pump=self._bilge_active, water_pump=water_pump_on,
        )

    def on_marina_arrival(self, refill_water: bool, refill_fuel: bool,
                          pump_out_bw: bool) -> None:
        self._marina_count += 1
        if refill_water:
            self._fw0 = 1.0; self._fw1 = 1.0
            self._active_fw_tank = 0
        if refill_fuel:
            self._fuel0 = 1.0; self._fuel1 = 1.0
            self._active_fuel_tank = 0
        if pump_out_bw:
            self._bw0 = 0.0; self._bw1 = 0.0; self._bw2 = 0.0
