# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# signalk/sim/modules/polars.py
from __future__ import annotations
import csv
import math
import pathlib
import numpy as np  # type: ignore[import]


class Polars:
    def __init__(self, tws_values: np.ndarray, twa_values: np.ndarray,
                 speeds: np.ndarray) -> None:
        self._tws_values = tws_values    # shape (n_tws,)
        self._twa_values = twa_values    # shape (n_twa,), degrees 0-180
        self._speeds = speeds            # shape (n_tws, n_twa), knots

    @classmethod
    def load(cls, csv_path: pathlib.Path) -> Polars:
        tws_list, twa_values, rows = [], None, []
        with open(csv_path) as f:
            reader = csv.reader(f)
            header = next(reader)
            twa_values = np.array([float(h) for h in header[1:]])
            for row in reader:
                tws_list.append(float(row[0]))
                rows.append([float(v) for v in row[1:]])
        return cls(np.array(tws_list), twa_values, np.array(rows))

    def boat_speed(self, tws_kts: float, twa_deg: float) -> float:
        """Bilinear interpolation. twa_deg may be negative (port tack)."""
        twa = abs(twa_deg) % 180
        tws = max(0.0, tws_kts)
        # clamp
        twa = float(np.clip(twa, self._twa_values[0], self._twa_values[-1]))
        tws = float(np.clip(tws, self._tws_values[0], self._tws_values[-1]))

        # find bracketing indices
        i_twa = int(np.clip(
            np.searchsorted(self._twa_values, twa, side="right") - 1,
            0, len(self._twa_values) - 2))
        i_tws = int(np.clip(
            np.searchsorted(self._tws_values, tws, side="right") - 1,
            0, len(self._tws_values) - 2))

        # fractions
        α_twa = ((twa - self._twa_values[i_twa]) /
                 (self._twa_values[i_twa + 1] - self._twa_values[i_twa] + 1e-9))
        α_tws = ((tws - self._tws_values[i_tws]) /
                 (self._tws_values[i_tws + 1] - self._tws_values[i_tws] + 1e-9))

        s00 = self._speeds[i_tws,     i_twa]
        s01 = self._speeds[i_tws,     i_twa + 1]
        s10 = self._speeds[i_tws + 1, i_twa]
        s11 = self._speeds[i_tws + 1, i_twa + 1]
        return float(s00 * (1 - α_twa) * (1 - α_tws) +
                      s01 * α_twa       * (1 - α_tws) +
                      s10 * (1 - α_twa) * α_tws +
                      s11 * α_twa       * α_tws)

    def best_vmg_upwind_twa(self, tws_kts: float) -> float:
        """TWA (degrees) giving max VMG toward wind (upwind)."""
        candidates = self._twa_values[self._twa_values <= 90]
        vmgs = [self.boat_speed(tws_kts, t) * math.cos(math.radians(t))
                for t in candidates]
        return float(candidates[int(np.argmax(vmgs))])

    def best_vmg_downwind_twa(self, tws_kts: float) -> float:
        """TWA (degrees) giving max VMG away from wind (downwind)."""
        candidates = self._twa_values[self._twa_values >= 90]
        vmgs = [self.boat_speed(tws_kts, t) * math.cos(math.radians(180 - t))
                for t in candidates]
        return float(candidates[int(np.argmax(vmgs))])

    # ── Performance helpers (used by the SignalK writer's performance.* emit) ──
    def polar_speed(self, tws_kts: float, twa_deg: float) -> float:
        """Alias for boat_speed: expected polar boat speed (knots) at the given
        true wind speed/angle. Provided as a clearly named helper for the
        performance.polarSpeed SignalK path."""
        return self.boat_speed(tws_kts, twa_deg)

    def beat_gybe_angles(self, tws_kts: float) -> tuple[float, float]:
        """VMG-optimal upwind (beat) and downwind (gybe) TWAs in DEGREES for the
        given true wind speed. Returns (beat_deg, gybe_deg)."""
        return (self.best_vmg_upwind_twa(tws_kts),
                self.best_vmg_downwind_twa(tws_kts))
