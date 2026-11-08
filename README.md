# yey.boats.simulator

Physics-accurate Adriatic sailing boat simulator (Beneteau Oceanis 45) with
pluggable output sinks.

## Install

    pip install yey-boats-simulator

## Run

    # SignalK (default), with automatic failover to SignalK@localhost then stdout
    yey-boats-sim --signalk-host signalk-server --signalk-port 3000

    # Local JSON to stdout, no server needed
    yey-boats-sim --sink stdout --no-failover

    # Docker
    docker run --rm -e SIGNALK_HOST=signalk-server -v sim-data:/data \
      ghcr.io/<org>/yey-boats-simulator:latest

## Configuration

| Env | CLI | Default | Meaning |
| --- | --- | --- | --- |
| `SIGNALK_HOST` | `--signalk-host` | `localhost` | SignalK server host |
| `SIGNALK_PORT` | `--signalk-port` | `3000` | SignalK server port |
| `SIGNALK_USERNAME` | `--signalk-username` | `admin` | SignalK auth |
| `SIGNALK_PASSWORD` | `--signalk-password` | `admin` | SignalK auth |
| `AISSTREAM_API_KEY` | — | _(empty)_ | Real AIS feed; synthetic traffic if unset |
| `SINK` | `--sink` | `signalk` | `signalk` / `stdout` / `nmea0183`* / `nmea2000`* |
| `SINK_FAILOVER` | `--no-failover` | on | Failover chain signalk->localhost->stdout |
| `DATA_DIR` | `--data-dir` | `./run-data` | Writable dir for the depth cache |
| `RESUME_ROUTE_AFTER_S` | `--resume-route-after-s` | `300` | Seconds after the last manual autopilot override before the navigator returns to the route (`0` = never) |

\* NMEA sinks are registered but not yet implemented (Phase C).

## Sinks & failover

The engine builds a neutral telemetry frame each tick and hands it to the active
sink. The default failover chain demotes SignalK -> SignalK@localhost -> stdout.

## Autopilot control via SignalK

The simulated autopilot listens on the SignalK stream for the private delta
`steering.autopilot.command = {action, value, nonce}`. Dashboards and displays
send standard SignalK autopilot PUTs instead. The
[`signalk-plugin/`](signalk-plugin/README.md) directory holds the
SIMULATOR-ONLY SignalK plugin `signalk-yey-sim-autopilot` (plugin id
`yey-sim-autopilot`) that translates those PUTs into the command delta. Install
it only on the demo SignalK server, never on a real boat.

If a command takes the boat off its route (any mode other than `route`), the
navigator returns to the route on its own once `RESUME_ROUTE_AFTER_S` seconds
pass with no further command. It steers back toward the next waypoint, and
`steering.autopilot.state` changes back to `route`.

## License

© 2026 Yey Boats Project. All rights reserved except as expressly licensed (see
[`NOTICE`](NOTICE)).

Source-available under the **PolyForm Noncommercial License 1.0.0** (see
[`LICENSE`](LICENSE)). You may use, modify, and share it for **any noncommercial
purpose** — hobby, personal, research, education, and evaluation — at no cost.

**Commercial use requires a separate commercial license.** If you want to use
this in a product or service, or otherwise for commercial advantage, see
[`COMMERCIAL.md`](COMMERCIAL.md) to obtain one. This is *source-available*, not an
OSI "open source" license.

Contributions are accepted under the [Developer Certificate of Origin](CONTRIBUTING.md)
(a `Signed-off-by` line), which lets the project offer the commercial license.
