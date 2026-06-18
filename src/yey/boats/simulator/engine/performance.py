# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-License-Identifier: MIT
# signalk/sim/modules/performance.py
"""Sim realism: a helm/sea-state efficiency factor applied to polar boat speed
so published STW (and thus performance.polarSpeedRatio) sits realistically
below 1.0 in a seaway instead of pinned at the polar."""
from __future__ import annotations


def polar_efficiency(wave_height_m: float, tws_kts: float) -> float:
    """Return a factor in [0.6, 1.0]. Flat water -> 1.0; bigger waves -> lower.

    A pure function (no I/O). Sea state is the dominant realism lever here: a
    seaway slows the boat below the flat-water polar (pitching, slamming, helm
    corrections), so the published polarSpeedRatio lands realistically <1.0.
    ~0.12 loss per metre of significant wave height (~0.3 loss at 2.5 m),
    clamped so the boat never drops below 60% of polar."""
    penalty = 0.12 * max(0.0, wave_height_m)
    eff = 1.0 - penalty
    return max(0.6, min(1.0, eff))
