"""CommandSource backed by the SignalK steering.autopilot.command channel.

Wraps the migrated CommandHandler/CommandListener so autopilot commands flow
from the bus into the engine's Autopilot, preserving Phase-A behavior.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from yey.boats.simulator.engine.command_listener import CommandHandler, CommandListener  # type: ignore[import]


class SignalKCommandSource:
    def __init__(self, host: str, port: int, token: str | None, autopilot: Any,
                 wind_fn: Callable[[], tuple[float, float]]) -> None:
        self.handler = CommandHandler(autopilot, wind_fn)
        self._listener = CommandListener(host, port, token, self.handler)

    async def run(self) -> None:
        await self._listener.run()
