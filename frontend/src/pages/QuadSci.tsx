import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  Briefcase, ExternalLink, Users, Building2, Radar, ShieldCheck,
  CheckCircle2, Rocket, Crosshair, LayoutGrid, ListChecks, Target, Mail, Layers,
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
interface Touch {
  day: number; channel: string; subject: string; body: string; notes: string
}
interface Hook {
  id: number; company_name: string; contact_name: string; contact_title: string
  subject: string; body: string; angle: string
  personalization_bucket: number | null; personalization_label: string
  touches?: Touch[]
}
interface TraceEntry {
  id: string; condition: string; state: 'fired' | 'not_fired' | 'no_evidence'
  points: number; why?: string; source_url?: string
}
interface Prospect {
  id: number; company_id: number; company_name: string; domain: string
  total_score: number; evaluable_weight: number; tier: string
  trace: TraceEntry[]; scored_at: string
}
interface Contact {
  company_id: number; company_name: string; full_name: string; first_name: string
  last_name: string; title: string; email: string; linkedin_url: string
  source: string; is_target: number
}
interface QuadSciData {
  icp: ICP
  signal_rules: SignalRule[]
  campaign: { id: number | null; name: string; keywords: string[]; exclude_companies: string[]; last_run_at: string | null }
  summary: { total_signals: number; total_companies: number }
  signals: Signal[]
  hooks: Hook[]
  prospects?: Prospect[]
  contacts_by_company?: Record<string, Contact[]>
}

type Tab = 'overview' | 'rules' | 'prospects' | 'signals' | 'contacts' | 'emails' | 'sequences'

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: 'overview',  label: 'Overview',        icon: <LayoutGrid size={14} /> },
  { id: 'rules',     label: 'Signal Rules',    icon: <ListChecks size={14} /> },
  { id: 'prospects', label: 'Scored Prospects', icon: <Target size={14} /> },
  { id: 'signals',   label: 'Live Signals',    icon: <Radar size={14} /> },
  { id: 'contacts',  label: 'Contacts',        icon: <Users size={14} /> },
  { id: 'emails',    label: 'Emails',          icon: <Mail size={14} /> },
  { id: 'sequences', label: 'Sequences',       icon: <Layers size={14} /> },
]

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

const TIER_COLOR = (tier: string) =>
  tier.includes('TIER 1') ? C.success :
  tier.includes('TIER 2') ? C.primary :
  tier.includes('TIER 3') ? C.warning : C.textFaint

const TRACE_STATE: Record<TraceEntry['state'], { icon: string; color: string; label: string }> = {
  fired:       { icon: '●', color: C.success,  label: 'fired' },
  not_fired:   { icon: '○', color: C.textMute,  label: 'not fired' },
  no_evidence: { icon: '–', color: C.textFaint, label: 'no evidence' },
}

