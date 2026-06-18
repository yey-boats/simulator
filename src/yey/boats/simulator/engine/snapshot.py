"""Canonical per-tick telemetry frame consumed by every sink.

The engine builds one of these each tick; sinks translate it to their wire
format. Fields mirror the arguments SignalKWriter.send_vessel_delta needs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AisContact:
    mmsi: str
    lat: float
    lon: float
    cog_deg: float
    sog_kts: float
    name: str
    ship_type: int


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
    ais_contacts: list[AisContact] = field(default_factory=list)
    current_set_deg: float = 0.0    # modelled current direction (degrees true, toward)
    current_drift_kts: float = 0.0  # modelled current speed (knots)
