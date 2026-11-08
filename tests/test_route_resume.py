# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Navigator return-to-course rule: after a manual autopilot override (a command
arriving from SignalK), the navigator re-engages route mode once
resume_route_after_s passes with no further command."""
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest  # type: ignore[import]

from yey.boats.simulator import resources  # type: ignore[import]
from yey.boats.simulator.config import Settings  # type: ignore[import]
from yey.boats.simulator.engine.engine import Engine  # type: ignore[import]
from yey.boats.simulator.engine.geogrid import GeoGrid  # type: ignore[import]
from yey.boats.simulator.engine.navigator import NavState, RouteResume  # type: ignore[import]
from yey.boats.simulator.engine.polars import Polars  # type: ignore[import]
from yey.boats.simulator.engine.route import Route  # type: ignore[import]
from yey.boats.simulator.engine.weather import DEFAULT_WEATHER, WeatherPoint  # type: ignore[import]
from yey.boats.simulator.web.api import _config_public, _validate_config  # type: ignore[import]

NOW = datetime(2026, 6, 14, 10, 0, 0, tzinfo=UTC)
DELAY = 10.0


@dataclass
class SteadyWx(WeatherPoint):
    """Deterministic wind (no gust/direction sampling) so headings are testable."""

    def sample(self) -> tuple[float, float]:
        return self.tws_kts, self.twd_deg


STEADY = SteadyWx(**{k: getattr(DEFAULT_WEATHER, k)
                     for k in DEFAULT_WEATHER.__dataclass_fields__})


class FakeData:
    async def get_weather(self, lat, lon, now): return STEADY
    async def twd_shift_next_6h(self, lat, lon, now): return 0.0
    async def mean_tws_next_6h(self, lat, lon, now): return STEADY.tws_kts


class FakeAIS:
    def get_contacts(self, lat, lon): return []


def _engine(delay=DELAY, route=None):
    route = route or Route.load(resources.route_kmz(), resources.marinas_json())
    start = NavState(lat=route.current.lat, lon=route.current.lon,
                     hdg_deg=route.current.berth_heading, cog_deg=0, sog_kts=0,
                     stw_kts=0, twa_deg=0, tws_kts=0, twd_deg=0, awa_deg=0,
                     aws_kts=0, heel_deg=0, depth_m=10.0)
    grid = GeoGrid(fetcher=lambda pts: [-10.0 for _ in pts])
    return Engine(route, Polars.load(resources.polar_csv()), FakeData(), FakeAIS(),
                  start_state=start, grid=grid, resume_route_after_s=delay)


async def _ticks(eng, n):
    for _ in range(n):
        await eng.tick(NOW)


def _route_heading(eng):
    tws, twd = STEADY.sample()
    brg = eng.route.bearing_to_next(eng.nav_state.lat, eng.nav_state.lon)
    return eng.nav.route_heading(eng.nav_state, brg, tws, twd, eng.sched.state)


def _ang(a, b):
    return abs(((a - b + 180) % 360) - 180)


# ── pure rule ────────────────────────────────────────────────────────────────

def test_rule_resumes_after_delay_and_only_once():
    r = RouteResume(5)
    r.on_command("route", "auto", route_active=True, now_s=100)
    assert r.armed
    assert not r.due("auto", True, 104)
    assert r.due("auto", True, 105)
    assert not r.armed
    assert not r.due("auto", True, 200)


def test_rule_ignores_commands_when_not_coming_from_route():
    r = RouteResume(5)
    r.on_command("auto", "standby", route_active=True, now_s=0)   # already manual
    assert not r.armed


def test_rule_operator_returning_to_route_disarms():
    r = RouteResume(5)
    r.on_command("route", "auto", route_active=True, now_s=0)
    r.on_command("auto", "route", route_active=True, now_s=1)
    assert not r.armed


# ── engine integration (sim clock, commands as they arrive from SignalK) ─────

@pytest.mark.asyncio
async def test_override_then_resume_after_delay():
    eng = _engine()
    await _ticks(eng, 3)
    eng.submit_command("adjust", 30.0)       # degrees (CommandHandler converts rad->deg)
    await _ticks(eng, 1)
    assert eng.autopilot.state.mode == "auto"
    await _ticks(eng, int(DELAY) - 1)
    assert eng.autopilot.state.mode == "auto"   # not yet
    await _ticks(eng, 1)
    assert eng.autopilot.state.mode == "route"
    assert eng.autopilot.state.engaged


@pytest.mark.asyncio
async def test_second_command_restarts_timer():
    eng = _engine()
    eng.submit_command("set_heading", 45.0)
    await _ticks(eng, 6)
    eng.submit_command("adjust", -10.0)     # 6 s in: restart the 10 s window
    await _ticks(eng, 9)
    assert eng.autopilot.state.mode == "auto"   # 15 s after first, 9 s after second
    await _ticks(eng, 2)
    assert eng.autopilot.state.mode == "route"


@pytest.mark.asyncio
async def test_disengage_also_resumes():
    eng = _engine()
    eng.submit_command("disengage", None)
    await _ticks(eng, 1)
    assert eng.autopilot.state.mode == "standby"
    await _ticks(eng, int(DELAY) + 1)
    assert eng.autopilot.state.mode == "route"


@pytest.mark.asyncio
async def test_delay_zero_never_resumes():
    eng = _engine(delay=0)
    eng.submit_command("set_mode", "wind")
    await _ticks(eng, 400)
    assert eng.autopilot.state.mode == "wind"


@pytest.mark.asyncio
async def test_no_active_route_no_resume():
    full = Route.load(resources.route_kmz(), resources.marinas_json())
    single = Route(waypoints=[full.waypoints[0]])      # nothing to return to
    eng = _engine(route=single)
    eng.submit_command("set_heading", 90.0)
    await _ticks(eng, int(DELAY) * 3)
    assert eng.autopilot.state.mode == "auto"


@pytest.mark.asyncio
async def test_resume_converges_heading_to_route():
    eng = _engine(delay=30)
    await _ticks(eng, 30)                         # settle on the route
    off = (_route_heading(eng) + 90.0) % 360       # steer well off course
    eng.submit_command("set_heading", off)
    await _ticks(eng, 30)
    assert eng.autopilot.state.mode == "auto"
    assert _ang(eng.nav_state.hdg_deg, off) < 5.0  # really overridden
    await _ticks(eng, 1)
    assert eng.autopilot.state.mode == "route"
    # Rejoin is turn-rate limited (no jump): the first ticks after resume move
    # by at most the slew cap, and within a few dozen ticks the boat is back on
    # the route heading (within the helm yaw-wander band).
    errs = []
    for _ in range(40):
        await _ticks(eng, 1)
        errs.append(_ang(eng.nav_state.hdg_deg, _route_heading(eng)))
    assert errs[0] > 30.0                          # still turning, not snapped
    assert max(errs[-10:]) < 5.0


# ── settings exposure ────────────────────────────────────────────────────────

def test_settings_default_env_and_persist(tmp_path, monkeypatch):
    assert Settings().resume_route_after_s == 300.0
    monkeypatch.setenv("RESUME_ROUTE_AFTER_S", "45")
    s = Settings.from_env()
    assert s.resume_route_after_s == 45.0
    s.save(tmp_path / "c.json")
    monkeypatch.delenv("RESUME_ROUTE_AFTER_S")
    assert Settings.from_file(tmp_path / "c.json").resume_route_after_s == 45.0


def test_web_api_exposes_and_validates_resume_delay():
    assert _config_public(Settings())["resume_route_after_s"] == 300.0
    changes, errors = _validate_config({"resume_route_after_s": 0})
    assert changes == {"resume_route_after_s": 0.0} and not errors
    for bad in (-1, "abc", None, True, float("nan")):
        _, errors = _validate_config({"resume_route_after_s": bad})
        assert "resume_route_after_s" in errors, bad


def test_cli_flag_sets_resume_delay(tmp_path, monkeypatch):
    from yey.boats.simulator.cli import build_settings  # type: ignore[import]
    monkeypatch.delenv("RESUME_ROUTE_AFTER_S", raising=False)
    s = build_settings(["--data-dir", str(tmp_path), "--resume-route-after-s", "0"])
    assert s.resume_route_after_s == 0.0
