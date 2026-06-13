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

\* NMEA sinks are registered but not yet implemented (Phase C).

## Sinks & failover

The engine builds a neutral telemetry frame each tick and hands it to the active
sink. The default failover chain demotes SignalK -> SignalK@localhost -> stdout.

---

Powered by [KDCube](https://kdcube.tech/).
