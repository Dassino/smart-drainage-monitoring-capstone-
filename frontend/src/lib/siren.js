// Alert sound made with the Web Audio API (no audio file). Browsers only allow sound after a click,
// so unlockSound() must be called from a button press.
let ctx = null
let osc = null
let gain = null
let timer = null

export function unlockSound() {
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)()
    if (ctx.state === 'suspended') ctx.resume()
    return true
  } catch {
    return false
  }
}

export function soundReady() {
  return !!ctx && ctx.state === 'running'
}

export function beep() {
  if (!ctx) return
  const o = ctx.createOscillator()
  const g = ctx.createGain()
  o.type = 'sine'
  o.frequency.value = 880
  g.gain.setValueAtTime(0.0001, ctx.currentTime)
  g.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + 0.03)
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35)
  o.connect(g).connect(ctx.destination)
  o.start()
  o.stop(ctx.currentTime + 0.4)
}

export function startSiren() {
  if (!ctx || osc) return
  osc = ctx.createOscillator()
  gain = ctx.createGain()
  osc.type = 'square'
  gain.gain.value = 0.0001
  osc.connect(gain).connect(ctx.destination)
  osc.start()
  let high = false
  const pulse = () => {
    const t = ctx.currentTime
    osc.frequency.setValueAtTime(high ? 880 : 620, t)
    gain.gain.cancelScheduledValues(t)
    gain.gain.setValueAtTime(0.0001, t)
    gain.gain.exponentialRampToValueAtTime(0.12, t + 0.03)
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.45)
    high = !high
  }
  pulse()
  timer = setInterval(pulse, 500)
}

export function stopSiren() {
  if (timer) clearInterval(timer)
  timer = null
  if (osc) {
    try { osc.stop() } catch { /* already stopped */ }
    osc.disconnect()
  }
  osc = null
  gain = null
}
