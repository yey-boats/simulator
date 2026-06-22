# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
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
    prev_wp: tuple[str, float, float] | None = None  # active leg origin (route.current)
    distance_to_next_nm: float = 0.0
    ais_contacts: list[AisContact] = field(default_factory=list)
    current_set_deg: float = 0.0    # modelled current direction (degrees true, toward)
    current_drift_kts: float = 0.0  # modelled current speed (knots)
    engine_run_s: float = 0.0       # cumulative engine-on seconds (HourMeter; -> propulsion.main.runTime)
    # ── Phase-3 diagnostic signals (None => path omitted, like engine_run_s) ──
    oil_pressure_pa: float | None = None          # propulsion.main.oilPressure (Pa)
    exhaust_temp_k: float | None = None           # propulsion.main.exhaustTemperature (K)
    starter_voltage: float | None = None          # electrical.batteries.starter.voltage (V)
    starter_soc: float | None = None              # electrical.batteries.starter.stateOfCharge (ratio)
    starter_current_a: float | None = None        # electrical.batteries.starter.current (A)
    gnss_satellites: int | None = None            # navigation.gnss.satellites (count)
    gnss_hdop: float | None = None                # navigation.gnss.horizontalDilution
    gnss_quality: str | None = None               # navigation.gnss.methodQuality
    gnss_antenna_altitude_m: float | None = None  # navigation.gnss.antennaAltitude (m)
    gnss_position_jitter_deg: tuple[float, float] | None = None  # (lat,lon) jitter applied to published position
    rate_of_turn_rad_s: float | None = None       # navigation.rateOfTurn (rad/s)
