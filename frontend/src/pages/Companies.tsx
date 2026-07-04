import { useState, useRef, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search, Download, ArrowUpRight, MoreHorizontal, Zap, Users, Send,
         Eye, UserX, Trash2, RefreshCw, X, Mail, ExternalLink, ChevronRight,
         Building2, Loader2, Package, ChevronDown, Filter, GitMerge } from 'lucide-react'
import { toast } from '../components/Toast'

// Deterministic product badge color — hash product name to a palette slot
const _PRODUCT_PALETTE: Array<{ bg: string; color: string }> = [
  { bg: 'rgba(59,130,246,0.12)',  color: '#3b82f6' },
  { bg: 'rgba(99,102,241,0.12)', color: '#6366f1' },
  { bg: 'rgba(139,92,246,0.12)', color: '#8b5cf6' },
  { bg: 'rgba(16,185,129,0.12)', color: '#10b981' },
  { bg: 'rgba(245,158,11,0.12)', color: '#f59e0b' },
  { bg: 'rgba(239,68,68,0.10)',  color: '#ef4444' },
  { bg: 'rgba(249,115,22,0.12)', color: '#f97316' },
  { bg: 'rgba(20,184,166,0.12)', color: '#14b8a6' },
]

function productStyle(p: string) {
  if (!p) return { bg: 'rgba(107,114,128,0.1)', color: '#6b7280' }
  let hash = 0
  for (let i = 0; i < p.length; i++) hash = (hash * 31 + p.charCodeAt(i)) >>> 0
  return _PRODUCT_PALETTE[hash % _PRODUCT_PALETTE.length]
}

const authH = (): Record<string, string> => ({
  'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
  'Content-Type': 'application/json',
})

interface Company {
  id: number
  name: string
  industry: string
  size: string
  score: number
  phase: string
  signals: number
  contacts: number
  location: string
  source: string
  domain?: string
  target_product: string
  // Fit/Intent split (chadboyda pattern)
  fit_score?: number
  intent_score?: number
  routing?: string
  routing_color?: string
  // Signal tier (janskuba pattern)
  signal_tier?: string
  // Why-now
  why_now_reason?: string
}

interface DupeCompany {
  id: number; name: string; domain: string; industry: string
  signal_count: number; contact_count: number
}
interface DupePair {
  score: number; keep: DupeCompany; drop: DupeCompany
}

interface Contact {
  id: number | string
  full_name?: string
  first_name: string
  last_name: string
  title: string
  email: string
  linkedin_url: string
  confidence: number
  is_target: boolean
  source?: string
  email_validation_status?: string
}

