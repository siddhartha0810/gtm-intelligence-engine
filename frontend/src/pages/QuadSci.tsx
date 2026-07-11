import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  Loader2, Briefcase, ExternalLink, Users, Building2, Radar, ShieldCheck,
  CheckCircle2, Rocket, Crosshair,
} from 'lucide-react'
import { toast } from '../components/Toast'

const authH = (): Record<string, string> => ({
  Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
})

const C = {
  card: '#ffffff', border: '#e2e8f0', primary: '#3b82f6', success: '#10b981',
  warning: '#f59e0b', danger: '#ef4444', violet: '#8b5cf6',
  text: '#0f172a', textMute: '#64748b', textFaint: '#94a3b8', pageBg: '#f1f5f9',
}

const card: React.CSSProperties = {
  background: C.card, border: `1px solid ${C.border}`, borderRadius: 12,
  padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}

const pill = (color: string): React.CSSProperties => ({
  display: 'inline-block', padding: '2px 8px', borderRadius: 999,
  fontSize: 11, fontWeight: 600, background: `${color}18`, color,
})

const PHASE_COLORS: Record<string, string> = {
  hiring: '#3b82f6', implementing: '#10b981', evaluating: '#8b5cf6',
  researching: '#f59e0b', budgeting: '#ef4444', supporting: '#64748b',
}

const CONFIDENCE_COLOR = (c: number) => c >= 0.75 ? C.success : c >= 0.6 ? C.warning : C.textMute

interface ICP {
  meta?: { company?: string; domain?: string; status?: string }
  category_terms?: string[]
  target_industries?: string[]
  current_clients?: string[]
  buyer_personas?: { primary?: string[]; secondary?: string[]; internal_ally?: string[] }
  identification_criteria?: { firmographic?: string[]; technographic?: string[] }
  excluded_segments?: string[]
  competitor_products?: string[]
}
interface SignalRule {
  type: string
  description: string
  detect: string[]
  context?: string
  confidence: number
}
interface Signal {
  company_id: number; name: string; domain: string; oracle_product: string
  phase: string; job_title: string; source: string; confidence: number; url: string
  detected_at: string
}
interface Hook {
  id: number; company_name: string; contact_name: string; contact_title: string
  subject: string; body: string; angle: string
  personalization_bucket: number | null; personalization_label: string
}
interface QuadSciData {
  icp: ICP
  signal_rules: SignalRule[]
  campaign: { id: number | null; name: string; keywords: string[]; exclude_companies: string[]; last_run_at: string | null }
  summary: { total_signals: number; total_companies: number }
  signals: Signal[]
  hooks: Hook[]
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 style={{ fontSize: 15, fontWeight: 700, color: C.text, margin: '0 0 12px' }}>{children}</h2>
}

function TagList({ items, color = C.primary }: { items?: string[]; color?: string }) {
  if (!items?.length) return <span style={{ fontSize: 12, color: C.textFaint }}>—</span>
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {items.map(i => <span key={i} style={pill(color)}>{i}</span>)}
    </div>
  )
}

