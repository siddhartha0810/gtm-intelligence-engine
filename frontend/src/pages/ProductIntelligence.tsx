import { useState, useEffect, useCallback } from 'react'
import { PackageSearch, Search, ChevronDown, ChevronRight, X, ExternalLink, AlertCircle } from 'lucide-react'

const card: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: 24,
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}

const token = () => localStorage.getItem('token') || ''
const authHeaders = () => ({
  'Content-Type': 'application/json',
  'Authorization': `Bearer ${token()}`,
})

interface Company {
  id: string | number
  name: string
  domain?: string
  oracle_cloud_solutions?: string[]
  oracle_onprem_solutions?: string[]
  oracle_version?: string
  relationship_type?: string
  oracle_users?: number
  oracle_support_end_date?: string
  contacts_count?: number
  status?: string
  product_taxonomy?: string[]
  [key: string]: unknown
}

interface Stats {
  total: number
  cloud: number
  onprem: number
  mixed: number
}

const RELATIONSHIP_COLORS: Record<string, { bg: string; text: string }> = {
  Customer:  { bg: '#eff6ff', text: '#2563eb' },
  Partner:   { bg: '#f0fdf4', text: '#10b981' },
  Prospect:  { bg: '#fff7ed', text: '#f97316' },
}

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  Active:    { bg: '#f0fdf4', text: '#10b981' },
  Inactive:  { bg: '#f1f5f9', text: '#64748b' },
  Churned:   { bg: '#fef2f2', text: '#ef4444' },
}

const PAGE_SIZE = 25

