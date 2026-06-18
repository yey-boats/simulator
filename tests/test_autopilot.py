# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from yey.boats.simulator.engine.autopilot import Autopilot, MODES  # type: ignore[import]


def test_defaults_engaged_route():
    ap = Autopilot()
    assert ap.state.engaged is True
    assert ap.state.mode == "route"  # follows the active route by default


def test_default_follows_route_heading():
    ap = Autopilot()
    hdg = ap.effective_heading(route_heading_deg=123, current_heading_deg=42, twd_deg=200)
    assert hdg == 123  # engaged+route by default → follow route


def test_disengaged_holds_current_heading():
    ap = Autopilot()
    ap.apply("disengage", None, current_heading_deg=42, twd_deg=200)
    hdg = ap.effective_heading(route_heading_deg=10, current_heading_deg=42, twd_deg=200)
    assert hdg == 42  # standby/disengaged → hold current


def test_route_mode_follows_route_heading():
    ap = Autopilot()
    ap.apply("set_mode", "route", current_heading_deg=42, twd_deg=200)
    hdg = ap.effective_heading(route_heading_deg=123, current_heading_deg=42, twd_deg=200)
    assert hdg == 123


def test_set_heading_engages_auto_and_holds():
    ap = Autopilot()
    ap.apply("set_heading", 90.0, current_heading_deg=42, twd_deg=200)
    assert ap.state.engaged and ap.state.mode == "auto"
    hdg = ap.effective_heading(route_heading_deg=123, current_heading_deg=42, twd_deg=200)
    assert hdg == 90.0  # ignores route


def test_engage_no_mode_defaults_auto_to_current():
    ap = Autopilot()
    ap.apply("engage", None, current_heading_deg=77, twd_deg=200)
    assert ap.state.mode == "auto"
    assert ap.effective_heading(route_heading_deg=5, current_heading_deg=77, twd_deg=200) == 77


def test_adjust_relative_to_target_with_wrap():
    ap = Autopilot()
    ap.apply("set_heading", 355.0, current_heading_deg=0, twd_deg=200)
    ap.apply("adjust", 10.0, current_heading_deg=355, twd_deg=200)
    assert ap.state.target_heading_deg == 5.0  # 365 wraps to 5


def test_wind_mode_holds_wind_angle():
    ap = Autopilot()
    # wind FROM 200, want TWA +30 (stbd) -> heading = twd - twa = 170
    ap.apply("set_mode", "wind", current_heading_deg=170, twd_deg=200)
    ap.state.target_wind_angle_deg = 30.0
    hdg = ap.effective_heading(route_heading_deg=0, current_heading_deg=170, twd_deg=200)
    assert abs(hdg - 170.0) < 1e-9


def test_tack_in_wind_mode_flips_sign():
    ap = Autopilot()
    ap.apply("set_mode", "wind", current_heading_deg=170, twd_deg=200)
    ap.state.target_wind_angle_deg = 30.0
    ap.apply("tack", None, current_heading_deg=170, twd_deg=200)
    assert ap.state.target_wind_angle_deg == -30.0


def test_tack_in_auto_reflects_about_wind():
    ap = Autopilot()
    ap.apply("set_heading", 170.0, current_heading_deg=170, twd_deg=200)  # twa +30
    ap.apply("tack", None, current_heading_deg=170, twd_deg=200)
    # reflect about wind 200: 2*200 - 170 = 230  (twa -30)
    assert ap.state.target_heading_deg == 230.0


def test_disengage_returns_to_standby_current():
    ap = Autopilot()
    ap.apply("set_heading", 90.0, current_heading_deg=42, twd_deg=200)
    ap.apply("disengage", None, current_heading_deg=88, twd_deg=200)
    assert ap.state.engaged is False and ap.state.mode == "standby"
    assert ap.effective_heading(route_heading_deg=1, current_heading_deg=88, twd_deg=200) == 88


def test_rudder_proportional_and_clamped():
    ap = Autopilot()
    ap.update_rudder(prev_hdg_deg=0, new_hdg_deg=100)  # big error
    assert ap.state.rudder_deg == 35.0  # clamped to MAX_RUDDER_DEG
    ap.update_rudder(prev_hdg_deg=100, new_hdg_deg=100)  # on course → decays
    assert abs(ap.state.rudder_deg) < 35.0


def test_unknown_action_ignored():
    ap = Autopilot()
    ap.apply("frobnicate", 1, current_heading_deg=10, twd_deg=200)
    assert ap.state.mode == "route" and ap.state.engaged is True  # unchanged


def test_modes_constant():
    assert MODES == ("standby", "auto", "wind", "route")
