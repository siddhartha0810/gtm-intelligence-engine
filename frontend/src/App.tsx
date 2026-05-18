import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import CommandPalette from './components/CommandPalette'
import { ToastContainer } from './components/Toast'
import Dashboard from './pages/Dashboard'
import Companies from './pages/Companies'
import Contacts from './pages/Contacts'
import EngineControl from './pages/EngineControl'
import ReviewQueue from './pages/ReviewQueue'
import IntentData from './pages/IntentData'
import Settings from './pages/Settings'
import Reporting from './pages/Reporting'

export default function App() {
  const [cmdOpen, setCmdOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setCmdOpen(v => !v)
      }
      if (e.key === 'Escape') setCmdOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <BrowserRouter>
      <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden', background: '#0d1117' }}>
        <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(v => !v)} />
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0, overflow: 'hidden' }}>
          <Topbar onCmdK={() => setCmdOpen(true)} />
          <main style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: 24, background: '#0d1117' }}>
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/companies" element={<Companies />} />
              <Route path="/contacts" element={<Contacts />} />
              <Route path="/engine" element={<EngineControl />} />
              <Route path="/review" element={<ReviewQueue />} />
              <Route path="/intent" element={<IntentData />} />
              <Route path="/reporting" element={<Reporting />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </main>
        </div>
        {cmdOpen && <CommandPalette onClose={() => setCmdOpen(false)} />}
        <ToastContainer />
      </div>
    </BrowserRouter>
  )
}
