# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# signalk/sim/modules/weather.py
# ruff: noqa: S311
from __future__ import annotations
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime
import httpx  # type: ignore[import]

MS_TO_KTS = 1.94384


def _lerp(a: float, b: float, α: float) -> float:
    return a + (b - a) * α


def _circular_lerp(a_rad: float, b_rad: float, α: float) -> float:
    """Interpolate between two angles (radians) via unit-vector blend."""
    ux = _lerp(math.cos(a_rad), math.cos(b_rad), α)
    uy = _lerp(math.sin(a_rad), math.sin(b_rad), α)
    return math.atan2(uy, ux)


def _sample_wind(mean_ms: float, gust_ms: float,
                 dir_deg: float) -> tuple[float, float]:
    """Return (tws_kts, twd_deg) sampled from forecast distribution."""
    sigma = max(0.0, (gust_ms - mean_ms) / 3.0)
    tws_ms = max(0.0, random.gauss(mean_ms, sigma))
    twd = random.gauss(dir_deg, 5.0) % 360
    return tws_ms * MS_TO_KTS, twd


@dataclass
class WeatherPoint:
    tws_ms: float
    twd_deg: float
    gust_ms: float
    cloud_cover: float     # 0–1
    wave_height_m: float
    wave_period_s: float
    wave_dir_deg: float
    temp_c: float
    pressure_pa: float
    humidity: float        # 0–1

    @property
    def tws_kts(self) -> float:
        return self.tws_ms * MS_TO_KTS

    def sample(self) -> tuple[float, float]:
        """Return (sampled_tws_kts, sampled_twd_deg)."""
        return _sample_wind(self.tws_ms, self.gust_ms, self.twd_deg)


# Fallback conditions used when the forecast API is unavailable (e.g. open-meteo
# 429 rate-limiting at startup). The sim must keep publishing vessel data rather
# than stall waiting for a first good sample — a light WSW breeze, calm sea.
DEFAULT_WEATHER = WeatherPoint(
    tws_ms=5.0, twd_deg=247.5, gust_ms=7.0, cloud_cover=0.3,
    wave_height_m=0.4, wave_period_s=4.0, wave_dir_deg=247.5,
    temp_c=20.0, pressure_pa=101325.0, humidity=0.6,
)


@dataclass
class _HourlyRow:
    wind_speed_ms: float
    wind_dir_deg: float
    gust_ms: float
    cloud_cover: float
    wave_height_m: float
    wave_period_s: float
    wave_dir_deg: float
    temp_c: float
    pressure_pa: float
    humidity: float


class WeatherFetcher:
    _BACKOFF_S = 60.0

    def __init__(self) -> None:
        self._cache: list[_HourlyRow] | None = None
        self._cache_lat: float = 0.0
        self._cache_lon: float = 0.0
        self._cache_hour: int = -1
        self._retry_after: float = 0.0

    async def get(self, lat: float, lon: float,
                  utc_now: datetime) -> WeatherPoint:
        hour = utc_now.hour
        needs_fetch = (
            self._cache is None
            or self._cache_hour != hour
            or self._cache_lat != lat
            or self._cache_lon != lon
        )
        if needs_fetch:
            if time.monotonic() < self._retry_after:
                # Still in backoff — use stale cache, or the default if we have
                # nothing yet (never stall the sim on a missing forecast).
                if self._cache is None:
                    return DEFAULT_WEATHER
            else:
                try:
                    self._cache = await _fetch_hourly(lat, lon)
                    self._cache_hour = hour
                    self._cache_lat = lat
                    self._cache_lon = lon
                except Exception:
                    self._retry_after = time.monotonic() + self._BACKOFF_S
                    if self._cache is None:
                        return DEFAULT_WEATHER
        assert self._cache is not None  # noqa: S101
        return _interpolate(self._cache, utc_now)

    async def mean_tws_next_6h(self, lat: float, lon: float,
                                utc_now: datetime) -> float:
        """Return mean TWS (kts) over next 6 forecast hours."""
        await self.get(lat, lon, utc_now)
        if self._cache is None:  # forecast unavailable — fall back to default
            return DEFAULT_WEATHER.tws_kts
        rows = self._cache
        start = utc_now.hour
        window = rows[start:start + 6] or rows[-6:]
        return sum(r.wind_speed_ms for r in window) / len(window) * MS_TO_KTS

    async def twd_shift_next_6h(self, lat: float, lon: float,
                                 utc_now: datetime) -> float:
        """Return max TWD shift (degrees) over next 6 forecast hours."""
        await self.get(lat, lon, utc_now)
        if self._cache is None:  # forecast unavailable — no known shift
            return 0.0
        rows = self._cache
        start = utc_now.hour
        window = rows[start:start + 6] or rows[-6:]
        dirs = [r.wind_dir_deg for r in window]
        if not dirs:
            return 0.0
        base = dirs[0]
        return max(abs(((d - base + 180) % 360) - 180) for d in dirs)


