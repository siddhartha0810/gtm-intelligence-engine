import { useState, useEffect } from 'react'
import { Radio, Target, MessageSquareText, Mail, ShieldCheck, ChevronDown, ChevronRight,
         Loader2, CheckCircle2, PauseCircle, ArrowRight, TrendingUp } from 'lucide-react'
import { toast } from '../components/Toast'

const authH = (): Record<string, string> => ({
  Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
})

const C = {
  pageBg: '#f1f5f9', card: '#ffffff', border: '#e2e8f0', borderStrong: '#cbd5e1',
  primary: '#3b82f6', success: '#10b981', warning: '#f59e0b', danger: '#ef4444',
  violet: '#8b5cf6', text: '#0f172a', textMute: '#64748b', textFaint: '#94a3b8',
}

const card: React.CSSProperties = {
  background: C.card, border: `1px solid ${C.border}`, borderRadius: 12,
  padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}

// Same mapping CampaignBuilder.tsx uses for angle chips — kept identical so
// an angle reads as the same color everywhere in the product. Colorblind-safe
// (re-validated with the 6th slot added: worst adjacent-pair ΔE 20.9 tritan /
// 32.7 deutan) but the contrast-vs-surface WARN on amber/green/teal means
// these are never the only way to tell angles apart — every bar below
// carries a direct text label too.
const ANGLE_COLORS: Record<string, string> = {
  Risk: '#ef4444', Effort: '#f59e0b', Time: '#8b5cf6', Cost: '#10b981', Identity: '#3b82f6',
  TwoTimelines: '#14b8a6',
}

// Mirrors _ANGLE_INSTRUCTIONS in hook_generator.py — real methodology, not
// marketing copy. Each is the actual tension the model is told to find.
const ANGLE_DEFS = [
  { key: 'Risk',     desc: "Something at their company is breaking or about to — a specific operational blind spot, not a vague warning." },
  { key: 'Effort',   desc: 'A painful manual task they’re doing right now — the report they pull by hand, the question they can’t answer without pinging five people.' },
  { key: 'Time',     desc: 'A window closing — a competitor moving faster, a hiring surge, a funding milestone that changes the timing pressure.' },
  { key: 'Cost',     desc: 'A specific dollar figure bleeding monthly — wasted spend, a blocked deal, runway burned on the wrong thing.' },
  { key: 'Identity', desc: 'Their credibility with the board, investors, or CEO is on the line — specific to their stage, never a generic "board will ask" line.' },
  { key: 'TwoTimelines', desc: 'Two near-term futures for their role — one still stuck in the pain, one that fixed it by changing one thing this quarter. The reader places themselves on a side.' },
]

// Mirrors BUCKET_LABELS + compute_personalization_bucket in hook_generator.py.
const BUCKET_DEFS = [
  { n: 6, label: 'Deep',            desc: 'LinkedIn activity + a specific company metric + recent news' },
  { n: 5, label: 'Signal-grounded', desc: 'A primary intent signal plus a real company summary' },
  { n: 4, label: 'Trigger-based',   desc: 'A funding event or hiring burst on file' },
  { n: 3, label: 'ICP-resonant',    desc: 'Industry and role pain point only — no company-specific evidence' },
  { n: 2, label: 'Generic',         desc: 'Minimal context, backed only by social proof' },
  { n: 1, label: 'Hold-back',       desc: 'No usable context — the hook is never sent, not even generated' },
]

interface HookStats {
  total_hooks: number; ok_hooks: number; held_back: number
  by_angle: Record<string, number>; by_bucket: Record<string, number>
  total_touches: number
}
interface RecentHook {
  id: number; contact_name: string; contact_email: string; company_name: string; contact_title: string
  angle: string; subject: string; body: string
  personalization_bucket: number | null; personalization_label: string
  grounded: boolean | null; grounded_on: string
  hold_back: boolean; ok: boolean; error: string
  created_at: string
}
interface AttributionBucket { value: string; total: number; positive: number; meetings: number; negative: number; positive_rate: number; meeting_rate: number; label?: string }
interface Attribution {
  by_angle: AttributionBucket[]; by_personalization_bucket: AttributionBucket[]
  headline: { total_outcomes: number; replies: number; meetings: number; reply_rate: number; meeting_rate: number }
}

