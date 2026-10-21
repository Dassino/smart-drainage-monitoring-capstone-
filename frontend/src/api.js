import { useEffect, useState } from 'react'

export async function getJSON(path) {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json()
}

export async function postJSON(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
  return data
}

// Re-fetches `path` every `ms` milliseconds.
export function usePolling(path, ms = 3000) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const d = await getJSON(path)
        if (alive) { setData(d); setError(null) }
      } catch (e) {
        if (alive) setError(e.message)
      }
    }
    tick()
    const id = setInterval(tick, ms)
    return () => { alive = false; clearInterval(id) }
  }, [path, ms])
  return { data, error }
}
