# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# yey/boats/simulator/engine/runner.py
# ruff: noqa: T201,BLE001,S110
"""Driver: builds ports + Engine and runs the 1 Hz loop.

This is the ONLY place that reads the wall clock and calls sinks/transport. The
Engine owns the physics; the driver owns the clock, cadence, output SinkChain,
SignalK transport side-tasks, and command-source wiring.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from yey.boats.simulator import resources  # type: ignore[import]
from yey.boats.simulator.config import Settings  # type: ignore[import]
from yey.boats.simulator.engine.engine import Engine, EngineCommandSink  # type: ignore[import]
from yey.boats.simulator.engine.navigator import NavState  # type: ignore[import]
from yey.boats.simulator.engine.polars import Polars  # type: ignore[import]
from yey.boats.simulator.engine.route import Route  # type: ignore[import]
from yey.boats.simulator.sinks.registry import build_sink_chain  # type: ignore[import]
from yey.boats.simulator.sinks.signalk import SignalKSink  # type: ignore[import]
from yey.boats.simulator.sources.ais import AISStreamSource, SyntheticAISSource  # type: ignore[import]
from yey.boats.simulator.sources.open_meteo import OpenMeteoDataSource  # type: ignore[import]
from yey.boats.simulator.sources.signalk_command import SignalKCommandSource  # type: ignore[import]
from yey.boats.simulator.sources.signalk_weather import SignalKDataSource  # type: ignore[import]

ROUTE_UUID = "ad1a7c00-0b0a-4d1a-8c0a-000000000001"
META_LOADS = ["fridge", "watermaker", "nav", "instruments", "lighting", "wifi",
              "cooker", "boiler", "kettle", "coffeemaker", "hvac",
              "bilge_pump", "water_pump"]


def build_data_source(settings: Settings):
    if settings.weather_source == "signalk":
        return SignalKDataSource(settings.signalk_host, settings.signalk_port)
    return OpenMeteoDataSource()


def _route_to_geojson(route: Route) -> dict:
    coords = [[wp.lon, wp.lat] for wp in route.waypoints]
    names = [wp.name for wp in route.waypoints]
    return {
        "name": "Adriatic Cruise",
        "description": "Venice -> Pula -> Zadar -> Split -> Hvar -> Korcula -> Dubrovnik -> Corfu",
        "feature": {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"waypoints": [{"name": n} for n in names]},
        },
    }


async def pipeline(settings: Settings, route, start_pos, report_status) -> None:
    """Single run of the engine pipeline.

    Args:
        settings: Current Settings snapshot.
        route: Pre-loaded Route, or None to load from resources.
        start_pos: (lat, lon) tuple to resume from, or None to use SignalK/origin.
        report_status: Callable[((lat, lon), connected: bool)] called after each
            engine tick. `connected` is True when the SignalK sink is the active
            chain member (i.e. not failed over).
    """
    if route is None:
        route = Route.load(resources.route_kmz(), resources.marinas_json())

    from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]
    from yey.boats.simulator.engine.autoroute import AutorouteConfig  # type: ignore[import]

    grid = GeoGrid(cache_path=resources.geogrid_cache_path(settings.data_dir))
    route_cfg = AutorouteConfig(hard_min_m=settings.boat_draft_m + 1.0)
    try:
        inserted = route.autoroute_legs(grid, route_cfg)
        print(f"[sim] autoroute inserted {inserted} navigable waypoints", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[sim] autoroute failed (using planner legs): {exc!r}", flush=True)
    polars = Polars.load(resources.polar_csv())

    chain = build_sink_chain(settings)
    print(f"[sim] opening sink chain (primary={settings.sink})...", flush=True)
    await chain.open()
    sk_sink = chain.active if isinstance(chain.active, SignalKSink) else None
    writer = sk_sink.writer if sk_sink else None

    if start_pos is not None:
        start_lat, start_lon = start_pos
        idx, _ = route.resync_from_position(start_lat, start_lon)
        start_hdg = route.bearing_to_next(start_lat, start_lon)
        print(f"[sim] resuming from ({start_lat:.4f}, {start_lon:.4f}) -> leg {idx}", flush=True)
    else:
        resume = await writer.get_self_position() if writer is not None else None
        if resume is not None:
            start_lat, start_lon = resume
            idx, _ = route.resync_from_position(start_lat, start_lon)
            start_hdg = route.bearing_to_next(start_lat, start_lon)
            print(f"[sim] resuming from ({start_lat:.4f}, {start_lon:.4f}) -> leg {idx}",
                  flush=True)
        else:
            start_lat, start_lon = route.current.lat, route.current.lon
            start_hdg = route.current.berth_heading
            print(f"[sim] starting at origin {route.current.name}", flush=True)

    if writer is not None:
        try:
            await writer.put_route_resource(ROUTE_UUID, _route_to_geojson(route))
            await writer.put_active_route(ROUTE_UUID, (route.current_index + 1) % len(route.waypoints))
        except Exception as exc:
            print(f"[sim] route resource upload failed (non-fatal): {exc!r}", flush=True)

    start_state = NavState(lat=start_lat, lon=start_lon, hdg_deg=start_hdg,
                           cog_deg=start_hdg, sog_kts=0, stw_kts=0, twa_deg=0,
                           tws_kts=0, twd_deg=0, awa_deg=0, aws_kts=0,
                           heel_deg=0, depth_m=10.0)

    data_source = build_data_source(settings)

    engine_ref: dict = {}

    def get_pos() -> tuple[float, float]:
        eng = engine_ref.get("engine")
        if eng is None:
            return (start_lat, start_lon)
        return (eng.nav_state.lat, eng.nav_state.lon)

    if settings.aisstream_api_key:
        ais_source = AISStreamSource(get_pos=get_pos, api_key=settings.aisstream_api_key)
    else:
        ais_source = SyntheticAISSource(get_pos=get_pos)

    engine = Engine(route, polars, data_source, ais_source,
                    start_state=start_state, grid=grid)
    engine_ref["engine"] = engine

    async def drive():
        while True:
            t0 = time.monotonic()
            now = datetime.now(timezone.utc)
            snap = await engine.tick(now)
            await chain.publish(snap)
            # chain.active may change over the run (failover); recompute each tick.
            connected = isinstance(chain.active, SignalKSink)
            report_status((engine.nav_state.lat, engine.nav_state.lon), connected)
            await asyncio.sleep(max(0, 1.0 - (time.monotonic() - t0)))

    tasks = [drive(), ais_source.start(), grid.fetch_loop()]
    if writer is not None:
        cmd_src = SignalKCommandSource(
            settings.signalk_host, settings.signalk_port, writer.token,
            EngineCommandSink(engine), lambda: (0.0, 0.0))
        tasks += [writer.flush_loop(),
                  writer.metadata_loop(extra_load_names=META_LOADS, interval=2.0),
                  cmd_src.run()]

    await asyncio.gather(*tasks)


async def run_with_web(settings: Settings, args) -> None:
    """Build SimController and optionally start the web admin, then run forever."""
    from yey.boats.simulator.control import SimController
    from yey.boats.simulator.web.server import WebSettings, web_settings_from, start_web

    route = Route.load(resources.route_kmz(), resources.marinas_json())
    route_json = settings.data_dir / "route.json"
    if route_json.exists():
        route = Route.load_json(route_json)

    controller = SimController(settings, route, settings.data_dir, pipeline)

    ws: WebSettings = web_settings_from(args)
    tasks = [controller.run_forever()]
    if ws.enabled:
        # Start the web server as a coroutine that sets up AppRunner then waits forever
        async def _web():
            await start_web(controller, ws)
            await asyncio.Event().wait()  # keep the task alive

        tasks.append(_web())

    await asyncio.gather(*tasks)


async def run(settings: Settings) -> None:
    """Legacy entry point (used by tests that import run directly)."""
    from argparse import Namespace
    args = Namespace(no_web=True, web_host=None, web_port=None, web_token=None)
    await run_with_web(settings, args)