function ContactsPanel({ company, onClose, onEnriched }: { company: Company; onClose: () => void; onEnriched?: () => void }) {
  const [contacts, setContacts]         = useState<Contact[]>([])
  const [loading, setLoading]           = useState(true)
  const [pushing, setPushing]           = useState<Record<string, boolean>>({})
  const [enriching, setEnriching]       = useState(false)
  const [enrichProgress, setEnrichProgress] = useState('')
  const [search, setSearch]             = useState('')
  const [showPicker, setShowPicker]     = useState(false)
  const [provider, setProvider]         = useState<'apollo' | 'zoominfo'>('apollo')
  const [maxPer, setMaxPer]             = useState(10)
  const [enrichResult, setEnrichResult] = useState<{ found: number } | null>(null)
  const enrichPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [deleting, setDeleting]         = useState<Record<string, boolean>>({})

  useEffect(() => {
    setLoading(true)
    fetch(`/api/company/${company.id}/contacts`, { headers: authH() })
      .then(r => r.ok ? r.json() : [])
      .then(data => setContacts(Array.isArray(data) ? data : []))
      .catch(() => setContacts([]))
      .finally(() => setLoading(false))
  }, [company.id])

  // clean up poll on unmount
  useEffect(() => () => { if (enrichPollRef.current) clearInterval(enrichPollRef.current) }, [])

  const reloadContacts = async () => {
    const r = await fetch(`/api/company/${company.id}/contacts`, { headers: authH() })
    if (r.ok) setContacts(await r.json())
  }

  const pushToHubSpot = async (c: Contact) => {
    setPushing(p => ({ ...p, [c.id]: true }))
    try {
      const r = await fetch('/api/contacts/push-hubspot', {
        method: 'POST', headers: authH(), body: JSON.stringify(c),
      })
      const d = await r.json()
      d.ok ? toast.success(`${c.first_name} ${c.last_name} — pushed`) : toast.error(d.message || 'Push failed')
    } catch { toast.error('Network error') }
    finally { setPushing(p => ({ ...p, [c.id]: false })) }
  }

  const deleteContact = async (c: Contact) => {
    if (!window.confirm(`Delete ${c.first_name} ${c.last_name}? This cannot be undone.`)) return
    setDeleting(d => ({ ...d, [c.id]: true }))
    try {
      const r = await fetch(`/api/contacts/${c.id}`, { method: 'DELETE', headers: authH() })
      if (r.ok) {
        setContacts(prev => prev.filter(x => x.id !== c.id))
        toast.success(`${c.first_name} ${c.last_name} deleted`)
        onEnriched?.()
      } else {
        toast.error('Delete failed')
      }
    } catch { toast.error('Network error') }
    finally { setDeleting(d => ({ ...d, [c.id]: false })) }
  }

  const launchEnrich = async () => {
    setShowPicker(false)
    setEnriching(true)
    setEnrichProgress(`Contacting ${provider === 'apollo' ? 'Apollo' : 'ZoomInfo'} API...`)
    try {
      const res = await fetch(`/api/company/${company.id}/contacts/enrich`, {
        method: 'POST',
        headers: authH(),
        body: JSON.stringify({ provider, max_per_company: maxPer }),
      })
      const d = await res.json()
      if (!res.ok) {
        toast.error(d.error || 'Failed to start enrichment')
        setEnriching(false)
        setEnrichProgress('')
        return
      }
      toast.info(`Enriching ${company.name} via ${provider === 'apollo' ? 'Apollo' : 'ZoomInfo'}...`)
      // Poll per-company status until done
      if (enrichPollRef.current) clearInterval(enrichPollRef.current)
      enrichPollRef.current = setInterval(async () => {
        try {
          const s = await fetch(`/api/company/${company.id}/enrich-status`, { headers: authH() }).then(r => r.json())
          if (s.status === 'running') {
            setEnrichProgress('Running Apollo/ZoomInfo + ZeroBounce pipeline...')
          } else {
            clearInterval(enrichPollRef.current!)
            enrichPollRef.current = null
            setEnriching(false)
            setEnrichProgress('')
            if (s.status === 'error') {
              toast.error(`Enrichment failed: ${s.error}`)
            } else {
              await reloadContacts()
              const found = s.contacts_found ?? 0
              setEnrichResult({ found })
              onEnriched?.()
            }
          }
        } catch { /* silent poll failure */ }
      }, 3000)
    } catch {
      toast.error('Network error')
      setEnriching(false)
      setEnrichProgress('')
    }
  }

  const confColor = (c: number) => c >= 0.8 ? '#10b981' : c >= 0.5 ? '#f59e0b' : '#ef4444'
  const filtered  = contacts
    .filter(c => c.email || c.linkedin_url)   // only contacts with at least one contact method
    .filter(c =>
      `${c.first_name} ${c.last_name}`.toLowerCase().includes(search.toLowerCase()) ||
      (c.full_name || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.title || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.email || '').toLowerCase().includes(search.toLowerCase())
    )

  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.25)', zIndex: 400, backdropFilter: 'blur(1px)' }} />
      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, width: 520,
        background: '#ffffff', zIndex: 500,
        boxShadow: '-8px 0 40px rgba(0,0,0,0.12)',
        display: 'flex', flexDirection: 'column',
        animation: 'slideInRight 0.22s ease',
      }}>
        <style>{`@keyframes slideInRight { from { transform: translateX(100%) } to { transform: translateX(0) } }`}</style>
        <div style={{ padding: '20px 24px', borderBottom: '1px solid #e2e8f0', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{ width: 42, height: 42, borderRadius: 10, background: 'linear-gradient(135deg, #3b82f6, #6366f1)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, fontWeight: 700, color: 'white', flexShrink: 0 }}>
                {company.name[0]}
              </div>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>{company.name}</div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                  {company.industry !== '—' ? company.industry : 'Unknown industry'} · {company.location}
                </div>
              </div>
            </div>
            <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 4, borderRadius: 6, flexShrink: 0 }}>
              <X size={18} />
            </button>
          </div>
          <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
            {[
              { label: 'Contacts', value: loading ? '…' : contacts.length, color: '#6366f1', icon: <Users size={12} /> },
              { label: 'Signals', value: company.signals, color: '#f59e0b', icon: <Zap size={12} /> },
              { label: 'Score', value: company.score, color: '#3b82f6', icon: <ChevronRight size={12} /> },
              { label: 'Phase', value: company.phase, color: '#10b981', icon: null },
            ].map(s => (
              <div key={s.label} style={{ flex: 1, padding: '8px 10px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0', textAlign: 'center' }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 3 }}>{s.label}</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: s.color }}>{s.value}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ padding: '12px 24px', borderBottom: '1px solid #f1f5f9', display: 'flex', gap: 10, flexShrink: 0 }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <Search size={12} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8' }} />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search contacts…"
              style={{ width: '100%', paddingLeft: 28, paddingRight: 10, paddingTop: 7, paddingBottom: 7, borderRadius: 7, border: '1px solid #d1d5db', fontSize: 12, color: '#0f172a', outline: 'none', boxSizing: 'border-box' }} />
          </div>
          <button onClick={() => !enriching && setShowPicker(true)} disabled={enriching}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 7, border: 'none', background: enriching ? '#93c5fd' : '#3b82f6', color: 'white', fontSize: 12, fontWeight: 600, cursor: enriching ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>
            {enriching ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <Zap size={12} />}
            {enriching ? 'Enriching…' : 'Enrich'}
          </button>
        </div>

        {/* enrichment progress bar */}
        {enriching && enrichProgress && (
          <div style={{ padding: '8px 24px', background: 'rgba(59,130,246,0.06)', borderBottom: '1px solid #dbeafe', fontSize: 11, color: '#3b82f6', display: 'flex', alignItems: 'center', gap: 6 }}>
            <Loader2 size={11} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
            {enrichProgress}
          </div>
        )}

        {/* provider picker modal */}
        {showPicker && (
          <>
            <div onClick={() => setShowPicker(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 600 }} />
            <div style={{
              position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
              width: 380, background: '#fff', borderRadius: 14, zIndex: 700,
              boxShadow: '0 20px 60px rgba(0,0,0,0.18)', padding: 24,
            }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', marginBottom: 4 }}>Find Contacts</div>
              <div style={{ fontSize: 12, color: '#64748b', marginBottom: 18 }}>{company.name}</div>

              {/* provider selection */}
              <div style={{ fontSize: 11, fontWeight: 600, color: '#374151', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Data Provider</div>
              <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
                {(['apollo', 'zoominfo'] as const).map(p => (
                  <button key={p} onClick={() => setProvider(p)}
                    style={{ flex: 1, padding: '10px 0', borderRadius: 8, border: `2px solid ${provider === p ? '#3b82f6' : '#e2e8f0'}`, background: provider === p ? 'rgba(59,130,246,0.07)' : '#f8fafc', cursor: 'pointer', textAlign: 'center' }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: provider === p ? '#3b82f6' : '#374151' }}>
                      {p === 'apollo' ? 'Apollo' : 'ZoomInfo'}
                    </div>
                    <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 2 }}>
                      {p === 'apollo' ? 'People API' : 'Contact DB'}
                    </div>
                  </button>
                ))}
              </div>

              {/* contacts per company */}
              <div style={{ fontSize: 11, fontWeight: 600, color: '#374151', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Contacts to Find</div>
              <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
                {[2, 5, 10, 15, 20].map(n => (
                  <button key={n} onClick={() => setMaxPer(n)}
                    style={{ flex: 1, padding: '7px 0', borderRadius: 7, border: `2px solid ${maxPer === n ? '#3b82f6' : '#e2e8f0'}`, background: maxPer === n ? 'rgba(59,130,246,0.07)' : '#f8fafc', cursor: 'pointer', fontSize: 13, fontWeight: 600, color: maxPer === n ? '#3b82f6' : '#374151' }}>
                    {n}
                  </button>
                ))}
              </div>

              <div style={{ display: 'flex', gap: 10 }}>
                <button onClick={() => setShowPicker(false)}
                  style={{ flex: 1, padding: '9px 0', borderRadius: 8, border: '1px solid #e2e8f0', background: '#f8fafc', fontSize: 13, fontWeight: 500, color: '#64748b', cursor: 'pointer' }}>
                  Cancel
                </button>
                <button onClick={launchEnrich}
                  style={{ flex: 2, padding: '9px 0', borderRadius: 8, border: 'none', background: '#3b82f6', fontSize: 13, fontWeight: 600, color: 'white', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                  <Zap size={13} /> Find Contacts via {provider === 'apollo' ? 'Apollo' : 'ZoomInfo'}
                </button>
              </div>
            </div>
          </>
        )}

        {/* enrichment result popup */}
        {enrichResult && (
          <>
            <div onClick={() => setEnrichResult(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 800 }} />
            <div style={{
              position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
              width: 340, background: '#fff', borderRadius: 16, zIndex: 900,
              boxShadow: '0 24px 64px rgba(0,0,0,0.2)', padding: '32px 28px', textAlign: 'center',
            }}>
              <div style={{ fontSize: 40, marginBottom: 12 }}>{enrichResult.found > 0 ? '✅' : 'ℹ️'}</div>
              <div style={{ fontSize: 17, fontWeight: 700, color: '#0f172a', marginBottom: 8 }}>
                {enrichResult.found > 0 ? `Found ${enrichResult.found} contact${enrichResult.found !== 1 ? 's' : ''}` : 'No new contacts'}
              </div>
              <div style={{ fontSize: 13, color: '#64748b', marginBottom: 24 }}>
                {enrichResult.found > 0
                  ? `Enriched ${enrichResult.found} contact${enrichResult.found !== 1 ? 's' : ''} for ${company.name}`
                  : `No new contacts were found for ${company.name}`}
              </div>
              <button onClick={() => setEnrichResult(null)}
                style={{ width: '100%', padding: '10px 0', borderRadius: 9, border: 'none', background: '#3b82f6', color: 'white', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>
                Done
              </button>
            </div>
          </>
        )}

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, gap: 8, color: '#94a3b8', fontSize: 13 }}>
              <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Loading contacts…
            </div>
          )}

          {!loading && filtered.length === 0 && (
            <div style={{ textAlign: 'center', padding: '48px 24px' }}>
              <div style={{ fontSize: 36, marginBottom: 12 }}>👤</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#374151' }}>No contacts found</div>
              <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 6, marginBottom: 20 }}>
                {contacts.length === 0
                  ? 'Click Enrich to find contacts for this company'
                  : 'No contacts match your search'}
              </div>
              {contacts.length === 0 && (
                <button onClick={() => setShowPicker(true)} disabled={enriching}
                  style={{ padding: '9px 20px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
                  Find Contacts Now
                </button>
              )}
            </div>
          )}

          {!loading && filtered.map((c, i) => {
            const name = c.full_name || `${c.first_name} ${c.last_name}`.trim() || 'Unknown'
            const conf = Math.round((c.confidence ?? 0) * 100)
            const COLORS = ['#3b82f6', '#6366f1', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']
            const avatarColor = COLORS[i % COLORS.length]

            return (
              <div key={c.id} style={{ padding: '14px 24px', borderBottom: '1px solid #f1f5f9', transition: 'background 0.12s' }}
                onMouseEnter={e => e.currentTarget.style.background = '#fafbff'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>

                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                  <div style={{ width: 36, height: 36, borderRadius: '50%', background: avatarColor, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700, color: 'white', flexShrink: 0 }}>
                    {name[0]?.toUpperCase()}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{name}</span>
                      {c.is_target && (
                        <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: 'rgba(16,185,129,0.12)', color: '#10b981', fontWeight: 600 }}>TARGET</span>
                      )}
                      {conf > 0 && (
                        <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 4, background: `${confColor(c.confidence)}18`, color: confColor(c.confidence), fontWeight: 600 }}>
                          {conf}%
                        </span>
                      )}
                      {(c.source === 'contacts_master' || c.source === 'master_leads') && (
                        <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: 'rgba(99,102,241,0.1)', color: '#818cf8', fontWeight: 500 }}>DB</span>
                      )}
                    </div>
                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{c.title || '—'}</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
                      {c.email ? (
                        <a href={`mailto:${c.email}`} onClick={e => e.stopPropagation()}
                          style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#3b82f6', textDecoration: 'none' }}>
                          <Mail size={11} /> {c.email}
                        </a>
                      ) : (
                        <span style={{ fontSize: 11, color: '#cbd5e1' }}>No email</span>
                      )}
                      {c.linkedin_url && (
                        <a href={c.linkedin_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
                          style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#6366f1', textDecoration: 'none' }}>
                          <ExternalLink size={11} /> LinkedIn
                        </a>
                      )}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6, flexShrink: 0, alignItems: 'center' }}>
                    <button onClick={() => pushToHubSpot(c)} disabled={pushing[c.id]}
                      title="Push to HubSpot"
                      style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 10px', borderRadius: 6, border: '1px solid rgba(16,185,129,0.3)', background: 'rgba(16,185,129,0.07)', color: '#10b981', fontSize: 11, fontWeight: 600, cursor: pushing[c.id] ? 'not-allowed' : 'pointer', opacity: pushing[c.id] ? 0.6 : 1 }}>
                      {pushing[c.id] ? <Loader2 size={10} style={{ animation: 'spin 1s linear infinite' }} /> : <Send size={10} />}
                      Push
                    </button>
                    <button onClick={() => deleteContact(c)} disabled={deleting[c.id]}
                      title="Delete contact"
                      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, borderRadius: 6, border: '1px solid rgba(239,68,68,0.25)', background: 'rgba(239,68,68,0.06)', color: '#ef4444', cursor: deleting[c.id] ? 'not-allowed' : 'pointer', opacity: deleting[c.id] ? 0.6 : 1 }}>
                      {deleting[c.id] ? <Loader2 size={10} style={{ animation: 'spin 1s linear infinite' }} /> : <Trash2 size={11} />}
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
        {!loading && contacts.length > 0 && (
          <div style={{ padding: '12px 24px', borderTop: '1px solid #e2e8f0', background: '#f8fafc', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>
              {filtered.length} of {contacts.length} contacts
            </span>
            <button
              onClick={async () => {
                let ok = 0
                for (const c of contacts) {
                  try {
                    const r = await fetch('/api/contacts/push-hubspot', { method: 'POST', headers: authH(), body: JSON.stringify(c) })
                    const d = await r.json()
                    if (d.ok) ok++
                  } catch {}
                }
                toast.success(`${ok}/${contacts.length} contacts pushed to HubSpot`)
              }}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', borderRadius: 7, border: 'none', background: '#3b82f6', color: 'white', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
              <Send size={11} /> Push All to HubSpot
            </button>
          </div>
        )}
      </div>
    </>
  )
}

