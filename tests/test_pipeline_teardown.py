# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""A failing pipeline child must take its siblings down with it.

Before the fix, pipeline() ended in a bare asyncio.gather: one child raising
(SignalK refusing connections at boot) ended the pipeline but left drive() and
the writer running, and SimController started another one on top. Each failed
start leaked an engine that kept writing vessels.self.
"""
import asyncio

import pytest

from yey.boats.simulator.config import Settings
from yey.boats.simulator.control import SimController
from yey.boats.simulator.engine.runner import run_together


@pytest.mark.asyncio
async def test_failure_cancels_siblings():
    cancelled = asyncio.Event()

    async def forever():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def boom():
        await asyncio.sleep(0.01)
        raise ConnectionRefusedError("signalk not up yet")

    with pytest.raises(ConnectionRefusedError):
        await run_together([forever(), boom()])
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_cancel_cancels_children():
    cancelled = asyncio.Event()

    async def forever():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(run_together([forever()]))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_failed_starts_do_not_leak_engines(tmp_path):
    """Three failed pipeline starts, then a good one: exactly one driver runs."""
    live = set()
    attempts = []

    async def fake_pipeline(settings, route, start_pos, report_status):
        n = len(attempts)
        attempts.append(n)

        async def drive():
            live.add(n)
            try:
                await asyncio.sleep(3600)
            finally:
                live.discard(n)

        async def connect():
            await asyncio.sleep(0.01)
            if n < 3:
                raise ConnectionRefusedError("signalk not up yet")
            await asyncio.sleep(3600)

        await run_together([drive(), connect()])

    c = SimController(Settings(), route=None, data_dir=tmp_path, pipeline=fake_pipeline)
    c_task = asyncio.create_task(c.run_forever())
    for _ in range(100):
        if len(attempts) >= 4:
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.05)
    assert len(attempts) >= 4
    assert live == {3}
    c_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await c_task
