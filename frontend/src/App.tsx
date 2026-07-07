import { useState, useEffect, lazy, Suspense } from 'react'
import type { User } from './types'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import CommandPalette from './components/CommandPalette'
import { ToastContainer } from './components/Toast'

// Login is eager — must render before BrowserRouter even mounts
import Login from './pages/Login'

// All route pages are lazy-loaded — each becomes its own JS chunk
const Dashboard           = lazy(() => import('./pages/Dashboard'))
const Companies           = lazy(() => import('./pages/Companies'))
const Contacts            = lazy(() => import('./pages/Contacts'))
const EngineControl       = lazy(() => import('./pages/EngineControl'))
const ReviewQueue         = lazy(() => import('./pages/ReviewQueue'))
const IntentData          = lazy(() => import('./pages/IntentData'))
const Settings            = lazy(() => import('./pages/Settings'))
const Reporting           = lazy(() => import('./pages/Reporting'))
const Metrics              = lazy(() => import('./pages/Metrics'))
const TechnologyProfiles  = lazy(() => import('./pages/TechnologyProfiles'))
const ListImport          = lazy(() => import('./pages/ListImport'))
const Events              = lazy(() => import('./pages/Events'))
const AuditLogs           = lazy(() => import('./pages/AuditLogs'))
const UserManagement      = lazy(() => import('./pages/UserManagement'))
const HubSpotSync         = lazy(() => import('./pages/HubSpotSync'))
const ProductIntelligence = lazy(() => import('./pages/ProductIntelligence'))
const Profile             = lazy(() => import('./pages/Profile'))
const PeopleSearch        = lazy(() => import('./pages/PeopleSearch'))
const CampaignBuilder     = lazy(() => import('./pages/CampaignBuilder'))
const Campaigns           = lazy(() => import('./pages/Campaigns'))
const DecisionIntelligence = lazy(() => import('./pages/DecisionIntelligence'))
const PredictionEngine     = lazy(() => import('./pages/PredictionEngine'))

function PageLoader() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#64748b' }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ width: 32, height: 32, border: '3px solid #e2e8f0', borderTopColor: '#6366f1', borderRadius: '50%', animation: 'spin 0.6s linear infinite', margin: '0 auto 12px' }} />
        <span style={{ fontSize: 14 }}>Loading…</span>
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}

export default function App() {
  const [cmdOpen, setCmdOpen]                   = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [token, setToken]                       = useState<string | null>(
    () => localStorage.getItem('token')
  )
  const [user, setUser]                         = useState<User | null>(
    () => { try { return JSON.parse(localStorage.getItem('user') || 'null') as User | null } catch { return null } }
  )

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); setCmdOpen(v => !v) }
      if (e.key === 'Escape') setCmdOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // Global 401 interceptor — intercept fetch so any expired session triggers logout
  useEffect(() => {
    const _orig = window.fetch.bind(window)
    window.fetch = async (...args) => {
      const res = await _orig(...args)
      if (res.status === 401) {
        const url = typeof args[0] === 'string' ? args[0] : (args[0] as Request).url
        if (url.includes('/api/') && !url.includes('/api/auth/login')) {
          handleLogout()
        }
      }
      return res
    }
    return () => { window.fetch = _orig }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleLogin = (tok: string, usr: User) => {
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

  const role = user?.role
  const isOwner    = role === 'owner'
  const isAdmin    = role === 'admin' || role === 'owner'
  const isAnalyst  = role === 'analyst' || isAdmin
  const isViewer   = role === 'viewer' || isAnalyst

  return (
    <BrowserRouter>
      <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden', background: '#f1f5f9' }}>
        <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(v => !v)} user={user ?? undefined} />
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0, overflow: 'hidden' }}>
          <Topbar onCmdK={() => setCmdOpen(true)} user={user ?? undefined} onLogout={handleLogout} />
          <main style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: 24, background: '#f1f5f9' }}>
            <Suspense fallback={<PageLoader />}>
              <Routes>
                <Route path="/"      element={<Navigate to="/dashboard" replace />} />
                <Route path="/login" element={<Navigate to="/dashboard" replace />} />

                {/* viewer+ */}
                {isViewer && <>
                  <Route path="/dashboard"                  element={<Dashboard />} />
                  <Route path="/decision-intelligence"      element={<DecisionIntelligence />} />
                  <Route path="/prediction-engine"          element={<PredictionEngine />} />
                  <Route path="/companies"                  element={<Companies />} />
                  <Route path="/contacts"                   element={<Contacts />} />
                  <Route path="/intent"                     element={<IntentData />} />
                  <Route path="/intent-data"                element={<IntentData />} />
                  <Route path="/events"                     element={<Events />} />
                  <Route path="/product-intelligence"       element={<ProductIntelligence />} />
                  <Route path="/profile"                    element={<Profile user={user ?? undefined} />} />
                  <Route path="/people-search"              element={<PeopleSearch />} />
                  <Route path="/campaign-builder"           element={<CampaignBuilder />} />
                  <Route path="/campaigns"                  element={<Campaigns />} />
                </>}

                {/* analyst+ */}
                {isAnalyst && <>
                  <Route path="/review"              element={<ReviewQueue />} />
                  <Route path="/review-queue"        element={<ReviewQueue />} />
                  <Route path="/technology-profiles" element={<TechnologyProfiles />} />
                  <Route path="/list-import"         element={<ListImport />} />
                  <Route path="/reporting"           element={<Reporting />} />
                  <Route path="/metrics"             element={<Metrics />} />
                </>}

                {/* admin+ */}
                {isAdmin && <>
                  <Route path="/engine"         element={<EngineControl />} />
                  <Route path="/engine-control" element={<EngineControl />} />
                  <Route path="/audit-logs"     element={<AuditLogs />} />
                  <Route path="/hubspot-sync"   element={<HubSpotSync />} />
                  <Route path="/settings"       element={<Settings />} />
                </>}

                {/* owner only */}
                {isOwner && <Route path="/user-management" element={<UserManagement />} />}

                {/* Catch-all → dashboard */}
                <Route path="*" element={<Navigate to="/dashboard" replace />} />
              </Routes>
            </Suspense>
          </main>
        </div>
        {cmdOpen && <CommandPalette onClose={() => setCmdOpen(false)} />}
        <ToastContainer />
      </div>
    </BrowserRouter>
  )
}
