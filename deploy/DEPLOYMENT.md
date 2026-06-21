# yey.boats cloud demo — deployment task definition

This document is the **deployment task definition** for the autorouting demo
stack. It describes the services, images, configuration options, and
verification steps so an agent (or operator) with cloud/host access can deploy
or update the demo. It is a spec, not a script — adapt the container runtime
(plain `docker`, Compose, ECS/Fargate, Nomad…) to the target.

## What the demo shows

A simulated yacht in the Adriatic/Ionian that **continuously lays autorouted
passages**: it picks a random navigable destination ~40–60 nM away, computes a
land-/shoal-avoiding route to it with A\* over GEBCO bathymetry, publishes that
route to SignalK, sails it, and on arrival lays the next one. Depth, course, and
the active route in SignalK update live.

## Services

Three containers on one network (the simulator must reach **both** SignalK and
the bathymetry server at runtime).

| Service | Image | Purpose |
|---|---|---|
| `signalk` | `signalk/signalk-server:latest` | SignalK server (+ display-manager plugin) |
| `bathy` | built from `yey-boats/simulator` `deploy/bathy-server/` | self-hosted GEBCO bathymetry API (no public quota) |
| `simulator` | `ghcr.io/yey-boats/simulator:latest` | the boat simulator (autorouting + random passages) |

### 1. `bathy` — bathymetry server

Tiny stdlib-only HTTP server (no GDAL). On first boot it loads a regional GEBCO
2020 grid from **NOAA CoastWatch ERDDAP** (one strided bbox request — no
per-point quota), caches it to its volume, and serves an OpenTopoData-compatible
API. Build context: `deploy/bathy-server/` (`Dockerfile` + `server.py`).
Runs on `arm64` and `amd64`; image is ~60 MB, cached grid for the default region
is a few MB.

- **Port:** `8089` (override `BATHY_PORT`)
- **Volume:** mount `/data` to persist the fetched grid across restarts
- **Region (env):** `BATHY_LAT_MIN/MAX`, `BATHY_LON_MIN/MAX` (defaults
  `36/46`, `12/20` — Adriatic + Ionian), `BATHY_STRIDE` (default `5` ≈ 2 km
  cells; `1` ≈ 450 m, ~25× the data/RAM)
- **Health:** `GET /health` → `{"status":"OK","cells":<n>}`; first boot is
  unhealthy for ~1–2 min while it fetches the grid (start-period 180 s)
- **Egress:** needs outbound HTTPS to `coastwatch.pfeg.noaa.gov` on first boot
  only (subsequent boots load from the cached volume)

### 2. `simulator` — boat simulator

Add these to the existing `boat-sim` environment to enable the demo:

| Env var | Demo value | Meaning |
|---|---|---|
| `GEOGRID_API_URL` | `http://bathy:8089/v1/gebco2020` | point depth/routing at the `bathy` service instead of the public OpenTopoData (avoids the 429 quota). Use the address by which the sim reaches `bathy` (service name on a Compose/ECS network, or `localhost` with host networking). |
| `RANDOM_PASSAGES` | `1` | enable random-passage mode |
| `PASSAGE_MIN_NM` | `40` | min passage length (nM) |
| `PASSAGE_MAX_NM` | `60` | max passage length (nM) |
| `PASSAGE_ARRIVAL_NM` | `1.0` | lay the next passage when within this distance of the destination |
| `PASSAGE_POLL_S` | `5` | how often the passage manager checks for arrival |
| `AUTOROUTE_MAX_CELLS` | `60000` | A\* search-area cap (raise from the public-API default of 8000 now that the local source has no quota) |
| `AUTOROUTE_MAX_NODES` | `300000` | A\* node-expansion cap |
| `AUTOROUTE_BBOX_MARGIN_DEG` | `0.3` | A\* search-box inflation per leg |

Existing env stays as-is: `SIGNALK_HOST`/`PORT`/`USERNAME`/`PASSWORD`,
`SIM_WEB_HOST`/`PORT`, `DATA_DIR`, `SINK=signalk`. Mount `/data` (`sim-data`
volume) so the GeoGrid cache persists.

**Leave `RANDOM_PASSAGES` unset** to keep the original fixed Adriatic-route
behavior (legs autorouted at startup + persisted).

## Reference deployment (Compose form)

```yaml
services:
  signalk:
    image: signalk/signalk-server:latest
    container_name: signalk-server
    ports: ["3000:3000"]
    volumes:
      - ./config:/home/node/.signalk

  bathy:
    build: ./deploy/bathy-server          # or a prebuilt image once published
    container_name: bathy
    environment:
      BATHY_PORT: "8089"
      BATHY_LAT_MIN: "36"
      BATHY_LAT_MAX: "46"
      BATHY_LON_MIN: "12"
      BATHY_LON_MAX: "20"
    volumes:
      - bathy-data:/data
    restart: unless-stopped

  simulator:
    image: ghcr.io/yey-boats/simulator:latest
    container_name: boat-sim
    depends_on: [signalk, bathy]
    environment:
      SIGNALK_HOST: signalk
      SIGNALK_PORT: "3000"
      SIGNALK_USERNAME: admin
      SIGNALK_PASSWORD: admin
      SIM_WEB_HOST: 0.0.0.0
      SIM_WEB_PORT: "8088"
      GEOGRID_API_URL: http://bathy:8089/v1/gebco2020
      RANDOM_PASSAGES: "1"
      PASSAGE_MIN_NM: "40"
      PASSAGE_MAX_NM: "60"
      AUTOROUTE_MAX_CELLS: "60000"
      AUTOROUTE_MAX_NODES: "300000"
    ports: ["8088:8088"]
    volumes:
      - sim-data:/data
    restart: unless-stopped

volumes:
  bathy-data:
  sim-data:
```

> The lab host (`mythra-nav`) runs the three as standalone `docker run`
> containers on `--network host` (so `GEOGRID_API_URL` uses `localhost:8089`).
> On a Compose/ECS network use the service name (`http://bathy:8089/...`).

## Verification

1. `bathy` healthy: `curl http://<bathy>:8089/health` → `cells` > 100000.
2. Simulator log shows: `random-passage mode: 40-60 nM autorouted passages`,
   then `passage: new <N> nM leg to (...), <k> wp` each time a passage is laid.
3. In SignalK: `vessels.self.navigation.course.*` and the active route resource
   update each passage; `environment.depth.belowKeel` reflects real bathymetry
   at the boat's position.

## Notes / caveats

- **Passage duration:** the sim runs in real time at sailing speed (~6 kn), so a
  40–60 nM passage takes **~7–10 hours** of wall-clock. This is a continuous,
  always-on demo, not a short showcase. For faster turnover, lower
  `PASSAGE_MIN_NM`/`MAX_NM` (e.g. 8–15 nM) — short legs also keep A\* well within
  the resolution where it routes cleanly.
- **Resolution limit:** at the default ~2 km grid (`BATHY_STRIDE=5`) the A\*
  router avoids open obstacles and coasts well but cannot thread the narrowest
  archipelago channels; passages that can't be routed cleanly are rejected and a
  new destination is drawn. `BATHY_STRIDE=1` (~450 m) improves this at ~25× the
  data/RAM — only worth it on a host with memory headroom.
- **First-boot egress:** `bathy` needs outbound HTTPS to NOAA ERDDAP once to
  build its grid; after that it is self-contained (cached in its volume).
- **Region:** keep the `bathy` bbox a superset of where the boat sails; a
  destination drawn outside the grid is treated as land and rejected.
