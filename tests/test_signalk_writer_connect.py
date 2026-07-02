# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""SIM-2 regression: SignalKWriter.connect() must not block the event loop.

The auth login used to call urllib.request.urlopen(..., timeout=10) directly
inside `async def connect`, freezing the event loop for up to 10s. It now
goes through httpx.AsyncClient, matching the rest of the async codebase.
"""
from __future__ import annotations

import httpx  # type: ignore[import]
import pytest  # type: ignore[import]

from yey.boats.simulator.engine import signalk_writer as sw  # type: ignore[import]


class _FakeWebSocket:
    async def recv(self):
        return "hello"


@pytest.mark.asyncio
async def test_connect_logs_in_via_httpx_and_opens_websocket(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, json={"token": "tok-123"})

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    async def fake_ws_connect(uri):
        captured["ws_uri"] = uri
        return _FakeWebSocket()

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)
    monkeypatch.setattr(sw.websockets, "connect", fake_ws_connect)

    w = sw.SignalKWriter("localhost", 3000)
    await w.connect("admin", "s3cr3t")

    assert w.token == "tok-123"
    assert captured["method"] == "POST"
    assert captured["url"] == "http://localhost:3000/signalk/v1/auth/login"
    assert b"s3cr3t" in captured["body"]
    assert captured["ws_uri"].endswith("token=tok-123")


def test_no_blocking_urlopen_import_in_signalk_writer():
    """Guards against regressing back to urllib.request.urlopen()."""
    assert not hasattr(sw, "urllib")