function CompanyMenu({ company, onClose, anchorRef, onRefresh }: {
  company: Company
  onClose: () => void
  anchorRef: React.RefObject<HTMLButtonElement | null>
  onRefresh: () => void
}) {
  const menuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node) && !anchorRef.current?.contains(e.target as Node)) onClose() }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [onClose, anchorRef])
  const rect = anchorRef.current?.getBoundingClientRect()

  const handleAction = async (label: string) => {
    onClose()
    if (label === 'Send to enrichment') {
      try {
        const r = await fetch(`/api/company/${company.id}/contacts/enrich`, { method: 'POST', headers: authH() })
        r.ok ? toast.success(`Enrichment started for ${company.name}`) : toast.error('Enrichment failed')
      } catch { toast.error('Network error') }
    } else if (label === 'Push to HubSpot') {
      try {
        const r = await fetch(`/api/companies/${company.id}/push-hubspot`, { method: 'POST', headers: authH() })
        const d = await r.json().catch(() => ({}))
        r.ok ? toast.success(d.message || `${company.name} pushed to HubSpot`) : toast.error(d.detail || 'Push failed')
      } catch { toast.error('Network error') }
    } else if (label === 'Delete') {
      if (!window.confirm(`Delete ${company.name}?`)) return
      try {
        const r = await fetch(`/api/companies/${company.id}`, { method: 'DELETE', headers: authH() })
        r.ok ? (toast.success(`${company.name} deleted`), onRefresh()) : toast.error('Delete failed')
      } catch { toast.error('Network error') }
    } else if (label === 'View signals') {
      toast.info(`Signals for ${company.name}: ${company.signals} total`)
    } else if (label === 'Exclude company') {
      try {
        const r = await fetch(`/api/companies/${company.id}/status`, { method: 'PATCH', headers: authH(), body: JSON.stringify({ status: 'excluded' }) })
        r.ok ? (toast.success(`${company.name} excluded`), onRefresh()) : toast.error('Failed to exclude')
      } catch { toast.error('Network error') }
    }
  }

  const menuItems = [
    { icon: Eye,          label: 'View signals',       color: '#f59e0b' },
    { icon: Send,         label: 'Send to enrichment', color: '#3b82f6' },
    { icon: ArrowUpRight, label: 'Push to HubSpot',    color: '#10b981' },
    { icon: UserX,        label: 'Exclude company',    color: '#f59e0b' },
    { icon: Trash2,       label: 'Delete',             color: '#ef4444' },
  ]

  return (
    <div ref={menuRef} style={{ position: 'fixed', top: rect ? rect.bottom + 4 : 0, right: rect ? window.innerWidth - rect.right : 0, zIndex: 1000, background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 10, padding: '6px 0', minWidth: 200, boxShadow: '0 8px 32px rgba(0,0,0,0.12)' }}>
      {menuItems.map((item, i) => (
        <button key={i} onClick={() => handleAction(item.label)}
          style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px', background: 'none', border: 'none', cursor: 'pointer', color: item.color, fontSize: 13, textAlign: 'left', borderTop: i === menuItems.length - 1 ? '1px solid #e2e8f0' : 'none', marginTop: i === menuItems.length - 1 ? 4 : 0 }}
          onMouseEnter={e => (e.currentTarget.style.background = '#f8fafc')}
          onMouseLeave={e => (e.currentTarget.style.background = 'none')}>
          <item.icon size={13} color={item.color} />{item.label}
        </button>
      ))}
    </div>
  )
}

