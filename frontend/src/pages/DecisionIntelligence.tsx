import { useState, useEffect, useMemo } from 'react'
import { Sparkles, ShieldCheck, Target, Users, Ban, Zap, Check, X,
         TrendingUp, TrendingDown, Mail, ChevronRight, ChevronDown, GitBranch, Loader2,
         AtSign, Link as LinkIcon, ExternalLink, UserCircle2 } from 'lucide-react'
import { toast } from '../components/Toast'

const authH = (): Record<string, string> => ({
  Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
  'Content-Type': 'application/json',
})

const C = {
  pageBg: '#f1f5f9', card: '#ffffff', border: '#e2e8f0', borderStrong: '#cbd5e1',
  primary: '#3b82f6', success: '#10b981', warning: '#f59e0b', danger: '#ef4444',
  violet: '#8b5cf6', text: '#0f172a', textMute: '#64748b', textFaint: '#94a3b8',
}

interface TraceRow { id: string; name: string; fired: boolean; points: number; why?: string; source_url?: string }
interface Prospect {
  name: string; total: number; tier: string; fired: number; of: number
  top_signal: string; trace: TraceRow[]
}
interface Target {
  company: string; domain: string; category_terms: string[]
  target_industries: string[]; personas: string[]; exclude_customers: string[]
}
interface RuleMeta { name: string; weight: number }
interface Contact {
  name: string; title: string; persona?: string
  email?: string | null; linkedin?: string | null; evidence?: string
}
interface DraftEmail {
  to_name: string; to: string; subject: string; body: string; touch: string; send_on?: string
}
interface DIResponse {
  target: Target; prospects: Prospect[]; tier_counts: Record<string, number>
  learned: Record<string, number>; learned_meta: { n_outcomes?: number; baseline_win_rate?: number }
  rule_meta: Record<string, RuleMeta>; outbox_count: number; contact_count: number
  outbox_sample: Array<{ to_name: string; subject: string; company: string; touch: string }>
  contacts_by_company: Record<string, Contact[]>
  emails_by_company: Record<string, DraftEmail[]>
}

const card: React.CSSProperties = {
  background: C.card, border: `1px solid ${C.border}`, borderRadius: 12,
  padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}

function tierStyle(tier: string): { bg: string; color: string; label: string } {
  if (tier.includes('TIER 1')) return { bg: 'rgba(16,185,129,0.12)', color: '#059669', label: 'TIER 1' }
  if (tier.includes('TIER 2')) return { bg: 'rgba(59,130,246,0.12)', color: '#2563eb', label: 'TIER 2' }
  if (tier.includes('TIER 3')) return { bg: 'rgba(245,158,11,0.14)', color: '#b45309', label: 'TIER 3' }
  return { bg: 'rgba(100,116,139,0.12)', color: '#475569', label: 'TIER 4' }
}

function personaLabel(persona?: string): string {
  if (!persona) return ''
  return ({ economic_buyer: 'Economic buyer', technical_buyer: 'Technical buyer',
            compliance_buyer: 'Compliance buyer' } as Record<string, string>)[persona] || persona
}

function Chip({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'neutral' | 'blue' | 'violet' | 'red' }) {
  const map = {
    neutral: { bg: '#f1f5f9', color: C.textMute },
    blue: { bg: 'rgba(59,130,246,0.1)', color: C.primary },
    violet: { bg: 'rgba(139,92,246,0.1)', color: C.violet },
    red: { bg: 'rgba(239,68,68,0.1)', color: C.danger },
  }[tone]
  return (
    <span style={{ background: map.bg, color: map.color, fontSize: 12, fontWeight: 600,
      padding: '3px 10px', borderRadius: 999, display: 'inline-block' }}>{children}</span>
  )
}

