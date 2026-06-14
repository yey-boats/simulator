# Phase C — Hexagonal Engine Core — Design

**Date:** 2026-06-14
**Status:** Approved (design); implementation plan to follow
**Repo:** `yey-boats-simulator` (branch `feat/engine-core`)
**Author:** Boris Sorochkin (with Claude)

## Goal

Refactor the simulator into a **hexagonal architecture** with a pure(ish),
deterministic, I/O-isolated **`Engine`** at the center and a thin **driver** around
it. The engine does no *direct* I/O (no `httpx`, no sockets, never reads the wall
clock) — all external data flows through **injected async ports**. This makes the
vessel physics fully unit-testable with fake ports + an injected clock, and unifies
all output (vessel state **and** AIS contacts) into a single `TelemetrySnapshot`
frame per tick.

This is **Phase C, cycle 1** ("the core"). It also lands a real **`SignalKDataSource`**
(weather from a SignalK server) alongside the Open-Meteo source. NMEA 0183/2000
encoders and serial command input remain future Phase C cycles.

## Decisions (from brainstorming)

| Topic | Decision |
| --- | --- |
| Scope this cycle | Engine core **+ real `SignalKDataSource`**. NMEA/serial deferred. |
| Determinism | **I/O-free engine, clock injected.** RNG *not* seeded (synthetic AIS stays random). |
| Weather boundary | **Engine holds an async `DataSource` port** and awaits it inside `tick()`. |
| AIS | **Folded into the engine/snapshot** — engine samples an `AISSource` each tick and emits contacts in the frame. |
| Migration strategy | **Big-bang extraction** (A): build the engine + ports + AIS-in-frame + `SignalKDataSource`, rewrite the runner→driver, swap in one cycle. Engine unit tests + the stdout smoke are the regression gate. |
| `DataSource` scope | **Per-tick weather only** (`get_weather` + the two 6 h lookaheads). Route/depth/maps stay a **startup-time** concern (loaded once at engine construction; `SignalKDataSource` may optionally supply them at startup). |
| Where it lives | Standalone repo, branch `feat/engine-core` → PR into `main`. |

## Background — what exists today (Phase B)

`engine/runner.py:run(settings)` interleaves three concerns in one `sim_loop`:

- **Non-determinism:** `datetime.now(timezone.utc)`, `time.monotonic()`, `asyncio.sleep`.
- **Direct I/O:** `await chain.open/publish`, `await writer.*` (SignalK transport),
  `await weather.get/twd_shift_next_6h/mean_tws_next_6h` (network).
- **Pure physics:** the module `.tick(...)` calls (`nav`, `elec`, `sys_`, `lights`,
  `thermal`, `autopilot`, `sched`) — already state-in/state-out.

AIS runs as independent side-tasks (`ais.run()`, `synth.run()`) that feed
`writer.enqueue_ais(...)` directly, outside the frame. The output goes through the
`SinkChain` (`SignalKSink`/`StdoutJsonSink`); the autopilot command channel comes in
via `SignalKCommandSource`.

Confirmed signatures the design builds on:
- `WeatherFetcher.get(lat,lon,now) -> WeatherPoint`, `.mean_tws_next_6h(lat,lon,now) -> float`,
  `.twd_shift_next_6h(lat,lon,now) -> float`.
- `WeatherPoint` (engine/weather.py): `.sample() -> (tws_kts, twd_deg)`, `.wave_height_m`,
  `.cloud_cover`, `.temp_c`, plus `tws_ms/twd_deg/gust_ms/wave_period_s/...`.
- `SignalKWriter.enqueue_ais(mmsi, lat, lon, cog_deg, sog_kts, name, ship_type)`.

## Architecture

### Ports (extend `ports/`)

- **`DataSource`** (async, weather) — exactly the three weather calls the loop makes:
  - `async get_weather(lat, lon, now) -> WeatherPoint`
  - `async twd_shift_next_6h(lat, lon, now) -> float`
  - `async mean_tws_next_6h(lat, lon, now) -> float`
  (Phase B shipped a `DataSource` stub with only `get_weather`; this widens it to the
  full weather contract.)
- **`AISSource`** (async) —
  - `async start() -> None` — long-running; maintains a live in-range contact set
    (from an AISStream WebSocket *or* a synthetic generator). Launched by the driver.
  - `get_contacts(lat, lon) -> list[AisContact]` — synchronous snapshot of current
    in-range contacts; the engine calls this each tick. (For synthetic, this advances
    and returns generated vessels; for AISStream, it returns the latest buffered set.)
