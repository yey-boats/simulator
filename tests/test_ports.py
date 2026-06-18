# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from yey.boats.simulator.ports import TelemetrySink, CommandSource, DataSource  # type: ignore[import]


class _Sink:
    async def open(self): ...
    async def publish(self, snapshot): ...
    async def close(self): ...
    @property
    def name(self): return "x"


def test_sink_protocol_is_structural():
    assert isinstance(_Sink(), TelemetrySink)  # noqa: S101


def test_protocols_exist():
    assert TelemetrySink is not None  # noqa: S101
    assert CommandSource is not None  # noqa: S101
    assert DataSource is not None  # noqa: S101
