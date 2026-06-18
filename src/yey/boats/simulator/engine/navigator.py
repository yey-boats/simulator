# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# signalk/sim/modules/navigator.py
from __future__ import annotations
import math
from dataclasses import dataclass
from yey.boats.simulator.engine.polars import Polars  # type: ignore[import]
from yey.boats.simulator.engine.route import haversine_nm, dead_reckon  # type: ignore[import]
from yey.boats.simulator.engine.schedule import Schedule, SimState  # type: ignore[import]

CURRENT_KTS   = 0.3
CURRENT_DIR   = 150.0   # NW→SE Adriatic drift

# ── Volvo D4-55 propulsion model ─────────────────────────────────────────────
# Gearbox: 2.5:1 (Volvo MS25L), propeller: 18" 3-blade folding
# Calibrated: 2200 RPM engine → ~5.87 kt STW on Oceanis 45 hull
MOTOR_CRUISE_RPM = 2200.0
_PROP_K          = 0.00267   # kt per engine RPM
MOTOR_STW_KTS    = MOTOR_CRUISE_RPM * _PROP_K   # ≈ 5.87 kt
_FUEL_K          = 2.259e-4  # L/h coefficient: k * RPM^1.3 → 2200 RPM = 5.0 L/h


def engine_rpm(stw_kts: float) -> float:
    """Inverse propeller model: STW → engine RPM."""
    if stw_kts <= 0:
        return 0.0
    return max(750.0, min(3000.0, stw_kts / _PROP_K))


def engine_fuel_L_h(stw_kts: float) -> float:
    """Volvo D4-55 fuel consumption in L/h from boat speed."""
    rpm = engine_rpm(stw_kts)
    return min(10.0, _FUEL_K * (rpm ** 1.3))


def _norm360(deg: float) -> float:
    return deg % 360


def _normalise_angle(deg: float) -> float:
    """Map angle to -180..+180."""
    return ((deg + 180) % 360) - 180


def _apparent_wind(stw_kts: float, hdg_deg: float,
                   tws_kts: float, twd_deg: float) -> tuple[float, float]:
    """Return (AWS kts, AWA degrees). AWA: + = starboard, - = port.

    AWA is the angle of the apparent wind source relative to the boat's bow:
    0° = head-to-wind, +90° = starboard beam, ±180° = dead downwind.
    """
    hdg_r = math.radians(hdg_deg)
    twd_r = math.radians(twd_deg)
    # True wind velocity vector in N/E frame (direction wind is blowing TO)
    # Wind FROM twd_deg means it flows in the opposite direction
    twv_x = -tws_kts * math.sin(twd_r)   # East component
    twv_y = -tws_kts * math.cos(twd_r)   # North component
    # Boat velocity vector in N/E frame
    bv_x  =  stw_kts * math.sin(hdg_r)
    bv_y  =  stw_kts * math.cos(hdg_r)
    # Apparent wind velocity in N/E frame (wind the boat feels)
    aw_x  = twv_x - bv_x
    aw_y  = twv_y - bv_y
    aws = math.sqrt(aw_x ** 2 + aw_y ** 2)
    # Rotate apparent wind vector into boat frame (subtract heading rotation)
    # to get angle relative to bow
    sin_h = math.sin(hdg_r)
    cos_h = math.cos(hdg_r)
    # Component along bow (forward = positive) and across bow (starboard = positive)
    aw_fwd   =  aw_x * sin_h + aw_y * cos_h   # projection onto bow direction
    aw_stbd  =  aw_x * cos_h - aw_y * sin_h   # projection onto starboard direction
    # AWA: angle of apparent wind SOURCE → negate the flow vector to get "from" direction
    awa = math.degrees(math.atan2(-aw_stbd, -aw_fwd))
    return aws, awa


@dataclass
class NavState:
    lat: float
    lon: float
    hdg_deg: float
    cog_deg: float
    sog_kts: float
    stw_kts: float
    twa_deg: float   # true wind angle, signed (-= port, += starboard)
    tws_kts: float
    twd_deg: float
    awa_deg: float
    aws_kts: float
    heel_deg: float
    depth_m: float
    log_nm: float = 0.0


