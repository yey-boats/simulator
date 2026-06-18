# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from yey.boats.simulator.config import Settings
from yey.boats.simulator.control import SimController
from yey.boats.simulator.web.server import make_full_app, web_settings_from
from yey.boats.simulator.cli import parse_args


def _ctl(tmp_path):
    async def noop(*a):
        import asyncio
        await asyncio.sleep(3600)
    return SimController(Settings(), route=None, data_dir=tmp_path, pipeline=noop)


async def test_spa_fallback_serves_index(aiohttp_client, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>sim</title>")
    cli = await aiohttp_client(make_full_app(_ctl(tmp_path), token=None, static_dir=static))
    r = await cli.get("/")
    assert r.status == 200 and "sim" in await r.text()
    deep = await cli.get("/route")          # client-side route -> index fallback
    assert deep.status == 200


async def test_api_still_works_with_static(aiohttp_client, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("x")
    cli = await aiohttp_client(make_full_app(_ctl(tmp_path), token=None, static_dir=static))
    assert (await cli.get("/api/status")).status == 200


async def test_missing_spa_serves_503_not_500(aiohttp_client, tmp_path):
    # Static-less install (dir exists with only .gitkeep, no index.html): the
    # API must still work and the SPA routes degrade to a clear 503, not a 500.
    static = tmp_path / "static"
    static.mkdir()  # no index.html
    cli = await aiohttp_client(make_full_app(_ctl(tmp_path), token=None, static_dir=static))
    root = await cli.get("/")
    assert root.status == 503 and "not built" in (await root.text())
    deep = await cli.get("/route")
    assert deep.status == 503
    assert (await cli.get("/api/status")).status == 200  # API unaffected


async def test_token_allows_spa_blocks_api(aiohttp_client, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>sim</title>")
    cli = await aiohttp_client(make_full_app(_ctl(tmp_path), token="t0p", static_dir=static))
    # SPA assets must load unauthenticated so the page can come up and prompt.
    assert (await cli.get("/")).status == 200
    # API requires the token.
    assert (await cli.get("/api/status")).status == 401


def test_web_flags_default_on_loopback():
    ws = web_settings_from(parse_args([]))
    assert ws.enabled is True
    assert ws.host == "127.0.0.1"
    assert ws.port == 8080


def test_web_flags_disable_and_override():
    ws = web_settings_from(parse_args(["--no-web"]))
    assert ws.enabled is False
    ws2 = web_settings_from(parse_args(["--web-port", "9000", "--web-host", "0.0.0.0"]))
    assert ws2.port == 9000 and ws2.host == "0.0.0.0"
