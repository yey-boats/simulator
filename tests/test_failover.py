# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
import pytest  # type: ignore[import]

from yey.boats.simulator.adapters.failover import SinkChain  # type: ignore[import]


class FlakyOpen:
    name = "flaky"
    def __init__(self): self.opened = False
    async def open(self): raise ConnectionError("nope")
    async def publish(self, snap): ...
    async def close(self): ...


class Good:
    name = "good"
    def __init__(self): self.published = []
    async def open(self): self.opened = True
    async def publish(self, snap): self.published.append(snap)
    async def close(self): ...


@pytest.mark.asyncio
async def test_chain_fails_over_to_next_on_open_error():
    good = Good()
    chain = SinkChain([FlakyOpen(), good])
    await chain.open()
    assert chain.active.name == "good"  # noqa: S101
    await chain.publish("snap")
    assert good.published == ["snap"]  # noqa: S101


@pytest.mark.asyncio
async def test_chain_raises_if_all_fail():
    chain = SinkChain([FlakyOpen(), FlakyOpen()])
    with pytest.raises(RuntimeError):
        await chain.open()


class FlakyPublish:
    name = "flaky-pub"
    def __init__(self): self.opened = False
    async def open(self): self.opened = True
    async def publish(self, snap): raise ConnectionError("publish boom")
    async def close(self): ...


@pytest.mark.asyncio
async def test_chain_demotes_on_publish_failure():
    good = Good()
    chain = SinkChain([FlakyPublish(), good])
    await chain.open()                 # FlakyPublish opens fine, becomes active
    assert chain.active.name == "flaky-pub"  # noqa: S101
    await chain.publish("snap")        # FlakyPublish.publish raises -> demote to good, re-publish
    assert chain.active.name == "good"       # noqa: S101
    assert good.published == ["snap"]        # noqa: S101
