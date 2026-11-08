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
// The yey.boats Python simulator's autopilot instead listens on the SignalK
// stream for a private `steering.autopilot.command` delta
// {action, value, nonce} (see src/yey/boats/simulator/engine/command_listener.py).
// This plugin registers PUT handlers for those paths and re-emits each one as
// the simulator's command delta, so the dashboard/device steering controls
// drive the modeled boat end-to-end.
//
// It is ONLY for the simulator's SignalK server. On a real boat these PUTs
// belong to the boat's real autopilot plugin; installing this there would
// answer PUTs as COMPLETED while steering nothing.

const PLUGIN_ID = 'yey-sim-autopilot'
const COMMAND_PATH = 'steering.autopilot.command'
const MODES = ['standby', 'auto', 'wind', 'route']
// advanceMode cycle: standby -> auto -> wind -> route -> standby
const NEXT_MODE = { standby: 'auto', auto: 'wind', wind: 'route', route: 'standby' }

const PATHS = {
  state: 'steering.autopilot.state',
  adjustHeading: 'steering.autopilot.actions.adjustHeading',
  headingTrue: 'steering.autopilot.target.headingTrue',
  tack: 'steering.autopilot.actions.tack',
  advanceMode: 'steering.autopilot.actions.advanceMode'
}

const ok = () => ({ state: 'COMPLETED', statusCode: 200 })
const bad = (message) => ({ state: 'COMPLETED', statusCode: 400, message })

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

module.exports = function yeySimAutopilot (app) {
  let running = false
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
    }
  }

  const plugin = {
    id: PLUGIN_ID,
    name: 'Yey Boats simulator autopilot (SIMULATOR ONLY)',
    description: 'Translates SignalK autopilot PUTs into the yey.boats simulator\'s ' +
      'steering.autopilot.command delta. Only for the simulator\'s SignalK server — never a real boat.',
    schema: () => ({ type: 'object', properties: {} }),
    start: () => {
      running = true
      if (typeof app.registerPutHandler !== 'function') {
        if (app.error) app.error('registerPutHandler unavailable; autopilot PUTs not handled')
        return
      }
      for (const [path, handle] of Object.entries(handlers)) {
        try {
          app.registerPutHandler('vessels.self', path, (context, p, value) => {
            // SignalK has no unregisterPutHandler on older servers; refuse while stopped.
            if (!running) return { state: 'COMPLETED', statusCode: 503, message: `${PLUGIN_ID} is stopped` }
            return handle(value)
          }, PLUGIN_ID)
        } catch (e) {
          if (app.debug) app.debug(`could not register PUT handler for ${path}: ${e.message}`)
        }
      }
      if (app.setPluginStatus) app.setPluginStatus('Handling autopilot PUTs for the simulator')
    },
    stop: () => {
      running = false
    }
  }

  return plugin
}

module.exports.PLUGIN_ID = PLUGIN_ID
module.exports.COMMAND_PATH = COMMAND_PATH
module.exports.PATHS = PATHS
module.exports.normaliseMode = normaliseMode
