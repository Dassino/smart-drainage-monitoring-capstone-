import { useLive } from '../live/LiveContext'

const WAIT = {
  paused: 'Paused: sensors are in the old mounting',
  warming_up: 'Warming up: collecting enough readings',
  no_live_data: 'No live data: a node has stopped sending',
  no_data: 'No data yet',
  no_model: 'Forecast model not trained (ml/models/lstm_forecast.pt)',
  error: 'Forecast error',
}

const fmt = (v, d = 1) => (v == null ? '—' : Number(v).toFixed(d))

// LSTM forecast: where node 1's water depth is heading in five minutes, against the Critical depth.
export default function ForecastPanel() {
  const { forecast: f, forecastError } = useLive()
  const ok = f?.status === 'ok'

  let tone = 'off'
  let headline = forecastError ? 'Forecast unavailable' : 'Waiting for the forecast'
  if (f && !ok) headline = WAIT[f.status] ?? '—'
  if (ok) {
    if (f.warn) { tone = 'crit'; headline = 'Critical depth expected within 5 min' }
    else if (f.streak > 0) { tone = 'stale'; headline = `Level heading toward Critical depth (${f.streak} of ${f.persist})` }
    else { tone = 'ok'; headline = 'Critical depth not expected' }
  }

  const max = ok ? Math.max(f.threshold_cm * 1.25, f.depth_now_cm + 1, f.forecast_cm + 1) : 1
  const at = (v) => `${Math.min(100, Math.max(0, (v / max) * 100))}%`

  return (
    <div>
      <div className="ew-sub">LSTM forecast, 5 minutes ahead</div>
      <div className={`fc-headline ${tone}`}>{headline}</div>
      {ok && (
        <>
          <div className="gauge" role="img" aria-label={`Depth now ${fmt(f.depth_now_cm)} cm, forecast ${fmt(f.forecast_cm)} cm, Critical ${fmt(f.threshold_cm)} cm`}>
            <span className="g-fill" style={{ width: at(f.depth_now_cm) }} />
            <span className="g-fc" style={{ left: at(f.forecast_cm) }} />
            <span className="g-crit" style={{ left: at(f.threshold_cm) }} />
          </div>
          <div className="g-legend">
            <span><i className="k-now" />Now {fmt(f.depth_now_cm)} cm</span>
            <span><i className="k-fc" />In 5 min {fmt(f.forecast_cm)} cm</span>
            <span><i className="k-crit" />Critical {fmt(f.threshold_cm)} cm</span>
          </div>
          <div className="muted small">
            Node 1 depth.{' '}
            {f.streak > 0 ? `Time to Critical depth: about ${Math.max(1, Math.round(f.ttc_s / 60))} min.` : 'No time to Critical depth expected within 10 min.'}
          </div>
        </>
      )}
    </div>
  )
}
