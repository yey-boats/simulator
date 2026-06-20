# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# yey/boats/simulator/engine/engine.py
# ruff: noqa: T201,BLE001,S110
"""Deterministic, I/O-isolated simulation engine.

Holds the physics modules + injected DataSource/AISSource + a command queue.
tick(now) runs one 1 Hz step using the injected clock and ports, and returns a
TelemetrySnapshot (vessel state + AIS contacts). No wall-clock reads, no sockets,
no sink calls — those belong to the driver.
"""
from __future__ import annotations

from typing import Any

from yey.boats.simulator.engine.autopilot import Autopilot  # type: ignore[import]
from yey.boats.simulator.engine.electrical import Electrical, solar_elevation_deg  # type: ignore[import]
from yey.boats.simulator.engine.lights import LightsModel  # type: ignore[import]
from yey.boats.simulator.engine.navigator import Navigator, engine_fuel_L_h  # type: ignore[import]
from yey.boats.simulator.engine.performance import polar_efficiency  # type: ignore[import]
from yey.boats.simulator.engine.schedule import Schedule, SimState  # type: ignore[import]
from yey.boats.simulator.engine.snapshot import TelemetrySnapshot  # type: ignore[import]
from yey.boats.simulator.engine.systems import Systems  # type: ignore[import]
from yey.boats.simulator.engine.temperatures import ThermalModel  # type: ignore[import]
from yey.boats.simulator.engine.current import tidal_current  # type: ignore[import]
from yey.boats.simulator.engine.weather import DEFAULT_WEATHER  # type: ignore[import]

ROUTE_UUID = "ad1a7c00-0b0a-4d1a-8c0a-000000000001"


