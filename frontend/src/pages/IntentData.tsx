import { useState, useEffect } from 'react'
import { Zap, TrendingUp, Building2, RefreshCw } from 'lucide-react'

const authH = () => ({ 'Authorization': `Bearer ${localStorage.getItem('token') || ''}` })

interface Signal {
  id: number
  company_name: string
  oracle_product: string
  phase: string
  source: string
  signal_type: string
  job_title: string
  evidence: string
  url: string
  confidence: number
  detected_at: string
}

const strengthLabel = (conf: number) =>
  conf >= 0.7 ? 'High' : conf >= 0.4 ? 'Medium' : 'Low'

const strengthStyle = (conf: number) => {
  const s = strengthLabel(conf)
  if (s === 'High')   return { background: 'rgba(239,68,68,0.12)',   color: '#f87171' }
  if (s === 'Medium') return { background: 'rgba(245,158,11,0.12)',  color: '#fbbf24' }
  return                     { background: 'rgba(107,114,128,0.12)', color: '#9ca3af' }
}

const relativeTime = (iso: string) => {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const h = Math.floor(diff / 3_600_000)
  if (h < 1) return `${Math.floor(diff / 60_000)}m ago`
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

const card = { background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }

export default function IntentData() {
  const [signals, setSignals] = useState<Signal[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const r = await fetch('/api/signals?limit=200', { headers: authH() })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setSignals(await r.json())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load signals')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const high   = signals.filter(s => s.confidence >= 0.7).length
  const avgScore = signals.length
    ? Math.round(signals.reduce((a, s) => a + s.confidence * 100, 0) / signals.length)
    : 0
  const uniqueCompanies = new Set(signals.map(s => s.company_name)).size

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>Intent Data</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
            Oracle/JDE buying signals detected across {uniqueCompanies} companies
          </p>
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

      <style>{`@keyframes spin { from { transform:rotate(0deg) } to { transform:rotate(360deg) } }`}</style>

      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        {[
          { label: 'High-intent signals',  value: loading ? '—' : String(high),              color: '#ef4444', icon: Zap },
          { label: 'Companies detected',   value: loading ? '—' : String(uniqueCompanies),   color: '#3b82f6', icon: Building2 },
          { label: 'Avg confidence score', value: loading ? '—' : `${avgScore}`,              color: '#10b981', icon: TrendingUp },
        ].map(k => (
          <div key={k.label} style={{ ...card, display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{ width: 44, height: 44, borderRadius: 10, background: `${k.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <k.icon size={20} color={k.color} strokeWidth={1.75} />
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#0f172a', lineHeight: 1 }}>{k.value}</div>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>{k.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Signals table */}
      <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        <div style={{ padding: '12px 20px', borderBottom: '1px solid #f1f5f9', fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: '#64748b' }}>
          LATEST INTENT SIGNALS ({signals.length})
        </div>

        {error && (
          <div style={{ padding: 20, color: '#f87171', fontSize: 13 }}>Error: {error}</div>
        )}

        {!error && signals.length === 0 && !loading && (
          <div style={{ padding: 40, textAlign: 'center', color: '#475569', fontSize: 13 }}>
            No signals yet. Run an Oracle Intent scan to populate this list.
          </div>
        )}

        {!error && signals.map((sig, i) => (
          <div
            key={sig.id}
            style={{
              display: 'flex', alignItems: 'center', gap: 16, padding: '14px 20px',
              borderBottom: i < signals.length - 1 ? '1px solid #f1f5f9' : 'none',
              background: '#ffffff',
            }}
          >
            <div style={{ width: 36, height: 36, borderRadius: 8, background: 'rgba(59,130,246,0.12)', color: '#60a5fa', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 14, flexShrink: 0 }}>
              {sig.company_name[0]}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 14, fontWeight: 500, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sig.company_name}</span>
                <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, fontWeight: 500, flexShrink: 0, ...strengthStyle(sig.confidence) }}>
                  {strengthLabel(sig.confidence)}
                </span>
                {sig.oracle_product && (
                  <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: 'rgba(99,102,241,0.12)', color: '#a5b4fc', flexShrink: 0 }}>
                    {sig.oracle_product}
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12, color: '#64748b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {sig.evidence || sig.job_title || sig.signal_type || '—'}
              </div>
            </div>
            <div style={{ textAlign: 'right', flexShrink: 0 }}>
              <div style={{ fontSize: 12, color: '#64748b' }}>{sig.source}</div>
              <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>{relativeTime(sig.detected_at)}</div>
            </div>
            <div style={{ fontSize: 14, fontWeight: 700, color: sig.confidence >= 0.7 ? '#10b981' : sig.confidence >= 0.4 ? '#f59e0b' : '#ef4444', flexShrink: 0, minWidth: 28, textAlign: 'right' }}>
              {Math.round(sig.confidence * 100)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