function ContactsList({ contacts }: { contacts: Contact[] }) {
  if (!contacts.length) {
    return <div style={{ fontSize: 12, color: C.textFaint, padding: '8px 0' }}>No contacts on file for this company yet.</div>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {contacts.map((c, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', background: '#f8fafc', borderRadius: 8, fontSize: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <span style={{ fontWeight: 600, color: C.text }}>{c.full_name || `${c.first_name} ${c.last_name}`.trim()}</span>
            {!!c.is_target && <span style={{ ...pill(C.success), marginLeft: 6, fontSize: 10 }}>target</span>}
            <div style={{ color: C.textMute, marginTop: 1 }}>{c.title || '—'}</div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
            {c.email && (
              <a href={`mailto:${c.email}`} style={{ color: C.primary, textDecoration: 'none', fontSize: 11.5 }}>{c.email}</a>
            )}
            {c.linkedin_url && (
              <a href={c.linkedin_url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 3, color: C.textFaint, textDecoration: 'none', fontSize: 11 }}>
                <ExternalLink size={9} /> LinkedIn
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function ProspectCard({ p, contacts }: { p: Prospect; contacts: Contact[] }) {
  const [open, setOpen] = useState(false)
  const [showContacts, setShowContacts] = useState(false)
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px' }}>
        <button onClick={() => setOpen(v => !v)} style={{
          flex: 1, minWidth: 0, textAlign: 'left', border: 'none', cursor: 'pointer', background: 'transparent',
          padding: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text, flexShrink: 0 }}>{p.company_name}</span>
          <span style={pill(TIER_COLOR(p.tier))}>{p.tier}</span>
          <span style={{ fontSize: 12, color: C.textMute, flex: 1 }}>
            {p.total_score} / {p.evaluable_weight} pts
          </span>
        </button>
        <button onClick={() => setShowContacts(v => !v)} style={{
          display: 'flex', alignItems: 'center', gap: 5, border: `1px solid ${contacts.length ? C.primary : C.border}`,
          background: showContacts ? (contacts.length ? '#eff6ff' : '#f8fafc') : 'transparent',
          color: contacts.length ? C.primary : C.textFaint, borderRadius: 7, padding: '5px 10px',
          fontSize: 11.5, fontWeight: 600, cursor: 'pointer', flexShrink: 0 }}>
          <Users size={12} /> Contacts {contacts.length > 0 && `(${contacts.length})`}
        </button>
      </div>
      {showContacts && (
        <div style={{ padding: '0 16px 14px' }}>
          <ContactsList contacts={contacts} />
        </div>
      )}
      {open && (
        <div style={{ padding: '0 16px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {p.trace.map(t => {
            const s = TRACE_STATE[t.state]
            return (
              <div key={t.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12 }}>
                <span style={{ color: s.color, flexShrink: 0, opacity: t.state === 'no_evidence' ? 0.5 : 1 }}>{s.icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ fontWeight: 600, color: t.state === 'no_evidence' ? C.textFaint : C.text, textTransform: 'capitalize' }}>
                    {t.condition.replace(/_/g, ' ')}
                  </span>
                  <span style={{ color: C.textFaint, marginLeft: 6 }}>
                    {t.state === 'fired' ? `+${t.points}` : t.state === 'no_evidence' ? '(not evaluated)' : '(checked, absent)'}
                  </span>
                  {t.why && <div style={{ color: C.textMute, marginTop: 2 }}>{t.why}</div>}
                  {t.source_url && (
                    <a href={t.source_url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: C.primary, textDecoration: 'none', marginTop: 2 }}>
                      <ExternalLink size={10} /> Source
                    </a>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function SequenceCard({ h }: { h: Hook }) {
  const [open, setOpen] = useState(false)
  const touches = h.touches || []
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, overflow: 'hidden' }}>
      <button onClick={() => setOpen(v => !v)} style={{
        width: '100%', textAlign: 'left', border: 'none', cursor: 'pointer', background: 'transparent',
        padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text, flexShrink: 0 }}>{h.company_name}</span>
        <span style={{ fontSize: 12, color: C.textMute, flex: 1 }}>{h.contact_name} · {h.contact_title}</span>
        <span style={{ fontSize: 11.5, color: C.textFaint }}>{touches.filter(t => t.day !== 1).length + 1} touches</span>
      </button>
      {open && (
        <div style={{ padding: '0 16px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* Touch 1 is the hook itself, not a row in the touches table */}
          <div style={{ padding: '10px 12px', background: '#f8fafc', borderRadius: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={pill(C.primary)}>Day 1 · Email</span>
            </div>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: C.text, marginBottom: 2 }}>{h.subject}</div>
            <div style={{ fontSize: 12, color: C.textMute, lineHeight: 1.5 }}>{h.body}</div>
          </div>
          {touches.filter(t => t.day !== 1).map((t, i) => {
            const isLinkedIn = t.channel.includes('linkedin')
            return (
            <div key={i} style={{ padding: '10px 12px', background: '#f8fafc', borderRadius: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={pill(isLinkedIn ? C.violet : C.primary)}>
                  Day {t.day} · {isLinkedIn ? 'LinkedIn' : 'Email'}
                </span>
              </div>
              {t.subject && <div style={{ fontSize: 12.5, fontWeight: 600, color: C.text, marginBottom: 2 }}>{t.subject}</div>}
              <div style={{ fontSize: 12, color: C.textMute, lineHeight: 1.5 }}>{t.body}</div>
              {t.notes && <div style={{ fontSize: 11, color: C.textFaint, marginTop: 4, fontStyle: 'italic' }}>{t.notes}</div>}
            </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function QuadSci() {
  const [data, setData]       = useState<QuadSciData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')
  const [tab, setTab]         = useState<Tab>('overview')
  const [hideZero, setHideZero] = useState(true)

  useEffect(() => {
    fetch('/api/decision-intelligence/quadsci', { headers: authH() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setData)
      .catch(e => { setError(e.message); toast.error(e.message) })
      .finally(() => setLoading(false))
  }, [])

  const allProspects = data?.prospects || []
  const zeroCount = useMemo(() => allProspects.filter(p => p.total_score <= 0).length, [allProspects])
  const visibleProspects = useMemo(
    () => (hideZero ? allProspects.filter(p => p.total_score > 0) : allProspects)
      .sort((a, b) => b.total_score - a.total_score),
    [allProspects, hideZero]
  )

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: C.textMute }}>Loading...</div>
  if (error || !data) return <div style={{ padding: 40, color: C.danger }}>Error: {error}</div>

  const icp = data.icp || {}
  const personas = icp.buyer_personas || {}
  const idc = icp.identification_criteria || {}

  const sequencedHooks = data.hooks.filter(h => (h.touches || []).length > 0)
  const contactsByCompany = data.contacts_by_company || {}
  const contactCompanyIds = Object.keys(contactsByCompany)

  const counts: Partial<Record<Tab, number>> = {
    rules: data.signal_rules.length,
    prospects: visibleProspects.length,
    signals: data.signals.length,
    contacts: contactCompanyIds.length,
    emails: data.hooks.length,
    sequences: sequencedHooks.length,
  }

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ marginBottom: 20 }}>
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

      {/* ── Tab bar ── */}
      <div style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${C.border}`, marginBottom: 20, overflowX: 'auto' }}>
        {TABS.map(t => {
          const active = tab === t.id
          const count = counts[t.id]
          return (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px',
              background: 'none', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
              borderBottom: active ? `2px solid ${C.primary}` : '2px solid transparent',
              color: active ? C.primary : C.textMute, fontWeight: active ? 700 : 500, fontSize: 13,
              marginBottom: -1, transition: 'color 150ms ease-out',
            }}>
              {t.icon} {t.label}
              {count !== undefined && (
                <span style={{
                  fontSize: 10.5, fontWeight: 700, padding: '1px 6px', borderRadius: 999,
                  background: active ? `${C.primary}18` : '#f1f5f9', color: active ? C.primary : C.textFaint,
                }}>{count}</span>
              )}
            </button>
          )
        })}
      </div>

      {/* ── Overview tab: ICP + clients + personas ── */}
      {tab === 'overview' && <>
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
      </>}

      {/* ── Signal Rules tab ── */}
      {tab === 'rules' && (
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
      )}

      {/* ── Scored Prospects tab (run_glassbox.py output) ── */}
      {tab === 'prospects' && (
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <SectionTitle>Scored Prospects</SectionTitle>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {zeroCount > 0 && (
              <button onClick={() => setHideZero(v => !v)} style={{
                fontSize: 11.5, fontWeight: 600, color: hideZero ? C.textMute : C.primary,
                background: hideZero ? '#f1f5f9' : `${C.primary}18`, border: 'none', borderRadius: 6,
                padding: '4px 9px', cursor: 'pointer',
              }}>
                {hideZero ? `${zeroCount} zero-score hidden` : `Hide ${zeroCount} zero-score`}
              </button>
            )}
            <span style={{ fontSize: 12, color: C.textMute }}>{visibleProspects.length} shown</span>
          </div>
        </div>
        {!allProspects.length ? (
          <div style={{ textAlign: 'center', padding: '32px 16px' }}>
            <ShieldCheck size={28} color={C.textFaint} style={{ marginBottom: 8 }} />
            <div style={{ fontSize: 13, color: C.textMute }}>
              No companies scored yet — run <code>python run_glassbox.py --campaign-id {data.campaign.id}</code> after a scan has surfaced candidate companies.
            </div>
          </div>
        ) : !visibleProspects.length ? (
          <div style={{ textAlign: 'center', padding: '32px 16px', fontSize: 13, color: C.textMute }}>
            All {zeroCount} scored companies are zero-score — nothing to show with the filter on.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {visibleProspects.map(p => (
              <ProspectCard key={p.id} p={p} contacts={data.contacts_by_company?.[String(p.company_id)] || []} />
            ))}
          </div>
        )}
      </div>
      )}

      {/* ── Live Signals tab ── */}
      {tab === 'signals' && (
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
      )}

      {/* ── Contacts tab ── */}
      {tab === 'contacts' && (
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <SectionTitle>Contacts</SectionTitle>
          <span style={{ fontSize: 12, color: C.textMute }}>
            {contactCompanyIds.length} companies · {Object.values(contactsByCompany).reduce((n, c) => n + c.length, 0)} contacts
          </span>
        </div>
        {contactCompanyIds.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px 16px' }}>
            <Users size={28} color={C.textFaint} style={{ marginBottom: 8 }} />
            <div style={{ fontSize: 13, color: C.textMute }}>
              No contacts on file yet for companies in this campaign — run enrichment
              (Apollo, via <code>run_glassbox.py --enrich-top N</code> or the Companies page) to populate this.
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {contactCompanyIds.map(cid => {
              const contacts = contactsByCompany[cid]
              const companyName = contacts[0]?.company_name || cid
              return (
                <div key={cid} style={{ border: `1px solid ${C.border}`, borderRadius: 10, padding: '12px 16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                    <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text }}>{companyName}</span>
                    <span style={pill(C.primary)}>{contacts.length} contact{contacts.length === 1 ? '' : 's'}</span>
                  </div>
                  <ContactsList contacts={contacts} />
                </div>
              )
            })}
          </div>
        )}
      </div>
      )}

      {/* ── Emails tab ── */}
      {tab === 'emails' && (
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
      )}

      {/* ── Sequences tab ── */}
      {tab === 'sequences' && (
      <div style={card}>
        <SectionTitle>Sequences</SectionTitle>
        {sequencedHooks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px 16px' }}>
            <Layers size={28} color={C.textFaint} style={{ marginBottom: 8 }} />
            <div style={{ fontSize: 13, color: C.textMute, marginBottom: 12 }}>
              No sequences built yet for the generated emails.
            </div>
            <Link to="/campaign-builder" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 600, color: C.primary, textDecoration: 'none' }}>
              <Rocket size={13} /> Build cadences in Campaign Builder
            </Link>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {sequencedHooks.map(h => <SequenceCard key={h.id} h={h} />)}
          </div>
        )}
      </div>
      )}
    </div>
  )
}
