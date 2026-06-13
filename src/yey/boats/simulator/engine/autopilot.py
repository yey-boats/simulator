# signalk/sim/modules/autopilot.py
"""Pure-logic autopilot controller for the boat simulator.

Decides the heading the boat should steer this tick based on engaged/mode/target
state, and tracks a believable rudder angle. No I/O — the sim wires it into
Navigator.tick and publishes steering.autopilot.* from `state`.
"""
from __future__ import annotations

from dataclasses import dataclass

MODES = ("standby", "auto", "wind", "route")


def _norm360(deg: float) -> float:
    return deg % 360


def _norm180(deg: float) -> float:
    return ((deg + 180) % 360) - 180


@dataclass
class AutopilotState:
    # Default: engaged in route mode, so the sim follows its active route out of
    # the box (preserves the pre-autopilot behaviour). "disengage" drops to
    # standby (hold heading); the other modes are opt-in via commands.
    engaged: bool = True
    mode: str = "route"                       # standby | auto | wind | route
    target_heading_deg: float | None = None   # auto
    target_wind_angle_deg: float | None = None  # wind (signed, +stbd)
    rudder_deg: float = 0.0


class Autopilot:
    MAX_RUDDER_DEG = 35.0
    RUDDER_GAIN = 0.8     # deg rudder per deg heading error
    RUDDER_DECAY = 0.5    # decay factor when on course

    def __init__(self) -> None:
        self.state = AutopilotState()

    def apply(self, action: str, value=None, *,
              current_heading_deg: float = 0.0, twd_deg: float = 0.0) -> None:
        a = (action or "").strip().lower()
        s = self.state
        if a == "engage":
            s.engaged = True
            if isinstance(value, str) and value in MODES:
                s.mode = value
            else:
                s.mode = "auto"   # bare engage = hold current heading
            self._ensure_target(current_heading_deg, twd_deg)
        elif a == "disengage":
            s.engaged = False
            s.mode = "standby"
            s.target_heading_deg = _norm360(current_heading_deg)
        elif a == "set_mode":
            if value in MODES:
                s.mode = value
                s.engaged = value != "standby"
                self._ensure_target(current_heading_deg, twd_deg)
        elif a == "set_heading":
            s.target_heading_deg = _norm360(float(value))
            s.mode = "auto"
            s.engaged = True
        elif a == "adjust":
            base = s.target_heading_deg if s.target_heading_deg is not None else current_heading_deg
            s.target_heading_deg = _norm360(base + float(value))
            if s.mode not in ("auto", "wind"):
                s.mode = "auto"
            s.engaged = True
        elif a == "tack":
            if s.mode == "wind" and s.target_wind_angle_deg is not None:
                s.target_wind_angle_deg = -s.target_wind_angle_deg
            else:
                base = s.target_heading_deg if s.target_heading_deg is not None else current_heading_deg
                s.target_heading_deg = _norm360(2 * twd_deg - base)
                s.mode = "auto"
                s.engaged = True
        # unknown action → ignored

    def _ensure_target(self, current_heading_deg: float, twd_deg: float) -> None:
        s = self.state
        if s.mode == "auto" and s.target_heading_deg is None:
            s.target_heading_deg = _norm360(current_heading_deg)
        if s.mode == "wind" and s.target_wind_angle_deg is None:
            s.target_wind_angle_deg = _norm180(twd_deg - current_heading_deg)

    def effective_heading(self, *, route_heading_deg: float,
                          current_heading_deg: float, twd_deg: float) -> float:
        s = self.state
        if not s.engaged or s.mode == "standby":
            return current_heading_deg
        if s.mode == "route":
            return route_heading_deg
        if s.mode == "auto":
            return s.target_heading_deg if s.target_heading_deg is not None else current_heading_deg
        if s.mode == "wind":
            twa = s.target_wind_angle_deg if s.target_wind_angle_deg is not None else 0.0
            return _norm360(twd_deg - twa)
        return route_heading_deg

    def update_rudder(self, prev_hdg_deg: float, new_hdg_deg: float) -> None:
        err = _norm180(new_hdg_deg - prev_hdg_deg)
        if abs(err) > 0.1:
            self.state.rudder_deg = max(-self.MAX_RUDDER_DEG,
                                        min(self.MAX_RUDDER_DEG, err * self.RUDDER_GAIN))
        else:
            self.state.rudder_deg *= self.RUDDER_DECAY
