# Phase-3 diagnostic signal modeling (with fault-injection hooks)

Status: **planned** (2026-06-22), not started. Follow-up to the diagnostic-signal
batch already shipped (PR #2: wind.directionTrue + 5 instruments; PR #3:
runTime + alternators.1.current + targetVmgToWaypoint).

Consumes/unblocks the navigator bundle's diagnostic catalog — see
`navigator-tg-bot/docs/superpowers/specs/2026-06-22-diagnostic-engine-and-catalog.md`
(rules P2 engine-overheat, E2 charging-fault root-cause, H2 gps-degraded,
P4 fouling, plus starter-bank crank checks).

## Why these need *modeling*, not just publishing

The signals below don't exist in the engine state today and, as **always-nominal**
values, would be decorative — they only enable anomaly *detection* if they can
**deviate**. So each gets (a) a small steady-state model and (b) a **fault-injection
hook** so the demo can trigger the exact anomaly the diagnostic is meant to catch.

## Fault-injection mechanism (shared)

Add a tiny `FaultState` (e.g. `engine/faults.py`) the engine holds, settable at
runtime so demos/tests can inject a fault and watch a diagnostic fire:

- **Source:** env (`SIM_FAULTS="raw_water_blocked,alternator_belt"` at boot) AND the
  existing command path (`command_listener` / web admin) so a fault can be toggled
  live. Mirror how `submit_command` already queues engine commands.
- **Shape:** `{fault_id: {active: bool, since: ts, severity: float}}`; pure, injected
  into the relevant model's `tick()`.
- Default: all clear (nominal). Faults are explicit, demo-driven.

## Signals + models + faults

| signal | units | nominal model | fault hook → diagnostic |
|---|---|---|---|
| `propulsion.main.oilPressure` | Pa | f(rpm): ~0 stopped, ~250 kPa idle → ~450 kPa cruise + small noise | `low_oil_pressure` drops it → **P2/oil-pressure alarm** |
| `propulsion.main.exhaustTemperature` (+ `.wetExhaustTemperature`) | K | f(rpm/load) + warmup curve (reuse `temperatures.ThermalModel`) | `raw_water_blocked` (impeller/strainer) spikes exhaust + coolant while RPM steady → **P2 engine-overheat cause** (the clean raw-water discriminator) |
| `electrical.alternators.1.current` (already shipped) + `…voltage` | A / V | from `alternator_w`/bus V | `alternator_belt` → current→0 while engine runs (couples coolant rise) → **E2 charging-fault root-cause** |
| `electrical.batteries.starter.{voltage,stateOfCharge,current}` | V/ratio/A | ~12.7 V float; crank dip on engine start; alternator recharge while running | `weak_starter` → deep crank dip / slow recovery → **starter-bank health** |
| `navigation.gnss.{satellites,horizontalDilution,methodQuality,antennaAltitude}` | count/—/str/m | 8–13 sats, HDOP 0.6–1.5, "GNSS Fix" + noise | `gps_degraded` (marina/bridge) → sats↓ HDOP↑ quality→"no fix" + position jitter → **H2 gps-degraded** |
| `navigation.rateOfTurn` | rad/s | heading delta per tick (thread prev heading; normalize ±180) | (no fault; helm-activity correlate for N2 course-drift) |
| `propulsion.main.transmission.oilTemperature` / `.oilPressure` *(opt)* | K/Pa | thermal model | optional gearbox fault |

Fouling (**P4**) needs no new signal — it's a *trend* on the already-published
`speedThroughWater`/RPM/`fuel.rate`; gated only on logging + history (done).

## Wiring (per the established pattern)

For each signal: a `_v(path, value)` in `_build_vessel_delta` (gated on `next_wp`/engine
state where relevant) + a `_METADATA` entry; modeled values come from the engine
modules (`temperatures.py`, `electrical.py`, a new small model for gnss/starter),
threaded through `engine.tick → TelemetrySnapshot → SignalK sink → writer` exactly
like `runTime` (PR #3). `rateOfTurn` reuses the prev-heading already available in
`engine.tick` (line ~116).

## Tests

- Each model: nominal range + monotonic warmup where applicable.
- Each fault: assert the signal deviates in the expected direction when the fault
  is active, and recovers when cleared.
- A small integration test per high-value pair (e.g. `raw_water_blocked` ⇒ exhaust
  + coolant rise at steady RPM) so the navigator diagnostic has a reproducible fixture.

## Suggested order (value × effort)

1. **`oilPressure` + `exhaustTemperature` + `raw_water_blocked` fault** → unlocks P2
   (engine-overheat cause), the highest-value engine diagnostic. Reuses ThermalModel.
2. **`alternator_belt` fault** (alternator current already published) → E2 root-cause;
   couple with coolant rise (shared-belt realism).
3. **`navigation.gnss.*` + `gps_degraded` fault** → H2 (very demo-friendly).
4. **`starter.*` + `weak_starter`** and **`rateOfTurn`** → lower priority.

## Notes
- Keep faults OFF by default; the demo is healthy unless a fault is injected.
- The navigator diagnostics for these (P2/E2/H2) are Phase-3 catalog entries — land
  the signals+faults here first so those rules have reproducible data to test against.
- Best done as one focused, fully-tested pass (the sim test suite runs locally);
  the background-subagent route is fine once the API isn't returning 529s.
