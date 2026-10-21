import { useState } from 'react'
import { usePolling } from '../api'
import TrendChart from '../components/TrendChart'

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

const DETECTOR = {
  alert: ['crit', 'Alert'],
  anomalous: ['stale', 'Unusual reading'],
  normal: ['ok', 'Normal'],
  warming_up: ['off', 'Warming up'],
  no_live_data: ['off', 'No live data'],
  no_data: ['off', 'No data'],
  error: ['crit', 'Detector error'],
}

function Reading({ k, v, u }) {
  return (
    <div className="reading">
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
  return (
    <div className={`node n${id}`}>
      <div className="node-head">
        <h3>Node {id}</h3>
        <span className={`badge ${cls}`}>{text}</span>
      </div>
      <p className="muted small">Last reading {fmtAge(s?.age_s)}</p>
      <div className="readings">
        <Reading k="Distance to surface" v={fmt(l?.water_level_cm)} u="cm" />
        <Reading k="Flow" v={fmt(l?.flow_rate_lpm, 2)} u="L/min" />
        <Reading k="MQ-4" v={fmt(l?.mq4_voltage, 3)} u="V" />
        {id === '2' ? (
          <Reading k="MQ-135" v="not fitted" />
        ) : (
          <Reading k="MQ-135" v={fmt(l?.mq135_voltage, 3)} u="V" />
        )}
      </div>
      <p className="muted small foot">
        Labelled <b>{s?.set_label ?? '—'}</b> · {s?.set_trial ?? '—'}
      </p>
    </div>
  )
}

export default function Dashboard() {
  const { data: status, error } = usePolling('/api/status', 3000)
  const { data: anomaly } = usePolling('/api/anomaly', 3000)
  const [metric, setMetric] = useState('water')
  const [minutes, setMinutes] = useState(15)

  const online = NODES.filter((n) => status?.[n]?.state === 'ONLINE')
  const rows10 = NODES.reduce((sum, n) => sum + (status?.[n]?.rows_10min ?? 0), 0)
  const flows = online.map((n) => status[n].latest?.flow_rate_lpm).filter((v) => v != null)
  const avgFlow = flows.length ? flows.reduce((a, b) => a + b, 0) / flows.length : null

  return (
    <>
      <h1 className="page-title">System Overview</h1>
      <p className="page-sub">Live readings from both sensor nodes. Updates every 3 seconds.</p>

      {error && (
        <div className="banner">Cannot reach the API ({error}). Is the dashboard server (app.py) running?</div>
      )}

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

      <section className="row split">
        <div className="card">
          <div className="card-head">
            <h2>Sensor nodes</h2>
          </div>
          <div className="card-body nodes">
            {NODES.map((n) => (
              <NodeCard key={n} id={n} s={status?.[n]} />
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Active Alerts</h2>
          </div>
            <div className="card-body">
            <ul className="detector">
              {NODES.map((n) => {
                const a = anomaly?.[n]
                const [cls, text] = DETECTOR[a?.status] ?? ['off', '—']
                return (
                  <li key={n}>
                    <div className="line">
                      <span>Node {n}</span>
                      <span className={`badge ${cls}`}>{text}</span>
                    </div>
                    {a?.score != null && (
                      <span className="muted small">
                        score {fmt(a.score, 3)} · threshold {fmt(a.threshold, 3)} · {a.streak} flagged in a row
                      </span>
                    )}
                    {a?.status === 'error' && <span className="muted small">{a.detail}</span>}
                  </li>
                )
              })}
            </ul>
            <p className="muted small foot">
              Isolation Forest, one model per node. An alert needs {anomaly?.['1']?.persist ?? 6} flagged readings in a row.
            </p>
          </div>
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