import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  Briefcase, ExternalLink, Users, Building2, Radar, ShieldCheck,
  CheckCircle2, Rocket, Crosshair, LayoutGrid, ListChecks, Target, Mail, Layers,
  RefreshCw, ArrowDown,
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
  grounded_on?: string; word_count?: number
  touches?: Touch[]
}
interface TraceEvent {
  label: string; url: string; date: string
}
interface TraceEntry {
  id: string; condition: string; state: 'fired' | 'not_fired' | 'no_evidence'
  points: number; why?: string; source_url?: string; events?: TraceEvent[]
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
  email_validation_status?: string; email_source?: string
}
interface CopyVariant {
  id: number; framework: string; subject: string; body: string
  word_count: number; fk_grade: number
  mechanical_score: number; judge_score: number; total_score: number
  gates: Record<string, boolean>
  judge: { specificity?: number; credibility?: number; reply_likelihood?: number; verdict?: string }
  is_winner: boolean; error: string
}
interface VariantGroup {
  company: string; contact: string; title: string; variants: CopyVariant[]
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
  copy_variants?: VariantGroup[]
}

type Tab = 'overview' | 'workflow' | 'rules' | 'prospects' | 'signals' | 'contacts' | 'emails' | 'sequences'

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: 'overview',  label: 'Overview',        icon: <LayoutGrid size={14} /> },
  { id: 'workflow',  label: 'The Loop',        icon: <RefreshCw size={14} /> },
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

function StageBlock({ n, title, deliverables, what, live, details, handoff, isFeedback }: {
  n: number; title: string; deliverables: string[]; what: React.ReactNode; live: React.ReactNode
  details?: React.ReactNode; handoff: React.ReactNode; isFeedback?: boolean
}) {
  const label = (t: string) => (
    <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.08em', color: '#047857', marginBottom: 6 }}>{t}</div>
  )
  return (
    <div>
      <div style={{ border: `1px solid ${C.border}`, borderRadius: 12, overflow: 'hidden', background: C.card }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', background: '#f8fafc', borderBottom: `1px solid ${C.border}`, flexWrap: 'wrap' }}>
          <span style={{ width: 24, height: 24, borderRadius: 999, background: C.primary, color: '#fff', fontSize: 12.5, fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{n}</span>
          <span style={{ fontSize: 14.5, fontWeight: 700, color: C.text }}>{title}</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginLeft: 'auto' }}>
            {deliverables.map(d => (
              <span key={d} style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 10.5, fontWeight: 600, color: '#047857', background: '#ecfdf5', border: '1px solid #a7f3d0', borderRadius: 999, padding: '2px 8px' }}>
                <CheckCircle2 size={10} /> {d}
              </span>
            ))}
          </div>
        </div>
        <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>{label('WHAT HAPPENS HERE')}<div style={{ fontSize: 12.5, color: C.textMute, lineHeight: 1.55 }}>{what}</div></div>
          {details && <div>{label('THE ARTIFACT')}{details}</div>}
          <div>{label('WHAT ACTUALLY HAPPENED — LIVE RUN')}<div style={{ fontSize: 12.5, color: C.text, lineHeight: 1.55 }}>{live}</div></div>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, margin: '10px 0 18px', padding: '10px 14px', background: '#ecfdf5', border: '1px solid #a7f3d0', borderRadius: 10 }}>
        <ArrowDown size={15} color="#047857" style={{ flexShrink: 0, marginTop: 2, transform: isFeedback ? 'rotate(180deg)' : 'none' }} />
        <div style={{ fontSize: 12, color: '#065f46', lineHeight: 1.55 }}>
          <span style={{ fontWeight: 700 }}>{isFeedback ? 'FEEDBACK → ' : 'HANDOFF → '}</span>{handoff}
        </div>
      </div>
    </div>
  )
}

