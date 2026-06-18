"""aiohttp JSON API for the simulator web admin.

Secrets are write-only: GET masks them as <field>_set booleans; PUT with an
empty string leaves the stored secret unchanged.
"""
from __future__ import annotations

from aiohttp import web

from yey.boats.simulator.engine.route import Route
from yey.boats.simulator.routeio import WaypointError, validate_waypoints

_SECRET_FIELDS = ("signalk_password", "aisstream_api_key")
_SINKS = ("signalk", "stdout", "nmea0183", "nmea2000")
_WEATHER = ("openmeteo", "signalk")


def _config_public(settings) -> dict:
    return {
        "signalk_host": settings.signalk_host,
        "signalk_port": settings.signalk_port,
        "signalk_username": settings.signalk_username,
        "signalk_password_set": bool(settings.signalk_password),
        "aisstream_api_key_set": bool(settings.aisstream_api_key),
        "sink": settings.sink,
        "weather_source": settings.weather_source,
        "failover": settings.failover,
        "data_dir": str(settings.data_dir),
    }


def _validate_config(payload: dict) -> tuple[dict, dict]:
    changes, errors = {}, {}
    if "signalk_host" in payload:
        if not str(payload["signalk_host"]).strip():
            errors["signalk_host"] = "must not be empty"
        else:
            changes["signalk_host"] = str(payload["signalk_host"]).strip()
    if "signalk_port" in payload:
        try:
            port = int(payload["signalk_port"])
            if not (1 <= port <= 65535):
                raise ValueError
            changes["signalk_port"] = port
        except (TypeError, ValueError):
            errors["signalk_port"] = "must be 1..65535"
    for k in ("signalk_username", "data_dir"):
        if k in payload and str(payload[k]).strip():
            changes[k] = str(payload[k]).strip()
    if "sink" in payload:
        if payload["sink"] in _SINKS:
            changes["sink"] = payload["sink"]
        else:
            errors["sink"] = f"must be one of {_SINKS}"
    if "weather_source" in payload:
        if payload["weather_source"] in _WEATHER:
            changes["weather_source"] = payload["weather_source"]
        else:
            errors["weather_source"] = f"must be one of {_WEATHER}"
    if "failover" in payload:
        changes["failover"] = bool(payload["failover"])
    for k in _SECRET_FIELDS:        # empty string => leave unchanged (skip)
        if k in payload and str(payload[k]) != "":
            changes[k] = str(payload[k])
    return changes, errors


def make_app(controller, token: str | None) -> web.Application:
    app = web.Application()

    @web.middleware
    async def auth(request, handler):
        if token is not None and request.path.startswith("/api/"):
            if request.headers.get("X-Sim-Token") != token:
                return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    app.middlewares.append(auth)

    async def get_config(request):
        return web.json_response(_config_public(controller.settings))

    async def put_config(request):
        payload = await request.json()
        changes, errors = _validate_config(payload)
        if errors:
            return web.json_response({"errors": errors}, status=400)
        await controller.apply_config(changes)
        return web.json_response(_config_public(controller.settings))

    async def get_route(request):
        r = controller.route
        wps = r.to_waypoint_dicts() if r is not None else []
        idx = getattr(r, "current_index", 0) if r is not None else 0
        return web.json_response({"waypoints": wps, "current_index": idx})

    async def put_route(request):
        payload = await request.json()
        try:
            valid = validate_waypoints(payload.get("waypoints", []))
        except WaypointError as exc:
            return web.json_response({"errors": {"waypoints": str(exc)}}, status=400)
        await controller.apply_route(Route.from_waypoint_dicts(valid))
        return web.json_response({"waypoints": valid})

    async def import_route(request):
        from yey.boats.simulator import resources
        from yey.boats.simulator.routeio import waypoints_from_geojson
        reader = await request.multipart()
        field = await reader.next()
        raw = await field.read()
        name = (field.filename or "").lower()
        try:
            if name.endswith(".kmz"):
                import pathlib
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".kmz", delete=False) as fh:
                    fh.write(raw)
                    tmp = pathlib.Path(fh.name)
                wps = Route.load(tmp, resources.marinas_json()).to_waypoint_dicts()
            else:
                import json
                wps = waypoints_from_geojson(json.loads(raw.decode()))
            wps = validate_waypoints(wps)
        except (WaypointError, Exception) as exc:  # noqa: BLE001
            return web.json_response({"errors": {"file": str(exc)}}, status=400)
        return web.json_response({"waypoints": wps})

    async def get_status(request):
        return web.json_response(controller.status())

    app.router.add_get("/api/config", get_config)
    app.router.add_put("/api/config", put_config)
    app.router.add_get("/api/route", get_route)
    app.router.add_put("/api/route", put_route)
    app.router.add_post("/api/route/import", import_route)
    app.router.add_get("/api/status", get_status)
    return app
