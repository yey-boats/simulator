# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""SimController: owns live Settings+Route and (re)runs the engine pipeline.

Live-apply = cancel the running pipeline task and start a new one with the new
settings/route, seeding it with the last reported position so the boat does not
jump back to the route origin.
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any
from collections.abc import Awaitable, Callable

PipelineFn = Callable[..., Awaitable[None]]


class SimController:
    def __init__(self, settings, route, data_dir, pipeline: PipelineFn):
        self._settings = settings
        self._route = route
        self._data_dir = Path(data_dir)
        self._pipeline = pipeline
        self._task: asyncio.Task | None = None
        self._last_pos: tuple[float, float] | None = None
        self._restart = asyncio.Event()
        self._last_error: str | None = None
        self._tick = 0
        self._connected = False

    # --- introspection ---------------------------------------------------
    @property
    def settings(self):
        return self._settings

    @property
    def route(self):
        return self._route

    def status(self) -> dict:
        pos = ({"lat": self._last_pos[0], "lon": self._last_pos[1]}
               if self._last_pos else None)
        return {
            "running": self._task is not None and not self._task.done(),
            "connected": self._connected,
            "sink": self._settings.sink,
            "weather_source": self._settings.weather_source,
            "signalk": f"{self._settings.signalk_host}:{self._settings.signalk_port}",
            "position": pos,
            "tick": self._tick,
            "last_error": self._last_error,
        }

    def _report_status(self, pos: tuple[float, float], connected: bool) -> None:
        self._last_pos = pos
        self._connected = connected
        self._tick += 1

    # --- supervisor loop -------------------------------------------------
    async def run_forever(self) -> None:
        while True:
            self._restart.clear()
            self._task = asyncio.create_task(self._run_once())
            restart_wait = asyncio.create_task(self._restart.wait())
            done, _ = await asyncio.wait(
                {self._task, restart_wait}, return_when=asyncio.FIRST_COMPLETED)
            restart_wait.cancel()
            if self._task in done:           # pipeline exited on its own (error)
                exc = self._task.exception()
                if exc is not None:
                    self._last_error = repr(exc)
                await asyncio.sleep(1.0)      # brief backoff, then relaunch
            else:                            # restart requested
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

    async def _run_once(self) -> None:
        await self._pipeline(self._settings, self._route,
                             self._last_pos, self._report_status)

    # --- live-apply ------------------------------------------------------
    async def apply_config(self, changes: dict[str, Any]) -> None:
        for k, v in changes.items():
            if v is not None and hasattr(self._settings, k):
                setattr(self._settings, k, v)
        self._settings.save(self._data_dir / "config.json")
        self._settings.warn_if_insecure_credentials()
        self._restart.set()

    async def apply_route(self, route) -> None:
        self._route = route
        if route is not None:
            route.save_json(self._data_dir / "route.json")
        self._restart.set()