const OUTCOME_OPTIONS = [
  { value: 'contacted',    label: 'Contacted' },
  { value: 'replied',      label: 'Replied' },
  { value: 'meeting',      label: 'Meeting booked' },
  { value: 'bounced',      label: 'Bounced' },
  { value: 'bad',          label: 'Bad contact' },
  { value: 'unsubscribed', label: 'Unsubscribed' },
]

function LogOutcome({ h, onLogged }: { h: RecentHook; onLogged: () => void }) {
  const [outcome, setOutcome] = useState('contacted')
  const [saving, setSaving] = useState(false)
  const [logged, setLogged] = useState(false)

  const submit = async () => {
    setSaving(true)
    try {
      const r = await fetch('/api/outcomes', {
        method: 'POST',
        headers: { ...authH(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ outcome, hook_id: h.id, company: h.company_name, email: h.contact_email }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setLogged(true)
      toast.success(`Logged "${outcome}" for this hook`)
      onLogged()
    } catch {
      toast.error('Failed to log outcome')
    } finally {
      setSaving(false)
    }
  }

  if (logged) {
    return (
      <div style={{ marginTop: 10, fontSize: 11.5, color: C.success, display: 'flex', alignItems: 'center', gap: 5 }}>
        <CheckCircle2 size={12} /> Outcome logged — feeds angle performance below.
      </div>
    )
  }

  return (
    <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
      <select value={outcome} onChange={e => setOutcome(e.target.value)} style={{
        fontSize: 11.5, padding: '4px 8px', borderRadius: 6, border: `1px solid ${C.border}`,
        background: C.card, color: C.text, cursor: 'pointer',
      }}>
        {OUTCOME_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <button onClick={submit} disabled={saving} style={{
        fontSize: 11.5, fontWeight: 600, padding: '4px 10px', borderRadius: 6, border: 'none',
        background: saving ? C.textFaint : C.primary, color: '#fff', cursor: saving ? 'default' : 'pointer',
      }}>
        {saving ? 'Logging…' : 'Log outcome'}
      </button>
    </div>
  )
}

function StepCard({ icon, step, title, desc }: { icon: React.ReactNode; step: number; title: string; desc: string }) {
  return (
    <div style={{ ...card, flex: 1, minWidth: 200 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ width: 20, height: 20, borderRadius: 6, background: 'rgba(59,130,246,0.12)',
          color: C.primary, fontSize: 11, fontWeight: 800, display: 'flex', alignItems: 'center',
          justifyContent: 'center', flexShrink: 0 }}>{step}</span>
        {icon}
        <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text }}>{title}</span>
      </div>
      <p style={{ margin: 0, fontSize: 12.5, color: C.textMute, lineHeight: 1.5 }}>{desc}</p>
    </div>
  )
}

function Bar({ label, count, total, color }: { label: string; count: number; total: number; color: string }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
      <span style={{ fontSize: 12, color: C.textMute, width: 110, flexShrink: 0 }}>{label}</span>
      <div style={{ flex: 1, height: 16, background: '#f1f5f9', borderRadius: 8, overflow: 'hidden', position: 'relative' }}>
        <div style={{ width: `${pct}%`, minWidth: count > 0 ? 4 : 0, height: '100%', background: color,
          borderRadius: 8, transition: 'width 200ms ease-out' }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color: C.text, width: 56, textAlign: 'right', flexShrink: 0 }}>
        {count} <span style={{ fontWeight: 400, color: C.textFaint }}>({pct}%)</span>
      </span>
    </div>
  )
}