// small building blocks for the on-screen deliverable artifacts
function MiniTable({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div style={{ overflowX: 'auto', border: `1px solid ${C.border}`, borderRadius: 8 }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
        <thead><tr style={{ background: '#f1f5f9' }}>
          {head.map(h => <th key={h} style={{ textAlign: 'left', padding: '7px 10px', fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}` }}>{h}</th>)}
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ borderBottom: i < rows.length - 1 ? `1px solid ${C.border}` : 'none' }}>
              {r.map((c, j) => <td key={j} style={{ padding: '7px 10px', color: j === 0 ? C.text : C.textMute, fontWeight: j === 0 ? 600 : 400 }}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
// The reviewer's unit of work, derived entirely from live payload data:
// the staged hook, its account's scoring trace, and the buyer's email status.
// The route verdict is COMPUTED from the same rules Stage 4 documents, so the
// panel can never drift from the policy table beside it.
function StagedRow({ hook, prospect, contact }: {
  hook: Hook; prospect?: Prospect; contact?: Contact
}) {
  const fired = (prospect?.trace || []).filter(t => t.state === 'fired')
  const cited = fired.filter(t => t.source_url)
  const clusterFired = fired.some(t => t.condition === 'buying_window_timing')
  const tierNum = prospect?.tier?.includes('TIER 1') ? 1
    : prospect?.tier?.includes('TIER 2') ? 2
    : prospect?.tier?.includes('TIER 3') ? 3 : 4
  const patternInferred = (contact?.email_source || '').includes('pattern')
    || (contact?.email_validation_status || '') === 'not_validated'
  const title = (hook.contact_title || '').toLowerCase()
  const isCLevel = /\bc[eforst]o\b|chief |founder|president/.test(title)

  // Same conditions as the auto-send table below this panel
  const holds: string[] = []
  if (tierNum > 2) holds.push('tier below TIER 2')
  if (cited.length < 2) holds.push(`${cited.length} independent citation${cited.length === 1 ? '' : 's'} (needs 2)`)
  if (patternInferred) holds.push('email is pattern-inferred, not validated')
  if (isCLevel) holds.push('C-level recipient — always reviewed')
  if (!clusterFired) holds.push('no live cluster (single signal type)')
  const autoSendEligible = holds.length === 0

  const gate = (ok: boolean, label: string) => (
    <span key={label} style={pill(ok ? C.success : C.warning)}>{label}</span>
  )
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden', marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 11px', background: '#f8fafc', borderBottom: `1px solid ${C.border}`, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: C.text }}>{hook.company_name}</span>
        {prospect && <span style={pill(TIER_COLOR(prospect.tier))}>{prospect.tier}</span>}
        <span style={{ fontSize: 11.5, color: C.textMute }}>{hook.contact_name} · {hook.contact_title}</span>
        <span style={{
          marginLeft: 'auto', fontSize: 11, fontWeight: 700,
          color: autoSendEligible ? '#065f46' : '#92400e',
          background: autoSendEligible ? '#ecfdf5' : '#fef3c7',
          border: `1px solid ${autoSendEligible ? '#a7f3d0' : '#fde68a'}`,
          borderRadius: 999, padding: '2px 9px',
        }}>
          ROUTE: {autoSendEligible ? 'AUTO-SEND ELIGIBLE' : 'HUMAN REVIEW'}
        </span>
      </div>
      <div style={{ padding: '9px 11px', display: 'flex', flexDirection: 'column', gap: 7 }}>
        <div style={{ fontSize: 11.5, color: C.text }}>
          <span style={{ color: C.textFaint }}>copy · </span>
          <strong>{hook.subject}</strong> — &quot;{hook.body}&quot;
          {!!hook.touches?.length && (
            <span style={{ color: C.textFaint }}> + {hook.touches.filter(t => t.day !== 1).length} more touches</span>
          )}
        </div>
        <div style={{ fontSize: 11.5, color: C.textMute }}>
          <span style={{ color: C.textFaint }}>evidence · </span>
          {fired.length === 0 ? <em>no fired rules on file</em> : fired.map((t, i) => (
            <span key={t.id}>
              {i > 0 && ' · '}
              {(t.why || t.condition).replace(/\s+/g, ' ').slice(0, 90)}
              {t.source_url && (
                <> (<a href={t.source_url} target="_blank" rel="noreferrer" style={{ color: C.primary, textDecoration: 'none' }}>source</a>)</>
              )}
            </span>
          ))}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
          {hook.grounded_on ? gate(true, `grounded on "${hook.grounded_on}"`) : gate(false, 'grounding unrecorded')}
          {gate((hook.word_count ?? hook.body.split(' ').length) >= 8, 'length ok')}
          {gate(!patternInferred, patternInferred ? 'email pattern-inferred' : 'email validated')}
          {gate(clusterFired, clusterFired ? 'cluster live' : 'no cluster — 1 signal type')}
          {gate(cited.length >= 2, `${cited.length} cited source${cited.length === 1 ? '' : 's'}`)}
        </div>
        <div style={{ fontSize: 11, color: C.textFaint, fontStyle: 'italic' }}>
          {autoSendEligible
            ? 'All gate conditions met — eligible for auto-send once its signal type graduates (~50 reviewed sends).'
            : `Held: ${holds.join('; ')} — the reviewer sees the reason, not just a verdict.`}
        </div>
      </div>
    </div>
  )
}

// The framework bake-off: one contact's PAS/OIQ/Challenger variants, ranked,
// with the winner expanded and the losers' scores visible. Every gate + judge
// number is live from copy_lab.
const FRAMEWORK_LABEL: Record<string, string> = {
  OIQ: 'Observation→Implication→Question', PAS: 'Problem→Agitate→Solve',
  CHALLENGER: 'Insight-led reframe',
}
const GATE_LABEL: Record<string, string> = {
  length_ok: '≤75 words', reading_level_ok: 'grade ≤6', interest_cta: 'interest-CTA',
  names_evidence: 'names the event', falsifiable: 'falsifiable', no_banned_vocab: 'no filler',
}
function VariantGroupCard({ group }: { group: VariantGroup }) {
  const [open, setOpen] = useState(false)
  const ranked = [...group.variants].sort((a, b) => b.total_score - a.total_score)
  const winner = ranked[0]
  if (!winner) return null
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, overflow: 'hidden' }}>
      <button onClick={() => setOpen(v => !v)} style={{
        width: '100%', textAlign: 'left', border: 'none', cursor: 'pointer', background: '#f8fafc',
        padding: '11px 14px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text }}>{group.company}</span>
        <span style={{ fontSize: 12, color: C.textMute }}>{group.contact} · {group.title}</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={pill(C.success)}>winner: {winner.framework} · {winner.total_score}/100</span>
          <span style={{ fontSize: 11, color: C.textFaint }}>{ranked.length} frameworks tested {open ? '▾' : '▸'}</span>
        </span>
      </button>
      {/* winner always shown */}
      <div style={{ padding: '11px 14px', borderTop: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: C.text }}>{winner.subject}</div>
        <div style={{ fontSize: 12.5, color: C.textMute, lineHeight: 1.55, marginTop: 2 }}>{winner.body}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 8 }}>
          {Object.entries(winner.gates || {}).map(([k, v]) =>
            <span key={k} style={pill(v ? C.success : C.warning)}>{v ? '✓' : '✗'} {GATE_LABEL[k] || k}</span>)}
          <span style={pill(C.violet)}>FK grade {winner.fk_grade}</span>
          <span style={pill(C.textMute)}>{winner.word_count}w</span>
        </div>
      </div>
      {/* the losers — the auditable part */}
      {open && (
        <div style={{ padding: '4px 14px 12px', borderTop: `1px solid ${C.border}`, background: '#fcfcfd' }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em', color: C.textFaint, margin: '10px 0 8px' }}>
            THE VARIANTS IT BEAT (same evidence, different framework)
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {ranked.map((v, i) => (
              <div key={v.id} style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: '9px 11px', background: v.is_winner ? '#f0fdf4' : C.card }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: C.text }}>#{i + 1} · {v.framework}</span>
                  <span style={{ fontSize: 11, color: C.textFaint }}>{FRAMEWORK_LABEL[v.framework] || ''}</span>
                  <span style={{ marginLeft: 'auto', fontSize: 11.5, fontWeight: 700, color: v.is_winner ? C.success : C.textMute }}>
                    {v.total_score}/100 <span style={{ fontWeight: 400, color: C.textFaint }}>(gates {v.mechanical_score}/60 · judge {v.judge_score}/40)</span>
                  </span>
                </div>
                {v.body
                  ? <div style={{ fontSize: 12, color: C.textMute, lineHeight: 1.5 }}>&quot;{v.body}&quot;</div>
                  : <div style={{ fontSize: 12, color: C.danger, fontStyle: 'italic' }}>generation failed: {v.error}</div>}
                {v.judge?.verdict && (
                  <div style={{ fontSize: 11, color: C.textFaint, marginTop: 4, fontStyle: 'italic' }}>
                    judge: &quot;{v.judge.verdict}&quot; — specificity {v.judge.specificity}/10 · credibility {v.judge.credibility}/10 · would-reply {v.judge.reply_likelihood}/10
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const codeBox: React.CSSProperties = {
  background: '#0f172a', color: '#e2e8f0', fontFamily: 'ui-monospace, Menlo, monospace',
  fontSize: 11, lineHeight: 1.5, padding: '12px 14px', borderRadius: 8, whiteSpace: 'pre-wrap',
  overflowX: 'auto', maxHeight: 320, overflowY: 'auto',
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
                  {!!t.events?.length && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 4, paddingLeft: 10, borderLeft: `2px solid ${C.border}` }}>
                      {t.events.map((e, i) => (
                        <div key={i} style={{ fontSize: 11, color: C.textMute }}>
                          {e.date && <span style={{ color: C.textFaint }}>{e.date.slice(0, 10)} — </span>}
                          {e.url ? (
                            <a href={e.url} target="_blank" rel="noreferrer" style={{ color: C.primary, textDecoration: 'none' }}>
                              {e.label}
                            </a>
                          ) : (
                            <span>{e.label}</span>
                          )}
                        </div>
                      ))}
                    </div>
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
  const disqualified = useMemo(
    () => allProspects.filter(p => (p.tier || '').includes('DISQUALIFIED'))
      .sort((a, b) => a.company_name.localeCompare(b.company_name)),
    [allProspects]
  )
  const scorable = useMemo(() => allProspects.filter(p => !(p.tier || '').includes('DISQUALIFIED')), [allProspects])
  const zeroCount = useMemo(() => scorable.filter(p => p.total_score <= 0).length, [scorable])
  const visibleProspects = useMemo(
    () => (hideZero ? scorable.filter(p => p.total_score > 0) : scorable)
      .sort((a, b) => b.total_score - a.total_score),
    [scorable, hideZero]
  )

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: C.textMute }}>Loading...</div>
  if (error || !data) return <div style={{ padding: 40, color: C.danger }}>Error: {error}</div>

  const icp = data.icp || {}
  const personas = icp.buyer_personas || {}
  const idc = icp.identification_criteria || {}

  const sequencedHooks = data.hooks.filter(h => (h.touches || []).length > 0)
  const contactsByCompany = data.contacts_by_company || {}
  const contactCompanyIds = Object.keys(contactsByCompany)

  // Live staged rows for the Stage-4 review-queue panel: the highest-scoring
  // sequenced hooks, joined to their account's scoring trace and the buyer's
  // real email status. Nothing here is hardcoded — if the board rescores, the
  // route verdicts change with it.
  // NB: plain computation, not useMemo — this runs after the loading/error
  // early-returns above, so a hook here would break React's rules-of-hooks
  // (conditional hook call → "rendered more hooks than previous render").
  const stagedRows = (() => {
    const byCompany = new Map(allProspects.map(p => [p.company_name, p]))
    return sequencedHooks
      .map(hook => {
        const prospect = byCompany.get(hook.company_name)
        const contacts = prospect ? (contactsByCompany[String(prospect.company_id)] || []) : []
        const contact = contacts.find(c =>
          (c.full_name || `${c.first_name} ${c.last_name}`).trim().toLowerCase()
            === (hook.contact_name || '').trim().toLowerCase()) || contacts[0]
        return { hook, prospect, contact }
      })
      .sort((a, b) => (b.prospect?.total_score || 0) - (a.prospect?.total_score || 0))
      .slice(0, 2)
  })()

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

      {/* ── The Loop tab: 4 stages + data flow ── */}
      {tab === 'workflow' && (
      <div style={{ ...card, marginBottom: 16 }}>
        <SectionTitle>The Loop — signal to campaign, one connected system</SectionTitle>
        <p style={{ fontSize: 12.5, color: C.textMute, margin: '-6px 0 18px', lineHeight: 1.55 }}>
          Each stage consumes exactly what the previous stage produced. The evidence is never summarized
          away — the same dated, cited signal records that score an account also write its email and sit
          next to it in the review queue.
        </p>

        <StageBlock n={1} title="Detect Signal Cluster"
          deliverables={['5 signals + sources', 'cluster definition', 'USP-tied signal']}
          what={<>Five free sources are monitored continuously — ATS job boards (keyless JSON), SEC 8-K
            Item 5.02 filings, the layoffs tracker, date-gated G2/Reddit pain language, and the Wayback
            churn watch on competitor customer walls. Every detection becomes a dated, cited signal
            record. One signal parks an account in monitor; two independent signal types inside 90 days
            declare intent. (Full 5-signal table with CRO-language meaning + free source per signal is on
            the <strong>Signal Rules</strong> tab.)</>}
          details={<>
            <div style={{ fontSize: 12, color: C.textMute, marginBottom: 8, lineHeight: 1.55 }}>
              <strong style={{ color: C.text }}>Cluster definition</strong> — a single signal is noise; a
              cluster is intent:
            </div>
            <MiniTable head={['Condition', 'Rule']} rows={[
              ['Per-account trigger', '≥2 signals of DIFFERENT types within 90 days of each other'],
              ['At least one', 'a pain or displacement signal (2 job posts = 1 event, not a cluster)'],
              ['1 signal only', '→ account parks in MONITOR, nothing sent'],
              ['Batch trigger', '5+ clustered accounts in a week → a campaign run'],
              ['USP-tied signal', 'renewal-window entry: went live 9–18 mo ago = inside QuadSci’s prediction window'],
            ]} />
          </>}
          live={<>~11,000 raw signals this scan → 681 classified. Real catches: Chatwork removed from
            Pendo&apos;s customer wall (it grew 118→127, so a specific takedown); Qualys, Trimble,
            Cloudflare and AppFolio 8-K officer changes; Cloudflare&apos;s May 2026 workforce reduction;
            live RevOps hires — Demandbase (VP RevOps), Postman (Director CS-Ops), Vanta, Abnormal.
            Qualys&apos;s hiring post + 8-K, 30 days apart, is a real cluster.</>}
          handoff={<>Candidate accounts, each carrying its full signal records
            — type, evidence text, source URL, date, confidence — flow to scoring. Nothing is summarized away.</>} />

        <StageBlock n={2} title="Score & Filter Accounts"
          deliverables={['scoring rubric', 'hard filters', 'buyer ID', 'Stage-3 threshold']}
          what={<>Hard ICP filters run first and disqualify regardless of signals. Survivors are scored
            by the weighted rubric with time decay; tier = points as a share of evaluable weight. Buyers
            found free: team pages, LinkedIn, Apollo free tier, email-pattern inference (CRO org primary:
            CRO / SVP-VP Sales / VP-Head-Director RevOps; CS secondary).</>}
          details={<>
            <div style={{ fontSize: 12, fontWeight: 700, color: C.text, margin: '0 0 6px' }}>Hard filters — disqualify before scoring (firm size · funding stage · GTM structure · tech stack)</div>
            <MiniTable head={['Dimension', 'Disqualifier']} rows={[
              ['Firm size', 'under 200 employees'],
              ['Funding stage', 'pre-Series B'],
              ['GTM structure', 'no CS function (no renewal motion = no buyer)'],
              ['Business type', 'not B2B SaaS; agencies / partners / existing customers'],
              ['Tech stack', 'no product-telemetry layer — nothing for Growth AI to read'],
            ]} />
            <div style={{ fontSize: 12, fontWeight: 700, color: C.text, margin: '12px 0 6px' }}>Scoring rubric (point system)</div>
            <MiniTable head={['Signal / factor', 'Points']} rows={[
              ['Legacy CS-platform friction / displacement', '+12'],
              ['Public NRR / forecast pain, new CRO-CCO (8-K)', '+10'],
              ['Director+ RevOps / CS-Ops hire', '+8'],
              ['Renewal-window entry (USP-tied)', '+8'],
              ['Cluster bonus (2+ types in 90d)', '+8'],
              ['Firmographic fit (200–500 sweet spot; >2k → −2)', '+6'],
              ['Named buyer on file', '+4'],
              ['Decay: every dated trigger fades linearly over 365 days', ''],
            ]} />
            <div style={{ fontSize: 12, fontWeight: 700, color: C.text, margin: '12px 0 6px' }}>Tiers &amp; the Stage-3 spend threshold</div>
            <MiniTable head={['Tier', 'Threshold', 'Action']} rows={[
              ['TIER 1 — PRIORITY', '≥60%', 'Outreach this week'],
              ['TIER 2 — QUALIFIED', '≥40%', 'Outreach this cycle → eligible for copy'],
              ['TIER 3 — MONITOR', '≥20%', 'Watch for the cluster to complete'],
              ['TIER 4', '<20%', 'Ignore'],
            ]} />
            <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 8, lineHeight: 1.5 }}>
              <strong>Spend AI credits only when:</strong> hard filters passed AND tier ≥ TIER 2 AND ≥2
              independent citations AND a named CRO-org buyer. Copy costs pennies — the real cost of a bad
              send is domain reputation, so the gate is evidence quality, not tokens.
            </div>
          </>}
          live={<>{scorable.filter(p => p.total_score > 0).length} scorable accounts,{' '}
            {allProspects.filter(p => p.tier.includes('TIER 2')).length} TIER 2 qualified
            (Cloudflare, Qualys, Trimble). Hard filters visibly disqualified {disqualified.length}{' '}
            accounts <em>before</em> scoring — Rivian (layoff fired, but an EV maker), Interface (rode a
            mis-attributed funding article to #1 before the guard caught it — it&apos;s a carpet
            manufacturer), Patreon and Whatnot (B2C), Skydio (drone hardware). Shown with reasons, not
            deleted. {Object.keys(contactsByCompany).length} companies carry named contacts; ~90 emails
            filled at $0 via pattern inference.</>}
          handoff={<>For every account clearing the gate (tier ≥ 2, ≥2 citations, named buyer): the full
            scoring trace — fired rules, why-text, citations, dates — plus the buyer. That trace IS the
            payload the copy prompt receives.</>} />

        <StageBlock n={3} title="Generate Personalized Copy"
          deliverables={['worked email', 'the full prompt', 'personalize-at-scale']}
          what={<>The Stage-2 trace is injected verbatim into the prompt, alongside product context in
            quadsci.ai&apos;s own words (Growth AI / Cohorts AI, 90%+ accuracy 9–18 months ahead,
            telemetry vs CRM-derived guesswork). Three mechanical gates before any human sees it:
            grounding (copy must quote real evidence), minimum length, banned vocabulary. Failures are
            held back — visibly. (The worked email + 5-touch sequence render on the <strong>Emails</strong>
            and <strong>Sequences</strong> tabs.)</>}
          details={<>
            <div style={{ fontSize: 12, fontWeight: 700, color: C.text, margin: '0 0 6px' }}>The production system prompt (verbatim)</div>
            <div style={codeBox}>{`You are a senior GTM engineer writing hyper-personalised cold email HOOKS.
A hook is the opening 1-2 sentences only — not a full email.

ICP RESEARCH (ground your angles in this): {icp_research}

HOOK RULES (non-negotiable):
- EXACTLY ONE SENTENCE. The hook NAMES THE PROBLEM only — never the product.
- Start with their first name. Max 20 words after the name. Plain vocabulary.
- Pick ONE angle: Risk / Effort / Time / Cost / Identity / TwoTimelines
- PHRASING: blame a shared enemy ("the spreadsheet"), never "you".
  BUT/THEREFORE structure, not a flat list of facts.
- GROUNDING: never invent a detail (report name, $ figure, deadline) not in
  the evidence. A generic-but-true line beats a specific-but-invented one.
- SPECIFICITY: if the evidence has a $ figure / investor / proper noun for THIS
  company, anchor on it — the hook should make it obvious which company it is.
- NEVER use: "leverage", "synergy", "quick question", "I wanted to reach out",
  "hope this finds you", "just checking in"
- Subject: under 8 words, no "?" or "!".`}</div>
            <div style={{ fontSize: 12, fontWeight: 700, color: C.text, margin: '12px 0 6px' }}>
              The user prompt — the Stage-2 trace, injected verbatim (real Chatwork payload)
            </div>
            <div style={codeBox}>{`Contact: Yasuyuki Iwata, Head of Sales & Customer Success at Chatwork

EVIDENCE (fired rules from scoring — quote from this, invent nothing):
- Names a competitor product/behavior ("removed from Pendo").
  src: web.archive.org/.../pendo.io/customers/  date: 2025-03-16
- Technographic fit — already uses/hires for "Pendo".
- Decision-maker on file: Yasuyuki Iwata (Head of Sales & Customer Success).

PRODUCT (use this language, it is the client's own):
QuadSci — Customer Intelligence AI for GTM teams. Growth AI predicts
customer growth, contraction and churn 9-18 months ahead of renewal at
90%+ accuracy, grounded in real user behavior (raw product telemetry),
not CRM-derived guesswork. Gainsight/Clari/Pendo are INTEGRATION
partners — say "make your stack predictive", never "rip it out".`}</div>
            <div style={{ fontSize: 11.5, color: C.textMute, margin: '8px 0 0', lineHeight: 1.5 }}>
              <strong style={{ color: C.text }}>Personalize at scale.</strong> Per-account variables: name ·
              company · verbatim signal evidence + dates · angle (by evidence type) · buyer-org framing
              (CRO → Growth AI language; CPO/CMO → Cohorts AI). Templated: structure, gates, banned
              vocabulary, cadence. The Stage-2 scoring trace (JSON of fired rules + citations) is fed
              straight into the prompt — the same evidence that scored the account writes its email.
            </div>

            <div style={{ fontSize: 12, fontWeight: 700, color: C.text, margin: '14px 0 6px' }}>
              Prompt iteration — what broke, what I changed (all real, all in git)
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              {[
                { broke: 'Hooks read plausibly but quoted nothing real — fluent, invented specifics.',
                  fixed: 'Added a grounding gate: copy must contain a distinctive term from the evidence actually held, or it is held back unsent.' },
                { broke: 'The gate cheated — a hook passed by matching the contact’s own first name ("casey").',
                  fixed: 'Name tokens are stripped before the check; generic GTM vocabulary ("your recent funding round") blocklisted from counting as grounding.' },
                { broke: '"Casey, your $3." shipped as a complete email body.',
                  fixed: 'The one-sentence enforcer was cutting at the first period — including the decimal in "$3.7M". Fixed the sentence-boundary regex; added a minimum-length gate. Regenerated in full.' },
                { broke: 'Truthful copy got held — a Cloudflare hook wrote "the layoffs" where evidence said "laid off 1,100 employees".',
                  fixed: 'Kept the hold. False-positive holds are the acceptable failure direction; semantic (embedding) grounding is the real fix, on the more-budget list.' },
                { broke: '"Interface" rode a misattributed article ("Aina Raises $5.5M" merely contained the word) to #1 on the board.',
                  fixed: 'The account name must now appear in the article title before a signal is credited — the same guard the G2/Reddit passes already used.' },
              ].map((it, i) => (
                <div key={i} style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: '8px 11px' }}>
                  <div style={{ fontSize: 11.5, color: '#7f1d1d', lineHeight: 1.5 }}>
                    <strong>✗ broke:</strong> {it.broke}
                  </div>
                  <div style={{ fontSize: 11.5, color: '#065f46', lineHeight: 1.5, marginTop: 3 }}>
                    <strong>✓ changed:</strong> {it.fixed}
                  </div>
                </div>
              ))}
            </div>
          </>}
          live={<>{data.hooks.length} grounded emails on this board. Flagship: &quot;Yasuyuki, Pendo
            records what happened but can&apos;t predict what&apos;s coming with your customers.&quot; —
            the churn-watch evidence as the first line. The audit of ~100 hooks regenerated 1 truncated
            body and held 10 as ungrounded template copy.</>}
          handoff={<>One staged row per approved contact: hook + 5-touch sequence + every gate result +
            the inherited evidence trace. Copy never travels without the evidence that justified it.</>} />

        <StageBlock n={4} title="Stage the Campaign" isFeedback
          deliverables={['staging mechanism', 'auto-send logic', 'feedback loop', 'biggest risk']}
          what={<>A review queue where each row shows the copy AND the evidence that produced it — the
            reviewer judges the claim, not the prose. It&apos;s a working web page here; the design ports
            to a Google Sheet review queue in an afternoon. Approve → the 5-touch sequence exports to a
            free-tier sender or Apollo sequence.</>}
          details={<>
            <div style={{ fontSize: 12, fontWeight: 700, color: C.text, margin: '0 0 6px' }}>
              What one staged row actually looks like (the reviewer&apos;s unit of work)
            </div>
            {stagedRows.length === 0
              ? <div style={{ fontSize: 12, color: C.textFaint, marginBottom: 12 }}>No staged rows yet — approve a sequence to populate the queue.</div>
              : stagedRows.map(r => (
                  <StagedRow key={r.hook.id} hook={r.hook} prospect={r.prospect} contact={r.contact} />
                ))}
            <div style={{ fontSize: 12, fontWeight: 700, color: C.text, margin: '0 0 6px' }}>Auto-send vs. human review (nothing auto-sends at cold start)</div>
            <MiniTable head={['Condition', 'Route']} rows={[
              ['All gates + tier ≥2 + ≥2 citations + validated email + below C-level', 'Auto-send eligible'],
              ['C-level recipient', 'Human review, always'],
              ['Copy derived from pain-language evidence', 'Human review, always'],
              ['Pattern-inferred (unvalidated) email', 'Human review'],
              ['Graduation', 'a signal type earns auto-send only after ~50 reviewed sends beat baseline'],
            ]} />
            <div style={{ fontSize: 11.5, color: C.textMute, margin: '10px 0 0', lineHeight: 1.5 }}>
              <strong style={{ color: C.text }}>Feedback loop.</strong> Every send logs reply / meeting /
              bounce, tagged by the signal type that sourced the account. Monthly, reply-rate by signal
              type reweights the Stage-2 rubric and reprioritizes Stage-1 sources — bounces trigger
              email-pattern re-learning; &quot;not relevant&quot; replies extend the hard-filter list.
            </div>
            <div style={{ fontSize: 11.5, color: '#7f1d1d', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '9px 12px', margin: '10px 0 0', lineHeight: 1.5 }}>
              <strong>Biggest risk — and it already happened.</strong> My top account (Skydio, 28 pts) owed
              10 points to a customer complaint posted in <strong>2020</strong> — undated evidence was
              bypassing decay and scoring like it was fresh. I shipped a date gate the same day (third-party
              pain evidence must carry a machine-readable publish date, &lt;18 months); my #1 dropped two
              tiers and the fix shipped anyway. Mitigations: human review on all pain-derived copy,
              citations on every point, decay on every trigger.
            </div>
          </>}
          live={<>{sequencedHooks.length} five-touch sequences staged (email → LinkedIn → email naming
            Growth AI → LinkedIn → breakup). Held-back copy sits visibly alongside — including a
            truthful-but-lexically-ungrounded Cloudflare hook: the gate working as designed. Nothing has
            auto-sent, by policy.</>}
          handoff={<>Every send logs reply / meeting / bounce, tagged by the signal type that sourced the
            account. Monthly, reply rate by signal type reweights the Stage-2 rubric and reprioritizes
            Stage-1 sources. Detection → scoring → copy → outcome → detection. The loop is closed.</>} />
      </div>
      )}

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

        {/* Hard-filtered accounts — shown, not deleted (Stage 2 requirement) */}
        {disqualified.length > 0 && (
          <div style={{ marginTop: 22, paddingTop: 16, borderTop: `1px dashed ${C.border}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <ShieldCheck size={15} color={C.danger} />
              <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text }}>Hard-filtered — disqualified before scoring</span>
              <span style={pill(C.danger)}>{disqualified.length}</span>
            </div>
            <p style={{ fontSize: 12, color: C.textFaint, margin: '0 0 12px' }}>
              These tripped a signal but fail the ICP hard filter (not B2B SaaS, below the size/stage floor,
              or a data artifact). Shown with the reason rather than silently dropped — a filter you can&apos;t
              audit is a filter you can&apos;t trust.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {disqualified.map(p => {
                const reason = (p.trace?.find(t => t.condition === 'hard_filter')?.why || '')
                  .replace('Hard-filtered before scoring: ', '')
                return (
                  <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', border: `1px solid ${C.border}`, borderRadius: 8, background: '#fef2f2' }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: C.text, minWidth: 130 }}>{p.company_name}</span>
                    <span style={{ fontSize: 12, color: C.textMute }}>{reason}</span>
                  </div>
                )
              })}
            </div>
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
      {tab === 'emails' && (<>
      {(data.copy_variants?.length ?? 0) > 0 && (
      <div style={{ ...card, marginBottom: 16 }}>
        <SectionTitle>Framework bake-off — the copy is chosen, not guessed</SectionTitle>
        <p style={{ fontSize: 12.5, color: C.textMute, margin: '-6px 0 12px', lineHeight: 1.55 }}>
          For each buyer, the same evidence is written three ways — <strong>PAS</strong>,
          <strong> OIQ</strong>, and an <strong>insight-led</strong> reframe — then every variant is
          scored: 60 points of deterministic gates (≤75 words, reading grade ≤6 by Flesch-Kincaid,
          an <em>interest</em>-CTA not a time-ask, names the dated event, falsifiable) plus a 40-point
          LLM judge role-played as a busy CRO. The winner ships; the losers stay on the record.
          The gates come from published data — Gong (304K emails: interest-CTA &gt; time-ask; &lt;100
          words), Lavender (231K: grade 3–5 reading level lifts replies ~67%).
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {data.copy_variants!.map(g => <VariantGroupCard key={g.company + g.contact} group={g} />)}
        </div>
      </div>
      )}
      <div style={card}>
        <SectionTitle>Generated Emails (single-shot baseline)</SectionTitle>
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
      </>)}

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
