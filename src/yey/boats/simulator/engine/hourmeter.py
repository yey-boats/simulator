# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Persisted engine-hour meter.

Accumulates engine-on seconds across ticks AND restarts, so
`propulsion.main.runTime` is monotonic over the boat's life (engine-hours are a
maintenance/anomaly signal — they must not reset when the sim restarts). The
count is flushed to a small JSON in DATA_DIR periodically and on demand; all I/O
is best-effort (a read/write failure degrades to in-memory only, never raises).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class HourMeter:
    def __init__(self, path: Optional[Path], flush_every_s: float = 60.0) -> None:
        self._path = Path(path) if path is not None else None
        self._flush_every_s = flush_every_s
        self._total_s = self._load()
        self._since_flush_s = 0.0

    def _load(self) -> float:
        if self._path is None:
            return 0.0
        try:
            return float(json.loads(self._path.read_text()).get("engine_run_s", 0.0))
        except (OSError, ValueError, TypeError):
            return 0.0

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"engine_run_s": round(self._total_s, 1)}))
        except OSError:
            pass  # best-effort persistence

    def tick(self, running: bool, dt_s: float = 1.0) -> float:
        """Advance by `dt_s` if the engine is running; return cumulative seconds."""
        if running and dt_s > 0:
            self._total_s += dt_s
            self._since_flush_s += dt_s
            if self._since_flush_s >= self._flush_every_s:
                self._save()
                self._since_flush_s = 0.0
        return self._total_s

    @property
    def total_s(self) -> float:
        return self._total_s
