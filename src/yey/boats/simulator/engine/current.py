"""Modelled tidal current for the Adriatic (NW–SE drift axis).

`tidal_current(now)` is a pure, deterministic function of the UTC datetime.
The phase is derived from `now.timestamp()` so it is consistent with how
other time-based engine models (electrical.solar_elevation_deg, schedule
sailing-window) derive their phases from the injected `now` clock.

Model:
  - Set:   150° ± 30° — Adriatic NW→SE baseline, swinging over a
           compressed cycle.
  - Drift: 0–0.8 kn, half-wave-rectified sine so the trough reaches
           exactly 0.0 kn (exercises the device's calm / zero-ring state)
           and the peak is 0.8 kn.

Both oscillations use a compressed ~8-minute (480 s) period, with a small
phase offset between set and drift so they do not peak simultaneously. The
real Adriatic tide is semi-diurnal (~12 h), but a sim that cycled that
slowly would show a near-constant current within any demo/soak session and
never exercise the device's calm/zero-drift rendering — so the cycle is
time-compressed on purpose.

NOTE: This is the *reported environmental current* (what a tide gauge or
current sensor would emit). It is independent of the navigator's internal
dead-reckoning current (navigator.py CURRENT_KTS / CURRENT_DIR) — those
constants bias the physics; this function models the observable value
published on environment.current.*.
"""
from __future__ import annotations

import math
from datetime import datetime

# Compressed tidal period (8 min) — short enough that the calm/zero-drift
# state is exercised within a demo/soak session (real semi-diurnal is ~12 h).
_TIDAL_PERIOD_S: float = 480.0

# Set: 150° baseline (Adriatic NW→SE), ±30° swing
_SET_BASE_DEG: float = 150.0
_SET_SWING_DEG: float = 30.0

# Drift: peak 0.8 kn, half-wave-rectified so it reaches exactly 0 at trough
_DRIFT_PEAK_KTS: float = 0.8

# Small phase offset (radians) so set and drift peaks are staggered
_DRIFT_PHASE_OFFSET: float = math.pi / 4  # 45° ahead of the set oscillation


def tidal_current(now: datetime) -> tuple[float, float]:
    """Return (set_deg, drift_kts) for the modelled Adriatic tidal current.

    Args:
        now: UTC datetime — the engine's injected clock value.

    Returns:
        set_deg:   current direction the water flows TOWARD, degrees true
                   (150° ± 30°, Adriatic NW→SE drift axis).
        drift_kts: current speed in knots, in [0.0, 0.8].

    The result is fully deterministic: the same `now` always produces the
    same output, so unit tests can assert exact values.
    """
    ts = now.timestamp()
    phase = (2.0 * math.pi * ts) / _TIDAL_PERIOD_S

    # Set oscillates sinusoidally around 150°
    set_deg = _SET_BASE_DEG + _SET_SWING_DEG * math.sin(phase)

    # Drift: half-wave-rectified — peaks at 0.8 kn, dips to exactly 0.0 kn.
    # max(0, sin) gives a half-wave rectified waveform; multiplying by the
    # peak scales it to [0, peak].
    drift_kts = _DRIFT_PEAK_KTS * max(0.0, math.sin(phase + _DRIFT_PHASE_OFFSET))

    return set_deg, drift_kts
