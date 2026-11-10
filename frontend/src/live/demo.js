// Simulated readings for rehearsing the screen without the rig: open the dashboard with ?demo=normal,
// dry, blockage, flood or offline. The page shows a banner so simulated data is never mistaken for real data.
import { FLOOR_CM } from '../config'

export const DEMO_MODES = ['normal', 'dry', 'blockage', 'flood', 'offline']

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v))

export function demoData(mode, t) {
  const ph = clamp(t / 40)
  let d1 = 3 + Math.sin(t / 3) * 0.3
  let d2 = 2.7 + Math.sin(t / 3 + 1) * 0.3
  let f1 = 2.1
  let f2 = 2.0
  const cls = mode === 'blockage' ? 'Blockage' : mode === 'flood' ? 'Flood' : null

  if (mode === 'dry') { d1 = 0; d2 = 0; f1 = 0; f2 = 0 }
  if (mode === 'blockage') { d1 = 3 + ph * 11; d2 = 2.7 - ph * 1.6; f1 = 2.1 - ph * 1.0; f2 = 2.0 - ph * 1.8 }
  if (mode === 'flood') { d1 = 3 + ph * 19; d2 = 2.7 + ph * 17; f1 = 2.1 + ph * 3; f2 = 2.0 + ph * 3.2 }

  const streak = cls && t >= 6 ? Math.min(6, Math.floor((t - 6) / 3) + 1) : 0
  const pc = cls ? clamp((t - 3) / 18) * 0.92 + 0.03 : 0.02
  const proba = { Normal: 1 - pc - 0.02, Blockage: cls === 'Blockage' ? pc : 0.01, Flood: cls === 'Flood' ? pc : 0.01 }
  const off = mode === 'offline'

  const node = (id, d, f, age) => ({
    state: off && id === '2' ? 'OFFLINE' : 'ONLINE',
    age_s: off && id === '2' ? 240 : age,
    rows_10min: off && id === '2' ? 0 : 70,
    latest: {
      water_level_cm: FLOOR_CM[id] - d, flow_rate_lpm: f,
      mq4_voltage: 0.42 + Math.sin(t / 5) * 0.01, mq135_voltage: id === '1' ? 0.61 : null,
    },
    set_label: cls ?? 'Normal', set_trial: 'demo',
  })
  const status = { 1: node('1', d1, f1, 4), 2: node('2', d2, f2, 5) }

  const ifNode = (s) => ({
    status: s >= 6 ? 'alert' : s > 0 ? 'anomalous' : 'normal', score: 0.4 + s * 0.04, threshold: 0.56, streak: s, persist: 6,
  })
  const anomaly = { 1: ifNode(streak), 2: ifNode(Math.max(0, streak - 1)) }

  const diag = off
    ? { status: 'no_live_data' }
    : { status: 'ok', label: streak ? cls : 'Normal', alert: streak >= 6, class: streak >= 6 ? cls : null, proba, streak, persist: 6 }
  // LSTM forecast of node 1 depth five minutes ahead (simulated)
  const crit = 15
  const extra = mode === 'flood' ? 11 : mode === 'blockage' ? 5 : 0.2
  const fcast = d1 + extra * clamp(t / 20)
  const over = fcast >= crit
  const fs = over ? Math.min(6, Math.floor(Math.max(0, t - 8) / 3) + 1) : 0
  const forecast = off
    ? { status: 'no_live_data' }
    : { status: 'ok', depth_now_cm: d1, forecast_cm: fcast, horizon_s: 300, threshold_cm: crit, warn: fs >= 6, streak: fs, persist: 6,
        ttc_s: over ? Math.max(40, 300 - Math.max(0, t - 8) * 6) : 600 }
  return { status, anomaly, diag, forecast }
}
