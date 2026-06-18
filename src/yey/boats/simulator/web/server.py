"""Static SPA serving + a WebSettings holder. Wraps the JSON API from web.api."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from aiohttp import web

from yey.boats.simulator.web.api import make_app


@dataclass
class WebSettings:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080
    token: str | None = None


def web_settings_from(args) -> WebSettings:
    """Build WebSettings from argparse Namespace (see cli.parse_args)."""
    enabled = (not getattr(args, "no_web", False)) and \
        os.environ.get("SIM_WEB_ENABLED", "1") not in ("0", "false", "False")
    host = getattr(args, "web_host", None) or os.environ.get("SIM_WEB_HOST", "127.0.0.1")
    port = getattr(args, "web_port", None) or int(os.environ.get("SIM_WEB_PORT", "8080"))
    token = getattr(args, "web_token", None) or os.environ.get("SIM_WEB_TOKEN") or None
    return WebSettings(enabled=enabled, host=host, port=int(port), token=token)


def default_static_dir() -> Path:
    return Path(__file__).parent / "static"


def make_full_app(controller, token, static_dir: Path) -> web.Application:
    app = make_app(controller, token=token)

    async def index(request):
        return web.FileResponse(static_dir / "index.html")

    # serve built assets, with SPA fallback to index.html for non-/api/ paths
    if (static_dir / "assets").exists():
        app.router.add_static("/assets/", static_dir / "assets")
    app.router.add_get("/", index)

    async def spa_fallback(request):
        if request.path.startswith("/api/"):
            return web.json_response({"error": "not found"}, status=404)
        return web.FileResponse(static_dir / "index.html")

    app.router.add_route("GET", "/{tail:.*}", spa_fallback)
    return app


async def start_web(controller, ws: WebSettings, static_dir: Path | None = None):
    static_dir = static_dir or default_static_dir()
    app = make_full_app(controller, ws.token, static_dir)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, ws.host, ws.port)
    await site.start()
    print(f"[web] admin UI at http://{ws.host}:{ws.port}", flush=True)  # noqa: T201
    return runner
