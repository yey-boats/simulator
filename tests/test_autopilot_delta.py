# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
import math
from yey.boats.simulator.engine.signalk_writer import _autopilot_values  # type: ignore[import]
from yey.boats.simulator.engine.autopilot import Autopilot  # type: ignore[import]


def _paths(values):
    return {v["path"]: v["value"] for v in values}


def test_autopilot_values_default_route():
    ap = Autopilot()
    p = _paths(_autopilot_values(ap, hdg_deg=90.0))
    assert p["steering.autopilot.state"] == "route"
    assert "steering.rudderAngle" in p


def test_autopilot_values_standby_when_disengaged():
    ap = Autopilot()
    ap.apply("disengage", None, current_heading_deg=90.0, twd_deg=200)
    p = _paths(_autopilot_values(ap, hdg_deg=90.0))
    assert p["steering.autopilot.state"] == "standby"


def test_autopilot_values_auto_publishes_target_heading():
    ap = Autopilot()
    ap.apply("set_heading", 90.0, current_heading_deg=90.0, twd_deg=200)
    p = _paths(_autopilot_values(ap, hdg_deg=90.0))
    assert p["steering.autopilot.state"] == "auto"
    assert abs(p["steering.autopilot.target.headingMagnetic"] - math.radians(90.0)) < 1e-9


def test_autopilot_values_wind_publishes_wind_angle():
    ap = Autopilot()
    ap.apply("set_mode", "wind", current_heading_deg=170.0, twd_deg=200)
    ap.state.target_wind_angle_deg = 30.0
    p = _paths(_autopilot_values(ap, hdg_deg=170.0))
    assert p["steering.autopilot.state"] == "wind"
    assert "steering.autopilot.target.windAngleApparent" in p


def test_autopilot_values_auto_publishes_target_heading_true():
    """Gap 1: firmware reads headingTrue; sim must emit it alongside headingMagnetic."""
    ap = Autopilot()
    ap.apply("set_heading", 135.0, current_heading_deg=135.0, twd_deg=200)
    p = _paths(_autopilot_values(ap, hdg_deg=135.0))
    # headingMagnetic must still be present (back-compat)
    assert "steering.autopilot.target.headingMagnetic" in p
    # headingTrue must now be present and equal (no variation model)
    assert "steering.autopilot.target.headingTrue" in p
    assert abs(p["steering.autopilot.target.headingTrue"]
               - p["steering.autopilot.target.headingMagnetic"]) < 1e-9
