import { useState } from 'react'
import { Search, Users, Zap, Download, RefreshCw, CheckCircle2, XCircle, Copy, Mail, MessageSquare, Link } from 'lucide-react'
import { toast } from '../components/Toast'

const authH = () => ({ Authorization: `Bearer ${localStorage.getItem('token') || ''}` })

const card: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: 20,
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}

const btn = (color: string): React.CSSProperties => ({
  background: color, color: '#fff', border: 'none', borderRadius: 8,
  padding: '8px 16px', cursor: 'pointer', fontWeight: 600, fontSize: 13,
  display: 'inline-flex', alignItems: 'center', gap: 6,
  transition: 'opacity 150ms ease-out',
})

const pill = (color: string): React.CSSProperties => ({
  display: 'inline-block', padding: '2px 8px', borderRadius: 20,
  fontSize: 11, fontWeight: 600, background: color + '20', color: color,
})

interface YCCompany {
  id: number
  name: string
  website: string
  one_liner: string
  team_size: number
  batch: string
  tags: string[]
  industry: string
  selected?: boolean
}

interface Contact {
  first_name: string
  last_name: string
  title: string
  email: string
  email_status: string
  linkedin_url: string
  company: string
  team_size?: number
  batch?: string
  one_liner?: string
  website?: string
  selected?: boolean
}

interface Hook {
  subject: string
  body: string
  angle: string
  word_count: number
  contact_name: string
  company: string
  title: string
  email: string
  linkedin_url: string
  ok: boolean
  error?: string
}

type Step = 'icp' | 'contacts' | 'hooks' | 'export' | 'cadence'

const STEPS: { id: Step; label: string }[] = [
  { id: 'icp',      label: '1. Find ICP' },
  { id: 'contacts', label: '2. Find Contacts' },
  { id: 'hooks',    label: '3. Generate Hooks' },
  { id: 'export',   label: '4. Export' },
  { id: 'cadence',  label: '5. Cadence' },
]

interface Touch {
  day: number
  channel: string
  subject: string
  body: string
  notes: string
}

interface Sequence {
  contact_name: string
  company: string
  email: string
  linkedin_url: string
  title: string
  touches: Touch[]
  ok: boolean
  error?: string
}

const ANGLE_COLORS: Record<string, string> = {
  Risk: '#ef4444', Effort: '#f59e0b', Time: '#8b5cf6',
  Cost: '#10b981', Identity: '#3b82f6',
}

