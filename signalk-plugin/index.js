// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
'use strict'

// signalk-yey-sim-autopilot — SIMULATOR-ONLY autopilot PUT translator.
//
// Dashboards and the yey-display firmware drive the autopilot the standard
// SignalK way (signalk-autopilot / spec-16 style):
//   PUT steering.autopilot.state                 = "<mode>"
//   PUT steering.autopilot.actions.adjustHeading = <degrees>
//   PUT steering.autopilot.target.headingTrue    = <radians>
//   PUT steering.autopilot.actions.tack          = "port" | "starboard" | true
//   PUT steering.autopilot.actions.advanceMode   = <anything>
//   PUT steering.autopilot.actions.advanceWaypoint = 1   (route mode only)
// The yey.boats Python simulator's autopilot instead listens on the SignalK
// stream for a private `steering.autopilot.command` delta
// {action, value, nonce} (see src/yey/boats/simulator/engine/command_listener.py).
// This plugin registers PUT handlers for those paths and re-emits each one as
// the simulator's command delta, so the dashboard/device steering controls
// drive the modeled boat end-to-end.
//
// It is ONLY for the simulator's SignalK server. On a real boat these PUTs
// belong to the boat's real autopilot plugin; installing this there would
// answer PUTs as COMPLETED while steering nothing. So (#14) it registers its
// PUT handlers only once it sees the simulator on this server: the simulator
// writes every delta with `$source: "simulator.py"` (the same label its own
// command listener filters on). Until then, or on a real boat, it handles
// nothing and its plugin status says so. The simulator must also be LIVE: once
// no fresh `simulator.py` data has been seen for `simulatorTimeoutMinutes`
// (default 2), PUTs get 503 "simulator not seen" until it reappears (the server
// keeps the sim's last values after it disconnects, so presence alone is not
// enough). The `simulation: true` option skips detection for a sim setup that
// relabels its source. Every answer carries `simulated: true` and a
// "SIMULATED" message.

const PLUGIN_ID = 'yey-sim-autopilot'
const COMMAND_PATH = 'steering.autopilot.command'
// The $source the simulator stamps on its deltas (src/yey/boats/simulator/
// engine/signalk_writer.py; command_listener.py SELF_SOURCE).
const SIM_SOURCE = 'simulator.py'
// Paths the simulator always publishes; seeing one from SIM_SOURCE = simulator present.
const DETECT_PATHS = ['steering.autopilot.state', 'navigation.position', 'navigation.speedOverGround']
const RECHECK_MS = 5000
const DEFAULT_TIMEOUT_MIN = 2
const MODES = ['standby', 'auto', 'wind', 'route']
// advanceMode cycle: standby -> auto -> wind -> route -> standby
const NEXT_MODE = { standby: 'auto', auto: 'wind', wind: 'route', route: 'standby' }

const PATHS = {
  state: 'steering.autopilot.state',
  adjustHeading: 'steering.autopilot.actions.adjustHeading',
  headingTrue: 'steering.autopilot.target.headingTrue',
  tack: 'steering.autopilot.actions.tack',
  advanceMode: 'steering.autopilot.actions.advanceMode',
  advanceWaypoint: 'steering.autopilot.actions.advanceWaypoint'
}

const SIMULATED = 'SIMULATED: sent to the yey.boats simulator only, no real autopilot'
const ok = () => ({ state: 'COMPLETED', statusCode: 200, simulated: true, message: SIMULATED })
const bad = (message) => ({ state: 'COMPLETED', statusCode: 400, simulated: true, message: `${SIMULATED}; ${message}` })
const unavailable = (message) => ({ state: 'COMPLETED', statusCode: 503, simulated: true, message })

const isSimSource = (src) => typeof src === 'string' && (src === SIM_SOURCE || src.endsWith(`.${SIM_SOURCE}`))

// The timestamps of every simulator-written value on the detect paths, as
// {key: timestamp} (key = path + source). Fails closed: no getSelfPath, or any
// error, gives none.
function simulatorStamps (app) {
  const out = {}
  if (typeof app.getSelfPath !== 'function') return out
  for (const path of DETECT_PATHS) {
    try {
      const node = app.getSelfPath(path)
      if (!node || typeof node !== 'object') continue
      if (isSimSource(node.$source)) out[`${path}|${node.$source}`] = String(node.timestamp)
      if (node.values && typeof node.values === 'object') {
        for (const [src, v] of Object.entries(node.values)) {
          if (isSimSource(src)) out[`${path}|${src}`] = String(v && v.timestamp)
        }
      }
    } catch (e) { /* not detected */ }
  }
  return out
}

// True when the server's self model holds data the simulator wrote (fresh or not).
function simulatorDetected (app) {
  return Object.keys(simulatorStamps(app)).length > 0
}