class Navigator:
    def __init__(self, polars: Polars, schedule: Schedule,
                 depth_profile: list) -> None:
        self._polars   = polars
        self._schedule = schedule
        self._depth    = depth_profile

    def route_heading(self, state: NavState, wp_bearing: float,
                      tws_kts: float, twd_deg: float,
                      sim_state: SimState) -> float:
        """Heading the boat would steer in ROUTE mode (motoring = straight to the
        waypoint; sailing = VMG-optimised tacking toward it)."""
        if sim_state == SimState.MOTORED:
            return wp_bearing
        return self.sail_heading(state.lat, state.lon, wp_bearing, twd_deg, tws_kts)

    # ── public tick ─────────────────────────────────────────────────────────
    def tick(self, state: NavState, wp_bearing: float,
             tws_kts: float, twd_deg: float,
             sim_state: SimState, dt_s: float = 1.0,
             efficiency: float = 1.0,
             heading_override: float | None = None) -> NavState:
        if heading_override is not None:
            hdg = heading_override
            if sim_state == SimState.MOTORED:
                stw = MOTOR_STW_KTS
            else:
                stw = self._polars.boat_speed(tws_kts, abs(_normalise_angle(twd_deg - hdg)))
                stw *= efficiency
        elif sim_state == SimState.MOTORED:
            hdg = wp_bearing
            stw = MOTOR_STW_KTS  # Volvo D4-55 at 2200 RPM cruise (unaffected by sea state)
        else:
            hdg = self.sail_heading(state.lat, state.lon, wp_bearing,
                                    twd_deg, tws_kts)
            stw = self._polars.boat_speed(tws_kts, abs(_normalise_angle(twd_deg - hdg)))
            # Sea-state / helm efficiency: a seaway pulls sailing STW below the
            # flat-water polar so performance.polarSpeedRatio lands realistically
            # <1.0. Applied only under sail (MOTORED speed is RPM-driven).
            stw *= efficiency

        twa = _normalise_angle(twd_deg - hdg)
        aws, awa = _apparent_wind(stw, hdg, tws_kts, twd_deg)
        sog, cog = self._apply_current(stw, hdg)
        lat, lon = self._dead_reckon(state.lat, state.lon, sog, cog, dt_s)
        depth = self._depth_at(lat, lon)
        heel  = self.compute_heel(tws_kts, twa)
        log   = state.log_nm + sog * dt_s / 3600

        return NavState(lat=lat, lon=lon, hdg_deg=hdg, cog_deg=cog,
                        sog_kts=sog, stw_kts=stw, twa_deg=twa,
                        tws_kts=tws_kts, twd_deg=twd_deg,
                        awa_deg=awa, aws_kts=aws,
                        heel_deg=heel, depth_m=depth, log_nm=log)

    # ── tacking / gybing model ───────────────────────────────────────────────
    def sail_heading(self, lat: float, lon: float, wp_bearing: float,
                     twd_deg: float, tws_kts: float) -> float:
        twa_to_wp = _normalise_angle(twd_deg - wp_bearing)
        best_up = self._polars.best_vmg_upwind_twa(tws_kts)
        best_dn = self._polars.best_vmg_downwind_twa(tws_kts)

        if abs(twa_to_wp) < best_up:
            return self._upwind_heading(wp_bearing, twd_deg, tws_kts, best_up)
        elif abs(twa_to_wp) > best_dn:
            return self._downwind_heading(wp_bearing, twd_deg, tws_kts, best_dn)
        else:
            return wp_bearing

    def _upwind_heading(self, wp_bearing: float, twd_deg: float,
                        tws_kts: float, best_up: float) -> float:
        stbd_hdg = _norm360(twd_deg - best_up)
        port_hdg = _norm360(twd_deg + best_up)
        # layline: if we can now fetch the waypoint at best_up
        if abs(_normalise_angle(twd_deg - wp_bearing)) >= best_up - 2:
            return wp_bearing
        spd = self._polars.boat_speed(tws_kts, best_up)
        vmg_s = spd * math.cos(math.radians(_normalise_angle(stbd_hdg - wp_bearing)))
        vmg_p = spd * math.cos(math.radians(_normalise_angle(port_hdg - wp_bearing)))
        desired = "starboard" if vmg_s >= vmg_p else "port"
        self._schedule.request_tack(desired)
        return stbd_hdg if self._schedule.tack == "starboard" else port_hdg

    def _downwind_heading(self, wp_bearing: float, twd_deg: float,
                          tws_kts: float, best_dn: float) -> float:
        stbd_hdg = _norm360(twd_deg + (180 - best_dn))
        port_hdg = _norm360(twd_deg - (180 - best_dn))
        if abs(_normalise_angle(twd_deg - wp_bearing)) <= best_dn + 2:
            return wp_bearing
        spd = self._polars.boat_speed(tws_kts, best_dn)
        vmg_s = spd * math.cos(math.radians(_normalise_angle(stbd_hdg - wp_bearing)))
        vmg_p = spd * math.cos(math.radians(_normalise_angle(port_hdg - wp_bearing)))
        desired = "starboard" if vmg_s >= vmg_p else "port"
        self._schedule.request_tack(desired)
        return stbd_hdg if self._schedule.tack == "starboard" else port_hdg

    # ── helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def compute_heel(tws_kts: float, twa_deg: float) -> float:
        return min(35.0, 0.12 * tws_kts * abs(math.sin(math.radians(twa_deg))))

    def _apply_current(self, stw_kts: float,
                       hdg_deg: float) -> tuple[float, float]:
        hdg_r = math.radians(hdg_deg)
        cur_r = math.radians(CURRENT_DIR)
        bx = stw_kts * math.sin(hdg_r) + CURRENT_KTS * math.sin(cur_r)
        by = stw_kts * math.cos(hdg_r) + CURRENT_KTS * math.cos(cur_r)
        sog = math.sqrt(bx ** 2 + by ** 2)
        cog = _norm360(math.degrees(math.atan2(bx, by)))
        return sog, cog

    @staticmethod
    def _dead_reckon(lat: float, lon: float, sog_kts: float,
                     cog_deg: float, dt_s: float) -> tuple[float, float]:
        return dead_reckon(lat, lon, sog_kts, cog_deg, dt_s)

    def _depth_at(self, lat: float, lon: float) -> float:
        if not self._depth:
            return 50.0
        best = min(self._depth, key=lambda p: haversine_nm(lat, lon, p["lat"], p["lon"]))
        return best["depth_m"]
