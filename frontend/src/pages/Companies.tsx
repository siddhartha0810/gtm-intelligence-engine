import { useState, useRef, useEffect, useCallback } from 'react'
import { Search, Download, ArrowUpRight, MoreHorizontal, Zap, Users, Send,
         Eye, UserX, Trash2, RefreshCw, X, Mail, ExternalLink, ChevronRight,
         Building2, Loader2, Package } from 'lucide-react'
import { toast } from '../components/Toast'

const ORACLE_PRODUCTS = [
  'JD Edwards', 'Oracle Cloud ERP', 'Oracle EBS', 'Oracle HCM',
  'Oracle SCM', 'Oracle EPM', 'Oracle CX', 'Oracle Database',
  'Oracle OCI', 'Oracle Integration', 'NetSuite', 'Oracle (General)',
]

const PRODUCT_COLORS: Record<string, { bg: string; color: string }> = {
  'JD Edwards':         { bg: 'rgba(239,68,68,0.1)',   color: '#ef4444' },
  'Oracle Cloud ERP':   { bg: 'rgba(59,130,246,0.12)', color: '#3b82f6' },
  'Oracle EBS':         { bg: 'rgba(99,102,241,0.12)', color: '#6366f1' },
  'Oracle HCM':         { bg: 'rgba(16,185,129,0.12)', color: '#10b981' },
  'Oracle SCM':         { bg: 'rgba(245,158,11,0.12)', color: '#f59e0b' },
  'Oracle EPM':         { bg: 'rgba(139,92,246,0.12)', color: '#8b5cf6' },
  'Oracle CX':          { bg: 'rgba(236,72,153,0.12)', color: '#ec4899' },
  'Oracle Database':    { bg: 'rgba(20,184,166,0.12)', color: '#14b8a6' },
  'Oracle OCI':         { bg: 'rgba(249,115,22,0.12)', color: '#f97316' },
  'Oracle Integration': { bg: 'rgba(34,197,94,0.12)',  color: '#22c55e' },
  'NetSuite':           { bg: 'rgba(168,85,247,0.12)', color: '#a855f7' },
  'Oracle (General)':   { bg: 'rgba(107,114,128,0.1)', color: '#6b7280' },
}

function productStyle(p: string) {
  return PRODUCT_COLORS[p] ?? { bg: 'rgba(107,114,128,0.1)', color: '#6b7280' }
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
}

