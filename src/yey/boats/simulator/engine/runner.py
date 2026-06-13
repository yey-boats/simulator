# yey/boats/simulator/engine/runner.py
# ruff: noqa: T201,BLE001,S110
"""Engine orchestration: wires modules together, ticks at 1 Hz, builds a
TelemetrySnapshot each tick and publishes via the configured SinkChain.

SignalK-transport side-tasks (flush_loop, metadata_loop, AIS feed, command
listener) are launched only when the active sink is the SignalK sink, since
they are owned by SignalKWriter.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from yey.boats.simulator import resources  # type: ignore[import]
from yey.boats.simulator.config import Settings  # type: ignore[import]
from yey.boats.simulator.engine.ais_relay import AISRelay  # type: ignore[import]
from yey.boats.simulator.engine.autopilot import Autopilot  # type: ignore[import]
from yey.boats.simulator.engine.electrical import Electrical, solar_elevation_deg  # type: ignore[import]
from yey.boats.simulator.engine.lights import LightsModel  # type: ignore[import]
from yey.boats.simulator.engine.navigator import Navigator, NavState, engine_fuel_L_h  # type: ignore[import]
from yey.boats.simulator.engine.performance import polar_efficiency  # type: ignore[import]
from yey.boats.simulator.engine.polars import Polars  # type: ignore[import]
from yey.boats.simulator.engine.route import Route  # type: ignore[import]
from yey.boats.simulator.engine.schedule import Schedule, SimState  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.engine.synthetic_ais import SyntheticTraffic  # type: ignore[import]
from yey.boats.simulator.engine.systems import Systems  # type: ignore[import]
from yey.boats.simulator.engine.temperatures import ThermalModel  # type: ignore[import]
from yey.boats.simulator.engine.weather import DEFAULT_WEATHER, WeatherFetcher  # type: ignore[import]
from yey.boats.simulator.sinks.registry import build_sink_chain  # type: ignore[import]
from yey.boats.simulator.sinks.signalk import SignalKSink  # type: ignore[import]
from yey.boats.simulator.sources.signalk_command import SignalKCommandSource  # type: ignore[import]

ROUTE_UUID = "ad1a7c00-0b0a-4d1a-8c0a-000000000001"
META_LOADS = ["fridge", "watermaker", "nav", "instruments", "lighting", "wifi",
              "cooker", "boiler", "kettle", "coffeemaker", "hvac",
              "bilge_pump", "water_pump"]


def build_snapshot(*, nav, elec, sys_, lights, wx, state, now, temps,
                   next_wp, route_href, point_index, polars, autopilot,
                   distance_to_next_nm) -> TelemetrySnapshot:
    return TelemetrySnapshot(
        nav=nav, elec=elec, sys=sys_, lights=lights, wx=wx, state=state,
        utc_now=now, temps=temps, next_wp=next_wp, route_href=route_href,
        point_index=point_index, polars=polars, autopilot=autopilot,
        distance_to_next_nm=distance_to_next_nm)


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


async def run(settings: Settings) -> None:
    route = Route.load(resources.route_kmz(), resources.marinas_json())
    print("[sim] fetching depth profile (may take ~30s first run)...", flush=True)
    route.load_depth_profile(resources.depth_cache_path(settings.data_dir))

    polars = Polars.load(resources.polar_csv())
    sched = Schedule()
    weather = WeatherFetcher()
    nav = Navigator(polars, sched, route._depth_profile)
    elec = Electrical(initial_soc=0.85)
    sys_ = Systems()
    lights = LightsModel()
    thermal = ThermalModel()
    autopilot = Autopilot()

    chain = build_sink_chain(settings)
    print(f"[sim] opening sink chain (primary={settings.sink})...", flush=True)
    await chain.open()

    sk_sink = chain.active if isinstance(chain.active, SignalKSink) else None
    writer = sk_sink.writer if sk_sink else None

    if writer is not None:
        resume = await writer.get_self_position()
    else:
        resume = None
    if resume is not None:
        start_lat, start_lon = resume
        idx, near_d = route.resync_from_position(start_lat, start_lon)
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
            next_idx = (route.current_index + 1) % len(route.waypoints)
            await writer.put_active_route(ROUTE_UUID, next_idx)
        except Exception as exc:
            print(f"[sim] route resource upload failed (non-fatal): {exc!r}", flush=True)

    nav_state = NavState(lat=start_lat, lon=start_lon, hdg_deg=start_hdg,
                         cog_deg=start_hdg, sog_kts=0, stw_kts=0, twa_deg=0,
                         tws_kts=0, twd_deg=0, awa_deg=0, aws_kts=0,
                         heel_deg=0, depth_m=10.0)
    last_wx = [DEFAULT_WEATHER]

    async def sim_loop():
        nonlocal nav_state
        while True:
            t0 = time.monotonic()
            now = datetime.now(timezone.utc)
            try:
                last_wx[0] = await weather.get(nav_state.lat, nav_state.lon, now)
            except Exception as exc:
                print(f"[sim] weather error (using last known): {exc!r}", flush=True)
            if last_wx[0] is None:
                await asyncio.sleep(max(0, 1.0 - (time.monotonic() - t0)))
                continue
            wx = last_wx[0]
            tws, twd = wx.sample()

            if (autopilot.state.mode == "route"
                    and route.distance_to_next(nav_state.lat, nav_state.lon) < 0.3):
                wp_meta = route.current
                sched.on_waypoint_arrival()
                route.advance()
                if writer is not None:
                    try:
                        await writer.advance_active_point(1)
                    except Exception:
                        pass
                sys_.on_marina_arrival(wp_meta.refill_water, wp_meta.refill_fuel,
                                       wp_meta.pump_out_bw)
                print(f"[sim] arrived {wp_meta.name}, next {route.next_wp.name}",
                      flush=True)

            if sched.lookahead_due:
                try:
                    if await weather.twd_shift_next_6h(nav_state.lat, nav_state.lon, now) > 15:
                        sched._tack_timer_s = 9999
                except Exception:
                    pass
                sched.reset_lookahead()

            if sched.state in (SimState.MOORED, SimState.BORA_HOLD):
                try:
                    mean_tws = await weather.mean_tws_next_6h(nav_state.lat, nav_state.lon, now)
                except Exception:
                    mean_tws = tws
                sched.try_depart(now, twd, mean_tws)

            wp_brg = route.bearing_to_next(nav_state.lat, nav_state.lon)
            stw_candidate = polars.boat_speed(tws, abs(nav_state.twa_deg))
            sched.update_sailing_state(stw_candidate)
            eff = polar_efficiency(wx.wave_height_m, tws)
            route_hdg = nav.route_heading(nav_state, wp_brg, tws, twd, sched.state)
            eff_hdg = autopilot.effective_heading(
                route_heading_deg=route_hdg, current_heading_deg=nav_state.hdg_deg,
                twd_deg=twd)
            prev_hdg = nav_state.hdg_deg
            nav_state = nav.tick(nav_state, wp_brg, tws, twd, sched.state,
                                 efficiency=eff, heading_override=eff_hdg)
            autopilot.update_rudder(prev_hdg, nav_state.hdg_deg)

            if sched.state == SimState.MOTORED:
                fuel_l = engine_fuel_L_h(nav_state.stw_kts) / 3600
            else:
                fuel_l = 0.0
            genset_running = elec._genset_state == "running"
            if genset_running:
                fuel_l += 2.0 / 3600

            elec_state = elec.tick(1.0, sched.state, nav_state.lat, nav_state.lon,
                                   wx.cloud_cover, now)
            sys_state = sys_.tick(1.0, sched.state, nav_state.tws_kts, now,
                                  fuel_l, False, False, False)
            is_night = solar_elevation_deg(nav_state.lat, nav_state.lon, now) < 0
            lights_state = lights.tick(1.0, sched.state, is_night, now)
            thermal.update_ambient(wx.temp_c)
            boiler_active = elec_state.loads.get("boiler", 0) > 0
            thermal.tick(1.0, sched.state, genset_running, boiler_active)
            temps = thermal.cabin_temps(wx.temp_c, now)

            nwp = route.next_wp
            snap = build_snapshot(
                nav=nav_state, elec=elec_state, sys_=sys_state,
                lights=lights_state, wx=wx, state=sched.state, now=now,
                temps=temps, next_wp=(nwp.name, nwp.lat, nwp.lon),
                route_href=f"/resources/routes/{ROUTE_UUID}",
                point_index=route.current_index, polars=polars,
                autopilot=autopilot,
                distance_to_next_nm=route.distance_to_next(nav_state.lat, nav_state.lon))
            await chain.publish(snap)

            sched.tick(1.0)
            await asyncio.sleep(max(0, 1.0 - (time.monotonic() - t0)))

    tasks = [sim_loop()]
    if writer is not None:
        ais = AISRelay(writer, lambda: (nav_state.lat, nav_state.lon))
        cmd_src = SignalKCommandSource(
            settings.signalk_host, settings.signalk_port, writer.token,
            autopilot, lambda: (nav_state.hdg_deg, last_wx[0].sample()[1]))
        tasks += [writer.flush_loop(),
                  writer.metadata_loop(extra_load_names=META_LOADS, interval=2.0),
                  ais.run(), cmd_src.run()]
        if not settings.aisstream_api_key:
            synth = SyntheticTraffic(writer, lambda: (nav_state.lat, nav_state.lon))
            tasks.append(synth.run())

    await asyncio.gather(*tasks)
