import { useState, useRef, useEffect } from 'react'

const authH = (): Record<string, string> => ({
  'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
  'Content-Type': 'application/json',
})
import { Search, Download, Mail, ExternalLink, MoreHorizontal, CheckCircle2, Trash2, Send, UserX, Loader, RefreshCw } from 'lucide-react'
import { toast } from '../components/Toast'

interface Contact {
  id: number
  first_name: string
  last_name: string
  title: string
  email: string
  linkedin_url: string
  confidence: number
  is_target: boolean
  source: string
  email_source: string
  email_validation_status: string
  email_prediction_pattern: string
  created_at: string
  company_name: string
  company_domain: string
}

const AVATAR_COLORS = ['#3b82f6', '#6366f1', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']
const scoreColor = (s: number) => s >= 0.8 ? '#10b981' : s >= 0.5 ? '#f59e0b' : '#ef4444'

const MENU_ITEMS = [
  { icon: Send,         label: 'Push to HubSpot',        color: '#3b82f6' },
  { icon: Mail,         label: 'Send email',              color: '#94a3b8' },
  { icon: ExternalLink, label: 'View on LinkedIn',        color: '#94a3b8' },
  { icon: CheckCircle2, label: 'Mark as validated',       color: '#10b981' },
  { icon: UserX,        label: 'Exclude from pipeline',   color: '#f59e0b' },
  { icon: Trash2,       label: 'Delete contact',          color: '#ef4444' },
]

function ActionMenu({ onClose, anchorRef, contact }: {
  onClose: () => void
  anchorRef: React.RefObject<HTMLButtonElement | null>
  contact: Contact
}) {
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node) && !anchorRef.current?.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose, anchorRef])

  const rect = anchorRef.current?.getBoundingClientRect()
  const name = `${contact.first_name} ${contact.last_name}`

  const handleItem = async (label: string) => {
    onClose()
    if (label === 'Push to HubSpot') {
      try {
        const r = await fetch('/api/contacts/push-hubspot', {
          method: 'POST',
          headers: authH(),
          body: JSON.stringify(contact),
        })
        const data = await r.json()
        data.ok ? toast.success(`${name} — ${data.message}`) : toast.error(data.message || 'Push failed')
      } catch { toast.error('Network error') }
    } else if (label === 'View on LinkedIn' && contact.linkedin_url) {
      window.open(contact.linkedin_url, '_blank')
    } else {
      toast.info(`${label}: ${name}`)
    }
  }

  return (
    <div ref={menuRef} style={{ position: 'fixed', top: rect ? rect.bottom + 4 : 0, right: rect ? window.innerWidth - rect.right : 0, zIndex: 1000, background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 10, padding: '6px 0', minWidth: 200, boxShadow: '0 8px 32px rgba(0,0,0,0.12)' }}>
      {MENU_ITEMS.map((item, i) => (
        <button key={i} onClick={() => handleItem(item.label)}
          style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px', background: 'none', border: 'none', cursor: 'pointer', color: item.color, fontSize: 13, textAlign: 'left', borderTop: i === MENU_ITEMS.length - 1 ? '1px solid #253047' : 'none', marginTop: i === MENU_ITEMS.length - 1 ? 4 : 0, paddingTop: i === MENU_ITEMS.length - 1 ? 10 : 8 }}
          onMouseEnter={e => (e.currentTarget.style.background = '#f8fafc')}
          onMouseLeave={e => (e.currentTarget.style.background = 'none')}>
          <item.icon size={14} color={item.color} />{item.label}
        </button>
      ))}
    </div>
  )
}

