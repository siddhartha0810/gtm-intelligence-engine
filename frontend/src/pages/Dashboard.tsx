import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Building2, Users, Zap, Send, Play, Square, RefreshCw, ArrowRight,
  Sparkles, Crosshair, Target, CheckCircle2, Rocket,
} from 'lucide-react'
import { toast } from '../components/Toast'
import { useNavigate } from 'react-router-dom'
import { colors, card, radius, shadow, fmt } from '../theme'

const authH = () => ({ Authorization: `Bearer ${localStorage.getItem('token') || ''}` })
const ts = () => new Date().toLocaleTimeString('en-GB', { hour12: false })
const logColor = (l: string) => l === 'SUCCESS' ? '#10b981' : l === 'ERROR' ? '#ef4444' : l === 'WARN' ? '#f59e0b' : '#64748b'

interface DashboardStats {
  companies_tracked: number
  contacts_enriched: number
  intent_signals: number
  pushed_to_hubspot: number
  outreach_ready: number
  implementing: number
  evaluating: number
  researching: number
  scan_status: { status: string; progress?: string }
}
interface ScanLog { t: string; level: string; msg: string }
type BackendState = 'loading' | 'online' | 'offline'

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [logs, setLogs] = useState<ScanLog[]>([])
  const [backendState, setBackendState] = useState<BackendState>('loading')
  const [scanRunning, setScanRunning] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [launching, setLaunching] = useState(false)

  const logRef = useRef<HTMLDivElement>(null)
  const failCount = useRef(0)
  const navigate = useNavigate()

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch('/api/dashboard', { headers: authH() })
      if (res.status === 401) { localStorage.removeItem('token'); navigate('/login'); return }
      if (!res.ok) throw new Error()
      const data: DashboardStats = await res.json()
      setStats(data)
      setBackendState('online')
      setScanRunning(data.scan_status?.status === 'running')
      failCount.current = 0
    } catch {
      failCount.current += 1
      if (failCount.current >= 2) setBackendState('offline')
    }
  }, [navigate])

  const fetchLog = useCallback(async () => {
    try {
      const res = await fetch('/scan/log', { headers: authH() })
      if (!res.ok) return
      const data = await res.json()
      const raw: string[] = Array.isArray(data) ? data : (data.log || data.logs || [])
      const entries: ScanLog[] = raw.map((line: string) => {
        const m = line.match(/^\[(\d{2}:\d{2}:\d{2})\]\s+\[(\w+)\]\s+(.+)$/)
        return m ? { t: m[1], level: m[2], msg: m[3] } : { t: ts(), level: 'INFO', msg: line }
      })
      if (entries.length) setLogs(entries.slice(-40))
    } catch { /* silent */ }
  }, [])

  useEffect(() => {
    fetchStats(); fetchLog()
    const si = setInterval(fetchStats, 30000)
    const li = setInterval(fetchLog, 15000)
    return () => { clearInterval(si); clearInterval(li) }
  }, [fetchStats, fetchLog])

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight }, [logs])

  const launchHunt = async () => {
    const p = prompt.trim()
    if (!p) { toast.info('Describe who you want to find first'); return }
    setLaunching(true)
    try {
      const res = await fetch('/api/agents/strategist/campaign', {
        method: 'POST', headers: { ...authH(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: p }),
      })
      if (res.status === 403) { toast.error('Your role can’t launch campaigns'); return }
      if (!res.ok) throw new Error()
      const data = await res.json()
      const name = data?.campaign?.name || 'campaign'
      toast.success(`Created “${name}”${data.degraded ? ' (review keywords)' : ''}`)
      setPrompt('')
      navigate('/campaigns')
    } catch { toast.error('Could not create campaign — is an LLM provider configured?') }
    finally { setLaunching(false) }
  }

  const toggleScan = async () => {
    try {
      if (scanRunning) {
        await fetch('/scan/stop', { method: 'POST', headers: authH() })
        setScanRunning(false); toast.info('Scan stopping…')
      } else {
        const res = await fetch('/scan/start', {
          method: 'POST', headers: { ...authH(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ sources: ['ats', 'linkedin', 'news'], max_pages: 3 }),
        })
        if (!res.ok) throw new Error()
        setScanRunning(true); toast.success('Scan started')
      }
    } catch { toast.error('Engine action failed') }
  }

  // ── Funnel stages (the GTM pipeline, left → right) ──────────────────────────
  const funnel = [
    { label: 'Intent Signals', value: stats?.intent_signals, icon: Zap,        color: colors.warning, to: '/intent-data' },
    { label: 'Companies',      value: stats?.companies_tracked, icon: Building2, color: colors.primary, to: '/companies' },
    { label: 'Contacts',       value: stats?.contacts_enriched, icon: Users,     color: colors.indigo,  to: '/contacts' },
    { label: 'Outreach-Ready', value: stats?.outreach_ready, icon: CheckCircle2, color: colors.success, to: '/people-search' },
  ]

  const stages = [
    { n: 1, label: 'Hunt', icon: Crosshair, color: colors.primary,
      metric: fmt(stats?.intent_signals), unit: 'signals detected',
      desc: 'Turn a prompt or ICP into live intent signals.',
      cta: 'Open Campaign Builder', to: '/campaign-builder' },
    { n: 2, label: 'Pipeline', icon: Target, color: colors.indigo,
      metric: fmt(stats?.companies_tracked), unit: 'companies in pipeline',
      desc: 'Review detected companies and their contacts.',
      cta: 'View Companies', to: '/companies' },
    { n: 3, label: 'Reach', icon: Send, color: colors.success,
      metric: fmt(stats?.outreach_ready), unit: 'contacts outreach-ready',
      desc: 'Enrich, validate, and push to sequences or CRM.',
      cta: 'People Search', to: '/people-search' },
  ]

  const dot = (s: BackendState) => s === 'online' ? colors.success : s === 'loading' ? colors.warning : '#94a3b8'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: colors.text, margin: 0, letterSpacing: '-0.01em' }}>Command Center</h1>
          <p style={{ fontSize: 13, color: colors.textMute, marginTop: 4 }}>Your GTM pipeline at a glance — from signal to outreach.</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: colors.textMute }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: dot(backendState), boxShadow: backendState === 'online' ? `0 0 6px ${colors.success}` : 'none' }} />
          {backendState === 'online' ? 'Backend live' : backendState === 'loading' ? 'Connecting…' : 'Backend offline'}
        </div>
      </div>

      {/* Prompt-driven entry — the workflow starts here */}
      <div style={{
        borderRadius: radius.xl, padding: 22,
        background: 'linear-gradient(135deg, #0f1e36 0%, #1e293b 100%)',
        boxShadow: shadow.lg, border: '1px solid #1a3050',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <Sparkles size={16} color="#93c5fd" />
          <span style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>Start a hunt</span>
          <span style={{ fontSize: 12, color: '#64748b' }}>— describe who you want to find, in plain English</span>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <input
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !launching) launchHunt() }}
            placeholder="e.g. mid-market manufacturers hiring NetSuite admins in the US"
            style={{
              flex: 1, padding: '12px 16px', borderRadius: radius.md, fontSize: 14,
              background: 'rgba(255,255,255,0.06)', border: '1px solid #334155',
              color: '#f1f5f9', outline: 'none',
            }}
          />
          <button onClick={launchHunt} disabled={launching}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 8, padding: '0 20px',
              borderRadius: radius.md, border: 'none', cursor: launching ? 'default' : 'pointer',
              background: 'linear-gradient(135deg, #3b82f6, #6366f1)', color: '#fff',
              fontSize: 14, fontWeight: 600, opacity: launching ? 0.7 : 1, whiteSpace: 'nowrap',
            }}>
            <Rocket size={15} style={{ animation: launching ? 'spin 1s linear infinite' : 'none' }} />
            {launching ? 'Creating…' : 'Launch'}
          </button>
        </div>
      </div>

      {/* Funnel strip */}
      <div style={{ ...card, padding: '18px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {funnel.map((f, i) => (
            <div key={f.label} style={{ display: 'contents' }}>
              <button onClick={() => navigate(f.to)} style={{
                flex: 1, display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 10px',
                background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left', borderRadius: radius.sm,
              }}
                onMouseEnter={e => (e.currentTarget.style.background = '#f8fafc')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 26, height: 26, borderRadius: 7, background: `${f.color}18`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <f.icon size={14} color={f.color} />
                  </span>
                  <span style={{ fontSize: 12, color: colors.textMute }}>{f.label}</span>
                </div>
                <span style={{ fontSize: 26, fontWeight: 700, color: colors.text, lineHeight: 1 }}>
                  {stats ? fmt(f.value) : '—'}
                </span>
              </button>
              {i < funnel.length - 1 && <ArrowRight size={16} color="#cbd5e1" style={{ flexShrink: 0 }} />}
            </div>
          ))}
        </div>
      </div>

      {/* Workflow stage cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        {stages.map(s => (
          <div key={s.n} style={{ ...card, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 34, height: 34, borderRadius: 9, background: `${s.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <s.icon size={17} color={s.color} strokeWidth={1.9} />
              </span>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', color: s.color }}>STEP {s.n}</div>
                <div style={{ fontSize: 15, fontWeight: 600, color: colors.text }}>{s.label}</div>
              </div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: colors.text, lineHeight: 1 }}>{stats ? s.metric : '—'}</div>
              <div style={{ fontSize: 12, color: colors.textMute, marginTop: 4 }}>{s.unit}</div>
            </div>
            <div style={{ fontSize: 12.5, color: colors.textMute, lineHeight: 1.5, minHeight: 36 }}>{s.desc}</div>
            <button onClick={() => navigate(s.to)} style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '9px 14px', borderRadius: radius.sm, border: `1px solid ${colors.border}`,
              background: '#f8fafc', color: colors.text, fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
              onMouseEnter={e => { e.currentTarget.style.background = `${s.color}10`; e.currentTarget.style.borderColor = `${s.color}40` }}
              onMouseLeave={e => { e.currentTarget.style.background = '#f8fafc'; e.currentTarget.style.borderColor = colors.border }}>
              {s.cta} <ArrowRight size={14} />
            </button>
          </div>
        ))}
      </div>

      {/* Engine + live log */}
      <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16, alignItems: 'stretch' }}>
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: colors.text }}>Signal Engine</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: scanRunning ? colors.success : '#cbd5e1', boxShadow: scanRunning ? `0 0 6px ${colors.success}` : 'none' }} />
            <span style={{ fontSize: 13, color: colors.text, fontWeight: 500 }}>{scanRunning ? 'Scanning' : 'Idle'}</span>
          </div>
          <p style={{ fontSize: 12, color: colors.textMute, margin: 0, lineHeight: 1.5 }}>
            Detects intent from ATS boards, LinkedIn, and news across your watch-list.
          </p>
          <button onClick={toggleScan} style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            padding: '9px 14px', borderRadius: radius.sm, border: 'none', cursor: 'pointer',
            background: scanRunning ? 'rgba(239,68,68,0.1)' : colors.primary,
            color: scanRunning ? colors.danger : '#fff', fontSize: 13, fontWeight: 600,
          }}>
            {scanRunning ? <><Square size={13} /> Stop scan</> : <><Play size={13} /> Run scan</>}
          </button>
        </div>

        <div style={{ background: '#080c14', border: '1px solid #1f2d45', borderRadius: radius.lg, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '1px solid #1f2d45' }}>
            <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#475569' }}>scan.log — {logs.length} lines</span>
            <button onClick={fetchLog} style={{ background: 'none', border: 'none', color: '#475569', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
              <RefreshCw size={11} /> refresh
            </button>
          </div>
          <div ref={logRef} style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, padding: 14, height: 150, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
            {logs.length === 0 && <span style={{ color: '#475569' }}>No scan activity yet — launch a hunt to begin.</span>}
            {logs.map((log, i) => (
              <div key={i} style={{ display: 'flex', gap: 12, lineHeight: 1.6 }}>
                <span style={{ color: '#374151', flexShrink: 0 }}>[{log.t}]</span>
                <span style={{ color: logColor(log.level), flexShrink: 0, minWidth: 64 }}>[{log.level}]</span>
                <span style={{ color: '#94a3b8' }}>{log.msg}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
