import { useState } from 'react'
import { usePolling } from '../api'
import ScoreChart from '../components/ScoreChart'

const NODES = ['1', '2']
const COLORS = { 1: '#0e7c86', 2: '#e8743b' }

const STATUS = {
  alert: ['crit', 'Alert'],
  anomalous: ['stale', 'Unusual reading'],
  normal: ['ok', 'Normal'],
  warming_up: ['off', 'Warming up'],
  no_live_data: ['off', 'No live data'],
  no_data: ['off', 'No data'],
  error: ['crit', 'Detector error'],
}

const SENSOR = {
  water_level_cm: ['Distance to surface', 'cm'],
  flow_rate_lpm: ['Flow', 'L/min'],
  mq4_voltage: ['MQ-4', 'V'],
  mq135_voltage: ['MQ-135', 'V'],
}
const KIND = { mean: '1-min average', std: '1-min spread', chg: '1-min change' }

function featureLabel(name) {
  const m = name.match(/^(.+?)_(mean|std|chg)$/)
  const base = m ? m[1] : name
  const [label, unit] = SENSOR[base] ?? [base, '']
  return { text: `${label}, ${m ? KIND[m[2]] : 'current'}`, unit }
}

const fmt = (v, d = 2) => (v == null ? '—' : Number(v).toFixed(d))

function NodeAlert({ id, minutes }) {
  const { data, error } = usePolling(`/api/anomaly/detail?node=${id}&minutes=${minutes}`, 5000)
  const [cls, text] = STATUS[data?.status] ?? ['off', '—']

  return (
    <div className={`node n${id}`}>
      <div className="node-head">
        <h3>Node {id}</h3>
        <span className={`badge ${cls}`}>{text}</span>
      </div>
      {error && <p className="empty">Could not load detail ({error})</p>}
      {data?.score != null && (
        <p className="muted small">
          Score {fmt(data.score, 3)} · threshold {fmt(data.threshold, 3)} ({data.percentile}th percentile of Normal) ·{' '}
          {data.streak} flagged in a row (alert at {data.persist})
        </p>
      )}
      {data?.status === 'error' && <p className="empty">{data.detail}</p>}
      {data?.status === 'warming_up' && (
        <p className="empty">Needs about a minute of readings in the current trial before it can score.</p>
      )}
      {data && data.series.length > 0 && (
        <div className="detail-block">
          <ScoreChart series={data.series} threshold={data.threshold} minutes={minutes} color={COLORS[id]} />
        </div>
      )}
      {data && data.features.length > 0 && (
        <div className="detail-block">
          <h4>Furthest from Normal on the latest reading</h4>
          <table className="ftable">
            <thead>
              <tr>
                <th>Measurement</th>
                <th className="num">Now</th>
                <th className="num">Normal average</th>
                <th className="num">Distance</th>
              </tr>
            </thead>
            <tbody>
              {data.features.map((f) => {
                const { text: label, unit } = featureLabel(f.name)
                return (
                  <tr key={f.name}>
                    <td>{label}</td>
                    <td className="num">{fmt(f.value, 3)} {unit}</td>
                    <td className="num">{fmt(f.normal, 3)} {unit}</td>
                    <td className="num">{f.z > 0 ? '+' : ''}{fmt(f.z, 1)} σ</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small foot">
        Trial <b>{data?.trial_id ?? '—'}</b>
      </p>
    </div>
  )
}

export default function Alerts() {
  const [minutes, setMinutes] = useState(15)
  return (
    <>
      <h1 className="page-title">Active Alerts</h1>
      <p className="page-sub">
        What the anomaly detector sees on each node. An alert needs 6 flagged readings in a row.
      </p>
      <div className="controls bar">
        <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} aria-label="Time window">
          <option value={15}>Last 15 min</option>
          <option value={60}>Last hour</option>
          <option value={180}>Last 3 hours</option>
        </select>
      </div>
      <section className="row pair">
        {NODES.map((n) => (
          <NodeAlert key={n} id={n} minutes={minutes} />
        ))}
      </section>
      <p className="muted small note">
        “Distance” is how many standard deviations a value is from the average of the Normal training data. It shows
        which signals look least normal. It is a guide to the cause, not an exact explanation of the model.
      </p>
    </>
  )
}