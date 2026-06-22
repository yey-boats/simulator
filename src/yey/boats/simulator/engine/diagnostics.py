# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Phase-3 diagnostic-signal models with fault-injection hooks.

Small, physically-plausible steady-state models for signals that don't exist in
the core engine state but are needed so downstream diagnostics can detect
anomalies. Each model takes a fault severity (0..1, from ``FaultState``) so a
demo can inject the exact deviation the diagnostic is meant to catch.

Outputs are SI (Pa, V, A, ratio) so the SignalK writer emits them directly.
Models are deterministic given their inputs except for small bounded noise, for
which a per-instance ``random.Random`` is used (seedable for tests).
"""
from __future__ import annotations

import math
import random


# ── Oil pressure ─────────────────────────────────────────────────────────────
# Volvo D4-55: ~0 stopped, ~250 kPa at idle, ~450 kPa at cruise. f(rpm).
OIL_P_IDLE_PA   = 250_000.0
OIL_P_CRUISE_PA = 450_000.0
OIL_P_NOISE_PA  = 6_000.0


def oil_pressure_pa(rpm_frac: float, engine_on: bool,
                    fault_severity: float = 0.0,
                    rng: random.Random | None = None) -> float:
    """Engine oil pressure (Pa). ``rpm_frac`` is 0..1 engine load fraction.

    ``fault_severity`` (``low_oil_pressure``) scales the pressure DOWN toward
    near-zero — a full-severity fault drops it into alarm territory.
    """
    if not engine_on:
        return 0.0
    rpm_frac = max(0.0, min(1.0, rpm_frac))
    base = OIL_P_IDLE_PA + rpm_frac * (OIL_P_CRUISE_PA - OIL_P_IDLE_PA)
    noise = (rng.uniform(-OIL_P_NOISE_PA, OIL_P_NOISE_PA) if rng else 0.0)
    sev = max(0.0, min(1.0, fault_severity))
    # At full severity, drop to ~8% of nominal (well below any low-oil alarm).
    base *= (1.0 - 0.92 * sev)
    return max(0.0, base + noise)


# ── Starter battery (12 V lead-acid cranking bank) ───────────────────────────
STARTER_FLOAT_V   = 12.7    # rested float voltage
STARTER_CHARGE_V  = 14.2    # while the alternator is recharging it
STARTER_CRANK_V   = 9.6     # dip during a healthy crank
STARTER_CRANK_A   = -180.0  # crank draw (negative = discharge), amps
STARTER_RECHARGE_A = 25.0   # alternator top-up current after a start


class StarterBattery:
    """Dedicated engine-cranking bank. Tracks a crank dip on engine start and a
    short alternator recharge afterward. ``weak_starter`` deepens the dip and
    slows the voltage recovery."""

    def __init__(self) -> None:
        self._was_on = False
        self._crank_t = 0.0       # seconds remaining in the crank event
        self._recharge_t = 0.0    # seconds remaining in the recharge phase
        self._soc = 0.95

    def tick(self, dt_s: float, engine_on: bool,
             weak_severity: float = 0.0) -> tuple[float, float, float]:
        """Return (voltage_V, soc_ratio, current_A).

        current sign: negative = discharge (cranking), positive = charging.
        """
        sev = max(0.0, min(1.0, weak_severity))
        started = engine_on and not self._was_on
        stopped = (not engine_on) and self._was_on
        self._was_on = engine_on

        if started:
            # A weak bank cranks longer (slow start).
            self._crank_t = 1.0 + 2.0 * sev
        if stopped:
            self._recharge_t = 0.0

        if self._crank_t > 0.0:
            self._crank_t = max(0.0, self._crank_t - dt_s)
            # Deeper dip with a weak starter.
            dip_v = STARTER_CRANK_V - 2.5 * sev
            crank_a = STARTER_CRANK_A * (1.0 + 0.6 * sev)
            self._soc = max(0.0, self._soc - 0.0005 * dt_s)
            if self._crank_t == 0.0 and engine_on:
                self._recharge_t = 30.0 + 90.0 * sev  # slow recovery when weak
            return dip_v, self._soc, crank_a

        if engine_on and self._recharge_t > 0.0:
            self._recharge_t = max(0.0, self._recharge_t - dt_s)
            self._soc = min(1.0, self._soc + 0.0002 * dt_s)
            # Weak bank accepts charge more slowly -> voltage sits lower.
            v = STARTER_CHARGE_V - 0.8 * sev
            return v, self._soc, STARTER_RECHARGE_A * (1.0 - 0.5 * sev)

        if engine_on:
            # Topped up, floating on the alternator.
            return STARTER_CHARGE_V - 0.3 * sev, self._soc, 1.0

        # Engine off: resting float voltage, a weak bank rests a touch lower.
        return STARTER_FLOAT_V - 0.6 * sev, self._soc, 0.0


# ── GNSS ─────────────────────────────────────────────────────────────────────
GNSS_NOMINAL_SATS = 11
GNSS_NOMINAL_HDOP = 0.9
GNSS_FIX_QUALITY  = "GNSS Fix"
GNSS_NO_FIX       = "no GNSS"
GNSS_ANT_ALT_M    = 2.0     # masthead antenna height above the waterline


class Gnss:
    """GNSS receiver health. Nominal: 8–13 sats, HDOP 0.6–1.5, a valid fix and
    small position noise. ``gps_degraded`` drops sats, raises HDOP, flips the
    method quality to "no GNSS" and adds position jitter (metres)."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def tick(self, degraded_severity: float = 0.0) -> dict:
        """Return a dict with satellites, horizontalDilution, methodQuality,
        antennaAltitude and a (lat_jitter_deg, lon_jitter_deg) position offset.
        """
        sev = max(0.0, min(1.0, degraded_severity))
        # Nominal counts/dilution with light noise.
        sats = round(GNSS_NOMINAL_SATS + self._rng.uniform(-3.0, 2.0))
        hdop = GNSS_NOMINAL_HDOP + self._rng.uniform(-0.3, 0.6)

        if sev > 0.0:
            # Degraded: sats drop toward 3, HDOP climbs, quality lost.
            sats = max(0, round(sats * (1.0 - 0.75 * sev)))
            hdop = hdop + sev * (9.0 + self._rng.uniform(0.0, 4.0))
            quality = GNSS_NO_FIX if sev > 0.5 else GNSS_FIX_QUALITY
            # Position jitter grows with severity: ~ up to ~40 m of wander.
            jit_m = sev * 40.0
        else:
            sats = max(4, sats)
            hdop = max(0.5, hdop)
            quality = GNSS_FIX_QUALITY
            jit_m = 1.5  # nominal receiver noise

        # Convert metre jitter to degrees (1 deg lat ~111 km; lon scaled by cos
        # is unnecessary at this magnitude — caller adds it to a position).
        deg_per_m = 1.0 / 111_000.0
        lat_jit = self._rng.uniform(-jit_m, jit_m) * deg_per_m
        lon_jit = self._rng.uniform(-jit_m, jit_m) * deg_per_m

        return {
            "satellites": int(sats),
            "horizontalDilution": round(hdop, 2),
            "methodQuality": quality,
            "antennaAltitude": GNSS_ANT_ALT_M,
            "position_jitter_deg": (lat_jit, lon_jit),
        }


# ── Rate of turn ──────────────────────────────────────────────────────────────
def rate_of_turn_rad_s(prev_hdg_deg: float, hdg_deg: float,
                       dt_s: float = 1.0) -> float:
    """Rate of turn (rad/s) from a heading delta, normalised to ±180°.
    + = turning to starboard (heading increasing)."""
    if dt_s <= 0.0:
        return 0.0
    delta = (hdg_deg - prev_hdg_deg + 180.0) % 360.0 - 180.0
    return math.radians(delta) / dt_s