export default function Contacts() {
  const [contacts, setContacts] = useState<Contact[]>([])
  const [loading, setLoading]     = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError]         = useState('')
  const [search, setSearch]       = useState('')
  const [searchInput, setSearchInput] = useState('')  // debounced
  const [total, setTotal]         = useState(0)
  const [selected, setSelected]   = useState<number[]>([])
  const [openMenu, setOpenMenu]   = useState<number | null>(null)
  const [sourceFilter, setSourceFilter] = useState<'all' | 'apollo' | 'master_leads'>('all')
  const menuRefs = useRef<Map<number, HTMLButtonElement>>(new Map())
  const PAGE_SIZE = 500

  const isApollo = (src: string) => src === 'apollo' || src === 'apollo.io'

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 300)
    return () => clearTimeout(t)
  }, [searchInput])

  const buildUrl = (offset = 0, q = search) => {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) })
    if (q) params.set('search', q)
    return `/api/contacts?${params}`
  }

  const load = async (q = search) => {
    setLoading(true)
    setError('')
    try {
      const r = await fetch(buildUrl(0, q), { headers: authH() })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      if (data.error) throw new Error(data.error)
      setTotal(data.total ?? 0)
      setContacts(Array.isArray(data.rows) ? data.rows : Array.isArray(data) ? data : [])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load contacts')
    } finally {
      setLoading(false)
    }
  }

  const loadMore = async () => {
    setLoadingMore(true)
    try {
      const r = await fetch(buildUrl(contacts.length), { headers: authH() })
      if (!r.ok) {
        if (r.status === 401) { window.location.href = '/login'; return }
        toast.error('Failed to load more contacts')
        return
      }
      const data = await r.json()
      const newRows = Array.isArray(data.rows) ? data.rows : []
      setContacts(prev => [...prev, ...newRows])
    } catch {
      toast.error('Failed to load more contacts')
    } finally {
      setLoadingMore(false)
    }
  }

  useEffect(() => { load() }, [])
  useEffect(() => { if (search !== undefined) load(search) }, [search])

  const filtered = contacts
    .filter(c =>
      (sourceFilter === 'all') ||
      (sourceFilter === 'apollo' && isApollo(c.source || '')) ||
      (sourceFilter === 'master_leads' && !isApollo(c.source || ''))
    )

  const toggleSelect = (id: number) => setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id])
  const allSelected = filtered.length > 0 && filtered.every(c => selected.includes(c.id))

  const pushSelected = async () => {
    let ok = 0
    for (const id of selected) {
      const c = contacts.find(x => x.id === id)
      if (!c) continue
      try {
        const r = await fetch('/api/contacts/push-hubspot', {
          method: 'POST', headers: authH(),
          body: JSON.stringify(c),
        })
        const data = await r.json()
        if (data.ok) ok++
      } catch {}
    }
    toast.success(`${ok}/${selected.length} contacts pushed to HubSpot`)
    setSelected([])
  }

  const exportCSV = () => {
    const headers = ['Name', 'Company', 'Title', 'Email', 'Email Status', 'LinkedIn', 'Source']
    const rows = filtered.map(c => [
      `${c.first_name} ${c.last_name}`, c.company_name, c.title, c.email || '',
      c.email_validation_status || '', c.linkedin_url || '', c.source || '',
    ])
    const csv = [headers, ...rows].map(r => r.map(v => `"${(v || '').replace(/"/g, '""')}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = 'contacts.csv'; a.click()
    URL.revokeObjectURL(url)
    toast.success(`Exported ${filtered.length} contacts`)
  }

  const validCount = contacts.filter(c => c.email_validation_status === 'valid').length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%', minWidth: 0 }}>
      <style>{`@keyframes spin { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }`}</style>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>Contacts</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
            {loading ? 'Loading...' : (() => {
              const apolloCount = contacts.filter(c => isApollo(c.source || '')).length
              const mlCount = contacts.length - apolloCount
              return `${contacts.length} contacts · ${apolloCount} Apollo (with role) · ${mlCount} master leads (email only) · ${validCount} valid emails`
            })()}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {selected.length > 0 && (
            <>
              <span style={{ fontSize: 13, color: '#64748b' }}>{selected.length} selected</span>
              <button onClick={pushSelected} style={{ padding: '7px 14px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>
                Push to HubSpot
              </button>
              <button onClick={() => setSelected([])} style={{ padding: '7px 14px', borderRadius: 8, border: '1px solid rgba(239,68,68,0.3)', background: 'rgba(239,68,68,0.08)', color: '#f87171', fontSize: 13, cursor: 'pointer' }}>
                Clear
              </button>
            </>
          )}
          <button onClick={() => load()} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>
            <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          </button>
          <button onClick={exportCSV} disabled={filtered.length === 0} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}
            onMouseEnter={e => e.currentTarget.style.borderColor = '#3b82f6'}
            onMouseLeave={e => e.currentTarget.style.borderColor = '#e2e8f0'}>
            <Download size={13} /> Export
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: '12px 16px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 10, fontSize: 13, color: '#f87171' }}>
          {error}
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: '1 1 260px', maxWidth: 360 }}>
          <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#475569', pointerEvents: 'none' }} />
          <input value={searchInput} onChange={e => setSearchInput(e.target.value)} placeholder="Search contacts, roles, companies..."
            style={{ width: '100%', padding: '8px 12px 8px 36px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 13, outline: 'none', boxSizing: 'border-box' }} />
        </div>
        <div style={{ display: 'flex', padding: 3, borderRadius: 8, background: '#f8fafc', border: '1px solid #e2e8f0', gap: 2 }}>
          {([['all', 'All'], ['apollo', '🔵 Apollo (with role)'], ['master_leads', '📋 Master Leads']] as const).map(([val, label]) => (
            <button key={val} onClick={() => setSourceFilter(val)}
              style={{ padding: '5px 12px', borderRadius: 6, border: 'none', fontSize: 12, fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap',
                background: sourceFilter === val ? (val === 'apollo' ? '#6366f1' : val === 'master_leads' ? '#0f172a' : '#3b82f6') : 'transparent',
                color: sourceFilter === val ? 'white' : '#64748b', transition: 'all 0.15s' }}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 700 }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                <th style={{ padding: '12px 16px', width: 44, textAlign: 'left' }}>
                  <input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? [] : filtered.map(c => c.id))} style={{ accentColor: '#3b82f6', cursor: 'pointer' }} />
                </th>
                {['Contact', 'Company', 'Role', 'Confidence', 'Email Status', 'Source', ''].map((h, i) => (
                  <th key={i} style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#475569', whiteSpace: 'nowrap', letterSpacing: '0.02em' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={8} style={{ padding: '48px 0', textAlign: 'center', color: '#475569' }}>
                  <Loader size={18} style={{ animation: 'spin 1s linear infinite', display: 'inline-block', marginBottom: 8 }} />
                  <div style={{ fontSize: 13, marginTop: 8 }}>Loading contacts...</div>
                </td></tr>
              )}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={8} style={{ padding: '48px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>
                  {contacts.length === 0 ? 'No contacts yet — run an enrichment scan to discover contacts.' : 'No contacts match your search.'}
                </td></tr>
              )}
              {!loading && filtered.map((c, i) => (
                <tr key={c.id}
                  style={{ background: selected.includes(c.id) ? 'rgba(37,99,235,0.04)' : '#ffffff', borderBottom: '1px solid #f1f5f9', transition: 'background 0.1s' }}
                  onMouseEnter={e => { if (!selected.includes(c.id)) e.currentTarget.style.background = 'rgba(37,99,235,0.04)' }}
                  onMouseLeave={e => { e.currentTarget.style.background = selected.includes(c.id) ? 'rgba(37,99,235,0.04)' : '#ffffff' }}>
                  <td style={{ padding: '12px 16px' }}>
                    <input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggleSelect(c.id)} onClick={e => e.stopPropagation()} style={{ accentColor: '#3b82f6', cursor: 'pointer' }} />
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{ width: 34, height: 34, borderRadius: '50%', background: AVATAR_COLORS[i % AVATAR_COLORS.length], display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, color: 'white', flexShrink: 0 }}>
                        {(c.first_name || '?')[0].toUpperCase()}
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 500, color: '#0f172a', whiteSpace: 'nowrap' }}>{c.first_name} {c.last_name}</div>
                        <div style={{ fontSize: 11, color: '#64748b', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 180 }}>{c.email || '—'}</div>
                      </div>
                    </div>
                  </td>
                  <td style={{ padding: '12px 16px', fontSize: 13, color: '#94a3b8', whiteSpace: 'nowrap' }}>{c.company_name || '—'}</td>
                  <td style={{ padding: '12px 16px', fontSize: 13, whiteSpace: 'nowrap' }}>
                    {c.title
                      ? <span style={{ color: '#0f172a', fontWeight: 500 }}>{c.title}</span>
                      : <span style={{ color: '#94a3b8' }}>—</span>
                    }
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, padding: '2px 8px', borderRadius: 6, background: `${scoreColor(c.confidence)}18`, color: scoreColor(c.confidence), minWidth: 32, textAlign: 'center' }}>
                        {Math.round((c.confidence || 0) * 100)}
                      </span>
                    </div>
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, whiteSpace: 'nowrap', background: c.email_validation_status === 'valid' ? 'rgba(16,185,129,0.1)' : c.email_validation_status === 'invalid' ? 'rgba(239,68,68,0.1)' : 'rgba(107,114,128,0.1)', color: c.email_validation_status === 'valid' ? '#34d399' : c.email_validation_status === 'invalid' ? '#f87171' : '#9ca3af' }}>
                        {c.email_validation_status || 'not validated'}
                      </span>
                      {c.email_source === 'predicted' && (
                        <span title={`Pattern: ${c.email_prediction_pattern}`} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, whiteSpace: 'nowrap', background: 'rgba(139,92,246,0.12)', color: '#a78bfa', letterSpacing: '0.02em' }}>
                          ✦ predicted · {c.email_prediction_pattern}
                        </span>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    {isApollo(c.source || '')
                      ? <span style={{ fontSize: 11, padding: '3px 8px', borderRadius: 999, background: 'rgba(99,102,241,0.12)', color: '#818cf8', fontWeight: 600 }}>Apollo</span>
                      : c.source === 'master_leads' || c.source === '280k_master_db'
                        ? <span style={{ fontSize: 11, padding: '3px 8px', borderRadius: 999, background: 'rgba(107,114,128,0.1)', color: '#94a3b8', fontWeight: 500 }}>Master DB</span>
                        : <span style={{ fontSize: 11, padding: '3px 8px', borderRadius: 999, background: 'rgba(245,158,11,0.1)', color: '#f59e0b', fontWeight: 500 }}>{c.source || '—'}</span>
                    }
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                      {c.email && (
                        <a href={`mailto:${c.email}`} title="Send email" style={{ width: 28, height: 28, borderRadius: 6, border: 'none', background: 'transparent', cursor: 'pointer', color: '#475569', display: 'flex', alignItems: 'center', justifyContent: 'center', textDecoration: 'none' }}
                          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.08)'; (e.currentTarget as HTMLElement).style.color = '#e2e8f0' }}
                          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; (e.currentTarget as HTMLElement).style.color = '#475569' }}>
                          <Mail size={13} color="currentColor" />
                        </a>
                      )}
                      {c.linkedin_url && (
                        <a href={c.linkedin_url} target="_blank" rel="noreferrer" title="View LinkedIn" style={{ width: 28, height: 28, borderRadius: 6, border: 'none', background: 'transparent', cursor: 'pointer', color: '#475569', display: 'flex', alignItems: 'center', justifyContent: 'center', textDecoration: 'none' }}
                          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.08)'; (e.currentTarget as HTMLElement).style.color = '#e2e8f0' }}
                          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; (e.currentTarget as HTMLElement).style.color = '#475569' }}>
                          <ExternalLink size={13} color="currentColor" />
                        </a>
                      )}
                      <button ref={el => { if (el) menuRefs.current.set(c.id, el) }} title="More actions"
                        onClick={() => setOpenMenu(openMenu === c.id ? null : c.id)}
                        style={{ width: 28, height: 28, borderRadius: 6, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', background: openMenu === c.id ? 'rgba(59,130,246,0.15)' : 'transparent', color: openMenu === c.id ? '#60a5fa' : '#475569' }}
                        onMouseEnter={e => { if (openMenu !== c.id) { e.currentTarget.style.background = 'rgba(255,255,255,0.08)'; e.currentTarget.style.color = '#e2e8f0' } }}
                        onMouseLeave={e => { if (openMenu !== c.id) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#475569' } }}>
                        <MoreHorizontal size={14} />
                      </button>
                      {openMenu === c.id && (
                        <ActionMenu onClose={() => setOpenMenu(null)} anchorRef={{ current: menuRefs.current.get(c.id) ?? null }} contact={c} />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', fontSize: 12, color: '#64748b' }}>
          <span>Showing {filtered.length} of {total.toLocaleString()} contacts</span>
          {contacts.length < total && (
            <button
              onClick={loadMore}
              disabled={loadingMore}
              style={{ padding: '5px 16px', borderRadius: 7, border: '1px solid #d1d5db', background: '#fff', color: '#3b82f6', fontSize: 12, fontWeight: 600, cursor: loadingMore ? 'not-allowed' : 'pointer', opacity: loadingMore ? 0.6 : 1 }}>
              {loadingMore ? 'Loading…' : `Load more (${(total - contacts.length).toLocaleString()} remaining)`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