// Mode string -> simulator mode, or null when not a valid mode.
// Strips surrounding quotes (some clients send a JSON-encoded string) and maps
// the firmware's "track"/"pretrack" onto the sim's "route".
function normaliseMode (value) {
  if (typeof value !== 'string') return null
  let mode = value.trim().replace(/^"|"$/g, '').trim().toLowerCase()
  if (mode === 'track' || mode === 'pretrack') mode = 'route'
  return MODES.includes(mode) ? mode : null
}

// Strict finite number: rejects null, '', booleans and NaN (Number(null) === 0
// would otherwise silently become a zero adjustment).
function toFinite (value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

// `deps.now` (wall clock, ms) is injectable for tests.
module.exports = function yeySimAutopilot (app, deps = {}) {
  const now = typeof deps.now === 'function' ? deps.now : Date.now
  // armed: PUTs are answered. True while the simulator is live (or with the
  // simulation option); stop() clears it. Current servers drop a plugin's PUT
  // handlers when it stops (registerPutHandler queues the de-register on the
  // plugin's stop handlers), so stop() also forgets `registered` and the next
  // start() registers again. Handlers check `armed` in case an older server
  // kept them.
  let armed = false
  let registered = false
  let forced = false // simulation option: never un-detect
  let timeoutMs = DEFAULT_TIMEOUT_MIN * 60000
  let lastSeen = -Infinity // wall-clock ms of the last fresh simulator data
  let stamps = null // simulatorStamps() at the previous look
  let timer = null
  let seq = 0
  let lastMode = null

  const emit = (action, value) => {
    app.handleMessage(PLUGIN_ID, {
      updates: [{
        values: [{
          path: COMMAND_PATH,
          value: { action, value, nonce: `${PLUGIN_ID}-${Date.now()}-${++seq}` }
        }]
      }]
    })
  }

  // The simulator publishes its live mode on steering.autopilot.state; prefer
  // it (it reflects e.g. the navigator's own return-to-route), falling back to
  // the last mode this plugin commanded.
  const currentMode = () => {
    if (typeof app.getSelfPath === 'function') {
      try {
        const node = app.getSelfPath(PATHS.state)
        const raw = node && typeof node === 'object' && 'value' in node ? node.value : node
        const mode = normaliseMode(raw)
        if (mode) return mode
      } catch (e) { /* fall through */ }
    }
    return lastMode || 'standby'
  }

  const setMode = (mode) => {
    lastMode = mode
    emit('set_mode', mode)
  }

  const handlers = {
    // Mode: "auto"|"wind"|"route"|"standby" (firmware "track"/"pretrack" -> "route").
    [PATHS.state]: (value) => {
      const mode = normaliseMode(value)
      if (!mode) return bad(`invalid autopilot mode ${JSON.stringify(value)}; expected one of ${MODES.join('|')}`)
      setMode(mode)
      return ok()
    },
    // Heading nudge: clients send DEGREES; the sim's "adjust" action expects
    // radians (it converts back to degrees), so scale here.
    [PATHS.adjustHeading]: (value) => {
      const deg = toFinite(value)
      if (deg === null) return bad(`adjustHeading must be a finite number of degrees, got ${JSON.stringify(value)}`)
      emit('adjust', (deg * Math.PI) / 180)
      return ok()
    },
    // Absolute target heading (radians, SI, passed through).
    [PATHS.headingTrue]: (value) => {
      const rad = toFinite(value)
      if (rad === null) return bad(`headingTrue must be a finite number of radians, got ${JSON.stringify(value)}`)
      emit('set_heading', rad)
      return ok()
    },
    // Tack: the sim tacks through the wind from its current target either way,
    // so the requested side is informational and passed through as the value.
    [PATHS.tack]: (value) => {
      const side = typeof value === 'string' ? value.trim().replace(/^"|"$/g, '').toLowerCase() : value
      if (side !== 'port' && side !== 'starboard' && side !== true) {
        return bad(`tack expects "port", "starboard" or true, got ${JSON.stringify(value)}`)
      }
      emit('tack', side === true ? null : side)
      return ok()
    },
    // Cycle standby -> auto -> wind -> route -> standby from the current mode.
    [PATHS.advanceMode]: () => {
      setMode(NEXT_MODE[currentMode()])
      return ok()
    },
    // Skip to the next route waypoint. The value must be exactly 1, as in the
    // connector's steering policy (signalk-yey-connector lib/steering-policy.js)
    // and signalk-autopilot. Only meaningful while following the route.
    [PATHS.advanceWaypoint]: (value) => {
      if (value !== 1) return bad(`advanceWaypoint expects 1, got ${JSON.stringify(value)}`)
      const mode = currentMode()
      if (mode !== 'route') return bad(`advanceWaypoint needs route mode, autopilot is in ${mode}`)
      emit('advance_waypoint', 1)
      return ok()
    }
  }

  const status = (msg) => { if (app.setPluginStatus) app.setPluginStatus(msg) }
  const failure = (msg) => {
    if (app.setPluginError) app.setPluginError(msg)
    else if (app.error) app.error(msg)
  }

  const register = () => {
    if (registered) return true
    if (typeof app.registerPutHandler !== 'function') {
      failure('registerPutHandler unavailable; autopilot PUTs not handled')
      return false
    }
    for (const [path, handle] of Object.entries(handlers)) {
      try {
        app.registerPutHandler('vessels.self', path, (context, p, value) => {
          if (!forced) look()
          if (!armed) {
            return unavailable(registered
              ? `${PLUGIN_ID}: simulator not seen for ${timeoutMin()} min; not handling autopilot PUTs`
              : `${PLUGIN_ID} is not active (no yey.boats simulator detected)`)
          }
          return handle(value)
        }, PLUGIN_ID)
      } catch (e) {
        if (app.debug) app.debug(`could not register PUT handler for ${path}: ${e.message}`)
      }
    }
    registered = true
    return true
  }

  const timeoutMin = () => Math.round((timeoutMs / 60000) * 100) / 100

  const arm = (why) => {
    if (!register()) return
    armed = true
    status(`SIMULATED autopilot: handling autopilot PUTs for the yey.boats simulator (${why})`)
  }

  const disarm = () => {
    armed = false
    status(`Not handling autopilot PUTs: yey.boats simulator not seen for ${timeoutMin()} min ` +
      `(no fresh "${SIM_SOURCE}" data); PUTs get 503 until it reappears. ` +
      'SIMULATOR ONLY: on a real boat, uninstall this plugin.')
  }

  // Fresh = a simulator timestamp within the timeout of the wall clock, or one
  // that changed since the previous look (the sim may run on its own clock).
  // An unchanged old value is what the server keeps after the sim disconnects.
  const look = () => {
    const t = now()
    const cur = simulatorStamps(app)
    for (const [key, ts] of Object.entries(cur)) {
      const ms = Date.parse(ts)
      if (Number.isFinite(ms) && ms <= t + timeoutMs && t - ms <= timeoutMs) lastSeen = Math.max(lastSeen, Math.min(ms, t))
      if (stamps && key in stamps && stamps[key] !== ts) lastSeen = t
    }
    stamps = cur
    const live = t - lastSeen <= timeoutMs
    if (live && !armed) arm(`detected fresh "${SIM_SOURCE}" data`)
    else if (!live && armed) disarm()
  }

  const recheck = () => { if (!forced) look() }

  const plugin = {
    id: PLUGIN_ID,
    name: 'Yey Boats simulator autopilot (SIMULATOR ONLY)',
    description: 'Translates SignalK autopilot PUTs into the yey.boats simulator\'s ' +
      'steering.autopilot.command delta. Only for the simulator\'s SignalK server — never a real boat.',
    schema: () => ({
      type: 'object',
      properties: {
        simulation: {
          type: 'boolean',
          title: 'Simulation (skip simulator detection)',
          description: 'Handle autopilot PUTs even if no data from the simulator ' +
            `("${SIM_SOURCE}") is seen. Only for a simulator server. Never on a real boat.`,
          default: false
        },
        simulatorTimeoutMinutes: {
          type: 'number',
          title: 'Stop handling PUTs after the simulator is silent for (minutes)',
          description: `With no fresh "${SIM_SOURCE}" data for this long, PUTs get 503 until the simulator reappears.`,
          default: DEFAULT_TIMEOUT_MIN
        }
      }
    }),
    start: (options) => {
      armed = false
      forced = false
      lastSeen = -Infinity
      stamps = null
      const min = options && Number(options.simulatorTimeoutMinutes)
      timeoutMs = (Number.isFinite(min) && min > 0 ? min : DEFAULT_TIMEOUT_MIN) * 60000
      if (options && options.simulation === true) {
        forced = true
        arm('simulation option')
        return
      }
      look()
      if (!armed) {
        status(`Not handling autopilot PUTs: no yey.boats simulator detected (no fresh "${SIM_SOURCE}" data). ` +
          'SIMULATOR ONLY: on a real boat, uninstall this plugin.')
      }
      timer = setInterval(recheck, RECHECK_MS)
      if (timer.unref) timer.unref()
    },
    stop: () => {
      armed = false
      // The server removes this plugin's PUT handlers on stop; register again
      // on the next start.
      registered = false
      if (timer) { clearInterval(timer); timer = null }
    },
    _recheck: recheck
  }

  return plugin
}

module.exports.PLUGIN_ID = PLUGIN_ID
module.exports.COMMAND_PATH = COMMAND_PATH
module.exports.PATHS = PATHS
module.exports.SIM_SOURCE = SIM_SOURCE
module.exports.simulatorDetected = simulatorDetected
module.exports.simulatorStamps = simulatorStamps
module.exports.normaliseMode = normaliseMode
