# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from __future__ import annotations

from yey.boats.simulator.engine.navigator import Navigator  # type: ignore[import]
from yey.boats.simulator.engine.schedule import Schedule  # type: ignore[import]


class _FakeGrid:
    def depth_at(self, lat, lon):
        return 123.0


def test_navigator_reads_depth_from_grid():
    nav = Navigator(polars=None, schedule=Schedule(), grid=_FakeGrid())
    assert nav._depth_at(45.0, 13.0) == 123.0
