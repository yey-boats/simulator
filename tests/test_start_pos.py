# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Tests for the START_LAT/START_LON cold-start override (engine/runner.py)."""
from __future__ import annotations

import pytest  # type: ignore[import]

from yey.boats.simulator.engine.runner import _env_start_pos  # type: ignore[import]


def test_no_env_returns_none(monkeypatch):
    monkeypatch.delenv("START_LAT", raising=False)
    monkeypatch.delenv("START_LON", raising=False)
    assert _env_start_pos() is None  # noqa: S101


def test_both_set_returns_tuple(monkeypatch):
    monkeypatch.setenv("START_LAT", "44.7")
    monkeypatch.setenv("START_LON", "13.1")
    assert _env_start_pos() == pytest.approx((44.7, 13.1))  # noqa: S101


def test_partial_env_returns_none(monkeypatch):
    monkeypatch.setenv("START_LAT", "44.7")
    monkeypatch.delenv("START_LON", raising=False)
    assert _env_start_pos() is None  # noqa: S101


def test_invalid_env_returns_none(monkeypatch):
    monkeypatch.setenv("START_LAT", "not-a-number")
    monkeypatch.setenv("START_LON", "13.1")
    assert _env_start_pos() is None  # noqa: S101
