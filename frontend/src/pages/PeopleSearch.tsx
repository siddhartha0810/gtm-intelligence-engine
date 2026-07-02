import { useState } from 'react'
import { Search, ExternalLink, Mail, MapPin, Building2, User, ChevronDown, ChevronUp } from 'lucide-react'
import { toast } from '../components/Toast'

interface PersonResult {
  id: string
  name: string
  first_name: string
  last_name: string
  title: string
  email: string
  email_status: string
  linkedin_url: string
  company: string
  company_domain: string
  city: string
  state: string
  country: string
  photo_url: string
}

interface SearchResponse {
  results: PersonResult[]
  total: number
  page: number
  per_page: number
  error?: string
}

const authH = () => ({
  Authorization: `Bearer ${localStorage.getItem('token') || ''}`
})

function initials(name: string): string {
  const parts = name.trim().split(' ')
  return parts.length >= 2
    ? `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase()
    : name.slice(0, 2).toUpperCase()
}

function locationStr(p: PersonResult): string {
  return [p.city, p.state, p.country].filter(Boolean).join(', ')
}

function emailColor(status: string): string {
  if (status === 'verified') return '#10b981'
  if (status === 'likely')   return '#f59e0b'
  return '#94a3b8'
}

const AVATAR_COLORS = ['#6366f1','#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4']
function avatarColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}

export default function PeopleSearch() {
  const [query,       setQuery]       = useState('')
  const [company,     setCompany]     = useState('')
  const [location,    setLocation]    = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [loading,     setLoading]     = useState(false)
  const [results,     setResults]     = useState<PersonResult[]>([])
  const [total,       setTotal]       = useState(0)
  const [page,        setPage]        = useState(1)
  const [searched,    setSearched]    = useState(false)

  const search = async (p = 1) => {
    if (!query.trim() && !company.trim()) return
    setLoading(true)
    try {
      const res = await fetch('/api/people-search', {
        method: 'POST',
        headers: { ...authH(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          q: query.trim(),
          company: company.trim(),
          location: location.trim(),
          page: p,
          per_page: 25,
        }),
      })
      const data: SearchResponse = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      setResults(data.results)
      setTotal(data.total)
      setPage(p)
      setSearched(true)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: '#0f172a', margin: 0 }}>People Search</h1>
        <p style={{ color: '#64748b', marginTop: 4, fontSize: 14 }}>
          Search by job title or name — powered by Apollo
        </p>
      </div>

      {/* Search card */}
      <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)', marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 10 }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <Search size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8', pointerEvents: 'none' }} />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && search(1)}
              placeholder='Job title (e.g. "GTM Engineer") or person name (e.g. "John Smith")'
              autoFocus
              style={{ width: '100%', boxSizing: 'border-box', paddingLeft: 38, paddingRight: 14, paddingTop: 11, paddingBottom: 11, border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14, color: '#0f172a', outline: 'none', background: '#fafafa' }}
              onFocus={e => { e.currentTarget.style.borderColor = '#3b82f6'; e.currentTarget.style.background = '#fff' }}
              onBlur={e =>  { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.background = '#fafafa' }}
            />
          </div>
          <button
            onClick={() => search(1)}
            disabled={loading || (!query.trim() && !company.trim())}
            style={{ padding: '11px 22px', background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 14, cursor: (loading || (!query.trim() && !company.trim())) ? 'not-allowed' : 'pointer', opacity: (loading || (!query.trim() && !company.trim())) ? 0.6 : 1, whiteSpace: 'nowrap', transition: 'opacity 150ms ease-out' }}>
            {loading ? 'Searching…' : 'Search'}
          </button>
          <button
            onClick={() => setShowFilters(v => !v)}
            style={{ padding: '11px 14px', background: showFilters ? '#f1f5f9' : '#fff', color: '#374151', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 13, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, transition: 'background 150ms ease-out' }}>
            Filters
            {showFilters ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        </div>

        {showFilters && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 14, paddingTop: 14, borderTop: '1px solid #f1f5f9' }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: '#374151', marginBottom: 5 }}>Company</label>
              <div style={{ position: 'relative' }}>
                <Building2 size={13} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8', pointerEvents: 'none' }} />
                <input
                  value={company}
                  onChange={e => setCompany(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && search(1)}
                  placeholder="e.g. Salesforce"
                  style={{ width: '100%', boxSizing: 'border-box', paddingLeft: 30, paddingRight: 12, paddingTop: 8, paddingBottom: 8, border: '1px solid #d1d5db', borderRadius: 8, fontSize: 13, color: '#0f172a', outline: 'none', background: '#fafafa' }}
                  onFocus={e => { e.currentTarget.style.borderColor = '#3b82f6'; e.currentTarget.style.background = '#fff' }}
                  onBlur={e =>  { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.background = '#fafafa' }}
                />
              </div>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: '#374151', marginBottom: 5 }}>Location</label>
              <div style={{ position: 'relative' }}>
                <MapPin size={13} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8', pointerEvents: 'none' }} />
                <input
                  value={location}
                  onChange={e => setLocation(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && search(1)}
                  placeholder="e.g. London, United Kingdom"
                  style={{ width: '100%', boxSizing: 'border-box', paddingLeft: 30, paddingRight: 12, paddingTop: 8, paddingBottom: 8, border: '1px solid #d1d5db', borderRadius: 8, fontSize: 13, color: '#0f172a', outline: 'none', background: '#fafafa' }}
                  onFocus={e => { e.currentTarget.style.borderColor = '#3b82f6'; e.currentTarget.style.background = '#fff' }}
                  onBlur={e =>  { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.background = '#fafafa' }}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ textAlign: 'center', padding: 60, color: '#64748b' }}>
          <div style={{ width: 32, height: 32, border: '3px solid #e2e8f0', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.6s linear infinite', margin: '0 auto 14px' }} />
          <div style={{ fontSize: 14 }}>Searching…</div>
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {/* No results */}
      {!loading && searched && results.length === 0 && (
        <div style={{ textAlign: 'center', padding: '60px 40px', color: '#94a3b8' }}>
          <User size={40} style={{ margin: '0 auto 12px', opacity: 0.25 }} />
          <div style={{ fontSize: 15, fontWeight: 500, color: '#64748b' }}>No results found</div>
          <div style={{ fontSize: 13, marginTop: 4 }}>Try a different title, name, or company</div>
        </div>
      )}

      {/* Results table */}
      {!loading && results.length > 0 && (
        <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, boxShadow: '0 1px 3px rgba(0,0,0,0.06)', overflow: 'hidden' }}>
          {/* Table meta */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 20px', borderBottom: '1px solid #f1f5f9' }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#374151' }}>
              {total.toLocaleString()} result{total !== 1 ? 's' : ''}
            </span>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>Page {page} · showing {results.length}</span>
          </div>

          {/* Column headers */}
          <div style={{ display: 'grid', gridTemplateColumns: '44px 1fr 180px 180px 90px', gap: 16, padding: '8px 20px', background: '#f8fafc', borderBottom: '1px solid #f1f5f9' }}>
            <div />
            <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Person</div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Company</div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Email</div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', textAlign: 'right' }}>LinkedIn</div>
          </div>

          {/* Rows */}
          {results.map((p, i) => (
            <div
              key={p.id || i}
              style={{ display: 'grid', gridTemplateColumns: '44px 1fr 180px 180px 90px', alignItems: 'center', gap: 16, padding: '13px 20px', borderBottom: i < results.length - 1 ? '1px solid #f8fafc' : 'none', transition: 'background 120ms ease-out' }}
              onMouseEnter={e => (e.currentTarget.style.background = '#f8fafc')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              {/* Avatar */}
              <div style={{ width: 36, height: 36, borderRadius: '50%', background: avatarColor(p.name || 'U'), display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, color: '#fff', flexShrink: 0 }}>
                {initials(p.name || '?')}
              </div>

              {/* Name + title */}
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {p.name || '—'}
                </div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {p.title || 'No title'}
                </div>
              </div>

              {/* Company + location */}
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: '#374151', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {p.company || '—'}
                </div>
                {locationStr(p) && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginTop: 2 }}>
                    <MapPin size={10} style={{ color: '#94a3b8', flexShrink: 0 }} />
                    <span style={{ fontSize: 11, color: '#94a3b8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{locationStr(p)}</span>
                  </div>
                )}
              </div>

              {/* Email */}
              <div style={{ minWidth: 0 }}>
                {p.email ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <Mail size={11} style={{ color: emailColor(p.email_status), flexShrink: 0 }} />
                    <span style={{ fontSize: 12, color: '#374151', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.email}</span>
                  </div>
                ) : (
                  <span style={{ fontSize: 12, color: '#cbd5e1' }}>—</span>
                )}
              </div>

              {/* LinkedIn */}
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                {p.linkedin_url ? (
                  <a
                    href={p.linkedin_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '5px 10px', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 6, color: '#1d4ed8', fontSize: 12, fontWeight: 500, textDecoration: 'none', transition: 'background 120ms ease-out' }}
                    onMouseEnter={e => (e.currentTarget.style.background = '#dbeafe')}
                    onMouseLeave={e => (e.currentTarget.style.background = '#eff6ff')}
                  >
                    <ExternalLink size={12} />
                    LinkedIn
                  </a>
                ) : (
                  <span style={{ fontSize: 12, color: '#e2e8f0' }}>—</span>
                )}
              </div>
            </div>
          ))}

          {/* Pagination */}
          {total > 25 && (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8, padding: '14px 20px', borderTop: '1px solid #f1f5f9' }}>
              <button
                onClick={() => search(page - 1)}
                disabled={page <= 1 || loading}
                style={{ padding: '6px 14px', border: '1px solid #d1d5db', borderRadius: 6, background: '#fff', color: '#374151', fontSize: 13, cursor: page <= 1 ? 'not-allowed' : 'pointer', opacity: page <= 1 ? 0.4 : 1 }}>
                ← Prev
              </button>
              <span style={{ fontSize: 13, color: '#64748b', minWidth: 60, textAlign: 'center' }}>Page {page}</span>
              <button
                onClick={() => search(page + 1)}
                disabled={page * 25 >= total || loading}
                style={{ padding: '6px 14px', border: '1px solid #d1d5db', borderRadius: 6, background: '#fff', color: '#374151', fontSize: 13, cursor: page * 25 >= total ? 'not-allowed' : 'pointer', opacity: page * 25 >= total ? 0.4 : 1 }}>
                Next →
              </button>
            </div>
          )}
        </div>
      )}

      {/* Initial empty state */}
      {!loading && !searched && (
        <div style={{ textAlign: 'center', padding: '70px 40px', color: '#94a3b8' }}>
          <Search size={48} style={{ margin: '0 auto 16px', opacity: 0.2, display: 'block' }} />
          <div style={{ fontSize: 16, fontWeight: 500, color: '#64748b', marginBottom: 8 }}>Search for people</div>
          <div style={{ fontSize: 13, color: '#94a3b8', lineHeight: 1.7 }}>
            Type a job title like <strong style={{ color: '#374151' }}>GTM Engineer</strong> to find people with that role,<br />
            or a full name like <strong style={{ color: '#374151' }}>John Smith</strong> to look up a specific person.
          </div>
          <div style={{ marginTop: 20, display: 'flex', justifyContent: 'center', gap: 8, flexWrap: 'wrap' }}>
            {['GTM Engineer', 'VP of Sales', 'Oracle DBA', 'CFO', 'IT Director'].map(ex => (
              <button
                key={ex}
                onClick={() => { setQuery(ex); setTimeout(() => search(1), 50) }}
                style={{ padding: '6px 14px', border: '1px solid #e2e8f0', borderRadius: 20, background: '#fff', color: '#64748b', fontSize: 12, cursor: 'pointer', transition: 'all 150ms ease-out' }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = '#3b82f6'; e.currentTarget.style.color = '#3b82f6' }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.color = '#64748b' }}
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
