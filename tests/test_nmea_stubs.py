import pytest  # type: ignore[import]

from yey.boats.simulator.sinks.nmea0183 import NMEA0183Sink  # type: ignore[import]
from yey.boats.simulator.sinks.nmea2000 import NMEA2000Sink  # type: ignore[import]


@pytest.mark.asyncio
async def test_nmea0183_stub_raises_on_open():
    with pytest.raises(NotImplementedError):  # noqa: S101
        await NMEA0183Sink().open()


@pytest.mark.asyncio
async def test_nmea2000_stub_raises_on_open():
    with pytest.raises(NotImplementedError):  # noqa: S101
        await NMEA2000Sink().open()