interface Contact {
  id: number | string        // number from company_contacts, "ml_xxx" from master_leads
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

// ── Contacts slide-over ────────────────────────────────────────────────────
function ContactsPanel({ company, onClose }: { company: Company; onClose: () => void }) {
  const [contacts, setContacts]   = useState<Contact[]>([])
  const [loading, setLoading]     = useState(true)
  const [pushing, setPushing]     = useState<Record<string, boolean>>({})
  const [enriching, setEnriching] = useState(false)
  const [search, setSearch]       = useState('')

  useEffect(() => {
    setLoading(true)
    fetch(`/api/company/${company.id}/contacts`, { headers: authH() })
      .then(r => r.ok ? r.json() : [])
      .then(data => setContacts(Array.isArray(data) ? data : []))
      .catch(() => setContacts([]))
      .finally(() => setLoading(false))
  }, [company.id])

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

  const enrich = async () => {
    setEnriching(true)
    try {
      const r = await fetch(`/api/company/${company.id}/contacts/enrich`, { method: 'POST', headers: authH() })
      const d = await r.json()
      if (r.ok) {
        toast.success(`Found ${d.count ?? 0} contacts for ${company.name}`)
        // Reload contacts
        const r2 = await fetch(`/api/company/${company.id}/contacts`, { headers: authH() })
        if (r2.ok) setContacts(await r2.json())
      } else {
        toast.error('Enrichment failed')
      }
    } catch { toast.error('Network error') }
    finally { setEnriching(false) }
  }

  const confColor = (c: number) => c >= 0.8 ? '#10b981' : c >= 0.5 ? '#f59e0b' : '#ef4444'
  const filtered  = contacts.filter(c =>
    `${c.first_name} ${c.last_name}`.toLowerCase().includes(search.toLowerCase()) ||
    (c.title || '').toLowerCase().includes(search.toLowerCase()) ||
    (c.email || '').toLowerCase().includes(search.toLowerCase())
  )

  return (
    <>
      {/* Backdrop */}
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.25)', zIndex: 400, backdropFilter: 'blur(1px)' }} />

      {/* Panel */}
      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, width: 520,
        background: '#ffffff', zIndex: 500,
        boxShadow: '-8px 0 40px rgba(0,0,0,0.12)',
        display: 'flex', flexDirection: 'column',
        animation: 'slideInRight 0.22s ease',
      }}>
        <style>{`@keyframes slideInRight { from { transform: translateX(100%) } to { transform: translateX(0) } }`}</style>

        {/* Header */}
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

          {/* Stats row */}
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

        {/* Toolbar */}
        <div style={{ padding: '12px 24px', borderBottom: '1px solid #f1f5f9', display: 'flex', gap: 10, flexShrink: 0 }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <Search size={12} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8' }} />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search contacts…"
              style={{ width: '100%', paddingLeft: 28, paddingRight: 10, paddingTop: 7, paddingBottom: 7, borderRadius: 7, border: '1px solid #d1d5db', fontSize: 12, color: '#0f172a', outline: 'none', boxSizing: 'border-box' }} />
          </div>
          <button onClick={enrich} disabled={enriching}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 7, border: 'none', background: enriching ? '#93c5fd' : '#3b82f6', color: 'white', fontSize: 12, fontWeight: 600, cursor: enriching ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>
            {enriching ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <Zap size={12} />}
            {enriching ? 'Enriching…' : 'Enrich'}
          </button>
        </div>

        {/* Contact list */}
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
                <button onClick={enrich} disabled={enriching}
                  style={{ padding: '9px 20px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
                  Find Contacts Now
                </button>
              )}
            </div>
          )}

          {!loading && filtered.map((c, i) => {
            const name = `${c.first_name} ${c.last_name}`.trim() || 'Unknown'
            const conf = Math.round((c.confidence ?? 0) * 100)
            const COLORS = ['#3b82f6', '#6366f1', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']
            const avatarColor = COLORS[i % COLORS.length]

            return (
              <div key={c.id} style={{ padding: '14px 24px', borderBottom: '1px solid #f1f5f9', transition: 'background 0.12s' }}
                onMouseEnter={e => e.currentTarget.style.background = '#fafbff'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>

                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                  {/* Avatar */}
                  <div style={{ width: 36, height: 36, borderRadius: '50%', background: avatarColor, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700, color: 'white', flexShrink: 0 }}>
                    {name[0]?.toUpperCase()}
                  </div>

                  {/* Info */}
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
                      {c.source === 'master_leads' && (
                        <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: 'rgba(99,102,241,0.1)', color: '#818cf8', fontWeight: 500 }}>DB</span>
                      )}
                    </div>
                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{c.title || '—'}</div>

                    {/* Contact links */}
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

                  {/* Actions */}
                  <div style={{ display: 'flex', gap: 6, flexShrink: 0, alignItems: 'center' }}>
                    <button onClick={() => pushToHubSpot(c)} disabled={pushing[c.id]}
                      title="Push to HubSpot"
                      style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 10px', borderRadius: 6, border: '1px solid rgba(16,185,129,0.3)', background: 'rgba(16,185,129,0.07)', color: '#10b981', fontSize: 11, fontWeight: 600, cursor: pushing[c.id] ? 'not-allowed' : 'pointer', opacity: pushing[c.id] ? 0.6 : 1 }}>
                      {pushing[c.id] ? <Loader2 size={10} style={{ animation: 'spin 1s linear infinite' }} /> : <Send size={10} />}
                      Push
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* Footer */}
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

// ── Company actions menu ───────────────────────────────────────────────────
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

// ── Constants ──────────────────────────────────────────────────────────────
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

// ── Main page ──────────────────────────────────────────────────────────────
export default function Companies() {
  const [companies, setCompanies]       = useState<Company[]>([])
  const [loading, setLoading]           = useState(true)
  const [search, setSearch]             = useState('')
  const [phase, setPhase]               = useState('All')
  const [selected, setSelected]         = useState<number[]>([])
  const [sortKey, setSortKey]           = useState('score')
  const [sortDir, setSortDir]           = useState<'asc' | 'desc'>('desc')
  const [openMenu, setOpenMenu]         = useState<number | null>(null)
  const [contactsPanel, setContactsPanel] = useState<Company | null>(null)
  const [productFilter, setProductFilter] = useState('All')
  const [editingProduct, setEditingProduct] = useState<number | null>(null)
  const menuRefs = useRef<Map<number, HTMLButtonElement>>(new Map())

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

  const fetchCompanies = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/companies?show_all=1', { headers: authH() })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      const mapped: Company[] = data.map((c: Record<string, unknown>) => ({
        id:       Number(c.id),
        name:     String(c.name || ''),
        industry: String(c.industry || '—'),
        size:     String(c.size || '—'),
        score:    Math.round(Number(c.priority_score ?? c.signal_count ?? 0)),
        phase:    normalisePhase(((c.phases as string[]) || [])[0] || String(c.phase || 'Researching')),
        signals:       Number(c.signal_count ?? 0),
        contacts:      Number(c.contact_count ?? 0),
        location:      String(c.location || 'UK'),
        source:        ((c.sources as string[]) || [])[0] || 'Oracle Scan',
        domain:        String(c.domain || ''),
        target_product: String(c.target_product || ''),
      }))
      setCompanies(mapped)
    } catch {
      toast.error('Could not load companies — is the backend running?')
      setCompanies([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchCompanies() }, [fetchCompanies])

  const filtered = companies
    .filter(c => phase === 'All' || c.phase === phase)
    .filter(c => productFilter === 'All' || c.target_product === productFilter)
    .filter(c => c.name.toLowerCase().includes(search.toLowerCase()) || c.industry.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      const d = sortDir === 'desc' ? -1 : 1
      if (sortKey === 'score')    return (b.score    - a.score)    * d
      if (sortKey === 'name')     return a.name.localeCompare(b.name) * d
      if (sortKey === 'signals')  return (b.signals  - a.signals)  * d
      if (sortKey === 'contacts') return (b.contacts - a.contacts) * d
      return 0
    })

  const toggleSort    = (k: string) => { if (sortKey === k) setSortDir(d => d === 'desc' ? 'asc' : 'desc'); else { setSortKey(k); setSortDir('desc') } }
  const toggleSelect  = (id: number) => setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id])
  const allSelected   = filtered.length > 0 && filtered.every(c => selected.includes(c.id))

  const thStyle: React.CSSProperties = { padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#475569', letterSpacing: '0.03em', cursor: 'pointer', whiteSpace: 'nowrap', userSelect: 'none' }
  const tdStyle: React.CSSProperties = { padding: '13px 16px', fontSize: 13, verticalAlign: 'middle' }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>

      {/* Contacts slide-over */}
      {contactsPanel && (
        <ContactsPanel company={contactsPanel} onClose={() => setContactsPanel(null)} />
      )}

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', margin: 0 }}>Companies</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
            {loading ? 'Loading…' : `${companies.length} tracked · ${companies.filter(c => c.phase === 'Implementing').length} implementing Oracle`}
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
                      // Poll progress
                      const poll = setInterval(async () => {
                        const pr = await fetch('/api/companies/bulk-enrich/progress', { headers: authH() })
                        const p = await pr.json()
                        if (!p.running) { clearInterval(poll); toast.success(`Enrichment complete: ${p.done} done, ${p.errors} errors`); fetchCompanies() }
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
          <button onClick={fetchCompanies} title="Refresh"
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}
            onMouseEnter={e => e.currentTarget.style.borderColor = '#3b82f6'}
            onMouseLeave={e => e.currentTarget.style.borderColor = '#e2e8f0'}>
            <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          </button>
          <a href="/export/csv/all" download
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer', textDecoration: 'none' }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = '#3b82f6'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = '#e2e8f0'}>
            <Download size={13} /> Export
          </a>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', width: 300 }}>
          <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#475569' }} />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search companies, industries…"
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
        {/* Product filter */}
        <select
          value={productFilter}
          onChange={e => setProductFilter(e.target.value)}
          style={{ padding: '7px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'white', color: productFilter !== 'All' ? '#3b82f6' : '#64748b', fontSize: 13, cursor: 'pointer', fontWeight: productFilter !== 'All' ? 600 : 400 }}>
          <option value="All">All Products</option>
          {ORACLE_PRODUCTS.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>

      {/* Table */}
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
              <th style={{ ...thStyle, width: 44, cursor: 'default' }}>
                <input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? [] : filtered.map(c => c.id))} style={{ accentColor: '#3b82f6' }} />
              </th>
              <th style={thStyle} onClick={() => toggleSort('name')}>
                Company {sortKey === 'name' ? (sortDir === 'desc' ? '↓' : '↑') : <span style={{ color: '#cbd5e1' }}>↕</span>}
              </th>
              <th style={{ ...thStyle, cursor: 'default' }}>Industry</th>
              <th style={{ ...thStyle, cursor: 'default' }}>Target Product</th>
              <th style={{ ...thStyle, cursor: 'default' }}>Phase</th>
              <th style={thStyle} onClick={() => toggleSort('score')}>
                Score {sortKey === 'score' ? (sortDir === 'desc' ? '↓' : '↑') : <span style={{ color: '#cbd5e1' }}>↕</span>}
              </th>
              <th style={thStyle} onClick={() => toggleSort('signals')}>
                Signals {sortKey === 'signals' ? (sortDir === 'desc' ? '↓' : '↑') : <span style={{ color: '#cbd5e1' }}>↕</span>}
              </th>
              <th style={thStyle} onClick={() => toggleSort('contacts')} title="Click to view contacts">
                Contacts {sortKey === 'contacts' ? (sortDir === 'desc' ? '↓' : '↑') : <span style={{ color: '#cbd5e1' }}>↕</span>}
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
                No companies found. Run the Oracle Intent Engine to populate data.
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

                {/* Company name */}
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

                {/* Target Product — inline editable */}
                <td style={tdStyle} onClick={e => e.stopPropagation()}>
                  {editingProduct === c.id ? (
                    <select autoFocus
                      defaultValue={c.target_product}
                      onBlur={e => setTargetProduct(c.id, e.target.value)}
                      onChange={e => setTargetProduct(c.id, e.target.value)}
                      style={{ fontSize: 12, padding: '3px 8px', borderRadius: 6, border: '1px solid #3b82f6', background: 'white', color: '#0f172a', cursor: 'pointer' }}>
                      <option value="">— unset —</option>
                      {ORACLE_PRODUCTS.map(p => <option key={p} value={p}>{p}</option>)}
                    </select>
                  ) : (
                    <span
                      onClick={() => setEditingProduct(c.id)}
                      title="Click to set Oracle product"
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                        fontSize: 11, padding: '3px 8px', borderRadius: 6, fontWeight: 500, cursor: 'pointer',
                        ...(c.target_product ? productStyle(c.target_product) : { background: '#f1f5f9', color: '#94a3b8' }),
                      }}>
                      {c.target_product ? <><Package size={10} />{c.target_product}</> : '+ set product'}
                    </span>
                  )}
                </td>

                {/* Phase */}
                <td style={tdStyle}>
                  <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, fontWeight: 500, background: phaseColor(c.phase).bg, color: phaseColor(c.phase).color }}>
                    {c.phase}
                  </span>
                </td>

                {/* Score */}
                <td style={tdStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, padding: '2px 8px', borderRadius: 6, background: `${scoreColor(c.score)}18`, color: scoreColor(c.score), minWidth: 28, textAlign: 'center' }}>{c.score}</span>
                    <div style={{ width: 52, height: 4, borderRadius: 999, background: '#e2e8f0', overflow: 'hidden' }}>
                      <div style={{ width: `${Math.min(c.score, 100)}%`, height: '100%', borderRadius: 999, background: scoreColor(c.score) }} />
                    </div>
                  </div>
                </td>

                {/* Signals */}
                <td style={tdStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, color: '#94a3b8', fontSize: 13 }}>
                    <Zap size={12} color="#f59e0b" /> {c.signals}
                  </div>
                </td>

                {/* Contacts — CLICKABLE BADGE */}
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

                {/* Actions */}
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

        {/* Footer */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', fontSize: 12, color: '#64748b' }}>
          <span>Showing {filtered.length} of {companies.length} companies</span>
          <span style={{ fontSize: 11, color: '#94a3b8' }}>Click the contacts badge on any row to view & manage contacts</span>
        </div>
      </div>
    </div>
  )
}