function RateBar({ rate, color }: { rate: number; color: string }) {
  const pct = Math.round(rate * 100)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ flex: 1, height: 16, background: '#f1f5f9', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, minWidth: pct > 0 ? 4 : 0, height: '100%', background: color,
          borderRadius: 8, transition: 'width 200ms ease-out' }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color: C.text, width: 60, textAlign: 'right', flexShrink: 0 }}>
        reply {pct}%
      </span>
    </div>
  )
}

function HookRow({ h, onLogged }: { h: RecentHook; onLogged: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden' }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: '100%', textAlign: 'left', border: 'none', cursor: 'pointer', background: 'transparent',
        padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10,
      }}>
        {h.hold_back
          ? <PauseCircle size={15} color={C.textFaint} style={{ flexShrink: 0 }} />
          : h.ok
            ? <CheckCircle2 size={15} color={C.success} style={{ flexShrink: 0 }} />
            : <PauseCircle size={15} color={C.danger} style={{ flexShrink: 0 }} />}
        <span style={{ fontSize: 13, fontWeight: 600, color: C.text, flexShrink: 0 }}>{h.contact_name || '—'}</span>
        <span style={{ fontSize: 12, color: C.textFaint, flexShrink: 0 }}>· {h.company_name}</span>
        <span style={{ fontSize: 12.5, color: C.textMute, flex: 1, minWidth: 0, overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.subject || (h.hold_back ? 'held back' : h.error)}</span>
        {h.angle && (
          <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 999, flexShrink: 0,
            background: `${ANGLE_COLORS[h.angle] || C.textMute}18`, color: ANGLE_COLORS[h.angle] || C.textMute }}>
            {h.angle}
          </span>
        )}
        {open ? <ChevronDown size={14} color={C.textFaint} /> : <ChevronRight size={14} color={C.textFaint} />}
      </button>
      {open && (
        <div style={{ padding: '0 14px 14px', borderTop: `1px solid ${C.border}` }}>
          {h.ok ? (
            <>
              <p style={{ margin: '10px 0 0', fontSize: 13, color: C.text, lineHeight: 1.6 }}>{h.body}</p>
              <div style={{ display: 'flex', gap: 14, marginTop: 10, fontSize: 11.5, color: C.textFaint, flexWrap: 'wrap' }}>
                {h.personalization_label && <span>bucket {h.personalization_bucket}: {h.personalization_label}</span>}
                {h.grounded != null && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <ShieldCheck size={12} color={h.grounded ? C.success : C.warning} />
                    {h.grounded ? `grounded on "${h.grounded_on}"` : 'ungrounded'}
                  </span>
                )}
              </div>
              <LogOutcome h={h} onLogged={onLogged} />
            </>
          ) : (
            <p style={{ margin: '10px 0 0', fontSize: 12.5, color: C.textFaint, fontStyle: 'italic' }}>
              {h.hold_back ? 'Held back — not enough context to personalize safely.' : (h.error || 'Failed')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default function CampaignEmails() {
  const [stats, setStats] = useState<HookStats | null>(null)
  const [hooks, setHooks] = useState<RecentHook[]>([])
  const [attribution, setAttribution] = useState<Attribution | null>(null)
  const [loading, setLoading] = useState(true)

  const loadAttribution = () => {
    fetch('/api/outcomes/attribution', { headers: authH() }).then(r => r.json()).then(setAttribution).catch(() => {})
  }

  useEffect(() => {
    Promise.all([
      fetch('/api/campaign/hook-stats', { headers: authH() }).then(r => r.json()),
      fetch('/api/campaign/recent-hooks?limit=50', { headers: authH() }).then(r => r.json()),
    ])
      .then(([s, h]) => { setStats(s); setHooks(h.hooks || []) })
      .catch(() => toast.error('Could not load campaign email data'))
      .finally(() => setLoading(false))
    loadAttribution()
  }, [])

  const total = stats?.total_hooks ?? 0
  const angleMax = stats ? Math.max(1, ...Object.values(stats.by_angle)) : 1
  const bucketMax = stats ? Math.max(1, ...Object.values(stats.by_bucket)) : 1

  return (
    <div style={{ paddingBottom: 40 }}>
      <div style={{ marginBottom: 22 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <Mail size={22} color={C.violet} />
          <h1 style={{ fontSize: 24, fontWeight: 700, color: C.text, margin: 0 }}>Campaign Emails</h1>
        </div>
        <p style={{ color: C.textMute, marginTop: 5, fontSize: 14 }}>
          How every outreach email actually gets written, and what's happening across every campaign that's used it.
        </p>
      </div>

      {/* Methodology — Signal -> Angle -> Hook -> Email */}
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 14 }}>The pipeline</div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'stretch' }}>
          <StepCard icon={<Radio size={14} color={C.primary} />} step={1} title="Signal"
            desc="Real evidence about the company — a hiring pattern, funding event, product detail. Everything downstream has to trace back to this." />
          <ArrowRight size={16} color={C.textFaint} style={{ alignSelf: 'center', flexShrink: 0 }} />
          <StepCard icon={<Target size={14} color={C.violet} />} step={2} title="Angle"
            desc="One of five tensions is picked to fit the evidence: Risk, Effort, Time, Cost, or Identity — never assigned at random." />
          <ArrowRight size={16} color={C.textFaint} style={{ alignSelf: 'center', flexShrink: 0 }} />
          <StepCard icon={<MessageSquareText size={14} color={C.warning} />} step={3} title="Hook"
            desc="One sentence. Names the problem, doesn't solve it, doesn't mention the product. Starts with their name, under 20 words after it." />
          <ArrowRight size={16} color={C.textFaint} style={{ alignSelf: 'center', flexShrink: 0 }} />
          <StepCard icon={<Mail size={14} color={C.success} />} step={4} title="Personalized email"
            desc="Gated by how much real context exists — six buckets, bucket 1 never sends. Every claim is checked against real evidence before it ships." />
        </div>

        <div style={{ marginTop: 18, paddingTop: 16, borderTop: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, color: C.textMute, textTransform: 'uppercase',
            letterSpacing: '0.04em', marginBottom: 10 }}>The five angles</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 10 }}>
            {ANGLE_DEFS.map(a => (
              <div key={a.key} style={{ borderLeft: `3px solid ${ANGLE_COLORS[a.key]}`, paddingLeft: 10 }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: C.text }}>{a.key}</div>
                <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 2, lineHeight: 1.4 }}>{a.desc}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 18, paddingTop: 16, borderTop: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, color: C.textMute, textTransform: 'uppercase',
            letterSpacing: '0.04em', marginBottom: 10 }}>The personalization gate</div>
          <p style={{ margin: '0 0 10px', fontSize: 12.5, color: C.textMute }}>
            Six buckets score how much real context exists for a contact before anything gets written.
            Bucket 1 is never sent — no hook is even generated for it.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 8 }}>
            {BUCKET_DEFS.map(b => (
              <div key={b.n} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <span style={{ width: 18, height: 18, borderRadius: 5, flexShrink: 0, marginTop: 1,
                  background: b.n === 1 ? 'rgba(148,163,184,0.15)' : 'rgba(59,130,246,0.12)',
                  color: b.n === 1 ? C.textFaint : C.primary, fontSize: 10, fontWeight: 800,
                  display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{b.n}</span>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{b.label}</div>
                  <div style={{ fontSize: 11, color: C.textFaint, lineHeight: 1.4 }}>{b.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {loading ? (
        <div style={{ ...card, textAlign: 'center', color: C.textMute, padding: 40 }}>
          <Loader2 size={22} className="ce-spin" style={{ marginBottom: 8 }} />
          <div>Loading campaign email data…</div>
          <style>{`@keyframes ce-spin{to{transform:rotate(360deg)}}.ce-spin{animation:ce-spin 1s linear infinite}
            @media (prefers-reduced-motion: reduce){.ce-spin{animation:none}}`}</style>
        </div>
      ) : total === 0 ? (
        <div style={{ ...card, textAlign: 'center', padding: 48, color: C.textFaint }}>
          <Mail size={28} style={{ marginBottom: 10, opacity: 0.5 }} />
          <div style={{ fontSize: 13.5 }}>No hooks generated yet — run Campaign Builder to see real numbers here.</div>
        </div>
      ) : (
        <>
          {/* Stats strip */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
            <div style={{ ...card, padding: '12px 18px', flex: '1 1 160px' }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.text }}>{stats!.total_hooks}</div>
              <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 3 }}>hooks generated</div>
            </div>
            <div style={{ ...card, padding: '12px 18px', flex: '1 1 160px' }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.success }}>{stats!.ok_hooks}</div>
              <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 3 }}>sent-ready</div>
            </div>
            <div style={{ ...card, padding: '12px 18px', flex: '1 1 160px' }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.textFaint }}>{stats!.held_back}</div>
              <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 3 }}>
                held back ({total > 0 ? Math.round((stats!.held_back / total) * 100) : 0}%)
              </div>
            </div>
            <div style={{ ...card, padding: '12px 18px', flex: '1 1 160px' }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.violet }}>{stats!.total_touches}</div>
              <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 3 }}>follow-up touches</div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 16, marginBottom: 16 }}>
            <div style={card}>
              <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 14 }}>Angle distribution</div>
              {ANGLE_DEFS.map(a => (
                <Bar key={a.key} label={a.key} count={stats!.by_angle[a.key] || 0} total={angleMax} color={ANGLE_COLORS[a.key]} />
              ))}
            </div>
            <div style={card}>
              <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 14 }}>Personalization depth</div>
              {BUCKET_DEFS.map(b => (
                <Bar key={b.n} label={`${b.n} · ${b.label}`} count={stats!.by_bucket[b.n] || 0} total={bucketMax} color={C.primary} />
              ))}
            </div>
          </div>

          {/* Angle performance — real reply/meeting rates, once outcomes are logged */}
          {attribution && attribution.headline.total_outcomes > 0 && (
            <div style={{ ...card, marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 4 }}>
                <TrendingUp size={14} color={C.success} />
                <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>Angle performance</div>
              </div>
              <p style={{ margin: '0 0 14px', fontSize: 12, color: C.textMute }}>
                Reply/meeting rate by angle, from outcomes logged against a specific hook below —
                the part of the pipeline that says whether Risk actually out-converts Cost, not just how often each was tried.
              </p>
              {attribution.by_angle.length === 0 ? (
                <div style={{ fontSize: 12.5, color: C.textFaint, fontStyle: 'italic' }}>
                  {attribution.headline.total_outcomes} outcome(s) logged, but none tied to a specific hook yet —
                  use "Log outcome" on a hook below to start attributing by angle.
                </div>
              ) : (
                attribution.by_angle.map(a => (
                  <div key={a.value} style={{ marginBottom: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                      <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 999,
                        background: `${ANGLE_COLORS[a.value] || C.textMute}18`, color: ANGLE_COLORS[a.value] || C.textMute }}>
                        {a.value}
                      </span>
                      <span style={{ fontSize: 11.5, color: C.textFaint }}>{a.total} outcome(s)</span>
                    </div>
                    <RateBar rate={a.positive_rate} color={ANGLE_COLORS[a.value] || C.primary} />
                  </div>
                ))
              )}
            </div>
          )}

          {/* Recent hooks */}
          <div style={card}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 12 }}>
              Recent hooks <span style={{ color: C.textFaint, fontWeight: 500 }}>({hooks.length})</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {hooks.map(h => <HookRow key={h.id} h={h} onLogged={loadAttribution} />)}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
