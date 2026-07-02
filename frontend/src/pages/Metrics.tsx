import { useState, useEffect } from 'react'
import { Activity, Zap, Building2, CreditCard, RefreshCw, AlertTriangle } from 'lucide-react'

const authH = () => ({ 'Authorization': `Bearer ${localStorage.getItem('token') || ''}` })

interface SourceHealth {
  tier: 'P0' | 'P1' | 'P2'
  last_seen: string | null
  hours_silent: number | null
  status: 'healthy' | 'warning' | 'critical' | 'never_seen'
}

interface HealthData {
  checked_at: string
  overall: 'healthy' | 'degraded' | 'critical'
  sources: Record<string, SourceHealth>
  alerts: string[]
}

interface SummaryData {
  signals: {
    total: number; companies: number; p0: number; p1: number; p2: number
    implementing: number; evaluating: number; hiring: number; last_signal_at: string | null
  }
  leads: { total: number; ready_for_outreach: number }
  error?: string
}

interface CreditEntry { step: string; calls: number; total_used: number; last_used_at: string }
interface CreditsData {
  log: { id: number; run_id: string; step: string; credits_used: number | null; logged_at: string }[]
  summary: { by_step: CreditEntry[]; grand_total: number }
  error?: string
}

const card = { background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }
const fmt = (n: number | undefined | null) => (n ?? 0).toLocaleString()

const STATUS_COLOR: Record<string, string> = {
  healthy: '#10b981', warning: '#f59e0b', critical: '#ef4444', never_seen: '#94a3b8',
}
const TIER_LABEL: Record<string, string> = { P0: 'Core (P0)', P1: 'Secondary (P1)', P2: 'Contextual (P2)' }

function SectionTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>{title}</div>
      {sub && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function SourceRow({ name, health }: { name: string; health: SourceHealth }) {
  const color = STATUS_COLOR[health.status] || '#94a3b8'
  const label = health.status === 'never_seen' ? 'never seen'
    : health.hours_silent !== null ? `${health.hours_silent}h silent`
    : '—'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid #f1f5f9' }}>
      <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
      <span style={{ flex: 1, fontSize: 13, color: '#334155' }}>{name}</span>
      <span style={{ fontSize: 12, color: '#94a3b8' }}>{label}</span>
    </div>
  )
}

export default function Metrics() {
  const [health, setHealth]   = useState<HealthData | null>(null)
  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [credits, setCredits] = useState<CreditsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [hr, sr, cr] = await Promise.all([
        fetch('/api/health/signals', { headers: authH() }).then(r => { if (!r.ok) throw new Error(`Health: HTTP ${r.status}`); return r.json() }),
        fetch('/api/metrics/summary', { headers: authH() }).then(r => { if (!r.ok) throw new Error(`Summary: HTTP ${r.status}`); return r.json() }),
        fetch('/api/metrics/credits', { headers: authH() }).then(r => { if (!r.ok) throw new Error(`Credits: HTTP ${r.status}`); return r.json() }),
      ])
      setHealth(hr)
      setSummary(sr)
      setCredits(cr)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load metrics')
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const sources = health?.sources ?? {}
  const tiers: ('P0' | 'P1' | 'P2')[] = ['P0', 'P1', 'P2']
  const healthyCount = Object.values(sources).filter(s => s.status === 'healthy').length
  const totalSources = Object.keys(sources).length
  const byStep = credits?.summary?.by_step ?? []
  const maxStep = Math.max(...byStep.map(s => s.total_used || 0), 1)

  const overallColor = health?.overall === 'healthy' ? '#10b981' : health?.overall === 'degraded' ? '#f59e0b' : '#ef4444'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      <style>{`@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}`}</style>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>System Metrics</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>Signal source health, API credit burn, and pipeline uptime</p>
        </div>
        <button onClick={load} disabled={loading}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 12, cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.5 : 1 }}>
          <RefreshCw size={12} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div style={{ padding: '12px 16px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 10, fontSize: 13, color: '#f87171' }}>
          {error}
        </div>
      )}

      {health && health.alerts.length > 0 && (
        <div style={{ padding: '14px 16px', background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 10, display: 'flex', gap: 10 }}>
          <AlertTriangle size={16} color="#ef4444" style={{ flexShrink: 0, marginTop: 1 }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {health.alerts.map((a, i) => <span key={i} style={{ fontSize: 13, color: '#ef4444' }}>{a}</span>)}
          </div>
        </div>
      )}

      {/* Top KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        {[
          { label: 'Signal Sources Healthy', value: `${healthyCount}/${totalSources || 0}`, icon: Activity,   color: overallColor },
          { label: 'Total Intent Signals',   value: fmt(summary?.signals?.total),          icon: Zap,        color: '#3b82f6' },
          { label: 'Companies Tracked',      value: fmt(summary?.signals?.companies),      icon: Building2,  color: '#6366f1' },
          { label: 'Apollo Credits Used',    value: fmt(credits?.summary?.grand_total),    icon: CreditCard, color: '#f59e0b' },
        ].map(k => (
          <div key={k.label} style={card}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
              <div style={{ width: 36, height: 36, borderRadius: 8, background: `${k.color}18`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <k.icon size={16} color={k.color} strokeWidth={1.75} />
              </div>
              <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, fontWeight: 500, background: 'rgba(16,185,129,0.1)', color: '#34d399' }}>live</span>
            </div>
            <div style={{ fontSize: 26, fontWeight: 700, color: '#0f172a', lineHeight: 1 }}>
              {loading ? '—' : k.value}
            </div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Source health grid — grouped by tier */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
        {tiers.map(tier => {
          const tierSources = Object.entries(sources).filter(([, h]) => h.tier === tier)
          return (
            <div key={tier} style={card}>
              <SectionTitle title={TIER_LABEL[tier]} sub={`${tierSources.length} source${tierSources.length === 1 ? '' : 's'}`} />
              {loading ? <div style={{ color: '#94a3b8', fontSize: 13 }}>Loading...</div>
              : tierSources.length === 0 ? <div style={{ color: '#94a3b8', fontSize: 13 }}>No sources in this tier.</div>
              : tierSources.map(([name, h]) => <SourceRow key={name} name={name} health={h} />)}
            </div>
          )
        })}
      </div>

      {/* Apollo credit burn by pipeline step */}
      <div style={card}>
        <SectionTitle title="Apollo Credit Burn by Step" sub="Where credits are being spent across the enrichment pipeline" />
        {loading ? <div style={{ color: '#94a3b8', fontSize: 13 }}>Loading...</div>
        : byStep.length === 0 ? <div style={{ color: '#94a3b8', fontSize: 13 }}>No credit usage logged yet.</div>
        : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {byStep.map(s => {
              const p = maxStep ? Math.round((s.total_used || 0) / maxStep * 100) : 0
              return (
                <div key={s.step}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                    <span style={{ color: '#475569', fontWeight: 500 }}>{s.step}</span>
                    <span style={{ color: '#64748b' }}>{fmt(s.total_used)} credits <span style={{ color: '#94a3b8' }}>({s.calls} calls)</span></span>
                  </div>
                  <div style={{ height: 6, borderRadius: 999, background: '#f1f5f9', overflow: 'hidden' }}>
                    <div style={{ height: '100%', borderRadius: 999, background: '#f59e0b', width: `${p}%`, transition: 'width 0.5s ease' }} />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
