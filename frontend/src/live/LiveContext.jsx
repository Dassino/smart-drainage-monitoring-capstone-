import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { usePolling } from '../api'
import { demoData, DEMO_MODES } from './demo'
import { unlockSound, beep } from '../lib/siren'

const Ctx = createContext(null)
export const useLive = () => useContext(Ctx)

// One place that polls the API, so every screen and the alert popup see the same data.
export function computeAlert(diag) {
  if (!diag || diag.status !== 'ok') return { level: 'none', cls: null, streak: 0, persist: 6 }
  const persist = diag.persist ?? 6
  const streak = diag.streak ?? 0
  if (diag.alert) return { level: 'alert', cls: diag.class ?? diag.label, streak, persist }
  if (streak > 0 && diag.label && diag.label !== 'Normal') return { level: 'warning', cls: diag.label, streak, persist }
  return { level: 'normal', cls: null, streak: 0, persist }
}

export function LiveProvider({ children }) {
  const mode = new URLSearchParams(window.location.search).get('demo')
  const demo = DEMO_MODES.includes(mode) ? mode : null

  const s = usePolling('/api/status', 3000)
  const a = usePolling('/api/anomaly', 3000)
  const d = usePolling('/api/diagnosis', 3000)
  const f = usePolling('/api/forecast', 5000)

  const [t, setT] = useState(0)
  useEffect(() => {
    if (!demo) return
    const t0 = Date.now()
    const id = setInterval(() => setT((Date.now() - t0) / 1000), 500)
    return () => clearInterval(id)
  }, [demo])

  const [soundOn, setSoundOnState] = useState(false)
  const [acked, setAcked] = useState(null)
  const [lastOk, setLastOk] = useState(null)
  useEffect(() => { if (s.data) setLastOk(Date.now()) }, [s.data])

  const setSoundOn = (on) => {
    if (on) {
      if (!unlockSound()) return
      beep()
    }
    setSoundOnState(on)
  }

  const value = useMemo(() => {
    const sim = demo ? demoData(demo, t) : null
    const status = sim ? sim.status : s.data
    const anomaly = sim ? sim.anomaly : a.data
    const diag = sim ? sim.diag : d.data
    const forecast = sim ? sim.forecast : f.data
    return {
      demo, status, anomaly, diag, forecast, forecastError: demo ? null : f.error,
      error: demo ? null : s.error,
      lastOk: demo ? Date.now() : lastOk,
      alert: computeAlert(diag),
      soundOn, setSoundOn, acked, setAcked,
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demo, t, s.data, s.error, a.data, d.data, f.data, f.error, lastOk, soundOn, acked])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
