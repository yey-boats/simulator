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


# ── SIM-5: default admin/admin credentials against a non-localhost host ─────

def test_warns_on_default_password_against_non_localhost_host(capsys):
    s = Settings(signalk_host="lab-server.example.com", signalk_password="admin")  # noqa: S106
    s.warn_if_insecure_credentials()
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "SIGNALK_PASSWORD" in err


def test_no_warning_on_localhost_with_default_password(capsys):
    s = Settings(signalk_host="localhost", signalk_password="admin")  # noqa: S106
    s.warn_if_insecure_credentials()
    assert capsys.readouterr().err == ""


def test_no_warning_on_non_localhost_with_custom_password(capsys):
    s = Settings(signalk_host="lab-server.example.com", signalk_password="s3cr3t")  # noqa: S106
    s.warn_if_insecure_credentials()
    assert capsys.readouterr().err == ""


def test_from_env_warns_for_non_localhost_default_creds(monkeypatch, capsys):
    monkeypatch.setenv("SIGNALK_HOST", "lab-server.example.com")
    monkeypatch.delenv("SIGNALK_PASSWORD", raising=False)
    Settings.from_env()
    err = capsys.readouterr().err
    assert "WARNING" in err