def _interpolate(rows: list[_HourlyRow], utc_now: datetime) -> WeatherPoint:
    h = utc_now.hour
    α = (utc_now.minute * 60 + utc_now.second) / 3600
    a = rows[h % len(rows)]
    b = rows[(h + 1) % len(rows)]
    dir_rad = _circular_lerp(math.radians(a.wind_dir_deg),
                              math.radians(b.wind_dir_deg), α)
    wave_dir_rad = _circular_lerp(math.radians(a.wave_dir_deg),
                                   math.radians(b.wave_dir_deg), α)
    return WeatherPoint(
        tws_ms=_lerp(a.wind_speed_ms, b.wind_speed_ms, α),
        twd_deg=math.degrees(dir_rad) % 360,
        gust_ms=_lerp(a.gust_ms, b.gust_ms, α),
        cloud_cover=_lerp(a.cloud_cover, b.cloud_cover, α),
        wave_height_m=_lerp(a.wave_height_m, b.wave_height_m, α),
        wave_period_s=_lerp(a.wave_period_s, b.wave_period_s, α),
        wave_dir_deg=math.degrees(wave_dir_rad) % 360,
        temp_c=_lerp(a.temp_c, b.temp_c, α),
        pressure_pa=_lerp(a.pressure_pa, b.pressure_pa, α),
        humidity=_lerp(a.humidity, b.humidity, α),
    )


async def _fetch_hourly(lat: float, lon: float) -> list[_HourlyRow]:
    async with httpx.AsyncClient(timeout=15) as client:
        atm = (await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": round(lat, 3), "longitude": round(lon, 3),
                "hourly": ",".join(["wind_speed_10m", "wind_direction_10m",
                                    "wind_gusts_10m", "cloudcover",
                                    "temperature_2m", "relative_humidity_2m",
                                    "surface_pressure"]),
                "models": "icon_eu", "forecast_days": 1,
            }
        )).raise_for_status().json()
        mar = (await client.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": round(lat, 3), "longitude": round(lon, 3),
                "hourly": "wave_height,wave_direction,wave_period",
                "models": "icon_eu",
                "forecast_days": 1,
            }
        )).raise_for_status().json()

    n = len(atm["hourly"]["wind_speed_10m"])
    rows = []
    for i in range(n):
        rows.append(_HourlyRow(
            wind_speed_ms=atm["hourly"]["wind_speed_10m"][i],
            wind_dir_deg=atm["hourly"]["wind_direction_10m"][i],
            gust_ms=atm["hourly"]["wind_gusts_10m"][i],
            cloud_cover=(atm["hourly"]["cloudcover"][i] or 0) / 100,
            wave_height_m=mar["hourly"]["wave_height"][i] or 0,
            wave_period_s=mar["hourly"]["wave_period"][i] or 6,
            wave_dir_deg=mar["hourly"]["wave_direction"][i] or 0,
            temp_c=atm["hourly"]["temperature_2m"][i],
            pressure_pa=(atm["hourly"]["surface_pressure"][i] or 1013.25) * 100,
            humidity=(atm["hourly"]["relative_humidity_2m"][i] or 70) / 100,
        ))
    return rows
