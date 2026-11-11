// Actions that change data (log an event, set a label, delete an event) need the admin key.
// This adds it to every non-GET request to /api/. If the server answers 401, the page asks for the key once
// (it is printed in the terminal where app.py started) and keeps it for this browser tab only.
const NAME = 'drainage-admin-key'

const read = () => {
  try { return sessionStorage.getItem(NAME) || '' } catch { return '' }
}
const save = (v) => {
  try { sessionStorage.setItem(NAME, v) } catch { /* private mode: the key is asked for again */ }
}

// The page shows a small dialog (components/AdminKeyDialog.jsx) and answers through this event.
const askForKey = () =>
  new Promise((resolve) => {
    window.dispatchEvent(new CustomEvent('admin-key-needed', { detail: { resolve } }))
    setTimeout(() => resolve(''), 120000)
  })

const nativeFetch = window.fetch.bind(window)

window.fetch = async (input, init = {}) => {
  const url = typeof input === 'string' ? input : input.url
  const method = String(init.method || (typeof input !== 'string' && input.method) || 'GET').toUpperCase()
  const write = url.startsWith('/api/') && method !== 'GET' && method !== 'HEAD'
  if (!write) return nativeFetch(input, init)

  const send = (key) => {
    const headers = new Headers(init.headers || {})
    if (key) headers.set('X-Admin-Key', key)
    return nativeFetch(input, { ...init, headers })
  }
  let res = await send(read())
  if (res.status === 401) {
    const key = await askForKey()
    if (key) {
      save(key)
      res = await send(key)
    }
  }
  return res
}
