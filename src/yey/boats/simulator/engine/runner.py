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
import os
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

    from yey.boats.simulator.engine.geogrid import GeoGrid, _opentopo_fetch  # type: ignore[import]
    from yey.boats.simulator.engine.autoroute import AutorouteConfig  # type: ignore[import]

    grid = GeoGrid(cache_path=resources.geogrid_cache_path(settings.data_dir))
    # Search bounds are env-tunable: the public OpenTopoData endpoint needs
    # conservative caps (its quota can't feed a big search), but a self-hosted
    # bathymetry source (GEOGRID_API_URL → deploy/bathy-server) can route the
    # long, island-threading Adriatic legs with larger caps.
    _def = AutorouteConfig()
    route_cfg = AutorouteConfig(
        hard_min_m=settings.boat_draft_m + 1.0,
        bbox_margin_deg=float(os.environ.get("AUTOROUTE_BBOX_MARGIN_DEG", _def.bbox_margin_deg)),
        max_cells=int(os.environ.get("AUTOROUTE_MAX_CELLS", _def.max_cells)),
        max_nodes=int(os.environ.get("AUTOROUTE_MAX_NODES", _def.max_nodes)),
    )
    # Autoroute is NOT run inline: it can fetch a lot of GEBCO and would stall
    # startup. Reuse a persisted expanded route when the planner+cfg are
    # unchanged (instant); otherwise the engine starts on the planner legs and a
    # background task computes the navigable legs, then swaps them in.
    autoroute_fp = route.planner_fingerprint()
    # Full cfg signature: any routing-tuning change invalidates a cached route.
    autoroute_cfg_sig = [route_cfg.hard_min_m, route_cfg.soft_min_m,
                         route_cfg.prefer_m, route_cfg.penalty_necessary,
                         route_cfg.penalty_tolerated, route_cfg.bbox_margin_deg,
                         route_cfg.max_cells, route_cfg.max_nodes]
    autoroute_cache = resources.autoroute_cache_path(settings.data_dir)
    cached_wps = Route.load_expanded_waypoints(autoroute_cache, autoroute_fp, autoroute_cfg_sig)
    autoroute_needed = cached_wps is None
    if cached_wps is not None:
        route.waypoints = Route.waypoints_from_full_dicts(cached_wps)
        print(f"[sim] autoroute: loaded cached expanded route ({len(route.waypoints)} wp)",
              flush=True)
    else:
        print("[sim] autoroute: computing in background (engine starts on planner legs)",
              flush=True)
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

    # One-slot handoff: autoroute_bg() computes the expanded waypoints in a
    # worker thread and drops them here; drive() applies the swap at the TOP of
    # its loop, before engine.tick(), where no tick is suspended. The swap must
    # not land mid-tick — engine.tick() awaits between its reads of the route, so
    # swapping during a tick would yield one logically-torn snapshot.
    pending_route: dict = {}

    async def _apply_pending_route():
        new_wps = pending_route.pop("wps", None)
        if new_wps is None:
            return
        # Synchronous, atomic relative to a tick (no await between these two):
        route.waypoints = new_wps
        route.resync_from_position(engine.nav_state.lat, engine.nav_state.lon)
        try:
            route.save_expanded_route(autoroute_cache, autoroute_fp, autoroute_cfg_sig)
        except OSError as exc:
            print(f"[sim] autoroute cache write failed (non-fatal): {exc!r}", flush=True)
        next_idx = (route.current_index + 1) % len(route.waypoints)  # snapshot before awaits
        print(f"[sim] autoroute: applied navigable route ({len(new_wps)} wp, background)",
              flush=True)
        if writer is not None:
            try:
                await writer.put_route_resource(ROUTE_UUID, _route_to_geojson(route))
                await writer.put_active_route(ROUTE_UUID, next_idx)
            except Exception as exc:  # noqa: BLE001
                print(f"[sim] autoroute route re-upload failed (non-fatal): {exc!r}",
                      flush=True)

    async def drive():
        while True:
            await _apply_pending_route()   # between ticks: safe swap point
            t0 = time.monotonic()
            now = datetime.now(timezone.utc)
            snap = await engine.tick(now)
            await chain.publish(snap)
            # chain.active may change over the run (failover); recompute each tick.
            connected = isinstance(chain.active, SignalKSink)
            report_status((engine.nav_state.lat, engine.nav_state.lon), connected)
            await asyncio.sleep(max(0, 1.0 - (time.monotonic() - t0)))

    async def autoroute_bg():
        """Compute navigable legs off the startup path, in a worker thread against
        a PRIVATE in-memory grid (no shared state with the live depth grid). The
        result is handed to drive() which applies it between ticks. On any failure
        (e.g. GEBCO 429) it keeps the planner legs and does not persist, so a
        later boot retries."""
        planner_snapshot = list(route.waypoints)
        rgrid = GeoGrid(fetcher=_opentopo_fetch)  # private, in-memory
        try:
            new_wps = await asyncio.to_thread(
                Route.expand_waypoints, planner_snapshot, rgrid, route_cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"[sim] autoroute background failed (keeping planner legs): {exc!r}",
                  flush=True)
            return
        pending_route["wps"] = new_wps   # drive() applies it between ticks

    tasks = [drive(), ais_source.start(), grid.fetch_loop()]
    if autoroute_needed:
        tasks.append(autoroute_bg())
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
