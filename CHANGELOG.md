# Changelog

## 0.1.0 — unreleased
- Extracted from kdcube-embedded `signalk/sim` into the standalone
  `yey.boats.simulator` package (Phase B).
- Pluggable telemetry sinks behind a failover chain: SignalK + STDOUT-JSON.
- Canonical `TelemetrySnapshot` per-tick frame.
- Autopilot command input preserved via SignalKCommandSource.
- NMEA 0183 / NMEA 2000 sinks and SignalK data-source registered as stubs (Phase C).
