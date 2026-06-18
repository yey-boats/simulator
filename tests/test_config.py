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
