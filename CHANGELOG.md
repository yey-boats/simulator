# Changelog

## 0.1.0 — unreleased
- Demo-boat equipment (`engine/signalk_writer.py`): six more fictional Rusty
  Boats devices, each with `/meta` source + description and live values so they
  show up in the navigator's `list_instruments`:
  RB-NORTH-ISH-9 magnetic compass (`navigation.headingMagnetic`,
  `.headingCompass`, `.magneticDeviation`, `.magneticVariation`; Adriatic WMM
  fit + swing-table deviation, exactly consistent with `headingTrue`),
  RB-SHOUTY-BOX-B Class B AIS transponder (`sensors.ais.*`: class, transmitting,
  navigational status, SOTDMA report interval, targets heard, antenna offsets),
  RB-CHATTY-CATHY-25 VHF/DSC (`communication.vhf.*`, `communication.dsc.*`),
  RB-BLIP-O-MATIC-4G radar (`sensors.radar.state|range|targetsTracked`,
  auto-range from AIS traffic), RB-CHILLY-WILLY fridge/freezer temperatures and
  RB-UMBILICAL-16 shore-power inlet (`electrical.shorePower.*`, unplugged: the
  sim anchors). `steering.autopilot.target.headingMagnetic` now applies the
  variation (was equal to true).
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
