import { NavLink } from 'react-router-dom'

const icons = {
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
    </>
  ),
  alerts: (
    <>
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </>
  ),
  reports: (
    <>
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </>
  ),
  admin: <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />,
}

const links = [
  ['/', 'Dashboard', 'dashboard'],
  ['/alerts', 'Active Alerts', 'alerts'],
  ['/reports', 'Historical Reports', 'reports'],
  ['/admin', 'System Administration', 'admin'],
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        Smart Drainage Monitoring
        <small>Prototype · 2 sensor nodes</small>
      </div>
      <nav className="nav">
        {links.map(([to, label, icon]) => (
          <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
            <svg viewBox="0 0 24 24" aria-hidden="true">{icons[icon]}</svg>
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
