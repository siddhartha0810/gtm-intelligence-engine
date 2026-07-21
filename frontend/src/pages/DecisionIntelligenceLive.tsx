import { useState, useEffect } from 'react'
import { Radio, Briefcase, ExternalLink, Loader2, Mail, ShieldCheck, ChevronDown, ChevronRight,
         CheckCircle2, Info, MessageCircle } from 'lucide-react'
import { toast } from '../components/Toast'

const authH = (): Record<string, string> => ({
  Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
})

const C = {
  card: '#ffffff', border: '#e2e8f0', primary: '#3b82f6', success: '#10b981',
  warning: '#f59e0b', violet: '#8b5cf6', text: '#0f172a', textMute: '#64748b', textFaint: '#94a3b8',
}

const card: React.CSSProperties = {
  background: C.card, border: `1px solid ${C.border}`, borderRadius: 12,
  padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}

const ANGLE_COLORS: Record<string, string> = {
  Risk: '#ef4444', Effort: '#f59e0b', Time: '#8b5cf6', Cost: '#10b981', Identity: '#3b82f6',
  TwoTimelines: '#14b8a6',
}

const PHASE_COLORS: Record<string, string> = {
  hiring: '#3b82f6', implementing: '#10b981', evaluating: '#8b5cf6',
  researching: '#f59e0b', budgeting: '#ef4444', supporting: '#64748b',
}

interface Signal {
  company_id: number; name: string; domain: string; detected_product: string
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
  grounded: boolean | null; grounded_on: string; created_at: string
  touches: Touch[]
}
interface LiveData {
  campaign: { name: string; keywords: string[]; exclude_companies: string[]; last_run_at: string | null }
  summary: { total_signals: number; total_companies: number; by_source: Record<string, number>; by_phase: Record<string, number> }
  signals: Signal[]
  hooks: Hook[]
}

function SignalRow({ s }: { s: Signal }) {
  const color = PHASE_COLORS[s.phase] || C.textMute
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px',
      border: `1px solid ${C.border}`, borderRadius: 8 }}>
      <Briefcase size={14} color={C.textFaint} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text }}>{s.name}</span>
          <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 999,
            background: `${color}18`, color }}>{s.phase}</span>
        </div>
        <div style={{ fontSize: 12, color: C.textMute, marginTop: 2, overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.job_title}</div>
      </div>
      <span style={{ fontSize: 11, color: C.textFaint, flexShrink: 0 }}>conf {s.confidence.toFixed(2)}</span>
      {s.url && (
        <a href={s.url} target="_blank" rel="noreferrer" style={{
          display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5,
          color: C.primary, textDecoration: 'none', flexShrink: 0 }}>
          <ExternalLink size={11} /> Source
        </a>
      )}
    </div>
  )
}

function HookCard({ h, open, onToggle }: { h: Hook; open: boolean; onToggle: () => void }) {
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, overflow: 'hidden' }}>
      <button onClick={onToggle} style={{
        width: '100%', textAlign: 'left', border: 'none', cursor: 'pointer', background: 'transparent',
        padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <CheckCircle2 size={15} color={C.success} style={{ flexShrink: 0 }} />
        <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text, flexShrink: 0 }}>{h.company_name}</span>
        <span style={{ fontSize: 12.5, color: C.textMute, flex: 1, minWidth: 0, overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.subject}</span>
        {h.angle && (
          <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 999, flexShrink: 0,
            background: `${ANGLE_COLORS[h.angle] || C.textMute}18`, color: ANGLE_COLORS[h.angle] || C.textMute }}>
            {h.angle}
          </span>
        )}
        {open ? <ChevronDown size={14} color={C.textFaint} /> : <ChevronRight size={14} color={C.textFaint} />}
      </button>
      {open && (
        <div style={{ padding: '0 16px 14px', borderTop: `1px solid ${C.border}` }}>
          <div style={{ marginTop: 10, padding: '10px 12px', borderRadius: 8, background: '#f8fafc' }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: C.textFaint, textTransform: 'uppercase',
              letterSpacing: '0.04em', marginBottom: 4 }}>Day 1 — Email</div>
            <p style={{ margin: 0, fontSize: 13, color: C.text, lineHeight: 1.6 }}>{h.body}</p>
            <p style={{ margin: '8px 0 0', fontSize: 11, color: C.textFaint, fontStyle: 'italic' }}>
              Deliberately no pitch — the opener's only job is a true, specific pain point. The
              product gets named in Day 5, once there's a reply-worthy reason to open the next one.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 14, margin: '10px 0', fontSize: 11.5, color: C.textFaint, flexWrap: 'wrap' }}>
            {h.personalization_label && <span>bucket {h.personalization_bucket}: {h.personalization_label}</span>}
            {h.grounded != null && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <ShieldCheck size={12} color={h.grounded ? C.success : C.warning} />
                {h.grounded ? `grounded on "${h.grounded_on}"` : 'ungrounded'}
              </span>
            )}
          </div>

          {h.touches.filter(t => t.day !== 1).length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {h.touches.filter(t => t.day !== 1).map((t, i) => {
                const isLinkedin = t.channel.includes('linkedin')
                return (
                  <div key={i} style={{ padding: '10px 12px', borderRadius: 8, background: '#f8fafc' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                      {isLinkedin
                        ? <MessageCircle size={11} color={C.primary} />
                        : <Mail size={11} color={C.textFaint} />}
                      <span style={{ fontSize: 10.5, fontWeight: 700, color: C.textFaint, textTransform: 'uppercase',
                        letterSpacing: '0.04em' }}>
                        Day {t.day} — {isLinkedin ? 'LinkedIn' : 'Email'}
                      </span>
                    </div>
                    {t.subject && (
                      <div style={{ fontSize: 12.5, fontWeight: 600, color: C.text, marginBottom: 3 }}>{t.subject}</div>
                    )}
                    <p style={{ margin: 0, fontSize: 12.5, color: C.text, lineHeight: 1.55 }}>{t.body}</p>
                  </div>
                )
              })}
            </div>
          )}

          <div style={{ marginTop: 10, padding: '8px 10px', borderRadius: 6, background: '#f8fafc',
            fontSize: 11, color: C.textFaint, display: 'flex', alignItems: 'flex-start', gap: 6 }}>
            <Info size={12} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>Contact, title, company, signal, and every touch above are real — sourced from this campaign's scan and the company_contacts database, not fabricated.</span>
          </div>
        </div>
      )}
    </div>
  )
}

