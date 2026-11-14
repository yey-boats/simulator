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

// A fake SignalK app whose self model is `model` (path -> node). Like the real
// server (src/interfaces/plugins.ts), registerPutHandler queues a de-register
// on the plugin's stop handlers, so `stopPlugin` removes every PUT handler.
function fakeApp (model = {}) {
  const app = {
    model,
    handlers: {},
    onStop: [],
    messages: [],
    statuses: [],
    errors: [],
    registerPutHandler (context, path, fn, source) {
      assert.equal(source, PLUGIN_ID)
      app.handlers[path] = fn
      app.onStop.push(() => { if (app.handlers[path] === fn) delete app.handlers[path] })
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

// What the server does on a config save / disable: plugin.stop(), then the
// queued stop handlers (which drop the PUT handlers).
function stopPlugin (app, plugin) {
  plugin.stop()
  app.onStop.splice(0).forEach((f) => f())
}

// The server answers 405 for a path with no PUT handler.
const put = (app, path, value) => {
  const fn = app.handlers[path]
  return fn ? fn('vessels.self', path, value, () => {}) : { state: 'COMPLETED', statusCode: 405 }
}
// Injectable wall clock; simNode timestamps are "now" on it.
let clock = Date.parse('2026-11-10T12:00:00Z')
const now = () => clock
const MIN = 60 * 1000
const lastStatus = (app) => app.statuses[app.statuses.length - 1]
const iso = (t) => new Date(t).toISOString()
const simNode = (value, t = clock) => ({ value, $source: SIM_SOURCE, timestamp: iso(t) })
const realNode = (value) => ({ value, $source: 'n2k-on-ve.can-socket.204', timestamp: '2026-11-10T00:00:00Z' })

test('schema exposes a simulation option that defaults to false', () => {
  const schema = makePlugin(fakeApp()).schema()
  assert.equal(schema.properties.simulation.type, 'boolean')
  assert.equal(schema.properties.simulation.default, false)
})

test('real boat (no simulator data): no PUT handlers, status says why', () => {
  const app = fakeApp({ 'navigation.position': realNode({ latitude: 1, longitude: 2 }) })
  const plugin = makePlugin(app, { now })
  plugin.start({})
  assert.deepEqual(Object.keys(app.handlers), [])
  assert.match(lastStatus(app), /not handling autopilot PUTs/i)
  assert.match(lastStatus(app), /simulator/i)
  plugin.stop()
})

test('no getSelfPath at all: refuses (fails closed)', () => {
  const app = fakeApp()
  delete app.getSelfPath
  const plugin = makePlugin(app, { now })
  plugin.start({})
  assert.deepEqual(Object.keys(app.handlers), [])
  plugin.stop()
})

test('simulation: false is the same as unset', () => {
  const app = fakeApp()
  const plugin = makePlugin(app, { now })
  plugin.start({ simulation: false })
  assert.deepEqual(Object.keys(app.handlers), [])
  plugin.stop()
})

test('simulator detected from its $source: handlers registered at start', () => {
  const app = fakeApp({ 'navigation.position': simNode({ latitude: 1, longitude: 2 }) })
  const plugin = makePlugin(app, { now })
  plugin.start({})
  assert.deepEqual(Object.keys(app.handlers).sort(), Object.values(PATHS).sort())
  assert.match(lastStatus(app), /simulat/i)
  plugin.stop()
})

test('simulator detected via the multi-source `values` map too', () => {
  const app = fakeApp({
    'navigation.position': {
      ...realNode({ latitude: 1, longitude: 2 }),
      values: { [SIM_SOURCE]: { value: { latitude: 1, longitude: 2 }, timestamp: iso(clock) } }
    }
  })
  const plugin = makePlugin(app, { now })
  plugin.start({})
  assert.ok(app.handlers[PATHS.state])
  plugin.stop()
})

test('simulator that starts after SignalK is picked up by the re-check', () => {
  const app = fakeApp({})
  const plugin = makePlugin(app, { now })
  plugin.start({})
  assert.deepEqual(Object.keys(app.handlers), [])
  app.model['steering.autopilot.state'] = simNode('route')
  plugin._recheck() // what the periodic timer calls
  assert.ok(app.handlers[PATHS.state])
  plugin.stop()
})

test('simulation: true registers without detection and says so', () => {
  const app = fakeApp({})
  const plugin = makePlugin(app, { now })
  plugin.start({ simulation: true })
  assert.ok(app.handlers[PATHS.adjustHeading])
  assert.match(lastStatus(app), /simulation option/i)
  plugin.stop()
})

test('every answer is marked simulated', () => {
  const app = fakeApp({ 'steering.autopilot.state': simNode('route') })
  const plugin = makePlugin(app, { now })
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

test('config save (stop + start) with the sim present: handlers re-registered, PUT 200', () => {
  const app = fakeApp({ 'steering.autopilot.state': simNode('route') })
  const plugin = makePlugin(app, { now })
  plugin.start({})
  assert.equal(put(app, PATHS.state, 'auto').statusCode, 200)
  stopPlugin(app, plugin)
  assert.equal(put(app, PATHS.state, 'auto').statusCode, 405) // server dropped them
  plugin.start({})
  assert.deepEqual(Object.keys(app.handlers).sort(), Object.values(PATHS).sort())
  assert.equal(put(app, PATHS.state, 'auto').statusCode, 200)
  assert.match(lastStatus(app), /handling autopilot PUTs/)
  stopPlugin(app, plugin)
})

test('restart after the simulator is gone: nothing registered (server dropped the old handlers)', () => {
  const app = fakeApp({ 'steering.autopilot.state': simNode('route') })
  const plugin = makePlugin(app, { now })
  plugin.start({})
  stopPlugin(app, plugin)
  app.model = {} // simulator gone
  plugin.start({})
  assert.equal(put(app, PATHS.state, 'auto').statusCode, 405)
  assert.equal(app.messages.length, 0)
  assert.match(lastStatus(app), /not handling autopilot PUTs/i)
  stopPlugin(app, plugin)
})

test('un-detect: no fresh simulator data for 2 min -> 503 and status says so; resumes when it reappears', () => {
  const t0 = clock
  try {
    const app = fakeApp({ 'navigation.position': simNode({ latitude: 1, longitude: 2 }) })
    const plugin = makePlugin(app, { now })
    plugin.start({})
    assert.equal(put(app, PATHS.state, 'auto').statusCode, 200)
    // The sim disconnects: the server keeps its last value (same timestamp).
    clock += 1.5 * MIN
    plugin._recheck()
    assert.equal(put(app, PATHS.state, 'auto').statusCode, 200) // still within 2 min
    clock += 1 * MIN
    plugin._recheck()
    const res = put(app, PATHS.state, 'auto')
    assert.equal(res.statusCode, 503)
    assert.match(res.message, /simulator not seen/i)
    assert.match(lastStatus(app), /not handling autopilot PUTs/i)
    assert.match(lastStatus(app), /not seen/i)
    const sent = app.messages.length
    // The sim comes back: fresh data again.
    app.model['navigation.position'] = simNode({ latitude: 1, longitude: 2 })
    plugin._recheck()
    assert.equal(put(app, PATHS.state, 'auto').statusCode, 200)
    assert.equal(app.messages.length, sent + 1)
    assert.match(lastStatus(app), /handling autopilot PUTs/)
    stopPlugin(app, plugin)
  } finally { clock = t0 }
})

test('un-detect is checked on the PUT itself, not only by the timer', () => {
  const t0 = clock
  try {
    const app = fakeApp({ 'navigation.position': simNode({ latitude: 1, longitude: 2 }) })
    const plugin = makePlugin(app, { now })
    plugin.start({})
    clock += 3 * MIN // no recheck ran
    assert.equal(put(app, PATHS.state, 'auto').statusCode, 503)
    assert.equal(app.messages.length, 0)
    stopPlugin(app, plugin)
  } finally { clock = t0 }
})

test('stale simulator data left in the model at start is not "detected"', () => {
  const app = fakeApp({ 'navigation.position': simNode({ latitude: 1, longitude: 2 }, clock - 10 * MIN) })
  const plugin = makePlugin(app, { now })
  plugin.start({})
  assert.deepEqual(Object.keys(app.handlers), [])
  stopPlugin(app, plugin)
})

test('sim clock offset from wall time: a changing timestamp still counts as fresh', () => {
  const t0 = clock
  try {
    const simT = Date.parse('2025-06-01T08:00:00Z') // sim runs on its own clock
    const app = fakeApp({ 'navigation.position': simNode({ latitude: 1, longitude: 2 }, simT) })
    const plugin = makePlugin(app, { now })
    plugin.start({})
    assert.deepEqual(Object.keys(app.handlers), [])
    clock += 5000
    app.model['navigation.position'] = simNode({ latitude: 1, longitude: 2 }, simT + 5000)
    plugin._recheck()
    assert.equal(put(app, PATHS.state, 'auto').statusCode, 200)
    // ...and it goes stale once the timestamp stops changing for 2 min.
    clock += 2.5 * MIN
    plugin._recheck()
    assert.equal(put(app, PATHS.state, 'auto').statusCode, 503)
    stopPlugin(app, plugin)
  } finally { clock = t0 }
})

test('simulatorTimeoutMinutes option sets the un-detect window', () => {
  const t0 = clock
  try {
    const app = fakeApp({ 'navigation.position': simNode({ latitude: 1, longitude: 2 }) })
    const plugin = makePlugin(app, { now })
    plugin.start({ simulatorTimeoutMinutes: 10 })
    clock += 5 * MIN
    plugin._recheck()
    assert.equal(put(app, PATHS.state, 'auto').statusCode, 200)
    stopPlugin(app, plugin)
  } finally { clock = t0 }
})

test('simulation: true never un-detects', () => {
  const t0 = clock
  try {
    const app = fakeApp({})
    const plugin = makePlugin(app, { now })
    plugin.start({ simulation: true })
    clock += 60 * MIN
    plugin._recheck()
    assert.equal(put(app, PATHS.state, 'auto').statusCode, 200)
    stopPlugin(app, plugin)
  } finally { clock = t0 }
})

test('advanceWaypoint (connector allowlist): route mode only', () => {
  const app = fakeApp({ 'steering.autopilot.state': simNode('route') })
  const plugin = makePlugin(app, { now })
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

test('advanceWaypoint accepts only the value 1 (connector steering-policy parity)', () => {
  const app = fakeApp({ 'steering.autopilot.state': simNode('route') })
  const plugin = makePlugin(app, { now })
  plugin.start({})
  for (const v of [2, 0, -1, '1', true, null, 1.5, 'next']) {
    const res = put(app, PATHS.advanceWaypoint, v)
    assert.equal(res.statusCode, 400, `value ${JSON.stringify(v)}`)
    assert.match(res.message, /advanceWaypoint/)
  }
  assert.equal(app.messages.length, 0)
  assert.equal(put(app, PATHS.advanceWaypoint, 1).statusCode, 200)
  plugin.stop()
})

test('the connector steering-policy actions are all handled', () => {
  for (const p of ['adjustHeading', 'tack', 'advanceMode', 'advanceWaypoint']) {
    assert.equal(PATHS[p], `steering.autopilot.actions.${p}`)
  }
})
