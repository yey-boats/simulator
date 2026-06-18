import asyncio
import pytest

from yey.boats.simulator.config import Settings
from yey.boats.simulator.control import SimController


@pytest.mark.asyncio
async def test_apply_config_rebuilds_pipeline(tmp_path):
    runs = []           # (settings.signalk_host, start_pos)
    started = asyncio.Event()

    async def fake_pipeline(settings, route, start_pos, report_pos):
        runs.append((settings.signalk_host, start_pos))
        report_pos((45.0, 13.0))   # controller records last position
        started.set()
        await asyncio.sleep(3600)  # runs until cancelled

    c = SimController(Settings(signalk_host="a"), route=None,
                      data_dir=tmp_path, pipeline=fake_pipeline)
    task = asyncio.create_task(c.run_forever())
    await asyncio.wait_for(started.wait(), 1)
    assert runs[0][0] == "a"
    assert runs[0][1] is None

    started.clear()
    await c.apply_config({"signalk_host": "b"})
    await asyncio.wait_for(started.wait(), 1)
    assert runs[1][0] == "b"             # rebuilt with new host
    assert runs[1][1] == (45.0, 13.0)    # position preserved across rebuild
    assert (tmp_path / "config.json").exists()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_status_reports_position(tmp_path):
    async def fake_pipeline(settings, route, start_pos, report_pos):
        report_pos((1.0, 2.0))
        await asyncio.sleep(3600)
    c = SimController(Settings(), route=None, data_dir=tmp_path, pipeline=fake_pipeline)
    task = asyncio.create_task(c.run_forever())
    await asyncio.sleep(0.05)
    st = c.status()
    assert st["position"] == {"lat": 1.0, "lon": 2.0}
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
