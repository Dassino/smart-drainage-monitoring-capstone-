import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Placeholder from './pages/Placeholder'

export default function App() {
  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route
            path="/alerts"
            element={<Placeholder title="Active Alerts" note="Alerts raised by the anomaly detector will be listed here." />}
          />
          <Route
            path="/reports"
            element={<Placeholder title="Historical Reports" note="Report filters and CSV downloads will be built here." />}
          />
          <Route
            path="/admin"
            element={<Placeholder title="System Administration" note="Alert thresholds, sensor nodes and model configuration will be shown here." />}
          />
        </Routes>
      </main>
    </div>
  )
}