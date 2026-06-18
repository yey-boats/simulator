"""Tests for the tidal-current model (engine/current.py).

Verifies:
  (a) Determinism: same `now` always returns the same (set_deg, drift_kts).
  (b) Set direction stays within 150° ± 35°.
  (c) Drift is bounded [0, ~0.9 kn], reaches near-zero (< 0.05 kn) at some
      phase, and reaches a meaningful peak (> 0.5 kn) at some phase.
"""
from __future__ import annotations

from datetime import datetime, timezone

from yey.boats.simulator.engine.current import tidal_current  # type: ignore[import]

# A fixed reference timestamp for determinism tests
_T0 = datetime(2025, 6, 18, 12, 0, 0, tzinfo=timezone.utc)

# Sample 1440 evenly-spaced "ticks" over one compressed tidal cycle so we sweep
# the full drift oscillation and catch the trough.
_PERIOD_S = 480  # one compressed tidal cycle (8 min) in seconds
_SAMPLES = 1440


def _sweep():
    """Return a list of (set_deg, drift_kts) over one full tidal period."""
    results = []
    t0_ts = _T0.timestamp()
    for i in range(_SAMPLES):
        ts = t0_ts + i * (_PERIOD_S / _SAMPLES)
        now = datetime.fromtimestamp(ts, tz=timezone.utc)
        results.append(tidal_current(now))
    return results


def test_determinism():
    """Same datetime always produces the same (set_deg, drift_kts)."""
    a = tidal_current(_T0)
    b = tidal_current(_T0)
    assert a == b, f"non-deterministic: {a} != {b}"  # noqa: S101


def test_determinism_second_call_different_time():
    """Different datetimes produce different results (not a constant)."""
    t1 = _T0
    # A quarter-period later (120 s) — deliberately NOT an integer multiple of
    # the 480 s period, so the phase genuinely differs.
    t2 = datetime(2025, 6, 18, 12, 2, 0, tzinfo=timezone.utc)
    a = tidal_current(t1)
    b = tidal_current(t2)
    # They should differ (the model actually varies over time)
    assert a != b, "model appears to be constant — phase is not varying"  # noqa: S101


def test_set_within_adriatic_range():
    """Current set stays within 150° ± 35° across one full tidal cycle."""
    for set_deg, _ in _sweep():
        delta = abs(((set_deg - 150.0) + 180) % 360 - 180)  # circular distance
        assert delta <= 35.0, (  # noqa: S101
            f"set_deg={set_deg:.1f}° is outside 150° ± 35°")


def test_drift_bounded():
    """Drift is always in [0, 0.9] kn."""
    for _, drift_kts in _sweep():
        assert 0.0 <= drift_kts <= 0.9, (  # noqa: S101
            f"drift_kts={drift_kts:.4f} outside [0, 0.9]")


def test_drift_reaches_near_zero():
    """Drift actually dips to near-zero (< 0.05 kn) at some point in the cycle."""
    min_drift = min(d for _, d in _sweep())
    assert min_drift < 0.05, (  # noqa: S101
        f"drift never reaches near-zero; min={min_drift:.4f} kn")


def test_drift_reaches_meaningful_peak():
    """Drift reaches a meaningful peak (> 0.5 kn) at some point in the cycle."""
    max_drift = max(d for _, d in _sweep())
    assert max_drift > 0.5, (  # noqa: S101
        f"drift peak is too low; max={max_drift:.4f} kn")