export default function DecisionIntelligenceLive() {
  const [data, setData] = useState<LiveData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [openHookId, setOpenHookId] = useState<number | null>(null)

  useEffect(() => {
    fetch('/api/decision-intelligence/live', { headers: authH() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setData)
      .catch(e => { setError(e.message); toast.error('Could not load live signal demo') })
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div style={{ padding: 60, textAlign: 'center', color: C.textMute }}>
      <Loader2 size={26} className="dil-spin" style={{ marginBottom: 10 }} />
      <div>Loading live signal data…</div>
      <style>{`@keyframes dil-spin{to{transform:rotate(360deg)}}.dil-spin{animation:dil-spin 1s linear infinite}
        @media (prefers-reduced-motion: reduce){.dil-spin{animation:none}}`}</style>
    </div>
  )
  if (error || !data) return <div style={{ padding: 40, color: '#ef4444' }}>Error: {error || 'no data'}</div>

  const { campaign, summary, signals, hooks } = data

  return (
    <div>
      <p style={{ color: C.textMute, marginTop: -14, marginBottom: 22, fontSize: 14 }}>
        Real signals from a live scan of {campaign.name.replace(/—.*$/, '').trim()}'s actual ICP, and real
        hooks generated from them — nothing on this page is fabricated or a static demo file.
      </p>

      {/* Campaign config */}
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <Radio size={15} color={C.primary} />
          <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text }}>Live campaign — {campaign.name}</span>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {campaign.keywords.map((k, i) => (
            <span key={i} style={{ fontSize: 11.5, fontWeight: 600, padding: '3px 10px', borderRadius: 999,
              background: 'rgba(59,130,246,0.08)', color: C.primary }}>{k}</span>
          ))}
        </div>
        {campaign.exclude_companies.length > 0 && (
          <p style={{ margin: '10px 0 0', fontSize: 11.5, color: C.textFaint }}>
            Self-excluded: {campaign.exclude_companies.join(', ')} — never persisted as a prospect of its own product.
          </p>
        )}
      </div>

      {/* Summary stats */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ ...card, padding: '12px 18px', flex: '1 1 160px' }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.text }}>{summary.total_signals}</div>
          <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 3 }}>real signals (job-board only)</div>
        </div>
        <div style={{ ...card, padding: '12px 18px', flex: '1 1 160px' }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.primary }}>{summary.total_companies}</div>
          <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 3 }}>distinct real companies</div>
        </div>
        <div style={{ ...card, padding: '12px 18px', flex: '1 1 160px' }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.success }}>{hooks.length}</div>
          <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 3 }}>real hooks generated</div>
        </div>
        <div style={{ ...card, padding: '12px 18px', flex: '1 1 160px' }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.violet }}>
            {summary.by_phase['hiring'] || 0}
          </div>
          <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 3 }}>actively hiring for this now</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 16 }}>
        {/* Real signals */}
        <div style={card}>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 4 }}>
            Real signals found <span style={{ color: C.textFaint, fontWeight: 500 }}>({signals.length})</span>
          </div>
          <p style={{ margin: '0 0 12px', fontSize: 11.5, color: C.textFaint }}>
            Direct job-board postings only — structured data, not article-text extraction, so every row
            traces to a verifiable source link.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 560, overflowY: 'auto' }}>
            {signals.map((s, i) => <SignalRow key={`${s.company_id}-${i}`} s={s} />)}
          </div>
        </div>

        {/* Real hooks */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 4 }}>
            <Mail size={14} color={C.violet} />
            <span style={{ fontSize: 13, fontWeight: 700, color: C.text }}>
              Real hooks generated <span style={{ color: C.textFaint, fontWeight: 500 }}>({hooks.length})</span>
            </span>
          </div>
          <p style={{ margin: '0 0 12px', fontSize: 11.5, color: C.textFaint }}>
            Each one ran through the real pipeline — personalization gate, angle selection, grounding
            check — against a real company above. Click to expand.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 720, overflowY: 'auto' }}>
            {hooks.length
              ? hooks.map(h => (
                  <HookCard
                    key={h.id}
                    h={h}
                    open={openHookId === h.id}
                    onToggle={() => setOpenHookId(id => id === h.id ? null : h.id)}
                  />
                ))
              : <div style={{ fontSize: 12.5, color: C.textFaint, fontStyle: 'italic' }}>No hooks generated yet.</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
