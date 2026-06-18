# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
import pytest

from yey.boats.simulator.config import Settings
from yey.boats.simulator.control import SimController
from yey.boats.simulator.web.api import make_app


class _Ctl(SimController):
    def __init__(self, tmp_path):
        async def noop(*a):  # pragma: no cover
            import asyncio
            await asyncio.sleep(3600)
        super().__init__(Settings(aisstream_api_key="SECRET"), route=None,
                         data_dir=tmp_path, pipeline=noop)
        self.applied = []

    async def apply_config(self, changes):
        self.applied.append(changes)
        await super().apply_config(changes)


@pytest.fixture
def client_ctl(tmp_path, aiohttp_client, loop):
    ctl = _Ctl(tmp_path)
    app = make_app(ctl, token=None)
    return loop.run_until_complete(aiohttp_client(app)), ctl


async def test_get_config_masks_secrets(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    r = await cli.get("/api/config")
    body = await r.json()
    assert r.status == 200
    assert "signalk_password" not in body
    assert "aisstream_api_key" not in body
    assert body["aisstream_api_key_set"] is True
    assert body["signalk_host"] == "localhost"


async def test_put_config_applies_and_keeps_empty_secret(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    r = await cli.put("/api/config", json={"signalk_host": "boat", "aisstream_api_key": ""})
    assert r.status == 200
    assert ctl.settings.signalk_host == "boat"
    assert ctl.settings.aisstream_api_key == "SECRET"   # empty => unchanged


async def test_put_config_rejects_bad_port(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    r = await cli.put("/api/config", json={"signalk_port": 99999})
    assert r.status == 400
    body = await r.json()
    assert "signalk_port" in body["errors"]


async def test_route_put_and_get(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    wps = [{"name": "A", "lat": 45.0, "lon": 13.0},
           {"name": "B", "lat": 44.0, "lon": 14.0}]
    r = await cli.put("/api/route", json={"waypoints": wps})
    assert r.status == 200
    g = await (await cli.get("/api/route")).json()
    assert g["waypoints"] == wps


async def test_route_put_rejects_one_point(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    r = await cli.put("/api/route", json={"waypoints": [{"name": "x", "lat": 1, "lon": 2}]})
    assert r.status == 400


async def test_status(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token=None))
    r = await cli.get("/api/status")
    assert r.status == 200
    body = await r.json()
    assert "position" in body
    assert "connected" in body
    assert "tick" in body


async def test_token_required_when_set(aiohttp_client, tmp_path):
    ctl = _Ctl(tmp_path)
    cli = await aiohttp_client(make_app(ctl, token="t0p"))
    assert (await cli.get("/api/config")).status == 401
    ok = await cli.get("/api/config", headers={"X-Sim-Token": "t0p"})
    assert ok.status == 200
