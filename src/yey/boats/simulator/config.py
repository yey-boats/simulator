"""Single source of truth for runtime configuration.

Precedence: explicit kwargs (CLI) > environment > defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_DATA_DIR = Path(os.environ.get("DATA_DIR", "./run-data")).resolve()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


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

    @classmethod
    def from_env(cls, **overrides: object) -> Settings:
        base = cls(
            signalk_host=_env("SIGNALK_HOST", "localhost"),
            signalk_port=int(_env("SIGNALK_PORT", "3000")),
            signalk_username=_env("SIGNALK_USERNAME", "admin"),
            signalk_password=_env("SIGNALK_PASSWORD", "admin"),
            aisstream_api_key=_env("AISSTREAM_API_KEY", "").strip(),
            sink=_env("SINK", "signalk"),
            weather_source=_env("WEATHER_SOURCE", "openmeteo"),
            failover=_env("SINK_FAILOVER", "1") not in ("0", "false", "False"),
            data_dir=Path(_env("DATA_DIR", "./run-data")).resolve(),
        )
        for k, v in overrides.items():
            if v is not None:
                setattr(base, k, v)
        return base
