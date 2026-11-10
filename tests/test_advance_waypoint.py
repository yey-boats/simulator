# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""advance_waypoint command (#14): the sim-autopilot plugin translates the
SignalK `steering.autopilot.actions.advanceWaypoint` PUT (on the connector's
steering allowlist) into it. In route mode it skips to the next waypoint; in
any other mode it changes nothing."""
import pytest  # type: ignore[import]

from tests.test_route_resume import NOW, _engine  # type: ignore[import]


@pytest.mark.asyncio
async def test_advance_waypoint_in_route_mode_skips_to_next():
    eng = _engine()
    eng.autopilot.apply("set_mode", "route")
    before = eng.route.current_index
    eng.submit_command("advance_waypoint", 1)
    snap = await eng.tick(NOW)
    assert eng.route.current_index == (before + 1) % len(eng.route.waypoints)
    assert snap.point_index == eng.route.current_index
    # Not a manual override: the mode stays route, no return timer armed.
    assert eng.autopilot.state.mode == "route"
    assert not eng.nav.route_resume.armed


@pytest.mark.asyncio
async def test_advance_waypoint_outside_route_mode_is_ignored():
    eng = _engine()
    eng.autopilot.apply("set_mode", "auto")
    before = eng.route.current_index
    eng.submit_command("advance_waypoint", 1)
    await eng.tick(NOW)
    assert eng.route.current_index == before
    assert eng.autopilot.state.mode == "auto"