// ─── Excel-style column filter ────────────────────────────────────────────
function ColumnFilter({
  label, options, selected, onApply, onSort, align = 'left',
}: {
  label: string
  options: string[]
  selected: string[]
  onApply: (vals: string[]) => void
  onSort?: (dir: 'asc' | 'desc') => void
  align?: 'left' | 'right'
}) {
  const [open, setOpen]     = useState(false)
  const [q, setQ]           = useState('')
  const [draft, setDraft]   = useState<string[]>(selected)
  const ref                 = useRef<HTMLDivElement>(null)
  const active              = selected.length > 0

  // Sync draft when re-opening
  useEffect(() => { if (open) setDraft(selected) }, [open])

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const visible   = options.filter(o => o.toLowerCase().includes(q.toLowerCase()))
  const allTicked = visible.length > 0 && visible.every(o => draft.includes(o))
  const anyTicked = visible.some(o => draft.includes(o))

  const toggle = (o: string) =>
    setDraft(d => d.includes(o) ? d.filter(x => x !== o) : [...d, o])

  const toggleAll = () =>
    setDraft(allTicked ? draft.filter(x => !visible.includes(x)) : [...new Set([...draft, ...visible])])

  const apply = () => { onApply(draft); setOpen(false) }
  const clear = () => { onApply([]); setDraft([]); setOpen(false) }

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
      <button
        onClick={() => setOpen(v => !v)}
        title={active ? `Filtered: ${selected.join(', ')}` : `Filter by ${label}`}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 3,
          background: active ? 'rgba(59,130,246,0.12)' : 'transparent',
          border: 'none', borderRadius: 5, padding: '2px 5px',
          cursor: 'pointer', color: active ? '#3b82f6' : '#94a3b8',
        }}>
        <Filter size={11} style={{ opacity: active ? 1 : 0.5 }} />
        {active && <span style={{ fontSize: 10, fontWeight: 700, color: '#3b82f6' }}>{selected.length}</span>}
        <ChevronDown size={10} style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }} />
      </button>

      {open && (
        <div style={{
          position: 'fixed', zIndex: 9999,
          background: '#fff', border: '1px solid #d1d5db', borderRadius: 8,
          boxShadow: '0 8px 32px rgba(0,0,0,0.16)', width: 240,
          display: 'flex', flexDirection: 'column',
          // Position will be set via ref below — we use a portal-like trick with fixed
        }}
        ref={el => {
          if (el && ref.current) {
            const btn = ref.current.querySelector('button')
            if (btn) {
              const r = btn.getBoundingClientRect()
              el.style.top  = `${r.bottom + 4}px`
              el.style.left = align === 'right' ? `${r.right - 240}px` : `${r.left}px`
            }
          }
        }}>
          {/* Sort options */}
          {onSort && (
            <div style={{ borderBottom: '1px solid #e2e8f0' }}>
              {[{ label: 'Sort A → Z', dir: 'asc' as const }, { label: 'Sort Z → A', dir: 'desc' as const }].map(s => (
                <button key={s.dir} onClick={() => { onSort(s.dir); setOpen(false) }}
                  style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: '#0f172a', textAlign: 'left' }}
                  onMouseEnter={e => e.currentTarget.style.background = '#f1f5f9'}
                  onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                  {s.dir === 'asc' ? '🔼' : '🔽'} {s.label}
                </button>
              ))}
            </div>
          )}

          {/* Clear filter */}
          <button onClick={clear}
            style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', background: 'none', border: 'none', borderBottom: '1px solid #e2e8f0', cursor: active ? 'pointer' : 'not-allowed', fontSize: 12, color: active ? '#ef4444' : '#cbd5e1', textAlign: 'left' }}
            disabled={!active}
            onMouseEnter={e => { if (active) e.currentTarget.style.background = '#fef2f2' }}
            onMouseLeave={e => e.currentTarget.style.background = 'none'}>
            <X size={11} /> Clear filter from "{label}"
          </button>

          {/* Search */}
          <div style={{ padding: '8px 10px', borderBottom: '1px solid #f1f5f9' }}>
            <div style={{ position: 'relative' }}>
              <Search size={11} style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8' }} />
              <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search…"
                style={{ width: '100%', paddingLeft: 26, paddingRight: 8, paddingTop: 5, paddingBottom: 5, border: '1px solid #d1d5db', borderRadius: 6, fontSize: 12, outline: 'none', boxSizing: 'border-box' }} />
            </div>
          </div>

          {/* Checkboxes */}
          <div style={{ overflowY: 'auto', maxHeight: 220 }}>
            {/* Select all row */}
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', cursor: 'pointer', borderBottom: '1px solid #f1f5f9', fontSize: 12, color: '#0f172a', fontWeight: 600 }}
              onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              <input type="checkbox" checked={allTicked} ref={el => { if (el) el.indeterminate = anyTicked && !allTicked }}
                onChange={toggleAll} style={{ accentColor: '#3b82f6', width: 13, height: 13 }} />
              (Select All)
            </label>
            {visible.map(o => (
              <label key={o} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 12px', cursor: 'pointer', fontSize: 12, color: '#0f172a' }}
                onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                <input type="checkbox" checked={draft.includes(o)} onChange={() => toggle(o)}
                  style={{ accentColor: '#3b82f6', width: 13, height: 13 }} />
                {o}
              </label>
            ))}
            {visible.length === 0 && (
              <div style={{ padding: '12px', fontSize: 12, color: '#94a3b8', textAlign: 'center' }}>No results</div>
            )}
          </div>

          {/* OK / Cancel */}
          <div style={{ display: 'flex', gap: 8, padding: '10px 12px', borderTop: '1px solid #e2e8f0', background: '#f8fafc' }}>
            <button onClick={apply}
              style={{ flex: 1, padding: '6px 0', borderRadius: 6, border: 'none', background: '#3b82f6', color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
              OK
            </button>
            <button onClick={() => setOpen(false)}
              style={{ flex: 1, padding: '6px 0', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', color: '#374151', fontSize: 12, fontWeight: 500, cursor: 'pointer' }}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

const PHASES = ['All', 'Implementing', 'Evaluating', 'Researching', 'Hiring', 'Live']

const normalisePhase = (p: string): string => {
  const m: Record<string, string> = { implementing: 'Implementing', evaluating: 'Evaluating', researching: 'Researching', hiring: 'Hiring', live: 'Live' }
  return m[p?.toLowerCase()] ?? (p ? p.charAt(0).toUpperCase() + p.slice(1) : 'Unknown')
}

const scoreColor = (s: number) => s >= 80 ? '#10b981' : s >= 65 ? '#f59e0b' : '#ef4444'
const phaseColor = (p: string) => {
  if (p === 'Implementing') return { bg: 'rgba(59,130,246,0.12)',  color: '#60a5fa' }
  if (p === 'Evaluating')   return { bg: 'rgba(99,102,241,0.12)',  color: '#a5b4fc' }
  if (p === 'Hiring')       return { bg: 'rgba(245,158,11,0.12)',  color: '#fbbf24' }
  if (p === 'Live')         return { bg: 'rgba(16,185,129,0.12)',  color: '#34d399' }
  return { bg: 'rgba(107,114,128,0.15)', color: '#9ca3af' }
}

export default function Companies() {
  const [searchParams, setSearchParams] = useSearchParams()

  const [companies, setCompanies]         = useState<Company[]>([])
  const [total, setTotal]                 = useState(0)
  const [loadingMore, setLoadingMore]     = useState(false)
  const [loading, setLoading]             = useState(true)
  const [searchInput, setSearchInput]     = useState(() => searchParams.get('search') || '')
  const [search, setSearch]               = useState(() => searchParams.get('search') || '')
  const [phase, setPhase]                 = useState(() => searchParams.get('phase') || 'All')
  const [selected, setSelected]           = useState<number[]>([])
  const [sortKey, setSortKey]             = useState('score')
  const [sortDir, setSortDir]             = useState<'asc' | 'desc'>('desc')
  const [openMenu, setOpenMenu]           = useState<number | null>(null)
  const [contactsPanel, setContactsPanel] = useState<Company | null>(null)
  const [productFilter, setProductFilter]   = useState(() => searchParams.get('product') || 'All')
  const [industryFilter, setIndustryFilter] = useState<string[]>(() => searchParams.get('industry')?.split(',').filter(Boolean) ?? [])
  const [locationFilter, setLocationFilter] = useState<string[]>(() => searchParams.get('location')?.split(',').filter(Boolean) ?? [])
  const [contactsFilter, setContactsFilter] = useState<string[]>(() => { const v = searchParams.get('has_contacts'); return v ? [v] : [] })
  const [filterOptions, setFilterOptions]   = useState<{ industries: string[]; locations: string[]; products: string[] }>({ industries: [], locations: [], products: [] })
  const [editingProduct, setEditingProduct] = useState<number | null>(null)
  const [exporting, setExporting] = useState(false)
  const [showDupes, setShowDupes]   = useState(false)
  const [dupePairs, setDupePairs]   = useState<DupePair[]>([])
  const [dupeLoading, setDupeLoading] = useState(false)
  const [merging, setMerging]       = useState<string | null>(null)
  const menuRefs   = useRef<Map<number, HTMLButtonElement>>(new Map())
  const bulkPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const PAGE = 200

  // Sync active filters to URL so the view is bookmarkable / shareable
  useEffect(() => {
    const p: Record<string, string> = {}
    if (search)                         p['search']      = search
    if (phase !== 'All')                p['phase']       = phase
    if (productFilter !== 'All')        p['product']     = productFilter
    if (industryFilter.length > 0)      p['industry']    = industryFilter.join(',')
    if (locationFilter.length > 0)      p['location']    = locationFilter.join(',')
    if (contactsFilter.length > 0)      p['has_contacts']= contactsFilter[0]
    setSearchParams(p, { replace: true })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, phase, productFilter, JSON.stringify(industryFilter), JSON.stringify(locationFilter), JSON.stringify(contactsFilter)])

  // Clean up bulk-enrich poll on unmount
  useEffect(() => () => { if (bulkPollRef.current) clearInterval(bulkPollRef.current) }, [])

  const findDuplicates = async () => {
    setDupeLoading(true)
    setShowDupes(true)
    try {
      const r = await fetch('/api/companies/duplicates', { headers: authH() })
      const d = await r.json()
      setDupePairs(d.pairs || [])
    } catch { toast.error('Could not load duplicates') }
    finally { setDupeLoading(false) }
  }

  const mergePair = async (keep: DupeCompany, drop: DupeCompany) => {
    const key = `${keep.id}-${drop.id}`
    setMerging(key)
    try {
      const r = await fetch('/api/companies/merge', {
        method: 'POST',
        headers: { ...authH(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ keep_id: keep.id, drop_id: drop.id }),
      })
      if (!r.ok) throw new Error('Merge failed')
      toast.success(`Merged "${drop.name}" into "${keep.name}"`)
      setDupePairs(prev => prev.filter(p => p.keep.id !== keep.id || p.drop.id !== drop.id))
      fetchCompanies()
    } catch { toast.error('Merge failed') }
    finally { setMerging(null) }
  }

  const exportCSV = async () => {
    setExporting(true)
    try {
      const r = await fetch('/export/csv/all', { headers: authH() })
      if (!r.ok) { toast.error('Export failed'); return }
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `companies_${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
      toast.success('Companies exported')
    } catch {
      toast.error('Export failed')
    } finally {
      setExporting(false)
    }
  }

  useEffect(() => {
    fetch('/api/companies/filter-options', { headers: authH() })
      .then(r => r.ok ? r.json() : { industries: [], locations: [], products: [] })
      .then(d => setFilterOptions(d))
      .catch(() => {})
  }, [])

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 300)
    return () => clearTimeout(t)
  }, [searchInput])

  const mapRow = (c: Record<string, unknown>): Company => ({
    id:            Number(c.id),
    name:          String(c.name || ''),
    industry:      String(c.industry || '—'),
    size:          String(c.size || '—'),
    score:         Math.round(Number(c.priority_score ?? c.signal_count ?? 0)),
    phase:         normalisePhase(((c.phases as string[]) || [])[0] || 'Researching'),
    signals:       Number(c.signal_count ?? 0),
    contacts:      Number(c.contact_count ?? 0),
    location:      String(c.location || 'UK'),
    source:        ((c.sources as string[]) || [])[0] || 'Intent Scan',
    domain:        String(c.domain || ''),
    target_product: String(c.target_product || ''),
    fit_score:     c.fit_score   != null ? Number(c.fit_score)   : undefined,
    intent_score:  c.intent_score != null ? Number(c.intent_score) : undefined,
    routing:       c.routing      ? String(c.routing)       : undefined,
    routing_color: c.routing_color ? String(c.routing_color) : undefined,
    signal_tier:   c.signal_tier  ? String(c.signal_tier)   : undefined,
    why_now_reason: c.why_now_reason ? String(c.why_now_reason) : undefined,
  })

  const buildUrl = (offset = 0, q = search) => {
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(offset) })
    if (q) p.set('search', q)
    if (phase !== 'All') p.set('phase', phase.toLowerCase())
    if (productFilter !== 'All') p.set('product', productFilter)
    if (industryFilter.length > 0) p.set('industry', industryFilter.join(','))
    if (locationFilter.length > 0) p.set('location', locationFilter.join(','))
    if (contactsFilter.length > 0) p.set('has_contacts', contactsFilter[0])
    return `/api/companies?${p}`
  }

  const setTargetProduct = async (companyId: number, product: string) => {
    try {
      await fetch(`/api/companies/${companyId}/product`, {
        method: 'PATCH', headers: authH(),
        body: JSON.stringify({ target_product: product }),
      })
      setCompanies(cs => cs.map(c => c.id === companyId ? { ...c, target_product: product } : c))
      toast.success('Product updated')
    } catch { toast.error('Failed to update product') }
    setEditingProduct(null)
  }

  const fetchCompanies = useCallback(async (q = search) => {
    setLoading(true)
    try {
      const res = await fetch(buildUrl(0, q), { headers: authH() })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      // Support both paginated {total, rows} and legacy plain array
      const rows = Array.isArray(data) ? data : (data.rows ?? [])
      setTotal(data.total ?? rows.length)
      setCompanies(rows.map(mapRow))
    } catch {
      toast.error('Could not load companies — is the backend running?')
      setCompanies([])
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, phase, productFilter, JSON.stringify(industryFilter), JSON.stringify(locationFilter), JSON.stringify(contactsFilter)])

  const loadMore = async () => {
    setLoadingMore(true)
    try {
      const res = await fetch(buildUrl(companies.length), { headers: authH() })
      if (!res.ok) return
      const data = await res.json()
      const rows = Array.isArray(data) ? data : (data.rows ?? [])
      setCompanies(prev => [...prev, ...rows.map(mapRow)])
    } finally {
      setLoadingMore(false)
    }
  }

  useEffect(() => { fetchCompanies() }, [])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchCompanies(search) }, [search, phase, productFilter, JSON.stringify(industryFilter), JSON.stringify(locationFilter), JSON.stringify(contactsFilter)])

  // Client-side sort only (data already filtered server-side)
  const filtered = companies
    .sort((a, b) => {
      const d = sortDir === 'desc' ? -1 : 1
      if (sortKey === 'score')    return (b.score    - a.score)    * d
      if (sortKey === 'name')     return a.name.localeCompare(b.name) * d
      if (sortKey === 'signals')  return (b.signals  - a.signals)  * d
      if (sortKey === 'contacts') return (b.contacts - a.contacts) * d
      return 0
    })

  const toggleSort = (k: string) => { if (sortKey === k) setSortDir(d => d === 'desc' ? 'asc' : 'desc'); else { setSortKey(k); setSortDir('desc') } }
  const toggleSelect  = (id: number) => setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id])
  const allSelected   = filtered.length > 0 && filtered.every(c => selected.includes(c.id))

  const thStyle: React.CSSProperties = { padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#475569', letterSpacing: '0.03em', cursor: 'pointer', whiteSpace: 'nowrap', userSelect: 'none' }
  const tdStyle: React.CSSProperties = { padding: '13px 16px', fontSize: 13, verticalAlign: 'middle' }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      {contactsPanel && (
        <ContactsPanel company={contactsPanel} onClose={() => setContactsPanel(null)} onEnriched={fetchCompanies} />
      )}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0, letterSpacing: '-0.01em' }}>Companies</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
            Search or filter the company database — matched from your hunts and enrichment.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {selected.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, color: '#64748b' }}>{selected.length} selected</span>
              <button onClick={async () => {
                  try {
                    const r = await fetch('/api/companies/bulk-enrich', { method: 'POST', headers: { ...authH(), 'Content-Type': 'application/json' }, body: JSON.stringify({ company_ids: selected }) })
                    const d = await r.json()
                    if (r.ok) {
                      toast.success(`Enrichment running for ${selected.length} companies — check back in a few minutes`)
                      setSelected([])
                      // Poll progress — stored in ref so it can be cleared on unmount
                      if (bulkPollRef.current) clearInterval(bulkPollRef.current)
                      bulkPollRef.current = setInterval(async () => {
                        const pr = await fetch('/api/companies/bulk-enrich/progress', { headers: authH() })
                        const p = await pr.json()
                        if (!p.running) { clearInterval(bulkPollRef.current!); bulkPollRef.current = null; toast.success(`Enrichment complete: ${p.done} done, ${p.errors} errors`); fetchCompanies() }
                      }, 5000)
                    } else { toast.error(d.error || 'Bulk enrich failed') }
                  } catch { toast.error('Network error') }
                }}
                style={{ padding: '7px 14px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>
                Enrich Selected
              </button>
              <button onClick={() => setSelected([])} style={{ padding: '7px 14px', borderRadius: 8, border: '1px solid rgba(239,68,68,0.3)', background: 'rgba(239,68,68,0.1)', color: '#f87171', fontSize: 13, cursor: 'pointer' }}>Clear</button>
            </div>
          )}
          <button onClick={() => fetchCompanies()} title="Refresh"
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}
            onMouseEnter={e => e.currentTarget.style.borderColor = '#3b82f6'}
            onMouseLeave={e => e.currentTarget.style.borderColor = '#e2e8f0'}>
            <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          </button>
          <button onClick={exportCSV} disabled={exporting}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: exporting ? '#cbd5e1' : '#94a3b8', fontSize: 13, cursor: exporting ? 'not-allowed' : 'pointer' }}
            onMouseEnter={e => { if (!exporting) e.currentTarget.style.borderColor = '#3b82f6' }}
            onMouseLeave={e => e.currentTarget.style.borderColor = '#e2e8f0'}>
            <Download size={13} /> {exporting ? 'Exporting…' : 'Export'}
          </button>
          <button onClick={findDuplicates} disabled={dupeLoading}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: dupeLoading ? '#cbd5e1' : '#94a3b8', fontSize: 13, cursor: dupeLoading ? 'not-allowed' : 'pointer' }}
            onMouseEnter={e => { if (!dupeLoading) e.currentTarget.style.borderColor = '#f59e0b' }}
            onMouseLeave={e => e.currentTarget.style.borderColor = '#e2e8f0'}
            title="Find and merge duplicate companies">
            <GitMerge size={13} /> Duplicates
          </button>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', width: 300 }}>
          <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#475569' }} />
          <input value={searchInput} onChange={e => setSearchInput(e.target.value)} placeholder="Search companies, industries…"
            style={{ width: '100%', padding: '8px 12px 8px 36px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 13, outline: 'none' }}
            onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
            onBlur={e => e.currentTarget.style.borderColor = '#d1d5db'} />
        </div>
        <div style={{ display: 'flex', padding: 4, borderRadius: 8, background: '#f8fafc', border: '1px solid #e2e8f0', gap: 2 }}>
          {PHASES.map(p => (
            <button key={p} onClick={() => setPhase(p)}
              style={{ padding: '5px 14px', borderRadius: 6, border: 'none', fontSize: 13, fontWeight: 500, cursor: 'pointer', background: phase === p ? '#3b82f6' : 'transparent', color: phase === p ? 'white' : '#64748b', transition: 'all 0.15s' }}>
              {p}
            </button>
          ))}
        </div>
        <select
          value={productFilter}
          onChange={e => setProductFilter(e.target.value)}
          style={{ padding: '7px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'white', color: productFilter !== 'All' ? '#3b82f6' : '#64748b', fontSize: 13, cursor: 'pointer', fontWeight: productFilter !== 'All' ? 600 : 400 }}>
          <option value="All">All Products</option>
          {filterOptions.products.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>
      {/* Active filter chips */}
      {(industryFilter.length > 0 || locationFilter.length > 0 || contactsFilter.length > 0) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, color: '#64748b', fontWeight: 500 }}>Active filters:</span>
          {industryFilter.length > 0 && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 10px', borderRadius: 999, background: 'rgba(59,130,246,0.1)', color: '#3b82f6', fontSize: 12, fontWeight: 500 }}>
              Industry: {industryFilter.length === 1 ? industryFilter[0] : `${industryFilter.length} selected`}
              <button onClick={() => setIndustryFilter([])} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#3b82f6', padding: 0, display: 'flex', alignItems: 'center' }}><X size={11} /></button>
            </span>
          )}
          {locationFilter.length > 0 && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 10px', borderRadius: 999, background: 'rgba(99,102,241,0.1)', color: '#6366f1', fontSize: 12, fontWeight: 500 }}>
              Location: {locationFilter.length === 1 ? locationFilter[0] : `${locationFilter.length} selected`}
              <button onClick={() => setLocationFilter([])} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6366f1', padding: 0, display: 'flex', alignItems: 'center' }}><X size={11} /></button>
            </span>
          )}
          {contactsFilter.length > 0 && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 10px', borderRadius: 999, background: 'rgba(16,185,129,0.1)', color: '#10b981', fontSize: 12, fontWeight: 500 }}>
              Contacts: {contactsFilter[0] === 'yes' ? 'With contacts' : 'Without contacts'}
              <button onClick={() => setContactsFilter([])} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#10b981', padding: 0, display: 'flex', alignItems: 'center' }}><X size={11} /></button>
            </span>
          )}
          <button onClick={() => { setIndustryFilter([]); setLocationFilter([]); setContactsFilter([]) }}
            style={{ fontSize: 12, color: '#94a3b8', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>
            Clear all
          </button>
        </div>
      )}

      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
              <th style={{ ...thStyle, width: 44, cursor: 'default' }}>
                <input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? [] : filtered.map(c => c.id))} style={{ accentColor: '#3b82f6' }} />
              </th>
              <th style={thStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ cursor: 'pointer' }} onClick={() => toggleSort('name')}>
                    Company {sortKey === 'name' ? (sortDir === 'desc' ? '↓' : '↑') : <span style={{ color: '#cbd5e1' }}>↕</span>}
                  </span>
                  <ColumnFilter label="Location" options={filterOptions.locations} selected={locationFilter} onApply={setLocationFilter}
                    onSort={d => { setSortKey('name'); setSortDir(d) }} />
                </div>
              </th>
              <th style={thStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  Industry
                  <ColumnFilter label="Industry" options={filterOptions.industries} selected={industryFilter} onApply={setIndustryFilter}
                    onSort={d => { setSortKey('name'); setSortDir(d) }} />
                </div>
              </th>
              <th style={{ ...thStyle, cursor: 'default' }}>Target Product</th>
              <th style={thStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  Phase
                  <ColumnFilter label="Phase" options={['Implementing', 'Evaluating', 'Researching', 'Hiring', 'Live']}
                    selected={phase === 'All' ? [] : [phase]}
                    onApply={vals => setPhase(vals[0] ?? 'All')} />
                </div>
              </th>
              <th style={thStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ cursor: 'pointer' }} onClick={() => toggleSort('score')}>
                    Score {sortKey === 'score' ? (sortDir === 'desc' ? '↓' : '↑') : <span style={{ color: '#cbd5e1' }}>↕</span>}
                  </span>
                </div>
              </th>
              <th style={thStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ cursor: 'pointer' }} onClick={() => toggleSort('signals')}>
                    Signals {sortKey === 'signals' ? (sortDir === 'desc' ? '↓' : '↑') : <span style={{ color: '#cbd5e1' }}>↕</span>}
                  </span>
                </div>
              </th>
              <th style={thStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ cursor: 'pointer' }} onClick={() => toggleSort('contacts')}>
                    Contacts {sortKey === 'contacts' ? (sortDir === 'desc' ? '↓' : '↑') : <span style={{ color: '#cbd5e1' }}>↕</span>}
                  </span>
                  <ColumnFilter label="Contacts" options={['yes', 'no']} selected={contactsFilter} onApply={setContactsFilter} align="right" />
                </div>
              </th>
              <th style={{ ...thStyle, cursor: 'default', width: 70 }} />
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={9} style={{ padding: '48px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>
                Loading companies…
              </td></tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={9} style={{ padding: '48px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>
                No companies match your filters. Import a list or launch a hunt to populate this view.
              </td></tr>
            )}
            {!loading && filtered.map((c) => (
              <tr key={c.id}
                style={{ background: selected.includes(c.id) ? 'rgba(37,99,235,0.04)' : '#ffffff', borderBottom: '1px solid #f1f5f9' }}
                onMouseEnter={e => { if (!selected.includes(c.id)) e.currentTarget.style.background = 'rgba(37,99,235,0.03)' }}
                onMouseLeave={e => { e.currentTarget.style.background = selected.includes(c.id) ? 'rgba(37,99,235,0.04)' : '#ffffff' }}>

                <td style={tdStyle} onClick={e => e.stopPropagation()}>
                  <input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggleSelect(c.id)} style={{ accentColor: '#3b82f6' }} />
                </td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{ width: 32, height: 32, borderRadius: 8, background: 'rgba(59,130,246,0.12)', color: '#60a5fa', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 13, flexShrink: 0 }}>
                      {c.name[0]}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, color: '#0f172a' }}>{c.name}</div>
                      <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{c.location} · {c.size}</div>
                    </div>
                  </div>
                </td>

                <td style={{ ...tdStyle, color: '#94a3b8', fontSize: 12 }}>{c.industry}</td>
                <td style={tdStyle} onClick={e => e.stopPropagation()}>
                  {editingProduct === c.id ? (
                    <select autoFocus
                      defaultValue={c.target_product}
                      onBlur={e => setTargetProduct(c.id, e.target.value)}
                      onChange={e => setTargetProduct(c.id, e.target.value)}
                      style={{ fontSize: 12, padding: '3px 8px', borderRadius: 6, border: '1px solid #3b82f6', background: 'white', color: '#0f172a', cursor: 'pointer' }}>
                      <option value="">— unset —</option>
                      {filterOptions.products.map(p => <option key={p} value={p}>{p}</option>)}
                    </select>
                  ) : (
                    <span
                      onClick={() => setEditingProduct(c.id)}
                      title="Click to set target product"
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                        fontSize: 11, padding: '3px 8px', borderRadius: 6, fontWeight: 500, cursor: 'pointer',
                        ...(c.target_product ? productStyle(c.target_product) : { background: '#f1f5f9', color: '#94a3b8' }),
                      }}>
                      {c.target_product ? <><Package size={10} />{c.target_product}</> : '+ set product'}
                    </span>
                  )}
                </td>
                <td style={tdStyle}>
                  <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, fontWeight: 500, background: phaseColor(c.phase).bg, color: phaseColor(c.phase).color }}>
                    {c.phase}
                  </span>
                </td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {/* Score + progress bar */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 12, fontWeight: 700, padding: '2px 8px', borderRadius: 6, background: `${scoreColor(c.score)}18`, color: scoreColor(c.score), minWidth: 28, textAlign: 'center' }}>{c.score}</span>
                      <div style={{ width: 52, height: 4, borderRadius: 999, background: '#e2e8f0', overflow: 'hidden' }}>
                        <div style={{ width: `${Math.min(c.score, 100)}%`, height: '100%', borderRadius: 999, background: scoreColor(c.score) }} />
                      </div>
                    </div>
                    {/* Signal tier badge (P0/P1/P2) */}
                    {c.signal_tier && (
                      <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                        <span style={{
                          fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4,
                          background: c.signal_tier === 'P0' ? '#fee2e2' : c.signal_tier === 'P1' ? '#fef3c7' : '#f1f5f9',
                          color:      c.signal_tier === 'P0' ? '#dc2626' : c.signal_tier === 'P1' ? '#d97706' : '#64748b',
                          letterSpacing: '0.04em',
                        }}>{c.signal_tier}</span>
                        {/* Routing badge */}
                        {c.routing && (
                          <span style={{
                            fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4,
                            background: `${c.routing_color || '#94a3b8'}18`,
                            color: c.routing_color || '#64748b',
                          }}>{c.routing}</span>
                        )}
                      </div>
                    )}
                    {/* Fit / intent mini bars */}
                    {c.fit_score != null && c.intent_score != null && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          <span style={{ fontSize: 9, color: '#94a3b8', width: 24 }}>Fit</span>
                          <div style={{ flex: 1, height: 3, background: '#e2e8f0', borderRadius: 999, overflow: 'hidden', maxWidth: 44 }}>
                            <div style={{ width: `${Math.round(c.fit_score * 100)}%`, height: '100%', background: '#6366f1', borderRadius: 999 }} />
                          </div>
                          <span style={{ fontSize: 9, color: '#64748b' }}>{Math.round(c.fit_score * 100)}</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          <span style={{ fontSize: 9, color: '#94a3b8', width: 24 }}>Int</span>
                          <div style={{ flex: 1, height: 3, background: '#e2e8f0', borderRadius: 999, overflow: 'hidden', maxWidth: 44 }}>
                            <div style={{ width: `${Math.round(c.intent_score * 100)}%`, height: '100%', background: '#f59e0b', borderRadius: 999 }} />
                          </div>
                          <span style={{ fontSize: 9, color: '#64748b' }}>{Math.round(c.intent_score * 100)}</span>
                        </div>
                      </div>
                    )}
                  </div>
                </td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, color: '#94a3b8', fontSize: 13 }}>
                    <Zap size={12} color="#f59e0b" /> {c.signals}
                  </div>
                </td>
                <td style={tdStyle}>
                  <button
                    onClick={e => { e.stopPropagation(); setContactsPanel(c) }}
                    title={c.contacts > 0 ? `View ${c.contacts} contacts` : 'No contacts — click to enrich'}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 5,
                      padding: '4px 10px', borderRadius: 7,
                      border: `1px solid ${c.contacts > 0 ? 'rgba(99,102,241,0.25)' : '#e2e8f0'}`,
                      background: c.contacts > 0 ? 'rgba(99,102,241,0.08)' : '#f8fafc',
                      color: c.contacts > 0 ? '#6366f1' : '#94a3b8',
                      fontSize: 12, fontWeight: 600, cursor: 'pointer',
                      transition: 'all 0.15s',
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.background = c.contacts > 0 ? 'rgba(99,102,241,0.14)' : '#f1f5f9'
                      e.currentTarget.style.borderColor = c.contacts > 0 ? 'rgba(99,102,241,0.4)' : '#cbd5e1'
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.background = c.contacts > 0 ? 'rgba(99,102,241,0.08)' : '#f8fafc'
                      e.currentTarget.style.borderColor = c.contacts > 0 ? 'rgba(99,102,241,0.25)' : '#e2e8f0'
                    }}>
                    <Users size={11} />
                    {c.contacts > 0 ? c.contacts : '+ Add'}
                    {c.contacts > 0 && <ChevronRight size={10} />}
                  </button>
                </td>
                <td style={tdStyle} onClick={e => e.stopPropagation()}>
                  <div style={{ display: 'flex', gap: 2 }}>
                    <button title="View contacts" onClick={() => setContactsPanel(c)}
                      style={{ width: 28, height: 28, borderRadius: 6, border: 'none', background: 'transparent', cursor: 'pointer', color: '#475569', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                      onMouseEnter={e => { e.currentTarget.style.background = '#f1f5f9'; e.currentTarget.style.color = '#6366f1' }}
                      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#475569' }}>
                      <Building2 size={13} />
                    </button>
                    <button ref={el => { if (el) menuRefs.current.set(c.id, el) }}
                      title="More actions"
                      onClick={() => setOpenMenu(openMenu === c.id ? null : c.id)}
                      style={{ width: 28, height: 28, borderRadius: 6, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', background: openMenu === c.id ? 'rgba(59,130,246,0.12)' : 'transparent', color: openMenu === c.id ? '#3b82f6' : '#475569' }}
                      onMouseEnter={e => { if (openMenu !== c.id) { e.currentTarget.style.background = '#f1f5f9' } }}
                      onMouseLeave={e => { if (openMenu !== c.id) { e.currentTarget.style.background = 'transparent' } }}>
                      <MoreHorizontal size={14} />
                    </button>
                    {openMenu === c.id && (
                      <CompanyMenu company={c} onClose={() => setOpenMenu(null)}
                        anchorRef={{ current: menuRefs.current.get(c.id) ?? null }}
                        onRefresh={fetchCompanies} />
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', fontSize: 12, color: '#64748b' }}>
          <span>Showing {filtered.length} companies</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {companies.length < total && (
              <button onClick={loadMore} disabled={loadingMore}
                style={{ padding: '5px 16px', borderRadius: 7, border: '1px solid #d1d5db', background: '#fff', color: '#3b82f6', fontSize: 12, fontWeight: 600, cursor: loadingMore ? 'not-allowed' : 'pointer', opacity: loadingMore ? 0.6 : 1 }}>
                {loadingMore ? 'Loading…' : 'Load more'}
              </button>
            )}
            <span style={{ fontSize: 11, color: '#94a3b8' }}>Click the contacts badge on any row to view & manage contacts</span>
          </div>
        </div>
      </div>

      {/* Duplicate review modal */}
      {showDupes && (
        <>
          <div onClick={() => setShowDupes(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 500, backdropFilter: 'blur(2px)' }} />
          <div style={{ position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', background: '#fff', borderRadius: 16, padding: 28, width: 680, maxWidth: '96vw', maxHeight: '80vh', overflow: 'hidden', display: 'flex', flexDirection: 'column', zIndex: 501, boxShadow: '0 20px 60px rgba(0,0,0,0.18)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
              <div>
                <h2 style={{ fontSize: 18, fontWeight: 700, color: '#0f172a', margin: 0 }}>Duplicate Companies</h2>
                <p style={{ color: '#64748b', fontSize: 13, margin: '4px 0 0' }}>
                  {dupeLoading ? 'Scanning…' : `${dupePairs.length} potential duplicate${dupePairs.length !== 1 ? 's' : ''} found`}
                </p>
              </div>
              <button onClick={() => setShowDupes(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 4 }}><X size={20} /></button>
            </div>

            <div style={{ overflowY: 'auto', flex: 1 }}>
              {dupeLoading && (
                <div style={{ textAlign: 'center', padding: 40, color: '#64748b' }}>
                  <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', marginBottom: 8 }} />
                  <div>Scanning for duplicates…</div>
                </div>
              )}
              {!dupeLoading && dupePairs.length === 0 && (
                <div style={{ textAlign: 'center', padding: 40, color: '#64748b' }}>No duplicates found</div>
              )}
              {!dupeLoading && dupePairs.map((pair, i) => {
                const key = `${pair.keep.id}-${pair.drop.id}`
                const busy = merging === key
                return (
                  <div key={i} style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 16, marginBottom: 12, background: '#f8fafc' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                          <span style={{ fontSize: 11, fontWeight: 600, background: '#dbeafe', color: '#1d4ed8', borderRadius: 4, padding: '2px 7px' }}>{pair.score}% match</span>
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 8, alignItems: 'center' }}>
                          {/* Keep */}
                          <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: '10px 12px' }}>
                            <div style={{ fontSize: 11, fontWeight: 600, color: '#15803d', marginBottom: 3 }}>KEEP</div>
                            <div style={{ fontWeight: 600, color: '#0f172a', fontSize: 13 }}>{pair.keep.name}</div>
                            <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{pair.keep.signal_count} signals · {pair.keep.contact_count} contacts</div>
                          </div>
                          <GitMerge size={16} style={{ color: '#94a3b8', flexShrink: 0 }} />
                          {/* Drop */}
                          <div style={{ background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: 8, padding: '10px 12px' }}>
                            <div style={{ fontSize: 11, fontWeight: 600, color: '#c2410c', marginBottom: 3 }}>REMOVE</div>
                            <div style={{ fontWeight: 600, color: '#0f172a', fontSize: 13 }}>{pair.drop.name}</div>
                            <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{pair.drop.signal_count} signals · {pair.drop.contact_count} contacts</div>
                          </div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0 }}>
                        <button onClick={() => mergePair(pair.keep, pair.drop)} disabled={!!merging}
                          style={{ padding: '7px 14px', borderRadius: 8, border: 'none', background: busy ? '#94a3b8' : '#3b82f6', color: '#fff', fontSize: 13, fontWeight: 600, cursor: merging ? 'not-allowed' : 'pointer' }}>
                          {busy ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : 'Merge'}
                        </button>
                        <button onClick={() => setDupePairs(prev => prev.filter((_, idx) => idx !== i))} disabled={!!merging}
                          style={{ padding: '7px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#64748b', fontSize: 13, cursor: merging ? 'not-allowed' : 'pointer' }}>
                          Skip
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
