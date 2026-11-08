# signalk-yey-sim-autopilot

> **SIMULATOR ONLY.** Install this plugin only on the SignalK server that the
> yey.boats Python simulator feeds (the demo boat). Never install it on a real
> boat: it answers autopilot PUTs as `COMPLETED` but steers nothing except the
> simulator. A real boat uses its own autopilot plugin (e.g. `signalk-autopilot`
> or the vendor's plugin).

A small SignalK server plugin (plugin id **`yey-sim-autopilot`**) that turns the
standard SignalK autopilot PUTs sent by dashboards and the yey-display ESP32
firmware into the simulator's private command delta
`steering.autopilot.command = {action, value, nonce}`. The simulator subscribes
to that path on the SignalK stream
(`src/yey/boats/simulator/engine/command_listener.py`) and applies it to its
modeled autopilot (`engine/autopilot.py`).

## PUT paths handled (context `vessels.self`)

| PUT path | Accepted value | Emitted command |
|---|---|---|
| `steering.autopilot.state` | `"auto"`, `"wind"`, `"route"`, `"standby"`; firmware `"track"`/`"pretrack"` mean `"route"`; surrounding quotes are stripped | `set_mode` with the mode |
| `steering.autopilot.actions.adjustHeading` | finite number, **degrees** (e.g. `-10`, `1`) | `adjust` with **radians** |
| `steering.autopilot.target.headingTrue` | finite number, **radians** | `set_heading` with the radians unchanged |
| `steering.autopilot.actions.tack` | `"port"`, `"starboard"` or `true` | `tack` (value `"port"`/`"starboard"`, or `null` for `true`) |
| `steering.autopilot.actions.advanceMode` | any value | `set_mode` with the next mode in the cycle standby → auto → wind → route → standby |

`advanceMode` starts from the live `steering.autopilot.state` the simulator
publishes (read via `app.getSelfPath`). If that value is missing, it starts from
the last mode this plugin sent, and from `standby` if the plugin has sent none.

A valid PUT returns `{state: "COMPLETED", statusCode: 200}`. An invalid value
returns `statusCode: 400` with a message and sends nothing. While the plugin is
stopped, PUTs return 503.

The simulator converts radians back to degrees for `adjust` and `set_heading`.
The command delta's `$source` is the plugin id. The simulator ignores only
deltas from its own `simulator.py` source, so it receives these.

### The navigator returns to the route on its own

If a command takes the simulated boat out of `route` mode while it is following
its route, the simulator's navigator sets a timer. When `resume_route_after_s`
has passed with no further command, it switches back to `route` and steers back
onto the route. The default is 300 s. Set it with the `RESUME_ROUTE_AFTER_S`
env var, the web admin config or `--resume-route-after-s`, and use `0` to turn
the return off. Each new command restarts the timer. When the navigator returns
to the route, `steering.autopilot.state` changes back to `"route"`.

## Install on the demo SignalK server

The plugin has no runtime dependencies. SignalK loads plugins from the
`node_modules` folder of its config directory (`~/.signalk`, or
`/home/node/.signalk` in the official Docker image).

**From a checkout (npm link), for development:**

```sh
cd /path/to/simulator/signalk-plugin
npm link
cd ~/.signalk
npm link signalk-yey-sim-autopilot
# restart signalk-server
```

**Copy or install into the plugin directory (Docker or a server without a checkout):**

```sh
cd ~/.signalk            # in Docker: the volume mounted at /home/node/.signalk
npm install /path/to/simulator/signalk-plugin
# or: npm pack in signalk-plugin/, copy the .tgz over, npm install ./signalk-yey-sim-autopilot-0.1.0.tgz
# restart signalk-server
```

Then open the SignalK admin UI, go to *Server → Plugin Config*, find
**Yey Boats simulator autopilot (SIMULATOR ONLY)** and make sure it is enabled.

On that server, make sure no other plugin handles the same PUT paths. In
particular, do not also run `@signalk/signalk-autopilot` in emulator mode, or
an older `yey-boats-display-manager` that still contains its built-in
"autopilot bridge" (it was removed in favour of this plugin).

Quick check, with the simulator running:

```sh
curl -X PUT -H 'Content-Type: application/json' -d '{"value":"auto"}' \
  http://localhost:3000/signalk/v1/api/vessels/self/steering/autopilot/state
curl -X PUT -H 'Content-Type: application/json' -d '{"value":10}' \
  http://localhost:3000/signalk/v1/api/vessels/self/steering/autopilot/actions/adjustHeading
```

If the server has security enabled, add an auth token.

## Tests

```sh
cd signalk-plugin && npm test     # node --test, uses a fake `app`; no SignalK server needed
```

## License

PolyForm-Noncommercial-1.0.0, the same license as the rest of the simulator repo.