class EngineCommandSink:
    """Autopilot-shaped shim handed to SignalKCommandSource/CommandHandler so they
    stay unchanged; .apply() enqueues onto the engine instead of mutating an AP."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def apply(self, action: str, arg: Any, current_heading_deg: float | None = None,
              twd_deg: float | None = None) -> None:
        self._engine.submit_command(action, arg)


class Engine:
    def __init__(self, route: Any, polars: Any, data_source: Any, ais_source: Any,
                 start_state: Any, grid: Any) -> None:
        self.route = route
        self.polars = polars
        self._data = data_source
        self._ais = ais_source
        self.sched = Schedule()
        self.nav = Navigator(polars, self.sched, grid)
        self.elec = Electrical(initial_soc=0.85)
        self.sys_ = Systems()
        self.lights = LightsModel()
        self.thermal = ThermalModel()
        self.autopilot = Autopilot()
        self.nav_state = start_state
        self._cmd_queue: list[tuple[str, Any]] = []
        self._last_wx = DEFAULT_WEATHER
        self._last_twd = 0.0

    def submit_command(self, action: str, arg: Any) -> None:
        self._cmd_queue.append((action, arg))

    async def tick(self, now: Any) -> TelemetrySnapshot:
        try:
            wx = await self._data.get_weather(self.nav_state.lat, self.nav_state.lon, now)
        except Exception as exc:
            print(f"[engine] weather error (using last known): {exc!r}", flush=True)
            wx = self._last_wx
        if wx is None:
            wx = self._last_wx
        self._last_wx = wx
        tws, twd = wx.sample()
        self._last_twd = twd

        while self._cmd_queue:
            action, arg = self._cmd_queue.pop(0)
            self.autopilot.apply(action, arg,
                                 current_heading_deg=self.nav_state.hdg_deg, twd_deg=twd)

        if (self.autopilot.state.mode == "route"
                and self.route.distance_to_next(self.nav_state.lat, self.nav_state.lon) < 0.3):
            wp_meta = self.route.current
            self.sched.on_waypoint_arrival()
            self.route.advance()
            self.sys_.on_marina_arrival(wp_meta.refill_water, wp_meta.refill_fuel,
                                        wp_meta.pump_out_bw)
            print(f"[engine] arrived {wp_meta.name}, next {self.route.next_wp.name}", flush=True)

        if self.sched.lookahead_due:
            try:
                if await self._data.twd_shift_next_6h(self.nav_state.lat, self.nav_state.lon, now) > 15:
                    self.sched._tack_timer_s = 9999
            except Exception:
                pass
            self.sched.reset_lookahead()

        if self.sched.state in (SimState.MOORED, SimState.BORA_HOLD):
            try:
                mean_tws = await self._data.mean_tws_next_6h(self.nav_state.lat, self.nav_state.lon, now)
            except Exception:
                mean_tws = tws
            self.sched.try_depart(now, twd, mean_tws)

        wp_brg = self.route.bearing_to_next(self.nav_state.lat, self.nav_state.lon)
        stw_candidate = self.polars.boat_speed(tws, abs(self.nav_state.twa_deg))
        self.sched.update_sailing_state(stw_candidate)
        eff = polar_efficiency(wx.wave_height_m, tws)
        route_hdg = self.nav.route_heading(self.nav_state, wp_brg, tws, twd, self.sched.state)
        commanded_hdg = self.autopilot.effective_heading(
            route_heading_deg=route_hdg, current_heading_deg=self.nav_state.hdg_deg, twd_deg=twd)
        # Add the helm yaw-wander offset so the boat oscillates a few degrees
        # around the commanded heading instead of holding it dead-flat. Real
        # course changes flow through commanded_hdg and are preserved exactly.
        eff_hdg = self.autopilot.steer(commanded_hdg, dt_s=1.0)
        prev_hdg = self.nav_state.hdg_deg
        self.nav_state = self.nav.tick(self.nav_state, wp_brg, tws, twd, self.sched.state,
                                       efficiency=eff, heading_override=eff_hdg)
        # Rudder reflects both the slew (turns) and the residual wander error the
        # helm is correcting (commanded vs actually-held heading).
        self.autopilot.update_rudder(prev_hdg, self.nav_state.hdg_deg,
                                     commanded_hdg_deg=commanded_hdg)

        if self.sched.state == SimState.MOTORED:
            fuel_l = engine_fuel_L_h(self.nav_state.stw_kts) / 3600
        else:
            fuel_l = 0.0
        genset_running = self.elec._genset_state == "running"
        if genset_running:
            fuel_l += 2.0 / 3600

        elec_state = self.elec.tick(1.0, self.sched.state, self.nav_state.lat,
                                    self.nav_state.lon, wx.cloud_cover, now)
        sys_state = self.sys_.tick(1.0, self.sched.state, self.nav_state.tws_kts, now,
                                   fuel_l, False, False, False)
        is_night = solar_elevation_deg(self.nav_state.lat, self.nav_state.lon, now) < 0
        lights_state = self.lights.tick(1.0, self.sched.state, is_night, now)
        self.thermal.update_ambient(wx.temp_c)
        boiler_active = elec_state.loads.get("boiler", 0) > 0
        self.thermal.tick(1.0, self.sched.state, genset_running, boiler_active)
        temps = self.thermal.cabin_temps(wx.temp_c, now)

        contacts = self._ais.get_contacts(self.nav_state.lat, self.nav_state.lon)
        current_set_deg, current_drift_kts = tidal_current(now)
        nwp = self.route.next_wp
        cwp = self.route.current  # active leg origin (previous waypoint)
        snap = TelemetrySnapshot(
            nav=self.nav_state, elec=elec_state, sys=sys_state, lights=lights_state,
            wx=wx, state=self.sched.state, utc_now=now, temps=temps,
            next_wp=(nwp.name, nwp.lat, nwp.lon),
            prev_wp=(cwp.name, cwp.lat, cwp.lon),
            route_href=f"/resources/routes/{ROUTE_UUID}",
            point_index=self.route.current_index, polars=self.polars,
            autopilot=self.autopilot,
            distance_to_next_nm=self.route.distance_to_next(self.nav_state.lat, self.nav_state.lon),
            ais_contacts=contacts,
            current_set_deg=current_set_deg,
            current_drift_kts=current_drift_kts)
        self.sched.tick(1.0)
        return snap
