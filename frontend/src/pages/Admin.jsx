import { useEffect, useState } from 'react'
import { postJSON, usePolling } from '../api'

const TRIAL_OK = /^[A-Za-z0-9_-]{1,40}$/
const LABELS = ['Normal', 'Blockage', 'Flood']
const EVENTS = [
  ['onset', 'Event starts'],
  ['critical', 'Critical level reached'],
  ['end', 'Event ends'],
]
const EVENT_NAME = Object.fromEntries(EVENTS)

const fmtAge = (s) => {
  if (s < 90) return `${Math.round(s)} s ago`
  if (s < 5400) return `${Math.round(s / 60)} min ago`
  return `${(s / 3600).toFixed(1)} h ago`
}

function TrialControl() {
  const { data: status } = usePolling('/api/status', 3000)
  const [node, setNode] = useState('both')
  const [label, setLabel] = useState('Normal')
  const [trial, setTrial] = useState('')
  const [late, setLate] = useState(0)
  const [note, setNote] = useState('')
  const [msg, setMsg] = useState(null)
  const valid = TRIAL_OK.test(trial)
  const { data: events, error: evError } = usePolling(
    valid ? `/api/events?trial_id=${encodeURIComponent(trial)}` : '/api/events',
    3000,
  )

  // Start with the trial the nodes are already recording.
  useEffect(() => {
    if (!trial && status?.['1']?.set_trial) setTrial(status['1'].set_trial)
  }, [status, trial])

  const run = async (fn, ok) => {
    try {
      await fn()
      setMsg({ ok: true, text: ok })
    } catch (e) {
      setMsg({ ok: false, text: e.message })
    }
  }
  const applyLabel = () =>
    run(
      () => postJSON('/api/label', { node_id: node, label, trial_id: trial }),
      `New readings from ${node === 'both' ? 'both nodes' : `node ${node}`} are stored as ${label} / ${trial}.`,
    )
  const logEvent = (type) =>
    run(
      () => postJSON('/api/event', { node_id: node, trial_id: trial, type, seconds_ago: Number(late) || 0, note }),
      `Logged “${EVENT_NAME[type]}” for ${trial}${Number(late) ? ` (${late} s ago)` : ''}.`,
    )
  const remove = (id) =>
    run(() => fetch(`/api/event/${id}`, { method: 'DELETE' }).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`) }), 'Event removed.')

  return (
    <div className="admin-grid">
      <div className="card">
        <div className="card-head"><h2>Label new readings</h2></div>
        <div className="card-body stack">
          <div className="filters">
            <label className="field">
              Apply to
              <select value={node} onChange={(e) => setNode(e.target.value)}>
                <option value="both">Both nodes</option>
                <option value="1">Node 1</option>
                <option value="2">Node 2</option>
              </select>
            </label>
            <label className="field">
              Label
              <select value={label} onChange={(e) => setLabel(e.target.value)}>
                {LABELS.map((l) => <option key={l}>{l}</option>)}
              </select>
            </label>
            <label className="field">
              Trial ID
              <input value={trial} maxLength={40} onChange={(e) => setTrial(e.target.value.trim())} placeholder="e.g. blockage_01" />
            </label>
            <button type="button" className="btn primary" disabled={!valid} onClick={applyLabel}>Apply label</button>
          </div>
          <p className="muted small">
            Readings arriving from now on are stored with this label and trial ID. Currently recording:{' '}
            {['1', '2'].map((n) => (
              <span key={n}>Node {n}: <b>{status?.[n]?.set_label ?? '—'} / {status?.[n]?.set_trial ?? '—'}</b>{n === '1' ? ' · ' : ''}</span>
            ))}
          </p>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Mark an event</h2></div>
        <div className="card-body stack">
          <p className="muted small">
            Press the button at the moment it happens. These times are what the lead time is measured from.
            Uses the node and trial ID chosen above.
          </p>
          <div className="filters">
            {EVENTS.map(([type, text]) => (
              <button key={type} type="button" className="btn primary big" disabled={!valid} onClick={() => logEvent(type)}>
                {text}
              </button>
            ))}
          </div>
          <div className="filters">
            <label className="field">
              Pressed late by (seconds)
              <input type="number" min="0" max="900" value={late} onChange={(e) => setLate(e.target.value)} />
            </label>
            <label className="field grow">
              Note (optional)
              <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} placeholder="e.g. rag inserted at the 2 m mark" />
            </label>
          </div>
          {msg && <p className={`msg ${msg.ok ? 'ok' : 'err'}`}>{msg.text}</p>}
          <h4>Recent events{valid ? ` for ${trial}` : ''}</h4>
          {evError && <p className="empty">Could not load events ({evError})</p>}
          {events && events.length === 0 && <p className="empty">No events logged yet.</p>}
          {events && events.length > 0 && (
            <table className="ftable">
              <thead>
                <tr><th>Event</th><th>Node</th><th>Trial</th><th>When</th><th>Note</th><th /></tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.event_id}>
                    <td>{EVENT_NAME[e.event_type] ?? e.event_type}</td>
                    <td>{e.node_id}</td>
                    <td>{e.trial_id}</td>
                    <td>{fmtAge(e.age_s)}</td>
                    <td>{e.note}</td>
                    <td className="num"><button type="button" className="btn" onClick={() => remove(e.event_id)}>Remove</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

function Thresholds() {
  const { data, error } = usePolling('/api/model_info', 30000)
  return (
    <div className="card">
      <div className="card-head"><h2>Alert thresholds</h2></div>
      <div className="card-body stack">
        {error && <p className="empty">Could not load model settings ({error})</p>}
        {data && (
          <table className="ftable">
            <thead>
              <tr><th>Node</th><th>Threshold set at</th><th className="num">Score threshold</th><th className="num">Alert after</th></tr>
            </thead>
            <tbody>
              {['1', '2'].map((n) => (
                <tr key={n}>
                  <td>Node {n}</td>
                  <td>{data[n].error ? data[n].error : `${data[n].percentile}th percentile of Normal training scores`}</td>
                  <td className="num">{data[n].threshold?.toFixed(4)}</td>
                  <td className="num">{data[n].persist} flagged readings in a row</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted small">
          The thresholds come from the Normal training data, so changing them means retraining the model. They are
          shown here, not edited. The alert rule (6 in a row, about 50 s) is a starting value to tune on the trials.
        </p>
      </div>
    </div>
  )
}

function Nodes() {
  const { data } = usePolling('/api/status', 3000)
  const sensors = { 1: 'Water level, flow, MQ-4, MQ-135', 2: 'Water level, flow, MQ-4 (MQ-135 not fitted)' }
  return (
    <div className="card">
      <div className="card-head"><h2>Sensor nodes</h2></div>
      <div className="card-body scroll">
        <table className="ftable">
          <thead>
            <tr><th>Node</th><th>State</th><th>Last reading</th><th className="num">Readings stored</th><th>Sensors</th><th>Recording as</th></tr>
          </thead>
          <tbody>
            {['1', '2'].map((n) => (
              <tr key={n}>
                <td>Node {n}</td>
                <td>{data?.[n]?.state ?? '—'}</td>
                <td>{data?.[n]?.age_s == null ? '—' : fmtAge(data[n].age_s)}</td>
                <td className="num">{data?.[n]?.total_rows ?? '—'}</td>
                <td>{sensors[n]}</td>
                <td>{data?.[n] ? `${data[n].set_label} / ${data[n].set_trial}` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ModelConfig() {
  const { data, error } = usePolling('/api/model_info', 30000)
  return (
    <div className="stack-lg">
      <div className="card">
        <div className="card-head"><h2>Three-stage pipeline</h2></div>
        <div className="card-body scroll">
          <table className="ftable">
            <thead><tr><th>Stage</th><th>Model</th><th>Status</th></tr></thead>
            <tbody>
              <tr><td>1. Detect unusual behaviour</td><td>Isolation Forest, one per node</td><td>Trained and connected</td></tr>
              <tr><td>2. Classify Blockage or Flood</td><td>Random Forest</td><td>Not trained yet: needs the Blockage and Flood trials</td></tr>
              <tr><td>3. Predict ahead</td><td>LSTM</td><td>Not trained yet: needs the Blockage and Flood trials</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h2>Isolation Forest settings</h2></div>
        <div className="card-body scroll">
          {error && <p className="empty">Could not load model settings ({error})</p>}
          {data && (
            <table className="ftable">
              <thead>
                <tr><th>Node</th><th className="num">Trees</th><th className="num">Window</th><th className="num">Features</th><th className="num">Trained on</th><th>File</th></tr>
              </thead>
              <tbody>
                {['1', '2'].map((n) => (
                  <tr key={n}>
                    <td>Node {n}</td>
                    <td className="num">{data[n].trees}</td>
                    <td className="num">{data[n].window} readings</td>
                    <td className="num">{data[n].features?.length}</td>
                    <td className="num">{data[n].trained_rows} readings</td>
                    <td>{data[n].file}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted small note">
            Trained on Normal readings only. Features per sensor: current value, and the average, spread and change
            over a one-minute window.
          </p>
        </div>
      </div>
    </div>
  )
}

const TABS = [
  ['trial', 'Trial Control', TrialControl],
  ['thresholds', 'Alert Thresholds', Thresholds],
  ['nodes', 'Sensor Nodes', Nodes],
  ['model', 'Model Configuration', ModelConfig],
]

export default function Admin() {
  const [tab, setTab] = useState('trial')
  const Active = TABS.find(([k]) => k === tab)[2]
  return (
    <>
      <h1 className="page-title">System Administration</h1>
      <p className="page-sub">Run the trials, and see how the nodes and the detector are set up.</p>
      <div className="controls bar">
        <div className="seg" role="tablist" aria-label="Administration sections">
          {TABS.map(([k, text]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>
              {text}
            </button>
          ))}
        </div>
      </div>
      <div className="admin-body">
        <Active />
      </div>
    </>
  )
}