/* The hero: a single rule's row in the decision trace */
function TraceLine({ row }: { row: TraceRow }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 12, padding: '12px 14px',
      borderRadius: 10, background: row.fired ? 'rgba(16,185,129,0.05)' : 'transparent',
      borderLeft: `3px solid ${row.fired ? C.success : C.border}`,
      opacity: row.fired ? 1 : 0.6, transition: 'opacity 150ms ease-out',
    }}>
      <div style={{
        width: 22, height: 22, borderRadius: 6, flexShrink: 0, marginTop: 1,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: row.fired ? C.success : '#e2e8f0',
      }}>
        {row.fired ? <Check size={14} color="#fff" strokeWidth={3} />
                   : <X size={13} color={C.textFaint} strokeWidth={3} />}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600, color: row.fired ? C.text : C.textMute }}>
            <span style={{ fontFamily: 'ui-monospace, monospace', color: C.textFaint, marginRight: 8 }}>{row.id}</span>
            {row.name}
          </span>
          <span style={{
            fontFamily: 'ui-monospace, monospace', fontSize: 13, fontWeight: 700, flexShrink: 0,
            color: row.fired ? C.success : C.textFaint,
          }}>{row.fired ? `+${row.points}` : '0'}</span>
        </div>
        {row.fired && row.why && (
          <p style={{ margin: '5px 0 0', fontSize: 12.5, lineHeight: 1.5, color: C.textMute }}>{row.why}</p>
        )}
        {row.fired && row.source_url && (
          <a href={row.source_url} target="_blank" rel="noreferrer" style={{
            display: 'inline-flex', alignItems: 'center', gap: 4, marginTop: 6, fontSize: 11.5,
            color: C.primary, textDecoration: 'none' }}>
            <ExternalLink size={11} /> View source</a>
        )}
      </div>
    </div>
  )
}

function ProspectRow({ p, active, onClick }: { p: Prospect; active: boolean; onClick: () => void }) {
  const t = tierStyle(p.tier)
  return (
    <button onClick={onClick} style={{
      width: '100%', textAlign: 'left', border: 'none', cursor: 'pointer',
      background: active ? 'rgba(59,130,246,0.06)' : 'transparent',
      borderLeft: `3px solid ${active ? C.primary : 'transparent'}`,
      padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12,
      transition: 'background 150ms ease-out',
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: C.text, whiteSpace: 'nowrap',
          overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name.replace(/\s*\(.*\)/, '')}</div>
        <div style={{ fontSize: 11.5, color: C.textFaint, marginTop: 2 }}>
          {p.fired}/{p.of} rules · {p.top_signal || '—'}</div>
      </div>
      <span style={{ background: t.bg, color: t.color, fontSize: 10.5, fontWeight: 700,
        padding: '2px 8px', borderRadius: 6, flexShrink: 0 }}>{t.label}</span>
      <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 15, fontWeight: 700,
        color: C.text, width: 34, textAlign: 'right', flexShrink: 0 }}>{Math.round(p.total)}</span>
      <ChevronRight size={15} color={active ? C.primary : C.textFaint} style={{ flexShrink: 0 }} />
    </button>
  )
}

function ContactCard({ c }: { c: Contact }) {
  return (
    <div style={{ padding: '10px 0', borderBottom: `1px solid ${C.border}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <UserCircle2 size={20} color={C.textFaint} />
        <span style={{ fontSize: 13.5, fontWeight: 600, color: C.text }}>{c.name}</span>
        <span style={{ fontSize: 12.5, color: C.textMute }}>· {c.title}</span>
        {c.persona && <Chip tone="violet">{personaLabel(c.persona)}</Chip>}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, marginTop: 9, paddingLeft: 28 }}>
        {c.email ? (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12,
            color: C.primary, fontFamily: 'ui-monospace, monospace' }}>
            <AtSign size={12} /> {c.email}</span>
        ) : (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: C.textFaint }}>
            <AtSign size={12} /> email not on file</span>
        )}
        {c.linkedin && (
          <a href={`https://${c.linkedin.replace(/^https?:\/\//, '')}`} target="_blank" rel="noreferrer"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12,
              color: C.primary, textDecoration: 'none' }}>
            <LinkIcon size={12} /> LinkedIn</a>
        )}
      </div>
      {c.evidence
        && !c.evidence.startsWith('email pattern-derived')
        && !c.evidence.toLowerCase().startsWith('confirmed email (leadiq')
        && !c.evidence.toLowerCase().startsWith('unverified') && (
        <p style={{ margin: '8px 0 0 28px', fontSize: 11.5, color: C.textFaint, fontStyle: 'italic' }}>
          {c.evidence}</p>
      )}
    </div>
  )
}