export default function CampaignBuilder() {
  const [step, setStep]           = useState<Step>('icp')
  const [companies, setCompanies] = useState<YCCompany[]>([])
  const [contacts,  setContacts]  = useState<Contact[]>([])
  const [hooks,      setHooks]      = useState<Hook[]>([])
  const [sequences,  setSequences]  = useState<Sequence[]>([])
  const [expandedSeq, setExpandedSeq] = useState<number | null>(null)
  const [loading,   setLoading]   = useState(false)
  const [minTeam,   setMinTeam]   = useState(8)
  const [maxTeam,   setMaxTeam]   = useState(300)
  const [expanded,  setExpanded]  = useState<number | null>(null)

  // ── Step 1 — fetch ICP companies ──────────────────────────────────────────
  async function fetchICP() {
    setLoading(true)
    try {
      const r = await fetch(
        `/api/campaign/icp-companies?min_team=${minTeam}&max_team=${maxTeam}&limit=80`,
        { headers: authH() }
      )
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d = await r.json()
      setCompanies((d.companies || []).map((c: YCCompany) => ({ ...c, selected: true })))
      setStep('contacts')
      toast.success(`Found ${d.count} companies matching Weave's ICP`)
    } catch (e: unknown) {
      toast.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  // ── Step 2 — find CTO contacts ────────────────────────────────────────────
  async function findContacts() {
    const selected = companies.filter(c => c.selected)
    if (!selected.length) { toast.error('Select at least one company'); return }
    setLoading(true)
    try {
      const r = await fetch('/api/campaign/find-contacts', {
        method: 'POST',
        headers: { ...authH(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ companies: selected }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d = await r.json()
      setContacts((d.contacts || []).map((c: Contact) => ({ ...c, selected: true })))
      setStep('hooks')
      toast.success(`Found ${d.count} contacts via Apollo`)
    } catch (e: unknown) {
      toast.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  // ── Step 3 — generate hooks ───────────────────────────────────────────────
  async function generateHooks() {
    const selected = contacts.filter(c => c.selected)
    if (!selected.length) { toast.error('Select at least one contact'); return }
    setLoading(true)
    toast.info(`Generating hooks for ${selected.length} contacts...`)
    try {
      const r = await fetch('/api/campaign/generate-hooks', {
        method: 'POST',
        headers: { ...authH(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ contacts: selected }),
      })
      if (!r.ok) {
        const err = await r.json()
        throw new Error(err.error || `HTTP ${r.status}`)
      }
      const d = await r.json()
      setHooks(d.hooks || [])
      setStep('export')
      const okCount = (d.hooks || []).filter((h: Hook) => h.ok).length
      toast.success(`Generated ${okCount} hooks`)
    } catch (e: unknown) {
      toast.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  // ── Export CSV ────────────────────────────────────────────────────────────
  async function exportCSV() {
    try {
      const r = await fetch('/api/campaign/export-csv', {
        method: 'POST',
        headers: { ...authH(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ hooks }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const blob = await r.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = 'weave_campaign.csv'
      a.click()
      URL.revokeObjectURL(url)
      toast.success('Downloaded weave_campaign.csv')
    } catch (e: unknown) {
      toast.error((e as Error).message)
    }
  }

  async function buildCadence() {
    const okHooks = hooks.filter(h => h.ok)
    if (!okHooks.length) { toast.error('No successful hooks to build cadence from'); return }
    setLoading(true)
    toast.info(`Building 5-touch sequences for ${okHooks.length} contacts…`)
    try {
      const r = await fetch('/api/campaign/build-cadence', {
        method: 'POST',
        headers: { ...authH(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ hooks: okHooks }),
      })
      if (!r.ok) { const e = await r.json(); throw new Error(e.error || `HTTP ${r.status}`) }
      const d = await r.json()
      setSequences(d.sequences || [])
      setStep('cadence')
      toast.success(`Built ${d.ok_count} sequences`)
    } catch (e: unknown) {
      toast.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function exportCadence() {
    try {
      const r = await fetch('/api/campaign/export-cadence', {
        method: 'POST',
        headers: { ...authH(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ sequences }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const blob = await r.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href = url; a.download = 'cadence_sequence.csv'; a.click()
      URL.revokeObjectURL(url)
      toast.success('Downloaded cadence_sequence.csv')
    } catch (e: unknown) {
      toast.error((e as Error).message)
    }
  }

  function copyHook(hook: Hook) {
    const text = `Subject: ${hook.subject}\n\n${hook.body}`
    navigator.clipboard.writeText(text)
    toast.success('Copied to clipboard')
  }

  const selectedCompanies = companies.filter(c => c.selected).length
  const selectedContacts  = contacts.filter(c => c.selected).length
  const successHooks      = hooks.filter(h => h.ok).length

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: '#0f172a', margin: 0 }}>
          Campaign Builder
        </h1>
        <p style={{ color: '#64748b', marginTop: 4, margin: '4px 0 0' }}>
          Find YC AI startups → enrich CTOs → generate personalised hooks → export
        </p>
      </div>

      {/* Step nav */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        {STEPS.map(s => (
          <div
            key={s.id}
            onClick={() => setStep(s.id)}
            style={{
              padding: '8px 14px', borderRadius: 8, cursor: 'pointer', fontSize: 13,
              fontWeight: step === s.id ? 700 : 500,
              background: step === s.id ? '#3b82f6' : '#f1f5f9',
              color: step === s.id ? '#fff' : '#64748b',
              transition: 'all 150ms ease-out',
            }}
          >
            {s.label}
          </div>
        ))}
      </div>

      {/* ── STEP 1: ICP companies ── */}
      {step === 'icp' && (
        <div style={card}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', marginTop: 0 }}>
            Find companies matching Weave's ICP
          </h2>
          <p style={{ color: '#64748b', fontSize: 13, marginBottom: 20 }}>
            Pulls from the public YC company directory — filters to AI / dev tool startups
            in recent batches (W22–W26) with team sizes matching Weave's customer profile.
          </p>

          <div style={{ display: 'flex', gap: 16, marginBottom: 20 }}>
            <div>
              <label style={{ fontSize: 12, fontWeight: 600, color: '#64748b', display: 'block', marginBottom: 4 }}>
                Min team size
              </label>
              <input
                type="number" value={minTeam}
                onChange={e => setMinTeam(+e.target.value)}
                style={{ width: 90, padding: '6px 10px', border: '1px solid #e2e8f0', borderRadius: 6, fontSize: 13 }}
              />
            </div>
            <div>
              <label style={{ fontSize: 12, fontWeight: 600, color: '#64748b', display: 'block', marginBottom: 4 }}>
                Max team size
              </label>
              <input
                type="number" value={maxTeam}
                onChange={e => setMaxTeam(+e.target.value)}
                style={{ width: 90, padding: '6px 10px', border: '1px solid #e2e8f0', borderRadius: 6, fontSize: 13 }}
              />
            </div>
          </div>

          <button onClick={fetchICP} disabled={loading} style={btn('#3b82f6')}>
            <Search size={14} />
            {loading ? 'Fetching...' : 'Fetch ICP Companies from YC Directory'}
          </button>
        </div>
      )}

      {/* ── STEP 2: company list + contact search ── */}
      {step === 'contacts' && companies.length > 0 && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ fontSize: 13, color: '#64748b' }}>
              {selectedCompanies} of {companies.length} companies selected
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => setCompanies(cs => cs.map(c => ({ ...c, selected: true })))} style={btn('#64748b')}>
                Select all
              </button>
              <button onClick={findContacts} disabled={loading} style={btn('#3b82f6')}>
                <Users size={14} />
                {loading ? 'Searching Apollo...' : `Find CTOs at ${selectedCompanies} companies`}
              </button>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 10 }}>
            {companies.map(co => (
              <div
                key={co.id}
                onClick={() => setCompanies(cs => cs.map(c => c.id === co.id ? { ...c, selected: !c.selected } : c))}
                style={{
                  ...card, cursor: 'pointer', padding: 14,
                  borderColor: co.selected ? '#3b82f6' : '#e2e8f0',
                  background: co.selected ? '#eff6ff' : '#fff',
                  transition: 'all 150ms ease-out',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>{co.name}</div>
                  <div style={pill('#3b82f6')}>{co.batch}</div>
                </div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 4, lineHeight: 1.4 }}>
                  {co.one_liner || '—'}
                </div>
                <div style={{ marginTop: 8, fontSize: 11, color: '#94a3b8' }}>
                  {co.team_size} people · {co.industry || co.tags?.[0] || ''}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── STEP 3: contacts + generate ── */}
      {step === 'hooks' && contacts.length > 0 && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ fontSize: 13, color: '#64748b' }}>
              {selectedContacts} of {contacts.length} contacts selected
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => setContacts(cs => cs.map(c => ({ ...c, selected: true })))} style={btn('#64748b')}>
                Select all
              </button>
              <button onClick={generateHooks} disabled={loading} style={btn('#8b5cf6')}>
                <Zap size={14} />
                {loading ? 'Generating...' : `Generate hooks for ${selectedContacts} contacts`}
              </button>
            </div>
          </div>

          <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: '#f8fafc' }}>
                  {['', 'Name', 'Title', 'Company', 'Email', 'Batch'].map(h => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 11, fontWeight: 700, color: '#64748b', borderBottom: '1px solid #e2e8f0' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {contacts.map((c, i) => (
                  <tr
                    key={i}
                    onClick={() => setContacts(cs => cs.map((x, j) => j === i ? { ...x, selected: !x.selected } : x))}
                    style={{ cursor: 'pointer', background: c.selected ? '#eff6ff' : '#fff', transition: 'background 100ms' }}
                  >
                    <td style={{ padding: '10px 14px', borderBottom: '1px solid #f1f5f9' }}>
                      <input type="checkbox" checked={!!c.selected} readOnly style={{ cursor: 'pointer' }} />
                    </td>
                    <td style={{ padding: '10px 14px', fontWeight: 600, fontSize: 13, color: '#0f172a', borderBottom: '1px solid #f1f5f9' }}>
                      {c.first_name} {c.last_name}
                    </td>
                    <td style={{ padding: '10px 14px', fontSize: 12, color: '#64748b', borderBottom: '1px solid #f1f5f9' }}>{c.title}</td>
                    <td style={{ padding: '10px 14px', fontSize: 12, color: '#0f172a', borderBottom: '1px solid #f1f5f9' }}>{c.company}</td>
                    <td style={{ padding: '10px 14px', fontSize: 12, color: '#3b82f6', borderBottom: '1px solid #f1f5f9' }}>{c.email || '—'}</td>
                    <td style={{ padding: '10px 14px', borderBottom: '1px solid #f1f5f9' }}>
                      {c.batch && <span style={pill('#3b82f6')}>{c.batch}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── STEP 4: hooks + export ── */}
      {step === 'export' && hooks.length > 0 && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div>
              <span style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>{successHooks}</span>
              <span style={{ fontSize: 13, color: '#64748b', marginLeft: 6 }}>hooks generated</span>
              {hooks.length - successHooks > 0 && (
                <span style={{ fontSize: 12, color: '#ef4444', marginLeft: 12 }}>
                  {hooks.length - successHooks} failed
                </span>
              )}
            </div>
            <button onClick={exportCSV} style={btn('#10b981')}>
              <Download size={14} />
              Export CSV
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {hooks.map((h, i) => (
              <div key={i} style={{ ...card, padding: 0, overflow: 'hidden' }}>
                {/* Hook header */}
                <div
                  onClick={() => setExpanded(expanded === i ? null : i)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '12px 16px', cursor: 'pointer',
                    background: expanded === i ? '#f8fafc' : '#fff',
                    transition: 'background 100ms',
                  }}
                >
                  {h.ok
                    ? <CheckCircle2 size={16} color="#10b981" />
                    : <XCircle size={16} color="#ef4444" />
                  }
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: 13, color: '#0f172a' }}>
                      {h.contact_name} · {h.company}
                    </div>
                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 1 }}>
                      {h.title}
                      {h.email && <span style={{ marginLeft: 8, color: '#3b82f6' }}>{h.email}</span>}
                    </div>
                  </div>
                  {h.ok && (
                    <>
                      <span style={pill(ANGLE_COLORS[h.angle] || '#64748b')}>{h.angle}</span>
                      <span style={{ fontSize: 11, color: '#94a3b8' }}>{h.word_count}w</span>
                    </>
                  )}
                  <button
                    onClick={e => { e.stopPropagation(); copyHook(h) }}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 4 }}
                    title="Copy to clipboard"
                  >
                    <Copy size={14} />
                  </button>
                </div>

                {/* Expanded email content */}
                {expanded === i && h.ok && (
                  <div style={{ padding: '0 16px 16px', borderTop: '1px solid #f1f5f9' }}>
                    <div style={{ marginTop: 12 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '.5px' }}>
                        Subject
                      </div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{h.subject}</div>
                    </div>
                    <div style={{ marginTop: 12 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '.5px' }}>
                        Email body
                      </div>
                      <div style={{
                        fontSize: 13, color: '#0f172a', lineHeight: 1.65,
                        background: '#f8fafc', borderRadius: 8, padding: 14,
                        whiteSpace: 'pre-wrap', fontFamily: 'system-ui, sans-serif',
                      }}>
                        {h.body}
                      </div>
                    </div>
                    {h.linkedin_url && (
                      <a
                        href={h.linkedin_url} target="_blank" rel="noreferrer"
                        style={{ fontSize: 12, color: '#3b82f6', marginTop: 8, display: 'inline-block' }}
                      >
                        LinkedIn →
                      </a>
                    )}
                  </div>
                )}

                {/* Error state */}
                {expanded === i && !h.ok && (
                  <div style={{ padding: '0 16px 16px', borderTop: '1px solid #f1f5f9' }}>
                    <div style={{ color: '#ef4444', fontSize: 13, marginTop: 12 }}>
                      Error: {h.error}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div style={{ marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button onClick={() => { setStep('icp'); setCompanies([]); setContacts([]); setHooks([]); setSequences([]) }} style={btn('#64748b')}>
              <RefreshCw size={14} /> Start over
            </button>
            <button onClick={exportCSV} style={btn('#10b981')}>
              <Download size={14} /> Export CSV
            </button>
            <button onClick={buildCadence} disabled={loading} style={btn('#6366f1')}>
              <MessageSquare size={14} /> Build 5-Touch Cadence →
            </button>
          </div>
        </div>
      )}

      {/* Empty states */}
      {step === 'contacts' && companies.length === 0 && (
        <div style={{ ...card, textAlign: 'center', padding: 60, color: '#64748b' }}>
          Go back to Step 1 to fetch companies first.
        </div>
      )}
      {step === 'hooks' && contacts.length === 0 && (
        <div style={{ ...card, textAlign: 'center', padding: 60, color: '#64748b' }}>
          Go back to Step 2 to find contacts first.
        </div>
      )}
      {step === 'export' && hooks.length === 0 && (
        <div style={{ ...card, textAlign: 'center', padding: 60, color: '#64748b' }}>
          Go back to Step 3 to generate hooks first.
        </div>
      )}

      {/* ── STEP 5: Cadence builder ── */}
      {step === 'cadence' && sequences.length > 0 && (() => {
        const CHANNEL_ICON: Record<string, React.ReactNode> = {
          email:             <Mail size={13} color="#3b82f6" />,
          linkedin_connect:  <Link size={13} color="#0077b5" />,
          linkedin_message:  <Link size={13} color="#0077b5" />,
        }
        const CHANNEL_LABEL: Record<string, string> = {
          email:            'Email',
          linkedin_connect: 'LinkedIn connect',
          linkedin_message: 'LinkedIn message',
        }
        const DAY_COLORS: Record<number, string> = { 1: '#3b82f6', 3: '#0077b5', 5: '#6366f1', 8: '#0077b5', 12: '#ef4444' }

        return (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <span style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>{sequences.filter(s => s.ok).length}</span>
                <span style={{ fontSize: 13, color: '#64748b', marginLeft: 6 }}>sequences built · 5 touches each</span>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={exportCadence} style={btn('#10b981')}>
                  <Download size={14} /> Export Apollo CSV
                </button>
              </div>
            </div>

            {/* Touch timeline legend */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
              {[
                { day: 1,  label: 'Day 1 — Email hook',          color: '#3b82f6' },
                { day: 3,  label: 'Day 3 — LinkedIn connect',     color: '#0077b5' },
                { day: 5,  label: 'Day 5 — Email follow-up',      color: '#6366f1' },
                { day: 8,  label: 'Day 8 — LinkedIn message',     color: '#0077b5' },
                { day: 12, label: 'Day 12 — Breakup email',       color: '#ef4444' },
              ].map(t => (
                <span key={t.day} style={{ fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 20, background: t.color + '18', color: t.color }}>
                  {t.label}
                </span>
              ))}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {sequences.map((seq, i) => (
                <div key={i} style={{ ...card, padding: 0, overflow: 'hidden' }}>
                  {/* Header */}
                  <div
                    onClick={() => setExpandedSeq(expandedSeq === i ? null : i)}
                    style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', cursor: 'pointer', background: expandedSeq === i ? '#f8fafc' : '#fff' }}
                  >
                    {seq.ok ? <CheckCircle2 size={16} color="#10b981" /> : <XCircle size={16} color="#ef4444" />}
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 700, fontSize: 13, color: '#0f172a' }}>{seq.contact_name} · {seq.company}</div>
                      <div style={{ fontSize: 12, color: '#64748b', marginTop: 1 }}>{seq.title}{seq.email && <span style={{ marginLeft: 8, color: '#3b82f6' }}>{seq.email}</span>}</div>
                    </div>
                    {seq.ok && (
                      <span style={{ fontSize: 12, color: '#64748b' }}>{seq.touches.length} touches</span>
                    )}
                  </div>

                  {/* Touch timeline */}
                  {expandedSeq === i && seq.ok && (
                    <div style={{ padding: '0 16px 16px', borderTop: '1px solid #f1f5f9' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 14 }}>
                        {seq.touches.map((touch, ti) => (
                          <div key={ti} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                            {/* Day badge */}
                            <div style={{ minWidth: 52, textAlign: 'center' }}>
                              <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: (DAY_COLORS[touch.day] || '#64748b') + '18', color: DAY_COLORS[touch.day] || '#64748b' }}>
                                Day {touch.day}
                              </span>
                            </div>
                            {/* Channel icon */}
                            <div style={{ minWidth: 18, paddingTop: 2 }}>{CHANNEL_ICON[touch.channel] || <Mail size={13} />}</div>
                            {/* Content */}
                            <div style={{ flex: 1 }}>
                              <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '.4px' }}>
                                {CHANNEL_LABEL[touch.channel] || touch.channel}
                                {touch.notes && <span style={{ fontWeight: 400, marginLeft: 8, textTransform: 'none', letterSpacing: 0 }}>· {touch.notes}</span>}
                              </div>
                              {touch.subject && (
                                <div style={{ fontSize: 12, fontWeight: 600, color: '#0f172a', marginBottom: 4 }}>Subject: {touch.subject}</div>
                              )}
                              <div style={{ fontSize: 13, color: '#374151', lineHeight: 1.6, background: '#f8fafc', borderRadius: 6, padding: '8px 10px', whiteSpace: 'pre-wrap' }}>
                                {touch.body}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {expandedSeq === i && !seq.ok && (
                    <div style={{ padding: '0 16px 16px', borderTop: '1px solid #f1f5f9', color: '#ef4444', fontSize: 13, marginTop: 12 }}>
                      Error: {seq.error}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
              <button onClick={() => setStep('export')} style={btn('#64748b')}>
                ← Back to hooks
              </button>
              <button onClick={exportCadence} style={btn('#10b981')}>
                <Download size={14} /> Export Apollo CSV
              </button>
            </div>
          </div>
        )
      })()}

      {step === 'cadence' && sequences.length === 0 && (
        <div style={{ ...card, textAlign: 'center', padding: 60, color: '#64748b' }}>
          Go back to Step 4 and click "Build 5-Touch Cadence" to generate sequences.
        </div>
      )}
    </div>
  )
}
