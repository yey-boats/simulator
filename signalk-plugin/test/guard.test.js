// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
'use strict'

// #14: the plugin must not answer autopilot PUTs on a real boat. It registers
// its PUT handlers only once it sees the simulator (deltas with the simulator's
// `$source`, "simulator.py") or when the `simulation: true` option is set, and
// every answer says it was simulated.

const test = require('node:test')
const assert = require('node:assert/strict')
const makePlugin = require('..')
const { PATHS, PLUGIN_ID, SIM_SOURCE } = makePlugin

// A fake SignalK app whose self model is `model` (path -> node).
function fakeApp (model = {}) {
  const app = {
    model,
    handlers: {},
    messages: [],
    statuses: [],
    errors: [],
    registerPutHandler (context, path, fn, source) {
      assert.equal(source, PLUGIN_ID)
      app.handlers[path] = fn
    },
    handleMessage (id, delta) { app.messages.push({ id, delta }) },
    getSelfPath (path) { return app.model[path] },
    debug () {},
    error () {},
    setPluginStatus (msg) { app.statuses.push(msg) },
    setPluginError (msg) { app.errors.push(msg) }
  }
  return app
}

const put = (app, path, value) => app.handlers[path]('vessels.self', path, value, () => {})
const lastStatus = (app) => app.statuses[app.statuses.length - 1]
const simNode = (value) => ({ value, $source: SIM_SOURCE, timestamp: '2026-11-10T00:00:00Z' })
const realNode = (value) => ({ value, $source: 'n2k-on-ve.can-socket.204', timestamp: '2026-11-10T00:00:00Z' })

test('schema exposes a simulation option that defaults to false', () => {
  const schema = makePlugin(fakeApp()).schema()
  assert.equal(schema.properties.simulation.type, 'boolean')
  assert.equal(schema.properties.simulation.default, false)
})

test('real boat (no simulator data): no PUT handlers, status says why', () => {
  const app = fakeApp({ 'navigation.position': realNode({ latitude: 1, longitude: 2 }) })
  const plugin = makePlugin(app)
  plugin.start({})
  assert.deepEqual(Object.keys(app.handlers), [])
  assert.match(lastStatus(app), /not handling autopilot PUTs/i)
  assert.match(lastStatus(app), /simulator/i)
  plugin.stop()
})

test('no getSelfPath at all: refuses (fails closed)', () => {
  const app = fakeApp()
  delete app.getSelfPath
  const plugin = makePlugin(app)
  plugin.start({})
  assert.deepEqual(Object.keys(app.handlers), [])
  plugin.stop()
})

test('simulation: false is the same as unset', () => {
  const app = fakeApp()
  const plugin = makePlugin(app)
  plugin.start({ simulation: false })
  assert.deepEqual(Object.keys(app.handlers), [])
  plugin.stop()
})

test('simulator detected from its $source: handlers registered at start', () => {
  const app = fakeApp({ 'navigation.position': simNode({ latitude: 1, longitude: 2 }) })
  const plugin = makePlugin(app)
  plugin.start({})
  assert.deepEqual(Object.keys(app.handlers).sort(), Object.values(PATHS).sort())
  assert.match(lastStatus(app), /simulat/i)
  plugin.stop()
})

test('simulator detected via the multi-source `values` map too', () => {
  const app = fakeApp({
    'navigation.position': {
      ...realNode({ latitude: 1, longitude: 2 }),
      values: { [SIM_SOURCE]: { value: { latitude: 1, longitude: 2 } } }
    }
  })
  const plugin = makePlugin(app)
  plugin.start({})
  assert.ok(app.handlers[PATHS.state])
  plugin.stop()
})

test('simulator that starts after SignalK is picked up by the re-check', () => {
  const app = fakeApp({})
  const plugin = makePlugin(app)
  plugin.start({})
  assert.deepEqual(Object.keys(app.handlers), [])
  app.model['steering.autopilot.state'] = simNode('route')
  plugin._recheck() // what the periodic timer calls
  assert.ok(app.handlers[PATHS.state])
  plugin.stop()
})

test('simulation: true registers without detection and says so', () => {
  const app = fakeApp({})
  const plugin = makePlugin(app)
  plugin.start({ simulation: true })
  assert.ok(app.handlers[PATHS.adjustHeading])
  assert.match(lastStatus(app), /simulation option/i)
  plugin.stop()
})

test('every answer is marked simulated', () => {
  const app = fakeApp({ 'steering.autopilot.state': simNode('route') })
  const plugin = makePlugin(app)
  plugin.start({})
  const okRes = put(app, PATHS.state, 'auto')
  assert.equal(okRes.statusCode, 200)
  assert.equal(okRes.simulated, true)
  assert.match(okRes.message, /simulat/i)
  const badRes = put(app, PATHS.state, 'nope')
  assert.equal(badRes.statusCode, 400)
  assert.equal(badRes.simulated, true)
  assert.match(badRes.message, /simulat/i)
  plugin.stop()
})

test('restart on a real boat: handlers left from an earlier sim start refuse', () => {
  const app = fakeApp({ 'steering.autopilot.state': simNode('route') })
  const plugin = makePlugin(app)
  plugin.start({})
  plugin.stop()
  app.model = {} // simulator gone
  plugin.start({})
  // SignalK cannot unregister PUT handlers; the stale ones must not answer 200.
  const res = put(app, PATHS.state, 'auto')
  assert.equal(res.statusCode, 503)
  assert.equal(app.messages.length, 0)
  plugin.stop()
})

test('advanceWaypoint (connector allowlist): route mode only', () => {
  const app = fakeApp({ 'steering.autopilot.state': simNode('route') })
  const plugin = makePlugin(app)
  plugin.start({})
  const res = put(app, PATHS.advanceWaypoint, 1)
  assert.equal(res.statusCode, 200)
  const [v] = app.messages[0].delta.updates[0].values
  assert.equal(v.value.action, 'advance_waypoint')
  app.model['steering.autopilot.state'] = simNode('auto')
  assert.equal(put(app, PATHS.advanceWaypoint, 1).statusCode, 400)
  assert.equal(app.messages.length, 1)
  plugin.stop()
})

test('the connector steering-policy actions are all handled', () => {
  for (const p of ['adjustHeading', 'tack', 'advanceMode', 'advanceWaypoint']) {
    assert.equal(PATHS[p], `steering.autopilot.actions.${p}`)
  }
})
