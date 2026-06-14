from yey.boats.simulator.config import Settings  # type: ignore[import]
from yey.boats.simulator.engine.runner import build_data_source  # type: ignore[import]
from yey.boats.simulator.sources.open_meteo import OpenMeteoDataSource  # type: ignore[import]
from yey.boats.simulator.sources.signalk_weather import SignalKDataSource  # type: ignore[import]


def test_build_data_source_openmeteo():
    s = Settings(weather_source="openmeteo")
    assert isinstance(build_data_source(s), OpenMeteoDataSource)  # noqa: S101


def test_build_data_source_signalk():
    s = Settings(weather_source="signalk", signalk_host="h", signalk_port=3001)
    ds = build_data_source(s)
    assert isinstance(ds, SignalKDataSource)  # noqa: S101
