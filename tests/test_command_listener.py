# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from yey.boats.simulator.engine.command_listener import CommandHandler  # type: ignore[import]
from yey.boats.simulator.engine.autopilot import Autopilot  # type: ignore[import]

COMMAND_PATH = "steering.autopilot.command"


def _delta(value, source="KDCube Navigator"):
    return {"context": "vessels.self", "updates": [
        {"$source": source, "values": [{"path": COMMAND_PATH, "value": value}]}]}


def test_applies_set_heading():
    ap = Autopilot()
    h = CommandHandler(ap, lambda: (90.0, 200.0))
    h.on_delta(_delta({"action": "set_heading", "value": 1.0, "nonce": "a"}))
    assert ap.state.mode == "auto" and ap.state.engaged


def test_ignores_self_source():
    ap = Autopilot()
    h = CommandHandler(ap, lambda: (90.0, 200.0))
    h.on_delta(_delta({"action": "disengage", "nonce": "b"}, source="simulator.py"))
    assert ap.state.engaged is True  # unchanged (self-source ignored)


def test_dedupes_repeated_nonce():
    ap = Autopilot()
    h = CommandHandler(ap, lambda: (90.0, 200.0))
    h.on_delta(_delta({"action": "adjust", "value": 0.1, "nonce": "n1"}))
    first = ap.state.target_heading_deg
    h.on_delta(_delta({"action": "adjust", "value": 0.1, "nonce": "n1"}))  # duplicate
    assert ap.state.target_heading_deg == first  # not applied twice


def test_ignores_other_paths_and_malformed():
    ap = Autopilot()
    h = CommandHandler(ap, lambda: (90.0, 200.0))
    h.on_delta({"updates": [{"$source": "x", "values": [
        {"path": "navigation.headingTrue", "value": 1.0}]}]})  # wrong path
    h.on_delta({"updates": [{"$source": "x", "values": [
        {"path": COMMAND_PATH, "value": "not-a-dict"}]}]})  # malformed
    assert ap.state.mode == "route"  # nothing applied


def test_value_converted_radians_to_degrees():
    import math
    ap = Autopilot()
    h = CommandHandler(ap, lambda: (90.0, 200.0))
    h.on_delta(_delta({"action": "set_heading", "value": math.radians(123.0), "nonce": "r"}))
    assert abs(ap.state.target_heading_deg - 123.0) < 1e-6
