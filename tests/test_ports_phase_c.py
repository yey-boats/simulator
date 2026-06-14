from yey.boats.simulator.ports import DataSource, AISSource  # type: ignore[import]


class _DS:
    async def get_weather(self, lat, lon, now): ...
    async def twd_shift_next_6h(self, lat, lon, now): ...
    async def mean_tws_next_6h(self, lat, lon, now): ...


class _AIS:
    async def start(self): ...
    def get_contacts(self, lat, lon): return []


def test_datasource_structural():
    assert isinstance(_DS(), DataSource)  # noqa: S101


def test_aissource_structural():
    assert isinstance(_AIS(), AISSource)  # noqa: S101
