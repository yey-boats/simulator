# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Port interfaces (structural Protocols) for the simulator's I/O boundaries.

- TelemetrySink: output — consumes TelemetrySnapshot, writes a wire format.
- CommandSource: input — feeds engine commands (e.g. autopilot) via a callback.
- DataSource:    input — supplies weather and/or route/depth data.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from yey.boats.simulator.engine.snapshot import AisContact, TelemetrySnapshot  # type: ignore[import]


@runtime_checkable
class TelemetrySink(Protocol):
    @property
    def name(self) -> str: ...

    async def open(self) -> None:
        """Connect/initialize. Raise on failure so the SinkChain can fail over."""

    async def publish(self, snapshot: TelemetrySnapshot) -> None:
        """Translate and emit one telemetry frame. Must not block the sim loop."""

    async def close(self) -> None:
        """Release resources."""


@runtime_checkable
class CommandSource(Protocol):
    async def run(self, on_command: Callable[[dict], Any]) -> None:
        """Long-running task; invokes on_command for each inbound command."""


@runtime_checkable
class DataSource(Protocol):
    async def get_weather(self, lat: float, lon: float, now: Any) -> Any: ...
    async def twd_shift_next_6h(self, lat: float, lon: float, now: Any) -> float: ...
    async def mean_tws_next_6h(self, lat: float, lon: float, now: Any) -> float: ...


@runtime_checkable
class AISSource(Protocol):
    async def start(self) -> None: ...

    def get_contacts(self, lat: float, lon: float) -> list[AisContact]: ...