- **`TelemetrySink`**, **`CommandSource`** — unchanged from Phase B.

### Adapters / implementations (`sources/`)

- **`OpenMeteoDataSource`** — wraps today's `WeatherFetcher` (Open-Meteo + caching +
  graceful degradation); implements `DataSource` verbatim.
- **`SignalKDataSource`** (new, real) — reads current weather from a SignalK server's
  environment paths (`environment.wind.speedTrue`/`directionTrue`,
  `environment.outside.temperature`, wave/cloud where present) via the SK REST API and
  builds a `WeatherPoint`. SignalK has **no forecast**, so `twd_shift_next_6h` →
  `0.0` and `mean_tws_next_6h` → the current TWS (neutral "no forecast" values). On
  read failure it degrades to `DEFAULT_WEATHER`/neutral, never raising into the engine.
  Use case: drive the sim's physics from a *real* boat's live instrument data.
- **`AISStreamSource`** — refactor of `ais_relay`: maintains contacts from the
  AISStream WS, returns them via `get_contacts`. **No longer writes to the SK writer.**
- **`SyntheticAISSource`** — refactor of `synthetic_ais`: generates/advances synthetic
  vessels around the own-ship position, returns them via `get_contacts`. Randomness is
  *not* seeded (per the determinism decision).

### `AisContact` (frame contact model)

New dataclass (in `engine/snapshot.py`, alongside `TelemetrySnapshot`), mirroring the
`enqueue_ais` arguments so sinks map 1:1:

```
AisContact: mmsi: str, lat: float, lon: float, cog_deg: float, sog_kts: float,
            name: str, ship_type: int
```

### `Engine` (`engine/engine.py`, new)

Owns the physics module instances (`route`, `polars`, `sched`, `nav`, `elec`, `sys_`,
`lights`, `thermal`, `autopilot`), the current `nav_state`, an injected `DataSource`
and `AISSource`, an `Autopilot`, and an in-memory **command queue**.

- Construction: `Engine(route, polars, data_source, ais_source, *, start_state)` —
  modules built from already-loaded route/polars (route/depth loaded at startup by the
  driver via `resources` or `SignalKDataSource`). `start_state` seeds `nav_state`
  (origin or a resumed position handed in by the driver).
- `def submit_command(cmd: dict) -> None` — the `CommandSource` calls this (via the
  driver) to enqueue autopilot commands; `tick` drains the queue and applies them to
  the `Autopilot`, preserving Phase B behavior.
- `async def tick(now) -> TelemetrySnapshot` — the **verbatim physics body** moved from
  `sim_loop`, with these substitutions only:
  - `now` is the injected parameter (no `datetime.now`).
  - weather comes from `await self._data.get_weather/twd_shift_next_6h/mean_tws_next_6h`.
  - autopilot commands are drained from the queue (not awaited from a listener).
  - AIS contacts come from `self._ais.get_contacts(lat, lon)` and are placed in the
    returned snapshot's `ais_contacts`.
  - returns the `TelemetrySnapshot` instead of calling a sink.
  The engine never opens a socket, never sleeps, never reads the wall clock.

### Driver (`engine/runner.py`, refactored)

`async def run(settings)` keeps only orchestration/transport:

1. Load route/polars/depth (startup); build the chosen `DataSource`
   (Open-Meteo or SignalK per `settings`) and `AISSource` (AISStream if
   `aisstream_api_key` else synthetic).
2. Open the `SinkChain`; if the active sink is SignalK, do position-resume +
   route-resource registration (transport concerns) and compute the engine's
   `start_state`.
3. Construct the `Engine` with the ports + `start_state`.
4. Launch side-tasks: `ais_source.start()`; SignalK-only `writer.flush_loop()`/
   `metadata_loop()`; `SignalKCommandSource` wired to `engine.submit_command`.
5. Main loop (the only place that touches the clock/cadence):
   `now = datetime.now(utc); snap = await engine.tick(now); await chain.publish(snap);
   sleep(1 - elapsed)`.

### Snapshot & sink changes

