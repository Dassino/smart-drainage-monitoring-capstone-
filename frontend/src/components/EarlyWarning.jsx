import { Link } from 'react-router-dom'
import { CHANNEL } from '../config'
import { useLive } from '../live/LiveContext'
import ForecastPanel from './ForecastPanel'

const CLASSES = ['Normal', 'Blockage', 'Flood']
const BAR = { Normal: 'ok', Blockage: 'warn', Flood: 'crit' }

const WAIT = {
  paused: 'Paused: sensors are in the old mounting',
  warming_up: 'Warming up: collecting enough readings',
  no_live_data: 'No live data: a node has stopped sending',
  no_data: 'No data yet',
  no_model: 'Model not trained',
  error: 'Diagnosis error',
}

const IF_BADGE = {
  alert: ['crit', 'Alert'], anomalous: ['stale', 'Unusual reading'], normal: ['ok', 'Normal'],
  warming_up: ['off', 'Warming up'], no_live_data: ['off', 'No live data'], no_data: ['off', 'No data'],
  paused: ['off', 'Paused'], error: ['crit', 'Error'],
}

const pct = (v) => `${Math.round((v ?? 0) * 100)}%`

// What the models are saying now, and how close they are to raising an alert.
export default function EarlyWarning() {
  const { diag, anomaly, alert } = useLive()
  const ok = diag?.status === 'ok'
  const left = Math.max(0, alert.persist - alert.streak)
  const eta = Math.round(left * CHANNEL.readingEveryS)

  let headline = 'Waiting for the model'
  let tone = 'off'
  if (!diag) headline = 'Waiting for the model'
  else if (!ok) headline = WAIT[diag.status] ?? '—'
  else if (alert.level === 'alert') { headline = `${alert.cls} alert`; tone = 'crit' }
  else if (alert.level === 'warning') { headline = `Possible ${alert.cls.toLowerCase()}, confirming`; tone = 'stale' }
  else { headline = 'Normal'; tone = 'ok' }

  return (
    <div className="card early">
      <div className="card-head">
        <h2>Early warning</h2>
        <Link to="/alerts" className="more">Details</Link>
      </div>
      <div className="card-body stack">
        <div className={`ew-headline ${tone}`}>{headline}</div>

        {ok && (
          <>
            <div>
              <div className="ew-sub">Random Forest, both nodes together</div>
              <div className="bars">
                {CLASSES.map((c) => (
                  <div key={c} className="bar-row">
                    <span className="bar-k">{c}</span>
                    <span className="bar-track"><span className={`bar-fill ${BAR[c]}`} style={{ width: pct(diag.proba?.[c]) }} /></span>
                    <span className="bar-v">{pct(diag.proba?.[c])}</span>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="ew-sub">Readings in a row that are not Normal</div>
              <div className="steps" role="img" aria-label={`${alert.streak} of ${alert.persist}`}>
                {Array.from({ length: alert.persist }).map((_, i) => (
                  <span key={i} className={`step ${i < alert.streak ? (alert.level === 'alert' ? 'crit' : 'warn') : ''}`} />
                ))}
              </div>
              <div className="muted small">
                {alert.level === 'alert'
                  ? `Alert raised after ${alert.persist} in a row.`
                  : alert.streak > 0
                    ? `${alert.streak} of ${alert.persist}. If this continues the alert fires in about ${eta} s.`
                    : `0 of ${alert.persist}. An alert needs ${alert.persist} in a row.`}
              </div>
            </div>
          </>
        )}

        <div>
          <div className="ew-sub">Isolation Forest, one model per node</div>
          <ul className="detector">
            {['1', '2'].map((n) => {
              const a = anomaly?.[n]
              const [cls, text] = IF_BADGE[a?.status] ?? ['off', '—']
              return (
                <li key={n}>
                  <div className="line"><span>Node {n}</span><span className={`badge ${cls}`}>{text}</span></div>
                  {a?.score != null && (
                    <span className="muted small">score {a.score.toFixed(2)} · threshold {a.threshold?.toFixed(2)} · {a.streak} flagged in a row</span>
                  )}
                </li>
              )
            })}
          </ul>
        </div>

        <ForecastPanel />

      </div>
    </div>
  )
}
