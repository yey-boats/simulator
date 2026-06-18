# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
import pytest  # type: ignore[import]

from yey.boats.simulator.sources.open_meteo import OpenMeteoDataSource  # type: ignore[import]


class FakeFetcher:
    async def get(self, lat, lon, now): return ("wx", lat, lon)
    async def twd_shift_next_6h(self, lat, lon, now): return 12.0
    async def mean_tws_next_6h(self, lat, lon, now): return 9.0


@pytest.mark.asyncio
async def test_forwards_to_fetcher():
    src = OpenMeteoDataSource(fetcher=FakeFetcher())
    assert await src.get_weather(45.0, 13.0, "now") == ("wx", 45.0, 13.0)  # noqa: S101
    assert await src.twd_shift_next_6h(45.0, 13.0, "now") == 12.0  # noqa: S101
    assert await src.mean_tws_next_6h(45.0, 13.0, "now") == 9.0  # noqa: S101