- `TelemetrySnapshot` gains `ais_contacts: list[AisContact] = field(default_factory=list)`.
- `SignalKSink.publish` — after `send_vessel_delta(...)`, emit each contact via
  `self.writer.enqueue_ais(c.mmsi, c.lat, c.lon, c.cog_deg, c.sog_kts, c.name, c.ship_type)`.
  (This replaces the old AIS side-tasks' direct writer calls.)
- `StdoutJsonSink.publish` — add `"ais": len(snapshot.ais_contacts)` (count) and, when
  contacts exist, a compact `"contacts"` list; keeps the legacy keys intact.

## Data flow (per tick)

```
driver: now = clock()
        snap = await engine.tick(now)
            engine: drain command queue → apply to autopilot
                    wx       = await data_source.get_weather(lat,lon,now)
                    shift    = await data_source.twd_shift_next_6h(...)   (when due)
                    meanTWS  = await data_source.mean_tws_next_6h(...)    (when departing)
                    <verbatim physics: arrival, departure, nav.tick, elec/sys/lights/thermal>
                    contacts = ais_source.get_contacts(lat,lon)
                    return TelemetrySnapshot(... ais_contacts=contacts)
        await sink_chain.publish(snap)        # SignalK deltas + enqueue_ais, or stdout JSON
        sleep(1 - elapsed)
meanwhile (driver side-tasks): ais_source.start(); writer.flush_loop/metadata_loop;
                               SignalKCommandSource → engine.submit_command
```

## Error handling

- Engine awaits ports inside `tick`; port impls **must not raise into the engine** —
  they degrade (Open-Meteo already returns last-known/`DEFAULT_WEATHER`;
  `SignalKDataSource` degrades to neutral; `AISSource.get_contacts` returns `[]` on
  any internal error). The engine keeps the Phase B `try/except` guards around weather
  calls as a backstop so one bad tick never stops the loop.
- Driver retains today's non-fatal guards (route-resource upload, `advance_active_point`).

## Testing (the big-bang regression gate)

1. **Engine unit tests** (the core win) — construct an `Engine` with a **`FakeDataSource`**
   (returns scripted `WeatherPoint`s + fixed lookahead values) and a **`FakeAISSource`**
   (returns a fixed contact list), feed an **injected fixed `now`** across several ticks,
   and assert: the vessel advances, state transitions fire, `ais_contacts` appear in the
   snapshot, and submitted commands change autopilot behavior. No network, no clock.
2. **Sink tests** — `SignalKSink` calls `enqueue_ais` once per contact; `StdoutJsonSink`
   emits the `ais` count (+ contacts) while preserving all legacy keys.
3. **Source tests** — `SignalKDataSource` builds a `WeatherPoint` from a fake SK env
   payload and returns neutral lookahead values; `SyntheticAISSource.get_contacts`
   returns plausible in-range vessels.
4. **Migrated physics tests** — unchanged, stay green (the modules are not modified).
5. **Integration gate** — the Phase B `yey-boats-sim --sink stdout` smoke still produces
   valid per-tick JSON (now with an `ais` field); SignalK mode still publishes vessel +
   AIS deltas and reacts to autopilot commands.

## File plan

- New: `engine/engine.py` (`Engine`), `sources/open_meteo.py` (`OpenMeteoDataSource`),
  `sources/signalk_weather.py` (`SignalKDataSource`), `sources/ais.py`
  (`AISStreamSource`, `SyntheticAISSource`).
- Modify: `ports/__init__.py` (widen `DataSource`, add `AISSource`),
  `engine/snapshot.py` (add `AisContact` + `ais_contacts`), `engine/runner.py`
  (engine/driver split), `sinks/signalk.py` + `sinks/stdout_json.py` (emit contacts),
  `sinks/registry.py` / `config.py` (select the `DataSource` impl).
- Reuse (not rewritten): the physics modules and `signalk_writer.py` are untouched;
  `ais_relay.py`/`synthetic_ais.py` logic is refactored into `sources/ais.py` adapters.

## Non-goals (YAGNI this cycle)

- No NMEA 0183/2000 encoders, no serial command input (later Phase C cycles).
- No seeded-RNG bit-reproducibility (clock is injected; RNG is not).
- No per-tick route/depth/maps sourcing (startup-time only).
- No change to the physics numerics — the loop body is moved verbatim.

## Success criteria

1. `Engine.tick(now)` runs with fake ports + injected clock and produces deterministic
   vessel-physics snapshots (given fixed weather/AIS inputs) including `ais_contacts`.
2. `yey-boats-sim --sink stdout` behaves as in Phase B plus an `ais` field; SignalK mode
   publishes vessel **and** AIS deltas (via the snapshot) and still reacts to autopilot
   commands — no behavioral regression.
3. `SignalKDataSource` can drive the engine's weather from a SignalK server (selectable
   via config), degrading gracefully when readings/forecasts are absent.
4. The driver contains the *only* wall-clock read and the *only* sink/transport calls;
   the engine contains none.
5. Full suite green (existing 51 + new engine/source/sink tests); ruff clean; wheel +
   docker build unaffected.
