import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import { AlertCenter, StatusBar } from './components/AlertCenter'
import AdminKeyDialog from './components/AdminKeyDialog'
import { LiveProvider } from './live/LiveContext'
import Dashboard from './pages/Dashboard'
import Admin from './pages/Admin'
import Alerts from './pages/Alerts'
import Reports from './pages/Reports'

export default function App() {
  return (
    <LiveProvider>
      <div className="app">
        <Sidebar />
        <main className="main">
          <StatusBar />
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/admin" element={<Admin />} />
          </Routes>
        </main>
      </div>
      <AlertCenter />
      <AdminKeyDialog />
    </LiveProvider>
  )
}
