# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
import json
from pathlib import Path

from yey.boats.simulator.config import Settings


def test_save_and_load_roundtrip(tmp_path: Path):
    s = Settings(signalk_host="boat.local", signalk_port=3001,
                 aisstream_api_key="KEY123", sink="stdout")
    p = tmp_path / "config.json"
    s.save(p)
    loaded = Settings.from_file(p)
    assert loaded.signalk_host == "boat.local"
    assert loaded.signalk_port == 3001
    assert loaded.aisstream_api_key == "KEY123"
    assert loaded.sink == "stdout"


def test_from_file_missing_returns_defaults(tmp_path: Path):
    s = Settings.from_file(tmp_path / "nope.json")
    assert s.signalk_host == "localhost"
    assert s.signalk_port == 3000


def test_precedence_cli_over_env_over_file(tmp_path: Path, monkeypatch):
    p = tmp_path / "config.json"
    Settings(signalk_host="from-file", signalk_port=3002).save(p)
    monkeypatch.setenv("SIGNALK_HOST", "from-env")
    # file provides port 3002; env overrides host; cli override wins for username
    s = Settings.from_env(config_path=p,
                          **{"signalk_username": "from-cli"})
    assert s.signalk_host == "from-env"      # env beats file
    assert s.signalk_port == 3002            # file beats default
    assert s.signalk_username == "from-cli"  # cli beats all


def test_save_is_json_with_known_keys(tmp_path: Path):
    p = tmp_path / "config.json"
    Settings().save(p)
    data = json.loads(p.read_text())
    assert set(data) >= {"signalk_host", "signalk_port", "signalk_username",
                         "signalk_password", "aisstream_api_key", "sink",
                         "weather_source", "failover", "data_dir"}
