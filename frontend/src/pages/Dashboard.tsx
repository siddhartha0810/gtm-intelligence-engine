import { useState, useEffect, useRef } from 'react'
import { Building2, Users, Zap, CheckCircle2, Play, Square, RefreshCw, ChevronRight, Clock, TrendingUp } from 'lucide-react'
import { toast } from '../components/Toast'
import { useNavigate } from 'react-router-dom'

const card = { background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }

const logColor = (level: string) => {
  if (level === 'SUCCESS') return '#10b981'
  if (level === 'ERROR') return '#ef4444'
  if (level === 'WARN') return '#f59e0b'
  return '#64748b'
}

const now = () => new Date().toLocaleTimeString('en-GB', { hour12: false })

interface DashboardStats {
  companies_tracked: number
  contacts_enriched: number
  intent_signals: number
  pushed_to_hubspot: number
  implementing: number
  evaluating: number
  researching: number
  scan_status: { status: string; progress?: Record<string, unknown> }
}

interface ScanLog { t: string; level: string; msg: string }

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [logs, setLogs] = useState<ScanLog[]>([{ t: now(), level: 'INFO', msg: 'Control panel loaded. Connecting to backend...' }])
  const [refreshing, setRefreshing] = useState(false)
  const [scanRunning, setScanRunning] = useState(false)
  const [backendOk, setBackendOk] = useState<boolean | null>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/dashboard')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: DashboardStats = await res.json()
      setStats(data)
      setBackendOk(true)
      setScanRunning(data.scan_status?.status === 'running')
    } catch {
      setBackendOk(false)
      setLogs(l => [...l, { t: now(), level: 'ERROR', msg: 'Backend unreachable. Start: uvicorn unified_app:app --reload --port 8000' }])
    }
  }

  const fetchLog = async () => {
    try {
      const res = await fetch('/scan/log')
      if (!res.ok) return
      const data = await res.json()
      const rawLog: string[] = Array.isArray(data) ? data : (data.log || data.logs || [])
      const entries: ScanLog[] = rawLog.map((line: string) => {
        const m = line.match(/^\[(\d{2}:\d{2}:\d{2})\]\s+\[(\w+)\]\s+(.+)$/)
        return m ? { t: m[1], level: m[2], msg: m[3] } : { t: now(), level: 'INFO', msg: line }
      })
      if (entries.length > 0) setLogs(entries.slice(-50))
    } catch { /* silent */ }
  }

  const refreshAll = async () => {
    setRefreshing(true)
    toast.info('Refreshing all systems...')
    await fetchStats()
    await fetchLog()
    setLogs(l => [...l, { t: now(), level: 'SUCCESS', msg: 'System refresh complete. All statuses updated.' }])
    setRefreshing(false)
    toast.success('All systems refreshed')
  }

  const toggleOracleScan = async () => {
    if (scanRunning) {
      try {
        await fetch('/scan/stop', { method: 'POST' })
        setScanRunning(false)
        setLogs(l => [...l, { t: now(), level: 'INFO', msg: 'Oracle Intent Engine stop signal sent.' }])
        toast.info('Oracle scan stopping...')
      } catch { toast.error('Failed to stop scan') }
    } else {
      try {
        const res = await fetch('/scan/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sources: ['indeed', 'linkedin', 'google_jobs', 'news'], max_pages: 3 }) })
        if (!res.ok) throw new Error()
        setScanRunning(true)
        setLogs(l => [...l, { t: now(), level: 'INFO', msg: 'Oracle Intent Engine starting... scanning LinkedIn Jobs, Indeed, Oracle News' }])
        toast.success('Oracle Intent scan started')
      } catch { toast.error('Failed to start scan') }
    }
  }

  useEffect(() => {
    fetchStats()
    fetchLog()
    const statsInterval = setInterval(fetchStats, 15000)
    const logInterval = setInterval(fetchLog, 5000)
    return () => { clearInterval(statsInterval); clearInterval(logInterval) }
  }, [])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  const kpis = [
    { label: 'Companies Tracked', value: stats ? stats.companies_tracked.toLocaleString() : '—', icon: Building2, color: '#3b82f6' },
    { label: 'Contacts Enriched', value: stats ? stats.contacts_enriched.toLocaleString() : '—', icon: Users, color: '#6366f1' },
    { label: 'Intent Signals', value: stats ? stats.intent_signals.toLocaleString() : '—', icon: Zap, color: '#f59e0b' },
    { label: 'Pushed to HubSpot', value: stats ? stats.pushed_to_hubspot.toLocaleString() : '—', icon: CheckCircle2, color: '#10b981' },
  ]

  const engineRows = [
    { id: 'oracle', label: 'Oracle Intent Engine', desc: '18 signal scrapers', color: '#3b82f6', live: scanRunning },
    { id: 'enrichment', label: 'Lead Enrichment', desc: '7-stage pipeline', color: '#6366f1', live: false },
    { id: 'hubspot', label: 'HubSpot Sync', desc: 'CRM connector', color: '#f59e0b', live: false },
  ]

  const activityItems = [
    { icon: CheckCircle2, color: '#10b981', msg: `${stats?.implementing ?? 0} companies in implementing phase`, time: 'live' },
    { icon: Zap, color: '#f59e0b', msg: `${stats?.intent_signals ?? 0} total Oracle intent signals`, time: 'live' },
    { icon: Building2, color: '#3b82f6', msg: `${stats?.companies_tracked ?? 0} companies tracked across all runs`, time: 'live' },
    { icon: TrendingUp, color: '#6366f1', msg: `${stats?.evaluating ?? 0} evaluating · ${stats?.researching ?? 0} researching`, time: 'live' },
    { icon: Clock, color: '#64748b', msg: backendOk === false ? 'Backend offline — run unified_app.py' : backendOk ? 'Backend connected on port 8000' : 'Connecting...', time: '' },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, width: '100%' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>Control Panel</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
            Live system overview — backend {backendOk === null ? 'connecting...' : backendOk ? <span style={{ color: '#10b981' }}>online</span> : <span style={{ color: '#ef4444' }}>offline</span>}
          </p>
        </div>
        <button
          onClick={refreshAll}
          disabled={refreshing}
          style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: refreshing ? 'default' : 'pointer', opacity: refreshing ? 0.75 : 1 }}
        >
          <RefreshCw size={13} style={{ animation: refreshing ? 'spin 1s linear infinite' : 'none' }} /> {refreshing ? 'Refreshing...' : 'Refresh All'}
        </button>
      </div>

      {/* Backend offline banner */}
      {backendOk === false && (
        <div style={{ padding: '12px 16px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 10, fontSize: 13, color: '#f87171' }}>
          Backend not running. From the DATA TOOL folder run: <code style={{ fontFamily: 'JetBrains Mono, monospace', background: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: 4 }}>uvicorn unified_app:app --reload --port 8000</code>
        </div>
      )}

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        {kpis.map(k => (
          <div key={k.label} style={card}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
              <div style={{ width: 36, height: 36, borderRadius: 8, background: `${k.color}20`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <k.icon size={17} color={k.color} strokeWidth={1.75} />
              </div>
              <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 999, background: backendOk ? 'rgba(16,185,129,0.12)' : 'rgba(107,114,128,0.15)', color: backendOk ? '#34d399' : '#6b7280' }}>
                {backendOk ? 'live' : 'offline'}
              </span>
            </div>
            <div style={{ fontSize: 26, fontWeight: 700, color: '#0f172a', lineHeight: 1 }}>{k.value}</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Middle row — engine status / review queue / live stats */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, alignItems: 'start' }}>

        {/* Engine Status */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>Engine Status</span>
            <span style={{ fontSize: 12, color: '#64748b' }}>{engineRows.filter(e => e.live).length}/{engineRows.length} active</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {engineRows.map((engine, i) => (
              <div key={engine.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: i < engineRows.length - 1 ? '1px solid #f1f5f9' : 'none' }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, background: engine.live ? engine.color : '#cbd5e1', boxShadow: engine.live ? `0 0 6px ${engine.color}` : 'none' }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#0f172a', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{engine.label}</div>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{engine.desc}</div>
                </div>
                <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, fontWeight: 500, flexShrink: 0, background: engine.live ? `${engine.color}18` : 'rgba(203,213,225,0.5)', color: engine.live ? engine.color : '#94a3b8' }}>
                  {engine.live ? 'Running' : 'Idle'}
                </span>
                {engine.id === 'oracle' && (
                  <button
                    onClick={toggleOracleScan}
                    style={{ width: 28, height: 28, borderRadius: 7, border: '1px solid #e2e8f0', background: 'transparent', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', color: engine.live ? '#ef4444' : '#94a3b8', flexShrink: 0 }}
                  >
                    {engine.live ? <Square size={11} /> : <Play size={11} />}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Review Queue */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>Review Queue</span>
            <button onClick={() => navigate('/review')} style={{ fontSize: 12, fontWeight: 500, color: '#3b82f6', display: 'flex', alignItems: 'center', gap: 4, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
              View all <ChevronRight size={12} />
            </button>
          </div>
          {stats ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {[
                { label: 'Implementing', count: stats.implementing, color: '#3b82f6' },
                { label: 'Evaluating', count: stats.evaluating, color: '#6366f1' },
                { label: 'Researching', count: stats.researching, color: '#94a3b8' },
              ].map(row => (
                <div key={row.label} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: row.color, flexShrink: 0 }} />
                  <div style={{ flex: 1, fontSize: 13, color: '#0f172a' }}>{row.label}</div>
                  <span style={{ fontSize: 13, fontWeight: 700, color: row.color }}>{row.count}</span>
                </div>
              ))}
              <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                <div style={{ flex: 1, textAlign: 'center', padding: '8px 0', borderRadius: 8, background: 'rgba(59,130,246,0.1)', color: '#60a5fa', fontSize: 12, fontWeight: 500 }}>
                  Total <strong>{stats.companies_tracked}</strong>
                </div>
                <div style={{ flex: 1, textAlign: 'center', padding: '8px 0', borderRadius: 8, background: 'rgba(16,185,129,0.1)', color: '#34d399', fontSize: 12, fontWeight: 500 }}>
                  Signals <strong>{stats.intent_signals}</strong>
                </div>
              </div>
            </div>
          ) : (
            <div style={{ color: '#94a3b8', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>Loading...</div>
          )}
        </div>

        {/* Recent Activity */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>Live Stats</span>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: backendOk ? '#10b981' : '#374151' }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {activityItems.map((item, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                <div style={{ width: 28, height: 28, borderRadius: 7, background: `${item.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <item.icon size={13} color={item.color} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, color: '#0f172a', lineHeight: '1.5' }}>{item.msg}</div>
                  {item.time && <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>{item.time}</div>}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* System Log */}
      <div style={{ background: '#080c14', border: '1px solid #1f2d45', borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '1px solid #1f2d45' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#ef4444' }} />
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#f59e0b' }} />
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#10b981' }} />
            <span style={{ marginLeft: 8, fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#475569' }}>
              system.log — {logs.length} lines
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: scanRunning ? '#10b981' : '#cbd5e1' }} />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>{scanRunning ? 'scanning' : 'idle'}</span>
          </div>
        </div>
        <div ref={logRef} style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, padding: 16, height: 160, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {logs.map((log, i) => (
            <div key={i} style={{ display: 'flex', gap: 12, lineHeight: '1.6' }}>
              <span style={{ color: '#374151', flexShrink: 0 }}>[{log.t}]</span>
              <span style={{ color: logColor(log.level), flexShrink: 0, minWidth: 72 }}>[{log.level}]</span>
              <span style={{ color: '#94a3b8' }}>{log.msg}</span>
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ color: '#374151' }}>›</span>
            <span style={{ display: 'inline-block', width: 7, height: 14, background: '#3b82f6' }} className="animate-blink" />
          </div>
        </div>
      </div>

    </div>
  )
}
