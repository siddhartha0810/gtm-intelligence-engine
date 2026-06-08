import { useState, useEffect } from 'react'
import { TrendingUp, Users, Building2, CheckCircle2, RefreshCw, Mail, Linkedin, BarChart2 } from 'lucide-react'

const authH = () => ({ 'Authorization': `Bearer ${localStorage.getItem('token') || ''}` })

interface ReportingData {
  total_companies: number
  total_signals: number
  phases: Record<string, number>
  sources: { label: string; count: number; pct: number }[]
  scan_runs: { id: number; started_at: string; completed_at: string; status: string; total_signals: number; total_companies: number }[]
  companies_by_product: { product: string; count: number }[]
  company_contact_stats: { total: number; with_contacts: number; without_contacts: number }
  contact_reach_stats: { total: number; email_and_linkedin: number; email_only: number; linkedin_only: number; no_reach: number; valid_emails: number }
  contact_by_source: { label: string; count: number; pct: number }[]
}

interface DashboardData {
  contacts_enriched: number
  pushed_to_hubspot: number
}

const card = { background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }
const BAR_COLORS = ['#3b82f6', '#6366f1', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316']

const fmt = (n: number | undefined) => (n ?? 0).toLocaleString()
const pct = (n: number, total: number) => total ? Math.round(n / total * 100) : 0

const relativeDate = (iso: string) => {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

function SectionTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>{title}</div>
      {sub && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function BarRow({ label, count, total, color }: { label: string; count: number; total: number; color: string }) {
  const p = pct(count, total)
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
        <span style={{ color: '#475569', fontWeight: 500 }}>{label}</span>
        <span style={{ color: '#64748b' }}>{fmt(count)} <span style={{ color: '#94a3b8' }}>({p}%)</span></span>
      </div>
      <div style={{ height: 6, borderRadius: 999, background: '#f1f5f9', overflow: 'hidden' }}>
        <div style={{ height: '100%', borderRadius: 999, background: color, width: `${p}%`, transition: 'width 0.5s ease' }} />
      </div>
    </div>
  )
}

function StatPill({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ flex: 1, minWidth: 120, background: `${color}0d`, border: `1px solid ${color}25`, borderRadius: 10, padding: '12px 16px' }}>
      <div style={{ fontSize: 22, fontWeight: 700, color, lineHeight: 1 }}>{fmt(value)}</div>
      <div style={{ fontSize: 12, color: '#64748b', marginTop: 6, lineHeight: 1.4 }}>{label}</div>
    </div>
  )
}

