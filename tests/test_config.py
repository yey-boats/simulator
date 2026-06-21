# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from pathlib import Path

from yey.boats.simulator.config import Settings


def test_defaults(monkeypatch):
    for k in ("SIGNALK_HOST", "SIGNALK_PORT", "SIGNALK_USERNAME",
              "SIGNALK_PASSWORD", "AISSTREAM_API_KEY", "SINK", "DATA_DIR"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.signalk_host == "localhost"  # noqa: S101
    assert s.signalk_port == 3000  # noqa: S101
    assert s.signalk_username == "admin"  # noqa: S101
    assert s.sink == "signalk"  # noqa: S101
    assert s.failover is True  # noqa: S101
    assert s.aisstream_api_key == ""  # noqa: S101
    assert isinstance(s.data_dir, Path)  # noqa: S101


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("SIGNALK_HOST", "signalk-server")
    monkeypatch.setenv("SIGNALK_PORT", "3001")
    monkeypatch.setenv("SINK", "stdout")
    s = Settings.from_env()
    assert s.signalk_host == "signalk-server"  # noqa: S101
    assert s.signalk_port == 3001  # noqa: S101
    assert s.sink == "stdout"  # noqa: S101


def test_explicit_overrides_env(monkeypatch):
    monkeypatch.setenv("SINK", "signalk")
    s = Settings.from_env(sink="stdout")
    assert s.sink == "stdout"  # noqa: S101


def test_settings_has_boat_geometry_defaults():
    from yey.boats.simulator.config import Settings  # type: ignore[import]
    s = Settings()
    assert s.boat_draft_m == 2.2
    assert s.transducer_depth_m == 0.6


def test_boat_geometry_single_source():
    """The SignalK writer's depth constants come from config (no duplication)."""
    from yey.boats.simulator import config
    from yey.boats.simulator.engine import signalk_writer
    assert signalk_writer.DRAFT_M == config.DEFAULT_BOAT_DRAFT_M
    assert signalk_writer.TRANSDUCER_DEPTH_M == config.DEFAULT_TRANSDUCER_DEPTH_M
