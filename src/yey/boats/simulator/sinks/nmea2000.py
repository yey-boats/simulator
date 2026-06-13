"""NMEA 2000 sink — Phase C. Will encode PGNs over CAN (python-can) / serial /
stdout. Registered now so the sink registry and CLI know the type."""
from __future__ import annotations

from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]

_ROADMAP = ("NMEA 2000 sink is planned for Phase C (PGN encoding over "
            "CAN/serial/stdout). See docs/superpowers/specs/2026-06-13-simulator-extraction-design.md")


class NMEA2000Sink:
    name = "nmea2000"

    async def open(self) -> None:
        raise NotImplementedError(_ROADMAP)

    async def publish(self, snapshot: TelemetrySnapshot) -> None:  # noqa: ARG002
        raise NotImplementedError(_ROADMAP)

    async def close(self) -> None:
        return None
