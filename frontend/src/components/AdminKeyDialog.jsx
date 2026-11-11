import { useEffect, useRef, useState } from 'react'
import '../lib/adminKey.js'   // installs the key header on data-changing requests (also imported in main.jsx)

// Asks for the admin key when the server refuses a change (401). The key is printed in the terminal running app.py.
export default function AdminKeyDialog() {
  const [ask, setAsk] = useState(null)
  const [value, setValue] = useState('')
  const input = useRef(null)

  useEffect(() => {
    const on = (e) => { setValue(''); setAsk(e.detail) }
    window.addEventListener('admin-key-needed', on)
    return () => window.removeEventListener('admin-key-needed', on)
  }, [])
  useEffect(() => { if (ask) input.current?.focus() }, [ask])

  if (!ask) return null
  const done = (v) => { ask.resolve(v.trim()); setAsk(null) }

  return (
    <div className="alert-overlay" role="dialog" aria-modal="true" aria-labelledby="ak-title">
      <form className="alert-box" onSubmit={(e) => { e.preventDefault(); done(value) }}>
        <h2 id="ak-title" style={{ marginTop: 0 }}>Admin key needed</h2>
        <p className="muted">Changing data needs the admin key. It is printed in the terminal where app.py is running, or it is the value you set in DASH_ADMIN_KEY.</p>
        <input ref={input} type="password" value={value} onChange={(e) => setValue(e.target.value)}
               placeholder="Admin key" autoComplete="off" style={{ width: '100%', padding: '10px 12px', margin: '8px 0 16px', fontSize: 15 }} />
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
          <button type="submit" className="btn primary">Continue</button>
          <button type="button" className="btn" onClick={() => done('')}>Cancel</button>
        </div>
      </form>
    </div>
  )
}
