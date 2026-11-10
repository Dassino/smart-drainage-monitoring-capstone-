import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useLive } from '../live/LiveContext'
import { startSiren, stopSiren } from '../lib/siren'

const COPY = {
  Flood: {
    title: 'Flood warning',
    text: 'The Random Forest reads flood conditions on the channel. Water is rising abnormally and flooding is likely if nothing changes. Check the drain and respond now.',
  },
  Blockage: {
    title: 'Blockage warning',
    text: 'Water level and flow match a blocked drain. Check the channel between the two nodes and clear the obstruction.',
  },
}

// Full-screen pop-up and siren. It sits above every screen, so an alert is seen wherever the user is.
export function AlertCenter() {
  const { alert, soundOn, acked, setAcked } = useLive()
  const btn = useRef(null)
  const cls = alert.level === 'alert' ? alert.cls : null
  const show = cls && acked !== cls

  useEffect(() => {
    if (cls === null && acked !== null) setAcked(null)   // alert cleared: arm the next one
  }, [cls, acked, setAcked])

  useEffect(() => {
    if (show && soundOn) startSiren()
    else stopSiren()
    return () => stopSiren()
  }, [show, soundOn])

  useEffect(() => { if (show) btn.current?.focus() }, [show])

  if (!show) return null
  const c = COPY[cls] ?? { title: `${cls} warning`, text: 'The model has raised an alert. Check the channel.' }
  return (
    <div className="alert-overlay" role="alertdialog" aria-modal="true" aria-labelledby="alert-title" aria-describedby="alert-text">
      <div className={`alert-box ${cls === 'Flood' ? 'flood' : 'block'}`}>
        <div className="alert-icon" aria-hidden="true">!</div>
        <h2 id="alert-title">{c.title}</h2>
        <p id="alert-text">{c.text}</p>
        <p className="alert-meta">
          {alert.streak} of {alert.persist} readings in a row flagged{!soundOn && ' · sound is off'}
        </p>
        <div className="alert-actions">
          <button ref={btn} type="button" className="btn primary big" onClick={() => setAcked(cls)}>Acknowledge</button>
          <Link to="/alerts" className="btn big" onClick={() => setAcked(cls)}>View details</Link>
        </div>
      </div>
    </div>
  )
}

function useClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

// Strip across the top of every screen: connection, overall status, sound.
export function StatusBar() {
  const { alert, error, lastOk, status, demo, soundOn, setSoundOn, forecast } = useLive()
  const now = useClock()
  const age = lastOk ? Math.round((now.getTime() - lastOk) / 1000) : null
  const link = error ? ['crit', 'API unreachable'] : age != null && age > 15 ? ['stale', `No update for ${age} s`] : ['ok', 'Live']
  const overall = alert.level === 'alert'
    ? ['crit', `${alert.cls} alert`]
    : alert.level === 'warning'
      ? ['stale', `Possible ${String(alert.cls).toLowerCase()}`]
      : alert.level === 'normal'
        ? ['ok', 'Normal']
        : ['off', 'Status unknown']
  const nodes = ['1', '2'].map((n) => status?.[n]?.state ?? 'NO DATA')
  return (
    <>
      <div className="statusbar">
        <span className={`pill ${link[0]}`}><i />{link[1]}</span>
        <span className={`pill ${overall[0]}`}>{overall[1]}</span>
        {forecast?.status === 'ok' && forecast.streak > 0 && alert.level !== 'alert' && (
          <span className="pill stale">{forecast.warn ? 'Forecast: Critical depth ahead' : 'Forecast: level rising'}</span>
        )}
        {nodes.map((s, i) => (
          <span key={i} className={`pill ${s === 'ONLINE' ? 'ok' : s === 'STALE' ? 'stale' : 'off'}`}>
            Node {i + 1}: {s === 'ONLINE' ? 'online' : s === 'STALE' ? 'stale' : 'offline'}
          </span>
        ))}
        <span className="grow" />
        <button
          type="button"
          className={`btn sound ${soundOn ? 'on' : ''}`}
          onClick={() => { if (soundOn) setSoundOn(false); else setSoundOn(true) }}
          aria-pressed={soundOn}
        >
          {soundOn ? 'Alert sound on' : 'Enable alert sound'}
        </button>
        <span className="muted small clock">{now.toLocaleTimeString()}</span>
      </div>
      {demo && (
        <div className="banner demo">
          Simulated data (demo mode: {demo}). These values are not from the sensors.
        </div>
      )}
    </>
  )
}
