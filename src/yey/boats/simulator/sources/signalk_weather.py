# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# ruff: noqa: BLE001
"""DataSource backed by a SignalK server's live environment readings.

Use case: drive the sim's physics from a real boat's instrument data. SignalK
serves SI units (m/s, radians, kelvin) and has no forecast, so the 6 h lookahead
methods return neutral values. All reads degrade to DEFAULT_WEATHER/neutral and
never raise into the engine.
"""
from __future__ import annotations

import math
from typing import Any

import httpx  # type: ignore[import]

from yey.boats.simulator.engine.weather import DEFAULT_WEATHER, WeatherPoint  # type: ignore[import]

_MS_TO_KTS = 1.94384


class SignalKDataSource:
    def __init__(self, host: str = "localhost", port: int = 3000) -> None:
        self._host = host
        self._port = port

    async def _read_path(self, path: str) -> Any:
        """Read a single SignalK self value (SI units), or None on absence/error."""
        dotted = path.replace(".", "/")
        url = f"http://{self._host}:{self._port}/signalk/v1/api/vessels/self/{dotted}"
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=6)
            r.raise_for_status()
            data = r.json()
        if isinstance(data, dict):
            return data.get("value", data)
        return data

    async def _current_tws_kts(self) -> float:
        ms = await self._read_path("environment.wind.speedTrue")
        return float(ms) * _MS_TO_KTS if ms is not None else DEFAULT_WEATHER.sample()[0]

    async def get_weather(self, lat: float, lon: float, now: Any) -> WeatherPoint:
        try:
            speed = await self._read_path("environment.wind.speedTrue")
            direction = await self._read_path("environment.wind.directionTrue")
            temp_k = await self._read_path("environment.outside.temperature")
        except Exception:
            return DEFAULT_WEATHER
        tws_ms = float(speed) if speed is not None else DEFAULT_WEATHER.tws_ms
        twd_deg = math.degrees(float(direction)) % 360 if direction is not None else DEFAULT_WEATHER.twd_deg
        temp_c = (float(temp_k) - 273.15) if temp_k is not None else DEFAULT_WEATHER.temp_c
        # gust_ms == tws_ms keeps sigma=0 in sample(), making it deterministic
        # (no forecast data from SignalK means no gust spread to model)
        return WeatherPoint(
            tws_ms=tws_ms,
            twd_deg=twd_deg,
            gust_ms=tws_ms,
            cloud_cover=DEFAULT_WEATHER.cloud_cover,
            wave_height_m=DEFAULT_WEATHER.wave_height_m,
            wave_period_s=DEFAULT_WEATHER.wave_period_s,
            wave_dir_deg=twd_deg,
            temp_c=temp_c,
            pressure_pa=DEFAULT_WEATHER.pressure_pa,
            humidity=DEFAULT_WEATHER.humidity,
        )

    async def twd_shift_next_6h(self, lat: float, lon: float, now: Any) -> float:
        return 0.0  # no forecast from SignalK

    async def mean_tws_next_6h(self, lat: float, lon: float, now: Any) -> float:
        try:
            return await self._current_tws_kts()
        except Exception:
            return DEFAULT_WEATHER.sample()[0]
