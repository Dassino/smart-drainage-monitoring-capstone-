import { NavLink } from 'react-router-dom'
import { BRAND } from '../config'
import { useLive } from '../live/LiveContext'

const Icon = ({ d }) => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    {d.map((p, i) => <path key={i} d={p} />)}
  </svg>
)

const ITEMS = [
  { to: '/', label: 'Dashboard', end: true, icon: ['M3 12l9-8 9 8', 'M5 10v10h14V10'] },
  { to: '/alerts', label: 'Active Alerts', icon: ['M12 3l10 18H2L12 3z', 'M12 10v5', 'M12 18h.01'] },
  { to: '/reports', label: 'Historical Reports', icon: ['M4 20V4', 'M4 20h16', 'M8 16v-5', 'M12 16V8', 'M16 16v-3'] },
  { to: '/admin', label: 'System Administration', icon: ['M12 15a3 3 0 100-6 3 3 0 000 6z', 'M19 12a7 7 0 00-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 00-2-1.2L14 3h-4l-.6 2.7a7 7 0 00-2 1.2l-2.3-1-2 3.4 2 1.5A7 7 0 005 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-1a7 7 0 002 1.2L10 21h4l.6-2.7a7 7 0 002-1.2l2.3 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z'] },
]

export default function Sidebar() {
  const { alert, status } = useLive()
  const online = ['1', '2'].filter((n) => status?.[n]?.state === 'ONLINE').length
  return (
    <aside className="sidebar">
      <div className="brand">
        {BRAND.name}
        <small>{BRAND.tagline}</small>
      </div>
      <nav className="nav" aria-label="Main">
        {ITEMS.map((it) => (
          <NavLink key={it.to} to={it.to} end={it.end}>
            <Icon d={it.icon} />
            <span>{it.label}</span>
            {it.to === '/alerts' && alert.level === 'alert' && <span className="nav-dot" aria-label="Active alert" />}
          </NavLink>
        ))}
      </nav>
      <div className="side-foot">
        <span className={`dot ${online === 2 ? 'ok' : online === 1 ? 'stale' : 'off'}`} />
        {online} of 2 nodes online
      </div>
    </aside>
  )
}
