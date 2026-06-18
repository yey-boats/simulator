# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""NMEA 0183 sink — Phase C. Will encode RMC/GGA/VTG/HDG/MWV/DBT sentences over
stdout or pyserial. Registered now so the sink registry and CLI know the type."""
from __future__ import annotations

from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]

_ROADMAP = ("NMEA 0183 sink is planned for Phase C (sentence encoding over "
            "stdout/serial). See docs/superpowers/specs/2026-06-13-simulator-extraction-design.md")


class NMEA0183Sink:
    name = "nmea0183"

    async def open(self) -> None:
        raise NotImplementedError(_ROADMAP)

    async def publish(self, snapshot: TelemetrySnapshot) -> None:  # noqa: ARG002
        raise NotImplementedError(_ROADMAP)

    async def close(self) -> None:
        return None
