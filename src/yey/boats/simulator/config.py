# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Single source of truth for runtime configuration.

Precedence (low -> high): defaults < file < env < cli(overrides).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_DATA_DIR = Path(os.environ.get("DATA_DIR", "./run-data")).resolve()


@dataclass
class Settings:
    signalk_host: str = "localhost"
    signalk_port: int = 3000
    signalk_username: str = "admin"
    signalk_password: str = "admin"  # noqa: S105
    aisstream_api_key: str = ""
    sink: str = "signalk"          # one of: signalk, stdout, nmea0183, nmea2000
    weather_source: str = "openmeteo"  # openmeteo | signalk
    failover: bool = True
    data_dir: Path = field(default_factory=lambda: _DEFAULT_DATA_DIR)

    _PERSIST_KEYS = ("signalk_host", "signalk_port", "signalk_username",
                     "signalk_password", "aisstream_api_key", "sink",
                     "weather_source", "failover", "data_dir")

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self._PERSIST_KEYS}
        d["data_dir"] = str(self.data_dir)
        return d

    def save(self, path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def from_file(cls, path) -> "Settings":
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text())
        if "data_dir" in raw:
            raw["data_dir"] = Path(raw["data_dir"]).resolve()
        known = {k: raw[k] for k in cls._PERSIST_KEYS if k in raw}
        return cls(**known)

    @classmethod
    def from_env(cls, *, config_path=None, **overrides: object) -> "Settings":
        # precedence (low -> high): defaults < file < env < cli(overrides)
        base = cls.from_file(config_path) if config_path is not None else cls()
        env_map = {
            "signalk_host": os.environ.get("SIGNALK_HOST"),
            "signalk_port": (int(os.environ["SIGNALK_PORT"]) if "SIGNALK_PORT" in os.environ else None),
            "signalk_username": os.environ.get("SIGNALK_USERNAME"),
            "signalk_password": os.environ.get("SIGNALK_PASSWORD"),
            "aisstream_api_key": (os.environ.get("AISSTREAM_API_KEY", "").strip() or None),
            "sink": os.environ.get("SINK"),
            "weather_source": os.environ.get("WEATHER_SOURCE"),
            "failover": (os.environ["SINK_FAILOVER"] not in ("0", "false", "False")
                         if "SINK_FAILOVER" in os.environ else None),
            "data_dir": (Path(os.environ["DATA_DIR"]).resolve() if "DATA_DIR" in os.environ else None),
        }
        for k, v in env_map.items():
            if v is not None:
                setattr(base, k, v)
        for k, v in overrides.items():
            if v is not None and hasattr(base, k):
                setattr(base, k, v)
        return base
