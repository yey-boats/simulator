# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Tests for the persisted engine-hour meter (engine/hourmeter.py)."""
from __future__ import annotations

from yey.boats.simulator.engine.hourmeter import HourMeter  # type: ignore[import]


def test_accumulates_only_while_running():
    m = HourMeter(path=None)
    assert m.tick(running=True, dt_s=1.0) == 1.0  # noqa: S101
    assert m.tick(running=False, dt_s=1.0) == 1.0  # stopped -> no change  # noqa: S101
    assert m.tick(running=True, dt_s=2.0) == 3.0  # noqa: S101
    assert m.total_s == 3.0  # noqa: S101


def test_persists_and_reloads(tmp_path):
    p = tmp_path / "engine_runtime.json"
    m = HourMeter(path=p, flush_every_s=1.0)
    for _ in range(5):
        m.tick(running=True, dt_s=1.0)  # 5 s, flushes (>= flush_every_s)
    assert p.exists()  # noqa: S101
    # A fresh meter on the same path resumes from the persisted total (monotonic).
    m2 = HourMeter(path=p)
    assert m2.total_s == 5.0  # noqa: S101


def test_missing_or_bad_cache_starts_at_zero(tmp_path):
    assert HourMeter(path=tmp_path / "nope.json").total_s == 0.0  # noqa: S101
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert HourMeter(path=bad).total_s == 0.0  # noqa: S101
