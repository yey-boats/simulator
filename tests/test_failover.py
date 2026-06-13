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
