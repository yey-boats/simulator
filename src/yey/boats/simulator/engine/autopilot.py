# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# signalk/sim/modules/autopilot.py
"""Pure-logic autopilot controller for the boat simulator.

Decides the heading the boat should steer this tick based on engaged/mode/target
state, and tracks a believable rudder angle. No I/O — the sim wires it into
Navigator.tick and publishes steering.autopilot.* from `state`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MODES = ("standby", "auto", "wind", "route")

# ── Heading-wander / helm-realism tuning ─────────────────────────────────────
# A real vessel holding a course never sits on an exact heading: it yaws a few
# degrees either side of the commanded heading while the helm/autopilot works
# continuously to correct. We model that as a deterministic offset (sum of two
# slow sine components + a tiny higher-frequency ripple) added ON TOP of the
# commanded heading. It is an offset, not a replacement, so real course changes
# (turns, tacks, route legs) still track exactly — the wander just rides along.
#
# Amplitudes are in degrees, periods in seconds. The two primaries sum to a
# slow ±2–4° yaw with a period of several seconds; the ripple adds a little
# texture so the trace never looks like a clean sinusoid. Tune freely.
WANDER_AMP1_DEG    = 2.2      # primary yaw amplitude (deg)
WANDER_PERIOD1_S   = 11.0     # primary yaw period (s)
WANDER_AMP2_DEG    = 1.1      # secondary yaw amplitude (deg)
WANDER_PERIOD2_S   = 4.7      # secondary yaw period (s) — non-harmonic w/ primary
WANDER_RIPPLE_DEG  = 0.35     # fast ripple amplitude (deg)
WANDER_RIPPLE_S    = 1.3      # fast ripple period (s)


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
    # Helm holding-correction gain: rudder applied per degree of residual
    # heading error (commanded vs actually-steered). Keeps a continuous,
    # physically-correlated rudder twitch while holding a course — the rudder
    # leads the yaw it is correcting rather than reading a dead zero.
    HOLD_RUDDER_GAIN = 1.6

    def __init__(self) -> None:
        self.state = AutopilotState()
        # Internal phase clock (seconds) advanced by steer(); drives the
        # deterministic heading wander so the offset is reproducible and
        # test-friendly (no RNG) yet looks organic on screen.
        self._wander_t = 0.0

    def heading_wander_deg(self) -> float:
        """Current deterministic yaw offset (deg) for the helm wander model.

        Sum of two slow, non-harmonic sine components plus a faster ripple.
        Bounded by |AMP1| + |AMP2| + |RIPPLE| (~±3.65° with defaults)."""
        t = self._wander_t
        return (
            WANDER_AMP1_DEG   * math.sin(2 * math.pi * t / WANDER_PERIOD1_S)
            + WANDER_AMP2_DEG * math.sin(2 * math.pi * t / WANDER_PERIOD2_S + 1.0)
            + WANDER_RIPPLE_DEG * math.sin(2 * math.pi * t / WANDER_RIPPLE_S + 2.0)
        )

    def steer(self, commanded_hdg_deg: float, dt_s: float = 1.0) -> float:
        """Advance the wander clock and return the heading the boat actually
        holds this tick: the commanded heading plus the yaw-wander offset.

        `commanded_hdg_deg` is what the route/auto/wind logic wants (the target
        the helm is trying to hold). The returned value wanders a few degrees
        around it; real course changes flow through `commanded_hdg_deg` and are
        preserved exactly (the offset rides on top)."""
        self._wander_t += dt_s
        return _norm360(commanded_hdg_deg + self.heading_wander_deg())

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

    def update_rudder(self, prev_hdg_deg: float, new_hdg_deg: float,
                      commanded_hdg_deg: float | None = None) -> None:
        """Update the believable rudder angle.

        Two coupled effects, both bounded to ±MAX_RUDDER_DEG:

        * Large slew (turns/tacks): the tick-to-tick heading change
          (`new_hdg - prev_hdg`) drives a big proportional rudder kick.
        * Holding correction: while on a steady course the residual error
          between the *commanded* heading and the heading actually being held
          (`actual - commanded`, i.e. the wander the helm is fighting) drives a
          continuous, opposite-sign rudder twitch. This keeps rudder non-zero
          and physically correlated with the heading wander (rudder leads the
          yaw it corrects) instead of decaying to a dead zero.
        """
        slew = _norm180(new_hdg_deg - prev_hdg_deg)
        if abs(slew) > 0.1:
            rudder = slew * self.RUDDER_GAIN
        else:
            rudder = self.state.rudder_deg * self.RUDDER_DECAY
        if commanded_hdg_deg is not None:
            # Helm fights the wander: error = how far off-course we are; apply
            # rudder in the opposite direction to pull the bow back.
            hold_err = _norm180(new_hdg_deg - commanded_hdg_deg)
            rudder += -hold_err * self.HOLD_RUDDER_GAIN
        self.state.rudder_deg = max(-self.MAX_RUDDER_DEG,
                                    min(self.MAX_RUDDER_DEG, rudder))