export default function ProductIntelligence() {
  const [companies, setCompanies]     = useState<Company[]>([])
  const [stats, setStats]             = useState<Stats>({ total: 0, cloud: 0, onprem: 0, mixed: 0 })
  const [allProducts, setAllProducts] = useState<string[]>([])
  const [search, setSearch]           = useState('')
  const [productFilter, setProductFilter] = useState('')
  const [page, setPage]               = useState(1)
  const [total, setTotal]             = useState(0)
  const [loading, setLoading]         = useState(true)
  const [selected, setSelected]       = useState<Company | null>(null)
  const [taxOpen, setTaxOpen]         = useState(true)

  const fetchData = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams({
      page: String(page),
      limit: String(PAGE_SIZE),
      ...(search && { search }),
      ...(productFilter && { product: productFilter }),
    })
    fetch(`/api/product-intelligence?${params}`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) {
          setCompanies(data.companies || [])
          setTotal(data.total || 0)
          setStats(data.stats || { total: 0, cloud: 0, onprem: 0, mixed: 0 })
          setAllProducts(data.products || [])
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [page, search, productFilter])

  useEffect(() => { fetchData() }, [fetchData])

  // Reset page on filter change
  useEffect(() => { setPage(1) }, [search, productFilter])

  const totalPages = Math.ceil(total / PAGE_SIZE)

  const isPastDate = (d?: string) => {
    if (!d) return false
    return new Date(d) < new Date()
  }

  const getColor = (map: Record<string, { bg: string; text: string }>, key?: string) => {
    if (!key) return { bg: '#f1f5f9', text: '#64748b' }
    return map[key] || { bg: '#f1f5f9', text: '#64748b' }
  }

  const allTaxonomy = Array.from(new Set(companies.flatMap(c => c.product_taxonomy || [])))

  return (
    <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
      {/* Main content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Header */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <PackageSearch size={22} color="#2563eb" />
            <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Product Intelligence</h1>
          </div>
          <p style={{ margin: 0, fontSize: 14, color: '#64748b' }}>Company × Oracle Product matrix</p>
        </div>

        {/* Stats row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 20 }}>
          {[
            { label: 'Total Companies', value: stats.total, color: '#2563eb', bg: '#eff6ff' },
            { label: 'Oracle Cloud',    value: stats.cloud, color: '#10b981', bg: '#f0fdf4' },
            { label: 'On-Premise',      value: stats.onprem, color: '#f97316', bg: '#fff7ed' },
            { label: 'Mixed',           value: stats.mixed, color: '#7c3aed', bg: '#fdf4ff' },
          ].map(s => (
            <div key={s.label} style={{ ...card, padding: '16px 18px' }}>
              <div style={{ fontSize: 12, color: '#64748b', marginBottom: 6, fontWeight: 500 }}>{s.label}</div>
              <div style={{ fontSize: 24, fontWeight: 700, color: s.color }}>{s.value}</div>
            </div>
          ))}
        </div>

        {/* Filter bar */}
        <div style={{ ...card, padding: '14px 18px', marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <Search size={14} color="#9ca3af" style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }} />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search company or product…"
              style={{
                width: '100%', padding: '8px 12px 8px 32px', borderRadius: 8,
                border: '1px solid #d1d5db', fontSize: 14, color: '#0f172a',
                background: '#fff', boxSizing: 'border-box', outline: 'none',
              }}
            />
          </div>
          <div style={{ position: 'relative' }}>
            <select
              value={productFilter}
              onChange={e => setProductFilter(e.target.value)}
              style={{
                padding: '8px 32px 8px 12px', borderRadius: 8, border: '1px solid #d1d5db',
                fontSize: 14, color: '#374151', background: '#fff', cursor: 'pointer',
                appearance: 'none', outline: 'none', minWidth: 180,
              }}
            >
              <option value="">All Products</option>
              {allProducts.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <ChevronDown size={14} color="#9ca3af" style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
          </div>
        </div>

        {/* Table */}
        <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                  {['Company', 'Oracle Cloud', 'On-Premise', 'Version', 'Relationship', 'Oracle Users', 'Support End', 'Contacts', 'Status'].map(h => (
                    <th key={h} style={{ padding: '11px 14px', textAlign: 'left', fontWeight: 600, color: '#374151', fontSize: 12, whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={9} style={{ padding: 32, textAlign: 'center', color: '#94a3b8' }}>Loading…</td></tr>
                ) : companies.length === 0 ? (
                  <tr><td colSpan={9} style={{ padding: 32, textAlign: 'center', color: '#94a3b8' }}>No companies found</td></tr>
                ) : companies.map((c, i) => {
                  const relColor = getColor(RELATIONSHIP_COLORS, c.relationship_type)
                  const stColor  = getColor(STATUS_COLORS, c.status)
                  const past     = isPastDate(c.oracle_support_end_date)
                  return (
                    <tr
                      key={c.id ?? i}
                      onClick={() => setSelected(c)}
                      style={{
                        borderBottom: '1px solid #f1f5f9', cursor: 'pointer',
                        background: selected?.id === c.id ? '#eff6ff' : '#fff',
                        transition: 'background 0.1s',
                      }}
                      onMouseEnter={e => { if (selected?.id !== c.id) (e.currentTarget as HTMLTableRowElement).style.background = '#f8fafc' }}
                      onMouseLeave={e => { if (selected?.id !== c.id) (e.currentTarget as HTMLTableRowElement).style.background = '#fff' }}
                    >
                      <td style={{ padding: '10px 14px' }}>
                        <div style={{ fontWeight: 600, color: '#0f172a' }}>{c.name}</div>
                        {c.domain && <div style={{ fontSize: 11, color: '#64748b', display: 'flex', alignItems: 'center', gap: 3 }}><ExternalLink size={10} />{c.domain}</div>}
                      </td>
                      <td style={{ padding: '10px 14px', maxWidth: 160 }}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {(c.oracle_cloud_solutions || []).slice(0, 2).map(s => (
                            <span key={s} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#eff6ff', color: '#2563eb', fontWeight: 500 }}>{s}</span>
                          ))}
                          {(c.oracle_cloud_solutions || []).length > 2 && (
                            <span style={{ fontSize: 11, color: '#94a3b8' }}>+{(c.oracle_cloud_solutions || []).length - 2}</span>
                          )}
                        </div>
                      </td>
                      <td style={{ padding: '10px 14px', maxWidth: 160 }}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {(c.oracle_onprem_solutions || []).slice(0, 2).map(s => (
                            <span key={s} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#fff7ed', color: '#f97316', fontWeight: 500 }}>{s}</span>
                          ))}
                          {(c.oracle_onprem_solutions || []).length > 2 && (
                            <span style={{ fontSize: 11, color: '#94a3b8' }}>+{(c.oracle_onprem_solutions || []).length - 2}</span>
                          )}
                        </div>
                      </td>
                      <td style={{ padding: '10px 14px', color: '#374151' }}>{c.oracle_version || '—'}</td>
                      <td style={{ padding: '10px 14px' }}>
                        {c.relationship_type ? (
                          <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, fontWeight: 600, background: relColor.bg, color: relColor.text }}>{c.relationship_type}</span>
                        ) : '—'}
                      </td>
                      <td style={{ padding: '10px 14px', color: '#374151', textAlign: 'right' }}>{c.oracle_users?.toLocaleString() || '—'}</td>
                      <td style={{ padding: '10px 14px' }}>
                        {c.oracle_support_end_date ? (
                          <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: past ? '#ef4444' : '#374151', fontWeight: past ? 600 : 400 }}>
                            {past && <AlertCircle size={12} />}
                            {new Date(c.oracle_support_end_date).toLocaleDateString()}
                          </span>
                        ) : '—'}
                      </td>
                      <td style={{ padding: '10px 14px', color: '#374151', textAlign: 'right' }}>{c.contacts_count ?? '—'}</td>
                      <td style={{ padding: '10px 14px' }}>
                        {c.status ? (
                          <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, fontWeight: 600, background: stColor.bg, color: stColor.text }}>{c.status}</span>
                        ) : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderTop: '1px solid #e2e8f0' }}>
              <span style={{ fontSize: 13, color: '#64748b' }}>
                {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  style={{ padding: '6px 14px', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', cursor: page === 1 ? 'not-allowed' : 'pointer', fontSize: 13, opacity: page === 1 ? 0.5 : 1 }}
                >
                  Prev
                </button>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  style={{ padding: '6px 14px', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', cursor: page === totalPages ? 'not-allowed' : 'pointer', fontSize: 13, opacity: page === totalPages ? 0.5 : 1 }}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Taxonomy sidebar */}
      <div style={{ width: 220, flexShrink: 0 }}>
        <div style={{ ...card, padding: '14px 16px' }}>
          <button
            onClick={() => setTaxOpen(v => !v)}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', background: 'none', border: 'none', cursor: 'pointer', padding: 0, marginBottom: taxOpen ? 12 : 0 }}
          >
            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>Product Taxonomy</span>
            {taxOpen ? <ChevronDown size={14} color="#64748b" /> : <ChevronRight size={14} color="#64748b" />}
          </button>
          {taxOpen && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {allTaxonomy.length === 0 && (
                <span style={{ fontSize: 12, color: '#94a3b8' }}>No taxonomy data</span>
              )}
              {allTaxonomy.map(t => (
                <span
                  key={t}
                  onClick={() => setProductFilter(productFilter === t ? '' : t)}
                  style={{
                    fontSize: 11, padding: '4px 10px', borderRadius: 999, cursor: 'pointer',
                    background: productFilter === t ? '#2563eb' : '#f1f5f9',
                    color: productFilter === t ? '#fff' : '#374151',
                    fontWeight: productFilter === t ? 600 : 400,
                    border: '1px solid', borderColor: productFilter === t ? '#2563eb' : '#e2e8f0',
                    transition: 'all 0.1s',
                  }}
                >
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Slide-over detail panel */}
      {selected && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 50, display: 'flex', justifyContent: 'flex-end',
          }}
          onClick={e => { if (e.target === e.currentTarget) setSelected(null) }}
        >
          <div style={{ position: 'absolute', inset: 0, background: 'rgba(15,23,42,0.3)' }} onClick={() => setSelected(null)} />
          <div style={{
            position: 'relative', width: 460, height: '100%', background: '#fff',
            boxShadow: '-4px 0 24px rgba(0,0,0,0.12)', overflowY: 'auto', zIndex: 51,
          }}>
            <div style={{ padding: '20px 24px', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
              <div>
                <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: '#0f172a' }}>{selected.name}</h2>
                {selected.domain && <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>{selected.domain}</div>}
              </div>
              <button onClick={() => setSelected(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280', padding: 4 }}>
                <X size={20} />
              </button>
            </div>
            <div style={{ padding: '20px 24px' }}>
              {Object.entries(selected).filter(([k]) => !['id', 'name', 'domain'].includes(k)).map(([key, val]) => {
                if (val == null || val === '') return null
                const label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
                const display = Array.isArray(val) ? (val as string[]).join(', ') || '—' : String(val)
                return (
                  <div key={key} style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
                    <div style={{ fontSize: 14, color: '#0f172a', wordBreak: 'break-word' }}>{display}</div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
