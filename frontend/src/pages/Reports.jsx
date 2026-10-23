import { useEffect, useMemo, useState } from 'react'
import { getJSON, usePolling } from '../api'
import ReplayChart, { METRICS } from '../components/ReplayChart'

const COLORS = { 1: '#0e7c86', 2: '#e8743b' }
const LABELS = ['Normal', 'Blockage', 'Flood']

const day = (iso) => new Date(iso).toLocaleDateString('en-CA')
const when = (iso) => new Date(iso).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' })

function fmtDur(s) {
  if (s < 60) return `${Math.round(s)} s`
  if (s < 3600) return `${Math.round(s / 60)} min`
  return `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`
}
const mmss = (s) => `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`

function csvUrl(params) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => v && v !== 'all' && q.set(k, v))
  return `/api/export.csv${q.toString() ? `?${q}` : ''}`
}

function Replay({ node, trial }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [metric, setMetric] = useState('score')

  useEffect(() => {
    let alive = true
    setData(null)
    setError(null)
    getJSON(`/api/trial?node=${node}&trial_id=${encodeURIComponent(trial)}`)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message))
    return () => { alive = false }
  }, [node, trial])

    const metrics = Object.entries(METRICS).filter(([, m]) => !m.node1Only || node === '1')
  const pct = data && data.scored_rows ? ((100 * data.flagged_rows) / data.scored_rows).toFixed(1) : null
  const hasOnset = data?.events?.some((e) => e.type === 'onset')

  return (
    <section className="card chart-card">
      <div className="card-head">
        <h2>
          Replay: node {node} · {trial}
        </h2>
        <div className="seg" role="group" aria-label="Measurement">
          {metrics.map(([k, m]) => (
            <button key={k} type="button" className={metric === k ? 'on' : ''} onClick={() => setMetric(k)}>
              {k === 'score' ? 'Score' : m.label.split(' (')[0]}
            </button>
          ))}
        </div>
      </div>
      <div className="card-body">
        {error && <p className="empty">Could not load the trial ({error})</p>}
        {!data && !error && <p className="empty">Loading…</p>}
        {data && (
          <>
            <div className="mini-tiles">
              <div className="mini">
                <div className="k">Recording</div>
                <div className="v">{data.rows} readings · {fmtDur(data.recording_s)}</div>
                {data.gaps.length > 0 && (
                  <div className="k">over {fmtDur(data.wall_s)} ({data.gaps.length} gap{data.gaps.length > 1 ? 's' : ''} removed)</div>
                )}
              </div>
              <div className="mini">
                <div className="k">Flagged readings</div>
                <div className="v">{data.flagged_rows} of {data.scored_rows} ({pct ?? '—'}%)</div>
              </div>
              <div className="mini">
                <div className="k">Alerts ({data.persist} flagged in a row)</div>
                <div className="v">
                  {data.episodes.length}
                  {data.alerts_per_hour != null && ` · ${data.alerts_per_hour.toFixed(2)} per hour`}
                </div>
              </div>
              <div className="mini">
                <div className="k">Against logged events</div>
                {data.events.length === 0 ? (
                  <div className="v">None logged</div>
                ) : !hasOnset ? (
                  <div className="v">No “event starts” logged</div>
                ) : (
                  <>
                    <div className="v">
                      {data.detection_delay_s == null ? 'Alert missed' : `Alert ${mmss(data.detection_delay_s)} after start`}
                    </div>
                    {data.lead_time_s != null && (
                      <div className="k">
                        {data.lead_time_s >= 0
                          ? `${mmss(data.lead_time_s)} before critical level`
                          : `${mmss(-data.lead_time_s)} after critical level`}
                      </div>
                    )}
                    {data.false_alerts_before_onset > 0 && (
                      <div className="k">{data.false_alerts_before_onset} false alert(s) before the event</div>
                    )}
                  </>
                )}
              </div>
            </div>
            {data.detector_error && <p className="empty">Detector error: {data.detector_error}</p>}
            <ReplayChart
              series={data.series}
              metric={metric}
              threshold={data.threshold}
              episodes={data.episodes}
              events={data.events}
              gaps={data.gaps}
              color={COLORS[node]}
            />
          </>
        )}
      </div>
    </section>
  )
}

export default function Reports() {
  const { data: trials, error } = usePolling('/api/trials', 15000)
  const [node, setNode] = useState('all')
  const [label, setLabel] = useState('all')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [sel, setSel] = useState(null)

  const shown = useMemo(
    () =>
      (trials ?? []).filter(
        (t) =>
          (node === 'all' || t.node === node) &&
          (label === 'all' || t.label === label) &&
          (!start || day(t.started) >= start) &&
          (!end || day(t.started) <= end),
      ),
    [trials, node, label, start, end],
  )

  return (
    <>
      <h1 className="page-title">Historical Reports</h1>
      <p className="page-sub">Browse recorded trials, replay one with the detector’s score, and download readings as CSV.</p>

      <section className="card chart-card">
        <div className="card-body filters">
          <label className="field">
            Node
            <select value={node} onChange={(e) => setNode(e.target.value)}>
              <option value="all">Both</option>
              <option value="1">Node 1</option>
              <option value="2">Node 2</option>
            </select>
          </label>
          <label className="field">
            Label
            <select value={label} onChange={(e) => setLabel(e.target.value)}>
              <option value="all">All</option>
              {LABELS.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </label>
          <label className="field">
            From
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="field">
            To
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
          <a className="btn primary" href={csvUrl({ node, label: label === 'all' ? '' : label, start, end })} download>
            Download CSV
          </a>
        </div>
      </section>

      <section className="card chart-card">
        <div className="card-head">
          <h2>Trials</h2>
          <span className="muted small">{shown.length} shown</span>
        </div>
        <div className="card-body scroll">
          {error && <p className="empty">Could not load trials ({error})</p>}
          {trials && shown.length === 0 && <p className="empty">No trials match these filters.</p>}
          {shown.length > 0 && (
            <table className="ftable ttable">
              <thead>
                <tr>
                  <th>Trial</th>
                  <th>Node</th>
                  <th>Label</th>
                  <th className="num">Readings</th>
                  <th>Started</th>
                  <th className="num">Duration</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {shown.map((t) => {
                  const on = sel && sel.node === t.node && sel.trial_id === t.trial_id
                  return (
                    <tr key={`${t.node}-${t.trial_id}`} className={on ? 'sel' : ''}>
                      <td>{t.trial_id}</td>
                      <td>{t.node}</td>
                      <td>{t.label}</td>
                      <td className="num">{t.rows}</td>
                      <td>{when(t.started)}</td>
                      <td className="num">{fmtDur(t.duration_s)}</td>
                      <td className="num actions">
                        <button type="button" className="btn" onClick={() => setSel({ node: t.node, trial_id: t.trial_id })}>
                          Replay
                        </button>{' '}
                        <a className="btn" href={csvUrl({ node: t.node, trial_id: t.trial_id })} download>
                          CSV
                        </a>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {sel && <Replay key={`${sel.node}-${sel.trial_id}`} node={sel.node} trial={sel.trial_id} />}

      <p className="muted small note">
        CSV files contain the readings exactly as stored (a value of -1 means the sensor gave no reading). The first
        alert is the moment the detector had flagged 6 readings in a row.
      </p>
    </>
  )
}