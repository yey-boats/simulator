import pytest  # type: ignore[import]

from yey.boats.simulator.sources.signalk_weather import SignalKDataSource  # type: ignore[import]


@pytest.mark.asyncio
async def test_builds_weatherpoint_from_sk_env(monkeypatch):
    src = SignalKDataSource(host="h", port=3000)

    async def fake_read(path):  # SI units as SignalK serves them
        return {
            "environment.wind.speedTrue": 5.0,          # m/s
            "environment.wind.directionTrue": 3.665,     # rad (~210 deg)
            "environment.outside.temperature": 291.15,   # K (=18 C)
        }.get(path)

    monkeypatch.setattr(src, "_read_path", fake_read)
    wx = await src.get_weather(45.0, 13.0, "now")
    # Use stored fields to avoid random noise from sample(); proves SK values flow in
    assert round(wx.tws_kts, 1) == round(5.0 * 1.94384, 1)  # noqa: S101  m/s -> kts
    assert round(wx.twd_deg) == 210  # noqa: S101
    assert round(wx.temp_c) == 18  # noqa: S101


@pytest.mark.asyncio
async def test_forecasts_are_neutral(monkeypatch):
    src = SignalKDataSource(host="h", port=3000)

    async def fake_read(path):
        return 6.0 if path == "environment.wind.speedTrue" else None

    monkeypatch.setattr(src, "_read_path", fake_read)
    assert await src.twd_shift_next_6h(45.0, 13.0, "now") == 0.0  # noqa: S101
    mean = await src.mean_tws_next_6h(45.0, 13.0, "now")
    assert round(mean, 1) == round(6.0 * 1.94384, 1)  # noqa: S101  current TWS in kts


@pytest.mark.asyncio
async def test_degrades_on_read_failure(monkeypatch):
    src = SignalKDataSource(host="h", port=3000)

    async def boom(path):
        raise RuntimeError("sk down")

    monkeypatch.setattr(src, "_read_path", boom)
    wx = await src.get_weather(45.0, 13.0, "now")  # must not raise
    assert wx is not None  # noqa: S101
