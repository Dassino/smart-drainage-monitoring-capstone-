import { useMemo, useState } from 'react'
import ChannelScene from '../components/ChannelScene'
import EarlyWarning from '../components/EarlyWarning'
import TrendChart from '../components/TrendChart'
import { useLive } from '../live/LiveContext'
import { depthFromDistance, FLOOR_CM } from '../config'

const NODES = ['1', '2']

const STATE = {
  ONLINE: ['ok', 'Online'],
  STALE: ['stale', 'Stale'],
  OFFLINE: ['off', 'Offline'],
  'NO DATA': ['off', 'No data'],
}

function fmtAge(s) {
  if (s == null) return '—'
  if (s < 60) return `${Math.round(s)} s ago`
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${(s / 3600).toFixed(1)} h ago`
  return `${(s / 86400).toFixed(1)} days ago`
}

const fmt = (v, d = 1) => (v == null ? '—' : Number(v).toFixed(d))

function Reading({ k, v, u, dim }) {
  return (
    <div className={`reading ${dim ? 'dim' : ''}`}>
      <div className="k">{k}</div>
      <div className="v">
        {v}
        {u && <small> {u}</small>}
      </div>
    </div>
  )
}

function NodeCard({ id, s }) {
  const [cls, text] = STATE[s?.state] ?? ['off', 'Unknown']
  const l = s?.latest
  const live = s?.state === 'ONLINE'
  const depth = depthFromDistance(id, l?.water_level_cm)
  return (
    <div className={`node n${id}`}>
      <div className="node-head">
        <h3>Node {id} <span className="muted small">{id === '1' ? 'upstream' : 'downstream'}</span></h3>
        <span className={`badge ${cls}`}>{text}</span>
      </div>
      <p className="muted small">
        {live ? `Last reading ${fmtAge(s?.age_s)}` : `No live data. Last reading ${fmtAge(s?.age_s)}. Values below are old.`}
      </p>
      <div className="readings">
        <Reading dim={!live} k="Distance to surface (measured)" v={fmt(l?.water_level_cm)} u="cm" />
        <Reading dim={!live} k="Flow" v={fmt(l?.flow_rate_lpm, 2)} u="L/min" />
        <Reading dim={!live} k="Water depth (estimate)" v={fmt(depth)} u="cm" />
        <Reading dim={!live} k="MQ-4" v={fmt(l?.mq4_voltage, 3)} u="V" />
        {id === '2'
          ? <Reading k="MQ-135" v="not fitted" />
          : <Reading dim={!live} k="MQ-135" v={fmt(l?.mq135_voltage, 3)} u="V" />}
      </div>
      <p className="muted small foot">
        Depth estimate = {FLOOR_CM[id]} cm (sensor to dry floor) minus the measured distance. If the sensor is remounted, measure the dry floor again.
      </p>
      <p className="muted small foot">
        Labelled <b>{s?.set_label ?? '—'}</b> · {s?.set_trial ?? '—'}
      </p>
    </div>
  )
}

export default function Dashboard() {
  const { status, error, alert } = useLive()
  const [metric, setMetric] = useState('water')
  const [minutes, setMinutes] = useState(15)

  const sceneNodes = useMemo(() => {
    const out = {}
    NODES.forEach((n) => {
      const s = status?.[n]
      out[n] = {
        state: s?.state ?? 'NO DATA',
        ageS: s?.age_s,
        depth: depthFromDistance(n, s?.latest?.water_level_cm),
        flow: s?.latest?.flow_rate_lpm ?? 0,
      }
    })
    return out
  }, [status])

  const online = NODES.filter((n) => status?.[n]?.state === 'ONLINE')
  const rows10 = NODES.reduce((sum, n) => sum + (status?.[n]?.rows_10min ?? 0), 0)
  const flows = online.map((n) => status[n].latest?.flow_rate_lpm).filter((v) => v != null)
  const avgFlow = flows.length ? flows.reduce((a, b) => a + b, 0) / flows.length : null

  return (
    <>
      <h1 className="page-title">Live Overview</h1>
      <p className="page-sub">Both sensor nodes and the channel between them. Updates every 3 seconds.</p>

      {error && (
        <div className="banner">Cannot reach the API ({error}). Is the dashboard server (app.py) running?</div>
      )}

      <section className="row hero">
        <div className="card scene-card">
          <div className="card-head">
            <h2>Channel, live view</h2>
            <span className="muted small">Drag to rotate. Water level and flow come from the latest readings.</span>
          </div>
          <ChannelScene nodes={sceneNodes} level={alert.level} cls={alert.cls} />
          <div className="scene-note">
            <p><b>How to read this.</b> The Random Forest raises the alert. The Isolation Forest shows unusual readings beside it, and the LSTM looks ahead. Both are hints.</p>
            <p>In the offline test the LSTM level forecast was no better than assuming the level stays as it is (error 1.24 cm against 1.23 cm), so treat it as an early indication only.</p>
            <p>Water depth is an estimate: the fixed sensor-to-floor distance minus the measured distance.</p>
          </div>
        </div>
        <EarlyWarning />
      </section>

      <section className="row tiles">
        <div className="tile">
          <div className="label">Nodes online</div>
          <div className="value">
            {online.length} <small>/ {NODES.length}</small>
          </div>
          <div className="hint">Online = reading in the last 25 s</div>
        </div>
        <div className="tile">
          <div className="label">Readings, last 10 min</div>
          <div className="value">{rows10}</div>
          <div className="hint">About 70 per node when online</div>
        </div>
        <div className="tile">
          <div className="label">Average flow</div>
          <div className="value">
            {fmt(avgFlow, 2)} <small>L/min</small>
          </div>
          <div className="hint">Online nodes only</div>
        </div>
      </section>

      <section className="card chart-card">
        <div className="card-head">
          <h2>Sensor nodes</h2>
        </div>
        <div className="card-body nodes">
          {NODES.map((n) => (
            <NodeCard key={n} id={n} s={status?.[n]} />
          ))}
        </div>
      </section>

      <section className="card chart-card">
        <div className="card-head">
          <h2>Live trend</h2>
          <div className="controls">
            <div className="seg" role="group" aria-label="Measurement">
              {[
                ['water', 'Distance'],
                ['flow', 'Flow'],
                ['mq4', 'MQ-4'],
                ['mq135', 'MQ-135'],
              ].map(([k, l]) => (
                <button key={k} type="button" className={metric === k ? 'on' : ''} onClick={() => setMetric(k)}>
                  {l}
                </button>
              ))}
            </div>
            <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} aria-label="Time window">
              <option value={15}>Last 15 min</option>
              <option value={60}>Last hour</option>
              <option value={360}>Last 6 hours</option>
            </select>
          </div>
        </div>
        <div className="card-body">
          <TrendChart metric={metric} minutes={minutes} />
        </div>
      </section>
    </>
  )
}
