import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import CommandPalette from './components/CommandPalette'
import { ToastContainer } from './components/Toast'

// Existing pages
import Dashboard from './pages/Dashboard'
import Companies from './pages/Companies'
import Contacts from './pages/Contacts'
import EngineControl from './pages/EngineControl'
import ReviewQueue from './pages/ReviewQueue'
import IntentData from './pages/IntentData'
import Settings from './pages/Settings'
import Reporting from './pages/Reporting'

// New pages
import Login from './pages/Login'
import TechnologyProfiles from './pages/TechnologyProfiles'
import ListImport from './pages/ListImport'
import Events from './pages/Events'
import ManufacturerIntel from './pages/ManufacturerIntel'
import AuditLogs from './pages/AuditLogs'
import UserManagement from './pages/UserManagement'

export default function App() {
  const [cmdOpen, setCmdOpen]                   = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [token, setToken]                       = useState<string | null>(
    () => localStorage.getItem('token')
  )
  const [user, setUser]                         = useState<any>(
    () => { try { return JSON.parse(localStorage.getItem('user') || 'null') } catch { return null } }
  )

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); setCmdOpen(v => !v) }
      if (e.key === 'Escape') setCmdOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleLogin = (tok: string, usr: any) => {
    setToken(tok); setUser(usr)
  }

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    setToken(null); setUser(null)
  }

  // ── Auth guard ─────────────────────────────────────────────────────────────
  // If no token, show login. The app still works without auth for backwards
  // compatibility (existing users can add auth later). To enforce auth remove
  // the !token check below.
  if (!token) {
    return (
      <>
        <Login onLogin={handleLogin} />
        <ToastContainer />
      </>
    )
  }

  const isAdmin = user?.role === 'admin' || user?.role === 'owner'

  return (
    <BrowserRouter>
      <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden', background: '#0d1117' }}>
        <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(v => !v)} user={user} isAdmin={isAdmin} />
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0, overflow: 'hidden' }}>
          <Topbar onCmdK={() => setCmdOpen(true)} user={user} onLogout={handleLogout} />
          <main style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: 24, background: '#0d1117' }}>
            <Routes>
              <Route path="/"                       element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard"              element={<Dashboard />} />
              <Route path="/companies"              element={<Companies />} />
              <Route path="/contacts"               element={<Contacts />} />
              <Route path="/engine"                 element={<EngineControl />} />
              <Route path="/review"                 element={<ReviewQueue />} />
              <Route path="/intent"                 element={<IntentData />} />
              <Route path="/reporting"              element={<Reporting />} />
              <Route path="/settings"               element={<Settings />} />
              {/* New unified platform pages */}
              <Route path="/technology-profiles"    element={<TechnologyProfiles />} />
              <Route path="/list-import"            element={<ListImport />} />
              <Route path="/events"                 element={<Events />} />
              <Route path="/manufacturer-intel"     element={<ManufacturerIntel />} />
              <Route path="/audit-logs"             element={<AuditLogs />} />
              {isAdmin && <Route path="/user-management" element={<UserManagement />} />}
            </Routes>
          </main>
        </div>
        {cmdOpen && <CommandPalette onClose={() => setCmdOpen(false)} />}
        <ToastContainer />
      </div>
    </BrowserRouter>
  )
}
