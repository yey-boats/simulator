"""SinkChain: try telemetry sinks in priority order, demoting on failure.

open() walks the chain until one connects; publish() forwards to the active
sink and, if it raises, demotes to the next still-openable sink.
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]


class SinkChain:
    def __init__(self, sinks: list[Any]) -> None:
        if not sinks:
            raise ValueError("SinkChain requires at least one sink")
        self._sinks = sinks
        self._idx = -1

    @property
    def active(self) -> Any:
        return self._sinks[self._idx] if self._idx >= 0 else None

    @property
    def name(self) -> str:
        return self.active.name if self.active else "none"

    async def _open_from(self, start: int) -> None:
        for i in range(start, len(self._sinks)):
            sink = self._sinks[i]
            try:
                await sink.open()
                self._idx = i
                print(f"[sink] active: {sink.name}", flush=True, file=sys.stderr)  # noqa: T201
                return
            except Exception as exc:  # noqa: BLE001
                print(  # noqa: T201
                    f"[sink] {sink.name} open failed ({exc!r}), trying next",
                    flush=True,
                    file=sys.stderr,
                )
        raise RuntimeError("all telemetry sinks failed to open")

    async def open(self) -> None:
        await self._open_from(0)

    async def publish(self, snapshot: TelemetrySnapshot) -> None:
        try:
            await self.active.publish(snapshot)
        except Exception as exc:  # noqa: BLE001
            print(  # noqa: T201
                f"[sink] {self.active.name} publish failed ({exc!r}), failing over",
                flush=True,
                file=sys.stderr,
            )
            await self._open_from(self._idx + 1)
            await self.active.publish(snapshot)

    async def close(self) -> None:
        if self.active:
            await self.active.close()
