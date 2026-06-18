# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# signalk/sim/modules/lights.py
# ruff: noqa: S311
from __future__ import annotations
import random
from dataclasses import dataclass
from datetime import datetime
from yey.boats.simulator.engine.schedule import SimState  # type: ignore[import]

ADRIATIC_OFFSET = 2  # UTC+2 CEST


@dataclass
class LightsState:
    # COLREGS navigation lights
    port_light: bool        # red, port side running light
    starboard_light: bool   # green, starboard side running light
    stern_light: bool       # white, 135° stern arc
    masthead_light: bool    # white 225° forward (steaming light; power only)
    anchor_light: bool      # all-round white (at anchor/moored)
    # Additional
    deck_light: bool        # exterior cockpit / deck floodlight
    # Cabin dimmers 0.0–1.0
    saloon_dimmer: float
    forward_cabin_dimmer: float
    port_aft_cabin_dimmer: float
    stbd_aft_cabin_dimmer: float
    instrument_dimmer: float   # chart-table / instrument-panel backlight


class LightsModel:
    _DECK_MEAN_OFF_S = 3600.0   # avg gap between deck-light on-events
    _DECK_MEAN_ON_S  = 1800.0   # avg duration deck light stays on
    _CABIN_MIN_S     =  600.0   # cabin update: shortest interval (10 min)
    _CABIN_MAX_S     = 1800.0   # cabin update: longest interval (30 min)

    def __init__(self) -> None:
        self._deck_on    = False
        self._deck_timer = 0.0
        self._deck_next  = random.expovariate(1 / self._DECK_MEAN_OFF_S)  # noqa: S311

        self._saloon   = 0.0
        self._fwd      = 0.0
        self._port_aft = 0.0
        self._stbd_aft = 0.0

        self._cabin_timer = 0.0
        self._cabin_next  = 0.0   # trigger immediately on first tick

    def tick(self, dt_s: float, sim_state: SimState,
             is_night: bool, utc_now: datetime) -> LightsState:
        local_h  = _local_hour(utc_now)
        underway = sim_state in (SimState.SAILING, SimState.MOTORED)
        moored   = sim_state in (SimState.MOORED, SimState.BORA_HOLD)

        # ── COLREGS nav lights (deterministic, safety-critical) ──────────────
        port_light      = underway and is_night
        starboard_light = underway and is_night
        stern_light     = underway and is_night
        masthead_light  = (sim_state == SimState.MOTORED) and is_night
        anchor_light    = moored and is_night

        # ── Deck light: random, only when moored at night ────────────────────
        self._deck_timer += dt_s
        if self._deck_timer >= self._deck_next:
            self._deck_timer = 0.0
            if self._deck_on:
                self._deck_on   = False
                self._deck_next = random.expovariate(1 / self._DECK_MEAN_OFF_S)  # noqa: S311
            elif moored and is_night:
                self._deck_on   = True
                self._deck_next = random.expovariate(1 / self._DECK_MEAN_ON_S)   # noqa: S311
            else:
                self._deck_next = random.expovariate(1 / self._DECK_MEAN_OFF_S)  # noqa: S311
        deck_light = self._deck_on and moored and is_night

        # ── Cabin dimmers: sampled every 10–30 min, time-of-day driven ───────
        self._cabin_timer += dt_s
        if self._cabin_timer >= self._cabin_next:
            self._cabin_timer = 0.0
            self._cabin_next  = random.uniform(self._CABIN_MIN_S, self._CABIN_MAX_S)  # noqa: S311
            self._saloon   = _saloon_target(local_h)
            self._fwd      = _cabin_target(local_h)
            self._port_aft = _cabin_target(local_h)
            self._stbd_aft = _cabin_target(local_h)

        instrument = 0.35 if (underway and is_night) else 0.0

        return LightsState(
            port_light=port_light,
            starboard_light=starboard_light,
            stern_light=stern_light,
            masthead_light=masthead_light,
            anchor_light=anchor_light,
            deck_light=deck_light,
            saloon_dimmer=round(self._saloon, 2),
            forward_cabin_dimmer=round(self._fwd, 2),
            port_aft_cabin_dimmer=round(self._port_aft, 2),
            stbd_aft_cabin_dimmer=round(self._stbd_aft, 2),
            instrument_dimmer=round(instrument, 2),
        )


def _local_hour(utc_now: datetime) -> float:
    return (utc_now.hour + ADRIATIC_OFFSET + utc_now.minute / 60) % 24


def _saloon_target(h: float) -> float:
    """Target saloon brightness for the current local hour."""
    if 6.0 <= h < 9.0:
        return random.uniform(0.20, 0.45)   # noqa: S311  dim morning light
    if 9.0 <= h < 18.0:
        return 0.0
    if 18.0 <= h < 22.0:
        return random.uniform(0.55, 0.85)   # noqa: S311  lively evening
    if 22.0 <= h < 23.5:
        return random.uniform(0.20, 0.45)   # noqa: S311  winding down
    return 0.0


def _cabin_target(h: float) -> float:
    """Target brightness for an individual cabin (called per cabin)."""
    if 6.0 <= h < 8.5:
        return random.uniform(0.20, 0.50) if random.random() < 0.50 else 0.0  # noqa: S311
    if 8.5 <= h < 19.0:
        return 0.0
    if 19.0 <= h < 22.5:
        return random.uniform(0.25, 0.65) if random.random() < 0.65 else 0.0  # noqa: S311
    if 22.5 <= h < 24.0:
        return random.uniform(0.10, 0.30) if random.random() < 0.25 else 0.0  # noqa: S311
    return 0.0
