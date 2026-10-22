import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Placeholder from './pages/Placeholder'
import Alerts from './pages/Alerts'

export default function App() {
  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/alerts" element={<Alerts />} />
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