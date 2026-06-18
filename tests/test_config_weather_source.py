# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from yey.boats.simulator.config import Settings  # type: ignore[import]


def test_weather_source_default(monkeypatch):
    monkeypatch.delenv("WEATHER_SOURCE", raising=False)
    assert Settings.from_env().weather_source == "openmeteo"  # noqa: S101


def test_weather_source_env(monkeypatch):
    monkeypatch.setenv("WEATHER_SOURCE", "signalk")
    assert Settings.from_env().weather_source == "signalk"  # noqa: S101