export default function QuadSci() {
  const [data, setData]       = useState<QuadSciData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  useEffect(() => {
    fetch('/api/decision-intelligence/quadsci', { headers: authH() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setData)
      .catch(e => { setError(e.message); toast.error(e.message) })
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: C.textMute }}>Loading...</div>
  if (error || !data) return <div style={{ padding: 40, color: C.danger }}>Error: {error}</div>

  const icp = data.icp || {}
  const personas = icp.buyer_personas || {}
  const idc = icp.identification_criteria || {}

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Radar size={22} color={C.primary} />
          <h1 style={{ fontSize: 24, fontWeight: 700, color: C.text, margin: 0 }}>
            {icp.meta?.company || 'QuadSci'}
          </h1>
        </div>
        <p style={{ color: C.textMute, marginTop: 4 }}>
          {icp.meta?.domain} — target ICP, signal rules, and live pipeline for the QuadSci account
        </p>
      </div>

      {/* ── ICP overview ── */}
      <div style={{ ...card, marginBottom: 16 }}>
        <SectionTitle>ICP Overview</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: C.textMute, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Target Industries / Sectors</div>
            <TagList items={icp.target_industries} color={C.primary} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: C.textMute, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Category</div>
            <TagList items={icp.category_terms} color={C.violet} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: C.textMute, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Firmographic Fit</div>
            <TagList items={idc.firmographic} color={C.success} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: C.textMute, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Technographic Identification</div>
            <TagList items={idc.technographic} color={C.warning} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: C.textMute, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Excluded Segments</div>
            <TagList items={icp.excluded_segments} color={C.danger} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: C.textMute, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Competitors</div>
            <TagList items={icp.competitor_products} color={C.textMute} />
          </div>
        </div>
      </div>

      {/* ── Current clients + personas ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        <div style={card}>
          <SectionTitle>Current Clients (reference)</SectionTitle>
          <p style={{ fontSize: 12, color: C.textFaint, margin: '-6px 0 12px' }}>QuadSci's own logos — proof points for ICP fit, not prospects</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(icp.current_clients || []).map(c => (
              <div key={c} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', border: `1px solid ${C.border}`, borderRadius: 8 }}>
                <Building2 size={14} color={C.textFaint} />
                <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{c}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={card}>
          <SectionTitle>Buyer Personas</SectionTitle>
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: C.textMute, marginBottom: 6 }}>PRIMARY</div>
            <TagList items={personas.primary} color={C.primary} />
          </div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: C.textMute, marginBottom: 6 }}>SECONDARY</div>
            <TagList items={personas.secondary} color={C.violet} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: C.textMute, marginBottom: 6 }}>INTERNAL ALLY</div>
            <TagList items={personas.internal_ally} color={C.success} />
          </div>
        </div>
      </div>

      {/* ── Signal rules & classification ── */}
      <div style={{ ...card, marginBottom: 16 }}>
        <SectionTitle>Signal Rules &amp; Classification</SectionTitle>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {data.signal_rules.map(r => (
            <div key={r.type} style={{ padding: '10px 14px', border: `1px solid ${C.border}`, borderRadius: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: C.text, textTransform: 'capitalize' }}>{r.type.replace(/_/g, ' ')}</span>
                <span style={pill(CONFIDENCE_COLOR(r.confidence))}>confidence {r.confidence.toFixed(2)}</span>
              </div>
              <div style={{ fontSize: 12, color: C.textMute, marginBottom: 6 }}>{r.description}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {r.detect.map(d => <span key={d} style={{ fontSize: 11, padding: '2px 7px', borderRadius: 6, background: '#f1f5f9', color: C.textMute }}>{d}</span>)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Live signals ── */}
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <SectionTitle>Live Signals</SectionTitle>
          <span style={{ fontSize: 12, color: C.textMute }}>
            {data.summary.total_signals} signals · {data.summary.total_companies} companies
          </span>
        </div>
        {data.signals.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px 16px' }}>
            <ShieldCheck size={28} color={C.textFaint} style={{ marginBottom: 8 }} />
            <div style={{ fontSize: 13, color: C.textMute, marginBottom: 12 }}>
              No scan has run yet for the {data.campaign.name} campaign.
            </div>
            <Link to="/campaigns" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 600, color: C.primary, textDecoration: 'none' }}>
              <Crosshair size={13} /> Run a scan on Signal Campaigns
            </Link>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {data.signals.map((s, i) => {
              const color = PHASE_COLORS[s.phase] || C.textMute
              return (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', border: `1px solid ${C.border}`, borderRadius: 8 }}>
                  <Briefcase size={14} color={C.textFaint} style={{ flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text }}>{s.name}</span>
                      {s.phase && <span style={pill(color)}>{s.phase}</span>}
                    </div>
                    <div style={{ fontSize: 12, color: C.textMute, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.job_title}</div>
                  </div>
                  <span style={{ fontSize: 11, color: C.textFaint, flexShrink: 0 }}>conf {s.confidence?.toFixed(2)}</span>
                  {s.url && (
                    <a href={s.url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5, color: C.primary, textDecoration: 'none', flexShrink: 0 }}>
                      <ExternalLink size={11} /> Source
                    </a>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* ── Generated emails ── */}
      <div style={card}>
        <SectionTitle>Generated Emails</SectionTitle>
        {data.hooks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px 16px' }}>
            <Users size={28} color={C.textFaint} style={{ marginBottom: 8 }} />
            <div style={{ fontSize: 13, color: C.textMute, marginBottom: 12 }}>
              No hooks generated yet for companies detected in this campaign.
            </div>
            <Link to="/campaign-builder" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 600, color: C.primary, textDecoration: 'none' }}>
              <Rocket size={13} /> Find contacts &amp; generate hooks in Campaign Builder
            </Link>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {data.hooks.map(h => (
              <div key={h.id} style={{ padding: '12px 16px', border: `1px solid ${C.border}`, borderRadius: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                  <CheckCircle2 size={15} color={C.success} />
                  <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text }}>{h.company_name}</span>
                  <span style={{ fontSize: 12, color: C.textMute }}>{h.contact_name} · {h.contact_title}</span>
                  {h.angle && <span style={pill(C.violet)}>{h.angle}</span>}
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, color: C.text, marginBottom: 2 }}>{h.subject}</div>
                <div style={{ fontSize: 12.5, color: C.textMute, lineHeight: 1.5 }}>{h.body}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
