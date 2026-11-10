# Changelog

## 0.1.0 — unreleased
- `signalk-plugin/`: new SIMULATOR-ONLY SignalK server plugin
  `signalk-yey-sim-autopilot` (plugin id `yey-sim-autopilot`). It registers PUT
  handlers for `steering.autopilot.state`, `.actions.adjustHeading` (degrees),
  `.target.headingTrue` (radians), `.actions.tack` and `.actions.advanceMode`,
  and re-emits each one as the sim's `steering.autopilot.command` delta. It
  replaces the autopilot bridge that used to live in Instruments-manager.
  Tested with `node --test` against a fake `app`.
- Navigator return-to-course rule (`engine/navigator.py` `RouteResume`): when an
  autopilot command takes the boat out of route mode while a route is active,
  route mode is re-engaged once `resume_route_after_s` seconds (default 300,
  `0` = never) pass with no further command. The timer runs on the engine's sim
  clock. The setting can come from the `RESUME_ROUTE_AFTER_S` env var, the
  `--resume-route-after-s` flag, `config.json` and the web admin
  `/api/config`.
- `engine/current.py`: deterministic `tidal_current(now) -> (set_deg, drift_kts)`
  model — Adriatic NW→SE drift (150° ± 30°), drift half-wave-rectified so it
  reaches exactly 0 kn at the trough and peaks at 0.8 kn. Cycle is
  time-compressed (~8 min, vs the real ~12 h semi-diurnal) so the calm /
  zero-drift state is exercised within a demo/soak session.
- `TelemetrySnapshot` gains `current_set_deg` and `current_drift_kts` fields
  (default 0.0 so existing constructors are unaffected).
- `Engine.tick()` populates those fields each step from `tidal_current(now)`.
- `_build_vessel_delta` / `SignalKWriter.send_vessel_delta` accept a
  `current: tuple[float, float] | None` kwarg (set_rad, drift_m/s); when
  present, emits `environment.current.setTrue` (radians) and
  `environment.current.drift` (m/s) on the SELF vessel delta.
- `SignalKSink.publish()` converts snapshot degrees→radians and knots→m/s
  and forwards as the `current` kwarg.


- Extracted from kdcube-embedded `signalk/sim` into the standalone
  `yey.boats.simulator` package (Phase B).
- Pluggable telemetry sinks behind a failover chain: SignalK + STDOUT-JSON.
- Canonical `TelemetrySnapshot` per-tick frame.
- Autopilot command input preserved via SignalKCommandSource.
- NMEA 0183 / NMEA 2000 sinks and SignalK data-source registered as stubs (Phase C).
- Versioning (#15): one version, `pyproject.toml` `[project].version`, mirrored
  in `__version__`, `signalk-plugin/package.json` and this file (pinned by
  `tests/test_version.py`). `yey-boats-sim --version` prints it. The image
  carries it as the `org.opencontainers.image.version` label and the `SIM_VERSION`
  env. `release.yml` runs on `v*` tags. It first checks with
  `scripts/check_version.py` that the tag is `v<version>` and that this file has a
  dated `## <version> — YYYY-MM-DD` section. Then it publishes
  `ghcr.io/yey-boats/simulator:<x.y.z>`, `:<x.y>` and `:v<x.y.z>` and no longer
  moves `:latest`, which tracks main (ci.yml). See `docs/RELEASING.md`.
