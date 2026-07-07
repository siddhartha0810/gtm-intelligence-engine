import { useState, useEffect, useRef } from 'react'
import { Wand2, Search, Building2, AtSign, UserCircle2, CheckCircle2, Sparkles,
         Database, Loader2, ChevronRight } from 'lucide-react'
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

interface SearchResult {
  company_name: string; domain: string; format_code: string; formula: string
  domain_example: string; share_pct: number; formats_found: number
  contacts_280k: number; validated_emails: number; is_predictable: boolean
}
interface FormatRow {
  format_rank: number; format_code: string; formula: string; description: string
  domain_example: string; share_pct: number; format_count: number
  sample_emails: string; is_predictable: boolean; recommended_action: string
}
interface ContactRow {
  name: string; title: string; email: string | null
  predicted_email: string | null; predicted_pattern: string | null; source: string
}
interface CompanyDetail {
  domain: string; company_name: string; formats: FormatRow[]
  primary_pattern: string | null; contacts: ContactRow[]
}
interface Stats { total_rows: number; domains: number; predictable_domains: number }

function Chip({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'neutral' | 'blue' | 'green' | 'amber' }) {
  const map = {
    neutral: { bg: '#f1f5f9', color: C.textMute },
    blue:    { bg: 'rgba(59,130,246,0.1)',  color: C.primary },
    green:   { bg: 'rgba(16,185,129,0.12)', color: '#059669' },
    amber:   { bg: 'rgba(245,158,11,0.14)', color: '#b45309' },
  }[tone]
  return (
    <span style={{ background: map.bg, color: map.color, fontSize: 11.5, fontWeight: 600,
      padding: '2px 9px', borderRadius: 999, display: 'inline-block' }}>{children}</span>
  )
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

function FormatCard({ f, isPrimary }: { f: FormatRow; isPrimary: boolean }) {
  const [open, setOpen] = useState(isPrimary)
  const samples = (f.sample_emails || '').split(';').map(s => s.trim()).filter(Boolean).slice(0, 3)
  return (
    <div style={{ border: `1px solid ${isPrimary ? C.primary : C.border}`, borderRadius: 10,
      overflow: 'hidden', background: isPrimary ? 'rgba(59,130,246,0.03)' : 'transparent' }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: '100%', textAlign: 'left', border: 'none', cursor: 'pointer', background: 'transparent',
        padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10, boxSizing: 'border-box',
      }}>
        {isPrimary && <Chip tone="blue">PRIMARY</Chip>}
        <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 13, fontWeight: 700, color: C.text, flexShrink: 0 }}>
          {f.format_code}
        </span>
        <span style={{ fontSize: 12.5, color: C.textMute, flex: 1, minWidth: 0, overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.description}</span>
        {!f.is_predictable && <Chip tone="amber">no template</Chip>}
        <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 13, fontWeight: 700, color: C.text, flexShrink: 0 }}>
          {f.share_pct}%
        </span>
        <ChevronRight size={14} color={C.textFaint}
          style={{ flexShrink: 0, transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 150ms ease-out' }} />
      </button>
      {open && (
        <div style={{ padding: '0 14px 14px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12.5 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ color: C.textFaint, fontSize: 11, marginBottom: 2 }}>FORMULA</div>
              <div style={{ fontFamily: 'ui-monospace, monospace', color: C.text, wordBreak: 'break-all' }}>{f.formula}</div>
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ color: C.textFaint, fontSize: 11, marginBottom: 2 }}>EXAMPLE</div>
              <div style={{ fontFamily: 'ui-monospace, monospace', color: C.primary, wordBreak: 'break-all' }}>{f.domain_example}</div>
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ color: C.textFaint, fontSize: 11, marginBottom: 2 }}>EVIDENCE</div>
              <div style={{ color: C.text }}>{f.format_count} validated {f.format_count === 1 ? 'email' : 'emails'}</div>
            </div>
          </div>
          {samples.length > 0 && (
            <div>
              <div style={{ color: C.textFaint, fontSize: 11, marginBottom: 4 }}>SAMPLE VALIDATED EMAILS</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {samples.map((s, i) => (
                  <span key={i} style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11.5,
                    background: '#f1f5f9', padding: '3px 8px', borderRadius: 6, color: C.textMute }}>{s}</span>
                ))}
              </div>
            </div>
          )}
          {isPrimary && f.recommended_action && (
            <p style={{ margin: '4px 0 0', fontSize: 12, color: C.textMute, fontStyle: 'italic' }}>
              {f.recommended_action}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function ContactCard({ c }: { c: ContactRow }) {
  return (
    <div style={{ padding: '10px 0', borderBottom: `1px solid ${C.border}`,
      display: 'flex', alignItems: 'center', gap: 10 }}>
      <UserCircle2 size={20} color={C.textFaint} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600, color: C.text }}>{c.name}</span>
          {c.title && <span style={{ fontSize: 12.5, color: C.textMute }}>· {c.title}</span>}
        </div>
        <div style={{ marginTop: 3 }}>
          {c.email ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12,
              color: C.text, fontFamily: 'ui-monospace, monospace' }}>
              <AtSign size={11} /> {c.email}
              <Chip tone="green">on file</Chip>
            </span>
          ) : c.predicted_email ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12,
              color: C.primary, fontFamily: 'ui-monospace, monospace' }}>
              <Sparkles size={11} /> {c.predicted_email}
              <Chip tone="blue">predicted via {c.predicted_pattern}</Chip>
            </span>
          ) : (
            <span style={{ fontSize: 12, color: C.textFaint }}>no email — name incomplete, can't apply format</span>
          )}
        </div>
      </div>
    </div>
  )
}

