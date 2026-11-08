// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const makePlugin = require('..')
const { PATHS, COMMAND_PATH, PLUGIN_ID } = makePlugin

function fakeApp ({ selfState } = {}) {
  const app = {
    handlers: {},
    messages: [],
    selfState,
    registerPutHandler (context, path, fn, source) {
      assert.equal(context, 'vessels.self')
      assert.equal(source, PLUGIN_ID)
      app.handlers[path] = fn
    },
    handleMessage (id, delta) { app.messages.push({ id, delta }) },
    debug () {},
    setPluginStatus () {}
  }
  if (selfState !== undefined) {
    app.getSelfPath = (path) => (path === PATHS.state ? app.selfState : undefined)
  }
  return app
}

function started (opts) {
  const app = fakeApp(opts)
  const plugin = makePlugin(app)
  plugin.start({})
  return { app, plugin, put: (path, value) => app.handlers[path]('vessels.self', path, value, () => {}) }
}

// The command value of the n-th emitted delta (default: the last one).
function command (app, n = app.messages.length - 1) {
  const { id, delta } = app.messages[n]
  assert.equal(id, PLUGIN_ID)
  const [v] = delta.updates[0].values
  assert.equal(v.path, COMMAND_PATH)
  return v.value
}

test('plugin metadata', () => {
  const plugin = makePlugin(fakeApp())
  assert.equal(plugin.id, 'yey-sim-autopilot')
  assert.equal(typeof plugin.schema().properties, 'object')
})

test('registers a PUT handler for every autopilot path on start', () => {
  const { app } = started()
  assert.deepEqual(Object.keys(app.handlers).sort(), Object.values(PATHS).sort())
})

test('state: plain modes map to set_mode', () => {
  const { app, put } = started()
  for (const mode of ['auto', 'wind', 'route', 'standby']) {
    assert.deepEqual(put(PATHS.state, mode), { state: 'COMPLETED', statusCode: 200 })
    const c = command(app)
    assert.equal(c.action, 'set_mode')
    assert.equal(c.value, mode)
    assert.ok(c.nonce)
  }
})

test('state: firmware track/pretrack -> route, quotes stripped', () => {
  const { app, put } = started()
  put(PATHS.state, 'track')
  assert.equal(command(app).value, 'route')
  put(PATHS.state, 'pretrack')
  assert.equal(command(app).value, 'route')
  put(PATHS.state, '"auto"')
  assert.equal(command(app).value, 'auto')
})

test('state: unknown mode -> 400 and nothing emitted', () => {
  const { app, put } = started()
  for (const v of ['nav', '', null, 3, true]) {
    assert.equal(put(PATHS.state, v).statusCode, 400)
  }
  assert.equal(app.messages.length, 0)
})

test('adjustHeading: degrees in, radians out', () => {
  const { app, put } = started()
  assert.equal(put(PATHS.adjustHeading, 10).statusCode, 200)
  let c = command(app)
  assert.equal(c.action, 'adjust')
  assert.ok(Math.abs(c.value - (10 * Math.PI) / 180) < 1e-12)
  put(PATHS.adjustHeading, '-1')
  c = command(app)
  assert.ok(Math.abs(c.value + Math.PI / 180) < 1e-12)
})

test('adjustHeading: non-finite -> 400', () => {
  const { app, put } = started()
  for (const v of [NaN, Infinity, 'abc', null, '', true, {}]) {
    assert.equal(put(PATHS.adjustHeading, v).statusCode, 400, `value ${String(v)}`)
  }
  assert.equal(app.messages.length, 0)
})

test('target.headingTrue: radians passed through to set_heading', () => {
  const { app, put } = started()
  assert.equal(put(PATHS.headingTrue, 1.5).statusCode, 200)
  assert.deepEqual([command(app).action, command(app).value], ['set_heading', 1.5])
  assert.equal(put(PATHS.headingTrue, 'x').statusCode, 400)
  assert.equal(app.messages.length, 1)
})

test('tack: port / starboard / true accepted, others 400', () => {
  const { app, put } = started()
  assert.equal(put(PATHS.tack, 'port').statusCode, 200)
  assert.deepEqual([command(app).action, command(app).value], ['tack', 'port'])
  put(PATHS.tack, 'starboard')
  assert.equal(command(app).value, 'starboard')
  put(PATHS.tack, true)
  assert.deepEqual([command(app).action, command(app).value], ['tack', null])
  assert.equal(put(PATHS.tack, 'left').statusCode, 400)
  assert.equal(put(PATHS.tack, false).statusCode, 400)
  assert.equal(app.messages.length, 3)
})

test('advanceMode: cycles from the last mode this plugin saw', () => {
  const { app, put } = started()
  const seen = []
  for (let i = 0; i < 5; i++) {
    put(PATHS.advanceMode, 1)
    seen.push(command(app).value)
  }
  // no prior mode -> treated as standby
  assert.deepEqual(seen, ['auto', 'wind', 'route', 'standby', 'auto'])
  put(PATHS.state, 'wind')
  put(PATHS.advanceMode, 1)
  assert.equal(command(app).value, 'route')
})

test('advanceMode: prefers the live steering.autopilot.state from getSelfPath', () => {
  const { app, put } = started({ selfState: { value: 'route' } })
  put(PATHS.advanceMode, 1)
  assert.deepEqual([command(app).action, command(app).value], ['set_mode', 'standby'])
  app.selfState = 'auto' // bare value form
  put(PATHS.advanceMode, 1)
  assert.equal(command(app).value, 'wind')
  app.selfState = undefined // unknown -> fall back to last seen ('wind')
  put(PATHS.advanceMode, 1)
  assert.equal(command(app).value, 'route')
})

test('nonces are unique per command', () => {
  const { app, put } = started()
  put(PATHS.state, 'auto')
  put(PATHS.state, 'auto')
  assert.notEqual(command(app, 0).nonce, command(app, 1).nonce)
})

test('after stop, PUTs are refused (503) and nothing is emitted', () => {
  const { app, plugin, put } = started()
  plugin.stop()
  assert.equal(put(PATHS.state, 'auto').statusCode, 503)
  assert.equal(app.messages.length, 0)
})

test('start without registerPutHandler does not throw', () => {
  const plugin = makePlugin({ handleMessage () {}, error () {} })
  assert.doesNotThrow(() => plugin.start({}))
})
