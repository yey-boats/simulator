# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# signalk/sim/modules/command_listener.py
"""Subscribe to steering.autopilot.command on the SignalK stream and apply
commands to the Autopilot. CommandHandler is pure (testable); CommandListener is
the asyncio WS glue."""
from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Callable

import websockets  # type: ignore[import]

COMMAND_PATH = "steering.autopilot.command"
SELF_SOURCE = "simulator.py"
# Actions whose `value` is an angle in radians (SI on the bus → degrees internally)
_ANGLE_ACTIONS = {"set_heading", "adjust"}


class CommandHandler:
    """Parse incoming deltas and apply autopilot commands. `wind_fn` returns the
    live (current_heading_deg, twd_deg) used to seed targets."""

    def __init__(self, autopilot: Any,
                 wind_fn: Callable[[], tuple[float, float]]) -> None:
        self._ap = autopilot
        self._wind_fn = wind_fn
        self._seen: set = set()

    def on_delta(self, delta: dict) -> None:
        for upd in (delta or {}).get("updates", []):
            if upd.get("$source") == SELF_SOURCE:
                continue
            for v in upd.get("values", []):
                if v.get("path") != COMMAND_PATH:
                    continue
                self._apply(v.get("value"))

    def _apply(self, value: Any) -> None:
        if not isinstance(value, dict):
            return
        action = value.get("action")
        if not isinstance(action, str):
            return
        nonce = value.get("nonce")
        if nonce is not None:
            if nonce in self._seen:
                return
            self._seen.add(nonce)
            if len(self._seen) > 512:        # bound memory
                self._seen = set(list(self._seen)[-256:])
        raw = value.get("value")
        arg: Any = raw
        if action in _ANGLE_ACTIONS and isinstance(raw, (int, float)):
            arg = math.degrees(float(raw))
        cur_hdg, twd = self._wind_fn()
        self._ap.apply(action, arg, current_heading_deg=cur_hdg, twd_deg=twd)


class CommandListener:
    """Owns a read-only WS subscribed to the command path; reconnects on drop."""

    def __init__(self, host: str, port: int, token: str, handler: CommandHandler) -> None:
        self._host = host
        self._port = port
        self._token = token
        self._handler = handler

    async def run(self) -> None:
        sub = json.dumps({"context": "vessels.self",
                          "subscribe": [{"path": COMMAND_PATH, "period": 500}]})
        uri = (f"ws://{self._host}:{self._port}/signalk/v1/stream"
               f"?subscribe=none&token={self._token}")
        while True:
            try:
                async with websockets.connect(uri) as ws:
                    await ws.recv()              # hello
                    await ws.send(sub)
                    print("[cmd] autopilot command listener connected", flush=True)  # noqa: T201
                    async for raw in ws:
                        try:
                            self._handler.on_delta(json.loads(raw))
                        except Exception as exc:  # noqa: BLE001
                            print(f"[cmd] bad delta: {exc!r}", flush=True)  # noqa: T201
            except Exception as exc:  # noqa: BLE001
                print(f"[cmd] listener disconnected: {exc!r}, retry 5s", flush=True)  # noqa: T201
                await asyncio.sleep(5)
