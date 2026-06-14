"""DataSource backed by Open-Meteo (wraps the existing WeatherFetcher)."""
from __future__ import annotations

from typing import Any

from yey.boats.simulator.engine.weather import WeatherFetcher  # type: ignore[import]


class OpenMeteoDataSource:
    def __init__(self, fetcher: Any = None) -> None:
        self._fetcher = fetcher if fetcher is not None else WeatherFetcher()

    async def get_weather(self, lat: float, lon: float, now: Any) -> Any:
        return await self._fetcher.get(lat, lon, now)

    async def twd_shift_next_6h(self, lat: float, lon: float, now: Any) -> float:
        return await self._fetcher.twd_shift_next_6h(lat, lon, now)

    async def mean_tws_next_6h(self, lat: float, lon: float, now: Any) -> float:
        return await self._fetcher.mean_tws_next_6h(lat, lon, now)