function EmailRow({ m }: { m: DraftEmail }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden' }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: '100%', textAlign: 'left', border: 'none', cursor: 'pointer', background: 'transparent',
        padding: '9px 12px', display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <Chip>{m.touch}</Chip>
        <span style={{ fontSize: 13, fontWeight: 600, color: C.text, flexShrink: 0 }}>{m.to_name}</span>
        <span style={{ fontSize: 12.5, color: C.textMute, whiteSpace: 'nowrap', overflow: 'hidden',
          textOverflow: 'ellipsis', flex: 1 }}>{m.subject}</span>
        {m.send_on && <span style={{ fontSize: 11, color: C.textFaint, flexShrink: 0 }}>{m.send_on}</span>}
        {open ? <ChevronDown size={14} color={C.textFaint} /> : <ChevronRight size={14} color={C.textFaint} />}
      </button>
      {open && (
        <div style={{ padding: '4px 14px 14px', borderTop: `1px solid ${C.border}` }}>
          <p style={{ margin: 0, fontSize: 12.5, color: C.textMute }}>To: <span style={{ fontFamily: 'ui-monospace, monospace' }}>{m.to || 'email not on file'}</span></p>
          <p style={{ whiteSpace: 'pre-wrap', margin: '10px 0 0', fontSize: 13, lineHeight: 1.6, color: C.text }}>{m.body}</p>
        </div>
      )}
    </div>
  )
}

