# signalk/sim/modules/schedule.py
from __future__ import annotations
from datetime import datetime
from enum import Enum

ADRIATIC_UTC_OFFSET = 2  # CEST (summer)
SAILING_START_LOCAL = 7   # 07:00
SAILING_END_LOCAL   = 18  # 18:00 (exclusive)
BORA_TWS_THRESHOLD  = 25.0   # kts


class SimState(Enum):
    SAILING    = "sailing"
    MOTORED    = "motored"
    MOORED     = "moored"
    BORA_HOLD  = "bora_hold"


class Schedule:
    def __init__(self) -> None:
        self.state: SimState = SimState.MOORED
        self._tack: str = "starboard"
        self._tack_timer_s: float = 999.0   # seconds on current tack
        self._lookahead_timer_s: float = 0.0

    # ── sailing window ──────────────────────────────────────────────────────
    @staticmethod
    def is_sailing_window(utc_now: datetime) -> bool:
        local_hour = (utc_now.hour + ADRIATIC_UTC_OFFSET) % 24
        local_frac = local_hour + utc_now.minute / 60
        return SAILING_START_LOCAL <= local_frac < SAILING_END_LOCAL

    # ── Bora detection ──────────────────────────────────────────────────────
    @staticmethod
    def is_bora(twd_deg: float, mean_tws_kts: float) -> bool:
        direction_ok = (0 <= twd_deg <= 90)
        return direction_ok and mean_tws_kts > BORA_TWS_THRESHOLD

    # ── state transitions ───────────────────────────────────────────────────
    def on_waypoint_arrival(self) -> None:
        self.state = SimState.MOORED

    def try_depart(self, utc_now: datetime,
                   twd_deg: float, mean_tws_kts: float) -> SimState:
        if not self.is_sailing_window(utc_now):
            self.state = SimState.MOORED
            return self.state
        if self.is_bora(twd_deg, mean_tws_kts):
            self.state = SimState.BORA_HOLD
            return self.state
        self.state = SimState.SAILING
        return self.state

    def update_sailing_state(self, stw_kts: float) -> SimState:
        """Call each tick while underway to toggle SAILING / MOTORED."""
        if self.state in (SimState.MOORED, SimState.BORA_HOLD):
            return self.state
        if stw_kts < 1.8:
            self.state = SimState.MOTORED
        else:
            self.state = SimState.SAILING
        return self.state

    # ── tack hysteresis ─────────────────────────────────────────────────────
    @property
    def tack(self) -> str:
        return self._tack

    def tick(self, dt_s: float = 1.0) -> None:
        self._tack_timer_s += dt_s
        self._lookahead_timer_s += dt_s

    def request_tack(self, desired: str) -> bool:
        """Switch tack if hysteresis (600 s) allows. Returns True if tacked."""
        if desired != self._tack and self._tack_timer_s >= 600:
            self._tack = desired
            self._tack_timer_s = 0.0
            return True
        return False

    @property
    def lookahead_due(self) -> bool:
        return self._lookahead_timer_s >= 300  # every 5 min

    def reset_lookahead(self) -> None:
        self._lookahead_timer_s = 0.0
