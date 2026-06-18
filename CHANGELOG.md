# Changelog

## 0.1.0 — unreleased
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
