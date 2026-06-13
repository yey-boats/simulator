"""Canonical per-tick telemetry frame consumed by every sink.

The engine builds one of these each tick; sinks translate it to their wire
format. Fields mirror the arguments SignalKWriter.send_vessel_delta needs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class TelemetrySnapshot:
    nav: Any              # NavState
    elec: Any             # ElecState
    sys: Any              # SystemsState
    lights: Any           # LightsState
    wx: Any               # WeatherPoint
    state: Any            # SimState
    utc_now: datetime
    temps: dict
    next_wp: tuple[str, float, float] | None
    route_href: str
    point_index: int
    polars: Any = None
    autopilot: Any = None
    distance_to_next_nm: float = 0.0