export default function PredictionEngine() {
  const [stats, setStats]       = useState<Stats | null>(null)
  const [query, setQuery]       = useState('')
  const [results, setResults]   = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [selected, setSelected] = useState<SearchResult | null>(null)
  const [detail, setDetail]     = useState<CompanyDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const debouncedQuery = useDebounced(query, 300)
  const reqId = useRef(0)

  useEffect(() => {
    fetch('/api/prediction-engine/stats', { headers: authH() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setStats)
      .catch(() => { /* stats strip is decorative — fail quietly */ })
  }, [])

  useEffect(() => {
    if (debouncedQuery.trim().length < 2) { setResults([]); return }
    const id = ++reqId.current
    setSearching(true)
    fetch(`/api/prediction-engine/search?q=${encodeURIComponent(debouncedQuery)}`, { headers: authH() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(d => { if (id === reqId.current) setResults(d.results || []) })
      .catch(() => { if (id === reqId.current) toast.error('Search failed') })
      .finally(() => { if (id === reqId.current) setSearching(false) })
  }, [debouncedQuery])

  const selectCompany = (r: SearchResult) => {
    setSelected(r)
    setLoadingDetail(true)
    setDetail(null)
    fetch(`/api/prediction-engine/company?domain=${encodeURIComponent(r.domain)}`, { headers: authH() })
      .then(res => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json() })
      .then(setDetail)
      .catch(() => toast.error('Could not load company detail'))
      .finally(() => setLoadingDetail(false))
  }

  return (
    <div style={{ paddingBottom: 40 }}>
      <div style={{ marginBottom: 22 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <Wand2 size={22} color={C.violet} />
          <h1 style={{ fontSize: 24, fontWeight: 700, color: C.text, margin: 0 }}>Prediction Engine</h1>
        </div>
        <p style={{ color: C.textMute, marginTop: 5, fontSize: 14 }}>
          Search any company to see its learned email format — and watch it applied live to contacts already on file.
          Every format below is derived from validated emails in the corpus, not guessed.
        </p>
      </div>

      {stats && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
          <div style={{ ...card, padding: '12px 18px', flex: '1 1 180px', display: 'flex', alignItems: 'center', gap: 12 }}>
            <Database size={18} color={C.primary} />
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.text, lineHeight: 1 }}>{stats.domains.toLocaleString()}</div>
              <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 3 }}>companies covered</div>
            </div>
          </div>
          <div style={{ ...card, padding: '12px 18px', flex: '1 1 180px', display: 'flex', alignItems: 'center', gap: 12 }}>
            <CheckCircle2 size={18} color={C.success} />
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.text, lineHeight: 1 }}>{stats.predictable_domains.toLocaleString()}</div>
              <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 3 }}>have a buildable format</div>
            </div>
          </div>
          <div style={{ ...card, padding: '12px 18px', flex: '1 1 180px', display: 'flex', alignItems: 'center', gap: 12 }}>
            <Sparkles size={18} color={C.violet} />
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.text, lineHeight: 1 }}>{stats.total_rows.toLocaleString()}</div>
              <div style={{ fontSize: 11.5, color: C.textMute, marginTop: 3 }}>format rows on file</div>
            </div>
          </div>
        </div>
      )}

      <div style={{ ...card, marginBottom: 16, padding: 14 }}>
        <div style={{ position: 'relative' }}>
          <Search size={16} color={C.textFaint} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)' }} />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search a company name or domain (e.g. Oracle, acme.com)…"
            style={{
              width: '100%', padding: '10px 12px 10px 36px', borderRadius: 8,
              border: `1px solid ${C.border}`, fontSize: 14, color: C.text, outline: 'none',
              boxSizing: 'border-box',
            }}
          />
          {searching && <Loader2 size={15} color={C.textFaint} className="pe-spin"
            style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)' }} />}
        </div>

        {results.length > 0 && (
          <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 320, overflowY: 'auto' }}>
            {results.map(r => (
              <button key={r.domain} onClick={() => selectCompany(r)} style={{
                textAlign: 'left', border: 'none', cursor: 'pointer',
                background: selected?.domain === r.domain ? 'rgba(59,130,246,0.06)' : 'transparent',
                borderRadius: 8, padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 12,
              }}>
                <Building2 size={16} color={C.textFaint} style={{ flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600, color: C.text }}>{r.company_name}</div>
                  <div style={{ fontSize: 11.5, color: C.textFaint }}>{r.domain} · {r.contacts_280k.toLocaleString()} contacts in corpus</div>
                </div>
                {r.is_predictable ? (
                  <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12, color: C.primary }}>
                    {r.format_code} <span style={{ color: C.textFaint }}>({r.share_pct}%)</span>
                  </span>
                ) : <Chip tone="amber">no template</Chip>}
                <ChevronRight size={14} color={C.textFaint} />
              </button>
            ))}
          </div>
        )}
        {debouncedQuery.trim().length >= 2 && !searching && results.length === 0 && (
          <p style={{ margin: '10px 0 0', fontSize: 12.5, color: C.textFaint }}>No match in the format reference.</p>
        )}
      </div>

      {loadingDetail && (
        <div style={{ ...card, textAlign: 'center', color: C.textMute, padding: 40 }}>
          <Loader2 size={22} className="pe-spin" style={{ marginBottom: 8 }} />
          <div>Loading format detail…</div>
        </div>
      )}

      {detail && !loadingDetail && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 16, alignItems: 'start' }}>
          <div style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <Building2 size={16} color={C.primary} />
              <span style={{ fontSize: 14, fontWeight: 700, color: C.text }}>{detail.company_name}</span>
            </div>
            <p style={{ margin: '0 0 14px', fontSize: 12.5, color: C.textFaint }}>{detail.domain} · {detail.formats.length} format{detail.formats.length === 1 ? '' : 's'} found in the validated corpus</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {detail.formats.map(f => <FormatCard key={f.format_rank} f={f} isPrimary={f.format_rank === 1} />)}
            </div>
          </div>

          <div style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <UserCircle2 size={16} color={C.primary} />
              <span style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Contacts at this company</span>
              <span style={{ color: C.textFaint, fontSize: 12 }}>({detail.contacts.length})</span>
            </div>
            {!detail.primary_pattern && (
              <p style={{ margin: '0 0 10px', fontSize: 12, color: C.warning }}>
                No buildable format for this domain — contacts below can't get a live-predicted email.
              </p>
            )}
            {detail.contacts.length ? (
              detail.contacts.map((c, i) => <ContactCard key={i} c={c} />)
            ) : (
              <p style={{ margin: 0, fontSize: 12.5, color: C.textFaint }}>
                No contacts on file yet for this domain. Once one is found — via Companies, Contacts, or People Search —
                it'll show up here with this format applied automatically.
              </p>
            )}
          </div>
        </div>
      )}

      {!detail && !loadingDetail && (
        <div style={{ ...card, textAlign: 'center', padding: 48, color: C.textFaint }}>
          <Wand2 size={28} style={{ marginBottom: 10, opacity: 0.5 }} />
          <div style={{ fontSize: 13.5 }}>Search a company above to see how its email format was learned.</div>
        </div>
      )}

      <style>{`@keyframes pe-spin{to{transform:rotate(360deg)}}.pe-spin{animation:pe-spin 1s linear infinite}
        @media (prefers-reduced-motion: reduce){.pe-spin{animation:none}}`}</style>
    </div>
  )
}