export default function Reporting() {
  const [report, setReport] = useState<ReportingData | null>(null)
  const [dash, setDash]     = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState('')

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
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load reporting data')
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const phases  = report?.phases   ?? {}
  const runs    = report?.scan_runs ?? []
  const totalPhase = Object.values(phases).reduce((a, b) => a + b, 0) || 1
  const maxSig  = Math.max(...runs.map(r => r.total_signals || 0), 1)

  const co  = report?.company_contact_stats
  const ct  = report?.contact_reach_stats
  const byProduct = report?.companies_by_product ?? []
  const bySrc     = report?.contact_by_source ?? []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      <style>{`@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}`}</style>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>Reporting</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>Live pipeline analytics — updates on every scan or import</p>
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

      {/* Top KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        {[
          { label: 'Total Companies',      value: co?.total            ?? report?.total_companies ?? 0, icon: Building2,    color: '#3b82f6' },
          { label: 'Total Contacts',       value: ct?.total            ?? dash?.contacts_enriched ?? 0, icon: Users,        color: '#6366f1' },
          { label: 'Intent Signals',       value: report?.total_signals ?? 0,                          icon: CheckCircle2, color: '#10b981' },
          { label: 'Scan Runs Completed',  value: runs.filter(r => r.status === 'completed').length,   icon: TrendingUp,   color: '#f59e0b' },
        ].map(k => (
          <div key={k.label} style={card}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
              <div style={{ width: 36, height: 36, borderRadius: 8, background: `${k.color}18`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <k.icon size={16} color={k.color} strokeWidth={1.75} />
              </div>
              <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, fontWeight: 500, background: 'rgba(16,185,129,0.1)', color: '#34d399' }}>live</span>
            </div>
            <div style={{ fontSize: 26, fontWeight: 700, color: '#0f172a', lineHeight: 1 }}>
              {loading ? '—' : fmt(k.value)}
            </div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* ── Companies section ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>

        {/* Companies by target product */}
        <div style={card}>
          <SectionTitle title="Companies by Target Product" sub="All companies in the database" />
          {loading ? <div style={{ color: '#94a3b8', fontSize: 13 }}>Loading...</div>
          : byProduct.length === 0 ? <div style={{ color: '#94a3b8', fontSize: 13 }}>No data yet.</div>
          : (
            <div>
              {byProduct.map((p, i) => (
                <BarRow key={p.product} label={p.product} count={p.count} total={co?.total || 1} color={BAR_COLORS[i % BAR_COLORS.length]} />
              ))}
            </div>
          )}
        </div>

        {/* Companies with / without contacts */}
        <div style={card}>
          <SectionTitle title="Companies — Contact Coverage" sub="How many companies have contacts enriched" />
          {loading ? <div style={{ color: '#94a3b8', fontSize: 13 }}>Loading...</div>
          : !co ? <div style={{ color: '#94a3b8', fontSize: 13 }}>No data yet.</div>
          : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <StatPill label="Total Companies"     value={co.total}            color="#3b82f6" />
                <StatPill label="With Contacts"       value={co.with_contacts}    color="#10b981" />
                <StatPill label="Without Contacts"    value={co.without_contacts} color="#f59e0b" />
              </div>
              <div style={{ marginTop: 4 }}>
                <BarRow label="With contacts"    count={co.with_contacts}    total={co.total} color="#10b981" />
                <BarRow label="Without contacts" count={co.without_contacts} total={co.total} color="#f59e0b" />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Contacts section ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>

        {/* Contact reach breakdown */}
        <div style={card}>
          <SectionTitle title="Contact Reach Breakdown" sub="What contact data we have per person" />
          {loading ? <div style={{ color: '#94a3b8', fontSize: 13 }}>Loading...</div>
          : !ct ? <div style={{ color: '#94a3b8', fontSize: 13 }}>No data yet.</div>
          : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <StatPill label="Valid Emails"        value={ct.valid_emails}      color="#10b981" />
                <StatPill label="Email + LinkedIn"    value={ct.email_and_linkedin} color="#3b82f6" />
                <StatPill label="Email Only"          value={ct.email_only}         color="#6366f1" />
                <StatPill label="LinkedIn Only"       value={ct.linkedin_only}      color="#0ea5e9" />
              </div>
              <div style={{ marginTop: 4 }}>
                <BarRow label="Email + LinkedIn"  count={ct.email_and_linkedin} total={ct.total} color="#3b82f6" />
                <BarRow label="Email only"        count={ct.email_only}         total={ct.total} color="#6366f1" />
                <BarRow label="LinkedIn only"     count={ct.linkedin_only}      total={ct.total} color="#0ea5e9" />
                <BarRow label="No reach info"     count={ct.no_reach}           total={ct.total} color="#94a3b8" />
              </div>
            </div>
          )}
        </div>

        {/* Contacts by source */}
        <div style={card}>
          <SectionTitle title="Contacts by Source" sub="Where each contact was discovered" />
          {loading ? <div style={{ color: '#94a3b8', fontSize: 13 }}>Loading...</div>
          : bySrc.length === 0 ? <div style={{ color: '#94a3b8', fontSize: 13 }}>No data yet.</div>
          : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {bySrc.map((s, i) => (
                <BarRow key={s.label} label={s.label} count={s.count} total={ct?.total || 1} color={BAR_COLORS[i % BAR_COLORS.length]} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Scan run history ── */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>Scan Run History</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 12, color: '#475569' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}><div style={{ width: 8, height: 8, borderRadius: 2, background: '#6366f1' }} /> Signals</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}><div style={{ width: 8, height: 8, borderRadius: 2, background: '#10b981' }} /> Companies</div>
          </div>
        </div>
        {runs.length === 0
          ? <div style={{ height: 160, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: 13 }}>No scan runs yet — run an Oracle Intent scan to see history here.</div>
          : (
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

      {/* ── Bottom: Signal sources + Phase distribution ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div style={card}>
          <SectionTitle title="Top Signal Sources" sub="Where intent signals were scraped from" />
          {(report?.sources ?? []).length === 0
            ? <div style={{ color: '#94a3b8', fontSize: 13 }}>No data yet.</div>
            : (report?.sources ?? []).map((s, i) => (
              <BarRow key={s.label} label={s.label} count={s.count} total={(report?.sources ?? []).reduce((a, b) => a + b.count, 0) || 1} color={BAR_COLORS[i % BAR_COLORS.length]} />
            ))}
        </div>
        <div style={card}>
          <SectionTitle title="Phase Distribution" sub="Companies by Oracle buying phase" />
          {Object.keys(phases).length === 0
            ? <div style={{ color: '#94a3b8', fontSize: 13 }}>No data yet.</div>
            : Object.entries(phases).map(([phase, count], i) => (
              <BarRow key={phase} label={phase.charAt(0).toUpperCase() + phase.slice(1)} count={count} total={totalPhase} color={BAR_COLORS[i % BAR_COLORS.length]} />
            ))}
        </div>
      </div>

      {/* ── Scan run log ── */}
      {runs.length > 0 && (
        <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
          <div style={{ padding: '12px 20px', borderBottom: '1px solid #f1f5f9', fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: '#64748b' }}>SCAN RUN LOG</div>
          {runs.map((run, i) => (
            <div key={run.id} style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '12px 20px', borderBottom: i < runs.length - 1 ? '1px solid #f1f5f9' : 'none', fontSize: 13 }}>
              <span style={{ color: '#94a3b8', minWidth: 32 }}>#{run.id}</span>
              <span style={{ flex: 1, color: '#0f172a' }}>{relativeDate(run.started_at)}</span>
              <span style={{ color: '#64748b', minWidth: 100 }}>{run.total_signals ?? 0} signals</span>
              <span style={{ color: '#64748b', minWidth: 110 }}>{run.total_companies ?? 0} companies</span>
              <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 999,
                background: run.status === 'completed' ? 'rgba(16,185,129,0.12)' : run.status === 'running' ? 'rgba(59,130,246,0.12)' : 'rgba(107,114,128,0.12)',
                color:      run.status === 'completed' ? '#34d399'               : run.status === 'running' ? '#60a5fa'               : '#9ca3af' }}>
                {run.status}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
