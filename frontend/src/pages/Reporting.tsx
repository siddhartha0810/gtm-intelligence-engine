import { useState, useEffect } from 'react'
import { TrendingUp, Users, Building2, CheckCircle2, RefreshCw } from 'lucide-react'

const authH = () => ({ 'Authorization': `Bearer ${localStorage.getItem('token') || ''}` })

interface ReportingData {
  total_companies: number
  total_signals: number
  phases: Record<string, number>
  sources: { label: string; count: number; pct: number }[]
  scan_runs: { id: number; started_at: string; completed_at: string; status: string; total_signals: number; total_companies: number }[]
}

interface DashboardData {
  contacts_enriched: number
  pushed_to_hubspot: number
}

const card = { background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }

const sourceColors = ['#3b82f6', '#6366f1', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']

const relativeDate = (iso: string) => {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function Reporting() {
  const [report, setReport]     = useState<ReportingData | null>(null)
  const [dash, setDash]         = useState<DashboardData | null>(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [rr, dr] = await Promise.all([
        fetch('/api/reporting', { headers: authH() }).then(r => { if (!r.ok) throw new Error(`Reporting: HTTP ${r.status}`); return r.json() }),
        fetch('/api/dashboard', { headers: authH() }).then(r => { if (!r.ok) throw new Error(`Dashboard: HTTP ${r.status}`); return r.json() }),
      ])
      setReport(rr)
      setDash(dr)
    } catch (e: any) {
      setError(e.message || 'Failed to load reporting data')
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const phases  = report?.phases   ?? {}
  const sources = report?.sources  ?? []
  const runs    = report?.scan_runs ?? []
  const totalPhase = Object.values(phases).reduce((a, b) => a + b, 0) || 1

  // Build scan-run bar chart — normalise on max total_signals
  const maxSig = Math.max(...runs.map(r => r.total_signals || 0), 1)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      <style>{`@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}`}</style>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>Reporting</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>Live pipeline analytics from your databases</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 12, cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.5 : 1 }}
        >
          <RefreshCw size={12} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div style={{ padding: '12px 16px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 10, fontSize: 13, color: '#f87171' }}>
          {error}
        </div>
      )}

      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        {[
          { label: 'Companies tracked',    value: report?.total_companies  ?? '—', icon: Building2,    color: '#3b82f6' },
          { label: 'Contacts enriched',    value: dash?.contacts_enriched  ?? '—', icon: Users,        color: '#6366f1' },
          { label: 'Intent signals found', value: report?.total_signals    ?? '—', icon: CheckCircle2, color: '#10b981' },
          { label: 'Scan runs completed',  value: runs.filter(r => r.status === 'completed').length ?? '—', icon: TrendingUp, color: '#f59e0b' },
        ].map(k => (
          <div key={k.label} style={card}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
              <div style={{ width: 36, height: 36, borderRadius: 8, background: `${k.color}18`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <k.icon size={16} color={k.color} strokeWidth={1.75} />
              </div>
              <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, fontWeight: 500, background: 'rgba(16,185,129,0.1)', color: '#34d399' }}>live</span>
            </div>
            <div style={{ fontSize: 26, fontWeight: 700, color: '#0f172a', lineHeight: 1 }}>
              {loading ? '—' : typeof k.value === 'number' ? k.value.toLocaleString() : k.value}
            </div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Scan run history chart */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>Scan Run History</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 12, color: '#475569' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: '#6366f1' }} /> Signals
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: '#10b981' }} /> Companies
            </div>
          </div>
        </div>

        {runs.length === 0 ? (
          <div style={{ height: 160, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#374151', fontSize: 13 }}>
            No scan runs yet — run an Oracle Intent scan to see history here.
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, height: 160 }}>
            {[...runs].reverse().map(run => {
              const sigPct  = (run.total_signals  || 0) / maxSig * 100
              const compPct = (run.total_companies || 0) / maxSig * 100
              return (
                <div key={run.id} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                  <div style={{ width: '100%', display: 'flex', alignItems: 'flex-end', gap: 3, height: 130 }}>
                    <div style={{ flex: 1, borderRadius: '4px 4px 0 0', background: '#6366f1', opacity: 0.75, height: `${sigPct}%`, minHeight: sigPct > 0 ? 2 : 0, transition: 'height 0.4s' }} title={`${run.total_signals} signals`} />
                    <div style={{ flex: 1, borderRadius: '4px 4px 0 0', background: '#10b981', opacity: 0.85, height: `${compPct}%`, minHeight: compPct > 0 ? 2 : 0, transition: 'height 0.4s' }} title={`${run.total_companies} companies`} />
                  </div>
                  <span style={{ fontSize: 10, color: '#475569' }}>#{run.id}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Bottom two panels */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>

        {/* Source breakdown */}
        <div style={card}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', marginBottom: 16 }}>Top Data Sources</div>
          {sources.length === 0 ? (
            <div style={{ color: '#374151', fontSize: 13, padding: '12px 0' }}>No data yet.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {sources.map((s, i) => (
                <div key={s.label}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 6 }}>
                    <span style={{ color: '#94a3b8' }}>{s.label}</span>
                    <span style={{ color: '#64748b' }}>{s.pct}% ({s.count})</span>
                  </div>
                  <div style={{ height: 5, borderRadius: 999, background: '#e2e8f0', overflow: 'hidden' }}>
                    <div style={{ height: '100%', borderRadius: 999, background: sourceColors[i % sourceColors.length], width: `${s.pct}%`, transition: 'width 0.4s' }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Phase distribution */}
        <div style={card}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', marginBottom: 16 }}>Phase Distribution</div>
          {Object.keys(phases).length === 0 ? (
            <div style={{ color: '#374151', fontSize: 13, padding: '12px 0' }}>No data yet.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {Object.entries(phases).map(([phase, count], i) => {
                const pct = Math.round(count / totalPhase * 100)
                const color = sourceColors[i % sourceColors.length]
                return (
                  <div key={phase} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 6 }}>
                        <span style={{ color: '#94a3b8', textTransform: 'capitalize' }}>{phase}</span>
                        <span style={{ color: '#64748b' }}>{count} companies</span>
                      </div>
                      <div style={{ height: 5, borderRadius: 999, background: '#e2e8f0', overflow: 'hidden' }}>
                        <div style={{ height: '100%', borderRadius: 999, background: color, width: `${pct}%`, transition: 'width 0.4s' }} />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Scan run table */}
      {runs.length > 0 && (
        <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
          <div style={{ padding: '12px 20px', borderBottom: '1px solid #f1f5f9', fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: '#64748b' }}>
            SCAN RUN LOG
          </div>
          {runs.map((run, i) => (
            <div key={run.id} style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '12px 20px', borderBottom: i < runs.length - 1 ? '1px solid #f1f5f9' : 'none', background: '#ffffff', fontSize: 13 }}>
              <span style={{ color: '#94a3b8', minWidth: 32 }}>#{run.id}</span>
              <span style={{ flex: 1, color: '#0f172a' }}>{relativeDate(run.started_at)}</span>
              <span style={{ color: '#64748b', minWidth: 100 }}>{run.total_signals ?? 0} signals</span>
              <span style={{ color: '#64748b', minWidth: 110 }}>{run.total_companies ?? 0} companies</span>
              <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 999, background: run.status === 'completed' ? 'rgba(16,185,129,0.12)' : run.status === 'running' ? 'rgba(59,130,246,0.12)' : 'rgba(107,114,128,0.12)', color: run.status === 'completed' ? '#34d399' : run.status === 'running' ? '#60a5fa' : '#9ca3af' }}>
                {run.status}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