export default function DecisionIntelligence() {
  const [data, setData] = useState<DIResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/decision-intelligence', { headers: authH() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d: DIResponse) => {
        setData(d)
        if (d.prospects?.length) setSelected(d.prospects[0].name)
      })
      .catch(e => { setError(e.message); toast('Could not load decision intelligence', 'error') })
      .finally(() => setLoading(false))
  }, [])

  const sel = useMemo(
    () => data?.prospects.find(p => p.name === selected) || null, [data, selected])

  if (loading) return (
    <div style={{ padding: 60, textAlign: 'center', color: C.textMute }}>
      <Loader2 size={26} className="di-spin" style={{ marginBottom: 10 }} />
      <div>Loading decision traces…</div>
      <style>{`@keyframes di-spin{to{transform:rotate(360deg)}}.di-spin{animation:di-spin 1s linear infinite}
        @media (prefers-reduced-motion: reduce){.di-spin{animation:none}}`}</style>
    </div>
  )
  if (error || !data) return <div style={{ padding: 40, color: C.danger }}>Error: {error || 'no data'}</div>

  const { target, prospects, tier_counts, learned, rule_meta, learned_meta, contacts_by_company, emails_by_company } = data
  const learnedIds = Object.keys(learned)
  const selContacts = sel ? (contacts_by_company[sel.name] || []) : []
  const selEmails = sel ? (emails_by_company[sel.name] || []) : []

  return (
    <div style={{ paddingBottom: 40 }}>
      {/* Header */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <Sparkles size={22} color={C.violet} />
          <h1 style={{ fontSize: 24, fontWeight: 700, color: C.text, margin: 0 }}>Decision Intelligence</h1>
        </div>
        <p style={{ color: C.textMute, marginTop: 5, fontSize: 14 }}>
          Every prospect scored by a transparent, auditable rule set — the way {target.company}'s
          own product makes a decision. Rules live as data; weights adapt from outcomes.
        </p>
      </div>

      {/* Auto-derived ICP card */}
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
          <Target size={16} color={C.primary} />
          <span style={{ fontSize: 14, fontWeight: 700, color: C.text }}>
            Target ICP — auto-derived from {target.domain || target.company}</span>
          <span style={{ marginLeft: 'auto', fontSize: 11, color: C.textFaint,
            border: `1px solid ${C.border}`, borderRadius: 6, padding: '2px 8px' }}>DRAFT · evidence-gated</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 18 }}>
          <IcpBlock icon={<Zap size={13} color={C.primary} />} label="Category signals" items={target.category_terms} tone="blue" />
          <IcpBlock icon={<GitBranch size={13} color={C.violet} />} label="Target industries" items={target.target_industries} tone="violet" />
          <IcpBlock icon={<Users size={13} color={C.textMute} />} label="Buyer personas" items={target.personas} tone="neutral" />
          <IcpBlock icon={<Ban size={13} color={C.danger} />} label="Excluded (their customers)" items={target.exclude_customers} tone="red" />
        </div>
      </div>

      {/* Tier summary */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        {['TIER 1', 'TIER 2', 'TIER 3', 'TIER 4'].map(t => {
          const s = tierStyle(t)
          return (
            <div key={t} style={{ ...card, padding: '12px 18px', flex: '1 1 140px', display: 'flex',
              alignItems: 'center', gap: 12 }}>
              <div style={{ width: 8, height: 40, borderRadius: 4, background: s.color, opacity: 0.85 }} />
              <div>
                <div style={{ fontSize: 26, fontWeight: 700, color: C.text, lineHeight: 1 }}>{tier_counts[t] || 0}</div>
                <div style={{ fontSize: 11.5, fontWeight: 600, color: s.color, marginTop: 3 }}>{s.label}</div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Master-detail: prospect list + decision trace */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(300px, 380px) 1fr', gap: 16, alignItems: 'start' }}>
        {/* List */}
        <div style={{ ...card, padding: 0, overflow: 'hidden', maxHeight: 620, display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '14px 16px', borderBottom: `1px solid ${C.border}`,
            fontSize: 13, fontWeight: 700, color: C.text, display: 'flex', justifyContent: 'space-between' }}>
            <span>Scored prospects</span><span style={{ color: C.textFaint, fontWeight: 500 }}>{prospects.length}</span>
          </div>
          <div style={{ overflowY: 'auto' }}>
            {prospects.map(p => (
              <ProspectRow key={p.name} p={p} active={p.name === selected} onClick={() => setSelected(p.name)} />
            ))}
          </div>
        </div>

        {/* Trace inspector + decision-makers + draft outreach */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={card}>
            {sel ? <TraceInspector p={sel} /> : <div style={{ color: C.textMute }}>Select a prospect</div>}
          </div>

          {sel && (
            <div style={card}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <Users size={16} color={C.primary} />
                <span style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Decision-makers</span>
                <span style={{ color: C.textFaint, fontSize: 12 }}>({selContacts.length})</span>
              </div>
              {selContacts.length
                ? selContacts.map((c, i) => <ContactCard key={i} c={c} />)
                : <p style={{ margin: 0, fontSize: 12.5, color: C.textFaint }}>No verified contact yet for this account.</p>}
            </div>
          )}

          {sel && selEmails.length > 0 && (
            <div style={card}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <Mail size={16} color={C.primary} />
                <span style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Draft outreach</span>
                <span style={{ marginLeft: 'auto', fontSize: 11.5, color: C.textFaint }}>nothing sent — human gate</span>
              </div>
              <div style={{ display: 'grid', gap: 8 }}>
                {selEmails.map((m, i) => <EmailRow key={i} m={m} />)}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Closed loop panel */}
      <div style={{ ...card, marginTop: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <ShieldCheck size={16} color={C.success} />
          <span style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Closed loop — weights learned from outcomes</span>
        </div>
        <p style={{ margin: '0 0 14px', fontSize: 12.5, color: C.textMute }}>
          From {learned_meta.n_outcomes ?? '—'} outcomes (baseline win-rate {learned_meta.baseline_win_rate != null
            ? `${Math.round((learned_meta.baseline_win_rate as number) * 100)}%` : '—'}). Rules that fire on
          winners get promoted; the rest decay. The scorer applies these on its next run.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: 10 }}>
          {learnedIds.map(id => {
            const orig = rule_meta[id]?.weight ?? 0
            const lw = learned[id]
            const up = lw > orig, down = lw < orig
            return (
              <div key={id} style={{ border: `1px solid ${C.border}`, borderRadius: 10, padding: '10px 12px',
                display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12, fontWeight: 700,
                  color: C.textMute, width: 26 }}>{id}</span>
                <span style={{ flex: 1, fontSize: 12.5, color: C.text, whiteSpace: 'nowrap',
                  overflow: 'hidden', textOverflow: 'ellipsis' }}>{rule_meta[id]?.name || id}</span>
                <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12.5, color: C.textFaint }}>{orig}</span>
                <span style={{ color: C.textFaint }}>→</span>
                <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 13, fontWeight: 700,
                  color: up ? C.success : down ? C.danger : C.text }}>{lw}</span>
                {up && <TrendingUp size={14} color={C.success} />}
                {down && <TrendingDown size={14} color={C.danger} />}
              </div>
            )
          })}
        </div>
      </div>

      {/* Outbox strip — sample across all accounts */}
      <div style={{ ...card, marginTop: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <Mail size={16} color={C.primary} />
          <span style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Dry-run outbox</span>
          <span style={{ marginLeft: 8 }}><Chip tone="blue">{data.outbox_count} emails staged</Chip></span>
          <span style={{ marginLeft: 8 }}><Chip>{data.contact_count} verified contacts</Chip></span>
          <span style={{ marginLeft: 'auto', fontSize: 11.5, color: C.textFaint }}>nothing sent — human gate</span>
        </div>
        <div style={{ display: 'grid', gap: 8 }}>
          {data.outbox_sample.map((m, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '9px 12px',
              border: `1px solid ${C.border}`, borderRadius: 8 }}>
              <Chip>{m.touch}</Chip>
              <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{m.to_name}</span>
              <span style={{ fontSize: 12.5, color: C.textMute, whiteSpace: 'nowrap', overflow: 'hidden',
                textOverflow: 'ellipsis', flex: 1 }}>{m.subject}</span>
              <span style={{ fontSize: 11.5, color: C.textFaint }}>{m.company.replace(/\s*\(.*\)/, '')}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function IcpBlock({ icon, label, items, tone }: {
  icon: React.ReactNode; label: string; items: string[]; tone: 'blue' | 'violet' | 'neutral' | 'red'
}) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        {icon}<span style={{ fontSize: 11.5, fontWeight: 700, color: C.textMute,
          textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {items.length ? items.map((it, i) => <Chip key={i} tone={tone}>{it}</Chip>)
          : <span style={{ fontSize: 12.5, color: C.textFaint }}>—</span>}
      </div>
    </div>
  )
}

function TraceInspector({ p }: { p: Prospect }) {
  const t = tierStyle(p.tier)
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 14,
        marginBottom: 4 }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: C.text, margin: 0 }}>{p.name.replace(/\s*\(.*\)/, '')}</h2>
          <p style={{ margin: '4px 0 0', fontSize: 12.5, color: C.textMute }}>
            Top signal: <strong style={{ color: C.text }}>{p.top_signal || '—'}</strong></p>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontFamily: 'ui-monospace, monospace', fontSize: 34, fontWeight: 700,
            color: C.text, lineHeight: 1 }}>{Math.round(p.total)}</div>
          <span style={{ background: t.bg, color: t.color, fontSize: 11, fontWeight: 700,
            padding: '3px 10px', borderRadius: 6, display: 'inline-block', marginTop: 6 }}>{t.label} — PRIORITY</span>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '14px 0', fontSize: 12.5,
        color: C.textMute }}>
        <ShieldCheck size={14} color={C.success} />
        Fired {p.fired} of {p.of} rules · fully auditable · editable in glassbox_rules.yaml
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {p.trace.map(row => <TraceLine key={row.id} row={row} />)}
      </div>
    </div>
  )
}
