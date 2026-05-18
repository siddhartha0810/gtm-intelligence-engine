import { useState, useRef, useEffect, useCallback } from 'react'
import { Search, Download, ArrowUpRight, MoreHorizontal, Zap, Users, Filter, Send, Eye, UserX, Trash2, RefreshCw } from 'lucide-react'
import { toast } from '../components/Toast'

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
}

const CO_MENU = [
  { icon: Eye, label: 'View details', color: '#94a3b8' },
  { icon: Send, label: 'Send to enrichment', color: '#3b82f6' },
  { icon: ArrowUpRight, label: 'View signals', color: '#f59e0b' },
  { icon: UserX, label: 'Exclude company', color: '#f59e0b' },
  { icon: Trash2, label: 'Delete', color: '#ef4444' },
]

function CompanyMenu({ onClose, anchorRef }: { onClose: () => void; anchorRef: React.RefObject<HTMLButtonElement | null> }) {
  const menuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node) && !anchorRef.current?.contains(e.target as Node)) onClose() }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [onClose, anchorRef])
  const rect = anchorRef.current?.getBoundingClientRect()
  return (
    <div ref={menuRef} style={{ position: 'fixed', top: rect ? rect.bottom + 4 : 0, right: rect ? window.innerWidth - rect.right : 0, zIndex: 1000, background: '#1c2333', border: '1px solid #253047', borderRadius: 10, padding: '6px 0', minWidth: 190, boxShadow: '0 8px 32px rgba(0,0,0,0.4)' }}>
      {CO_MENU.map((item, i) => (
        <button key={i} onClick={onClose} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px', background: 'none', border: 'none', cursor: 'pointer', color: item.color, fontSize: 13, textAlign: 'left', borderTop: i === CO_MENU.length - 1 ? '1px solid #253047' : 'none', marginTop: i === CO_MENU.length - 1 ? 4 : 0 }}
          onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
          onMouseLeave={e => (e.currentTarget.style.background = 'none')}>
          <item.icon size={13} color={item.color} />{item.label}
        </button>
      ))}
    </div>
  )
}

const PHASES = ['All', 'Implementing', 'Evaluating', 'Researching', 'Hiring', 'Live']

// Map backend phase strings (lowercase) to display labels
const normalisePhase = (p: string): string => {
  const m: Record<string, string> = { implementing: 'Implementing', evaluating: 'Evaluating', researching: 'Researching', hiring: 'Hiring', live: 'Live' }
  return m[p?.toLowerCase()] ?? (p ? p.charAt(0).toUpperCase() + p.slice(1) : 'Unknown')
}

const scoreColor = (s: number) => s >= 80 ? '#10b981' : s >= 65 ? '#f59e0b' : '#ef4444'
const phaseColor = (p: string) => p === 'Implementing' ? { bg: 'rgba(59,130,246,0.12)', color: '#60a5fa' } : p === 'Evaluating' ? { bg: 'rgba(99,102,241,0.12)', color: '#a5b4fc' } : { bg: 'rgba(107,114,128,0.15)', color: '#9ca3af' }

export default function Companies() {
  const [companies, setCompanies] = useState<Company[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [phase, setPhase] = useState('All')
  const [selected, setSelected] = useState<number[]>([])
  const [sortKey, setSortKey] = useState('score')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [openMenu, setOpenMenu] = useState<number | null>(null)
  const menuRefs = useRef<Map<number, HTMLButtonElement>>(new Map())

  const fetchCompanies = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/companies?show_all=1')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      // Map backend fields to UI shape
      const mapped: Company[] = data.map((c: Record<string, unknown>) => ({
        id:       Number(c.id),
        name:     String(c.name || ''),
        industry: String(c.industry || '—'),
        size:     String(c.size || '—'),
        score:    Math.round(Number(c.priority_score ?? c.signal_count ?? 0)),
        phase:    normalisePhase(((c.phases as string[]) || [])[0] || String(c.phase || 'Researching')),
        signals:  Number(c.signal_count ?? 0),
        contacts: Number(c.contact_count ?? 0),
        location: String(c.location || 'UK'),
        source:   ((c.sources as string[]) || [])[0] || 'Oracle Scan',
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
    .filter(c => c.name.toLowerCase().includes(search.toLowerCase()) || c.industry.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      const d = sortDir === 'desc' ? -1 : 1
      if (sortKey === 'score') return (b.score - a.score) * d
      if (sortKey === 'name') return a.name.localeCompare(b.name) * d
      if (sortKey === 'signals') return (b.signals - a.signals) * d
      return 0
    })

  const toggleSort = (k: string) => { if (sortKey === k) setSortDir(d => d === 'desc' ? 'asc' : 'desc'); else { setSortKey(k); setSortDir('desc') } }
  const toggleSelect = (id: number) => setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id])
  const allSelected = filtered.length > 0 && filtered.every(c => selected.includes(c.id))

  const thStyle: React.CSSProperties = { padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#475569', letterSpacing: '0.03em', cursor: 'pointer', whiteSpace: 'nowrap' }
  const tdStyle: React.CSSProperties = { padding: '13px 16px', fontSize: 13, verticalAlign: 'middle' }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: 'white', margin: 0 }}>Companies</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
            {loading ? 'Loading...' : `${companies.length} tracked · ${companies.filter(c => c.phase === 'Implementing').length} implementing Oracle`}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {selected.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, color: '#64748b' }}>{selected.length} selected</span>
              <button
                onClick={async () => {
                  let ok = 0
                  for (const id of selected) {
                    try {
                      const r = await fetch(`/api/company/${id}/contacts/enrich`, { method: 'POST' })
                      if (r.ok) ok++
                    } catch {}
                  }
                  toast.success(`Enrichment started for ${ok}/${selected.length} companies`)
                  setSelected([])
                }}
                style={{ padding: '7px 14px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>
                Enrich Selected
              </button>
              <button onClick={() => setSelected([])} style={{ padding: '7px 14px', borderRadius: 8, border: '1px solid rgba(239,68,68,0.3)', background: 'rgba(239,68,68,0.1)', color: '#f87171', fontSize: 13, cursor: 'pointer' }}>Clear</button>
            </div>
          )}
          <button onClick={fetchCompanies} title="Refresh from database" style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: '1px solid #253047', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}
            onMouseEnter={e => e.currentTarget.style.borderColor = '#3b82f6'}
            onMouseLeave={e => e.currentTarget.style.borderColor = '#253047'}>
            <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          </button>
          <a href="/export/csv/all" download style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: '1px solid #253047', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer', textDecoration: 'none' }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = '#3b82f6'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = '#253047'}>
            <Download size={13} /> Export
          </a>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ position: 'relative', width: 320 }}>
          <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#475569' }} />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search companies, industries..."
            style={{ width: '100%', padding: '8px 12px 8px 36px', borderRadius: 8, background: '#161b27', border: '1px solid #253047', color: '#e2e8f0', fontSize: 13, outline: 'none' }}
          />
        </div>

        <div style={{ display: 'flex', padding: 4, borderRadius: 8, background: '#161b27', border: '1px solid #253047', gap: 2 }}>
          {PHASES.map(p => (
            <button
              key={p}
              onClick={() => setPhase(p)}
              style={{ padding: '5px 14px', borderRadius: 6, border: 'none', fontSize: 13, fontWeight: 500, cursor: 'pointer', background: phase === p ? '#3b82f6' : 'transparent', color: phase === p ? 'white' : '#64748b' }}
            >
              {p}
            </button>
          ))}
        </div>

        <button
          onClick={() => toast.info('Advanced filters coming soon')}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8, border: '1px solid #253047', background: 'transparent', color: '#64748b', fontSize: 13, cursor: 'pointer' }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = '#3b82f6'; e.currentTarget.style.color = '#94a3b8' }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = '#253047'; e.currentTarget.style.color = '#64748b' }}>
          <Filter size={13} /> More filters
        </button>
      </div>

      {/* Table */}
      <div style={{ border: '1px solid #1f2d45', borderRadius: 12, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#161b27', borderBottom: '1px solid #1f2d45' }}>
              <th style={{ ...thStyle, width: 44, cursor: 'default' }}>
                <input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? [] : filtered.map(c => c.id))} style={{ accentColor: '#3b82f6' }} />
              </th>
              <th style={thStyle} onClick={() => toggleSort('name')}>Company {sortKey === 'name' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</th>
              <th style={thStyle}>Industry</th>
              <th style={thStyle}>Phase</th>
              <th style={thStyle} onClick={() => toggleSort('score')}>Score {sortKey === 'score' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</th>
              <th style={thStyle} onClick={() => toggleSort('signals')}>Signals {sortKey === 'signals' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</th>
              <th style={thStyle}>Contacts</th>
              <th style={{ ...thStyle, cursor: 'default', width: 70 }}></th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={8} style={{ padding: '40px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>Loading companies from database...</td></tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={8} style={{ padding: '40px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>No companies found. Run the Oracle Intent Engine to populate data.</td></tr>
            )}
            {!loading && filtered.map((c, i) => (
              <tr
                key={c.id}
                style={{ background: selected.includes(c.id) ? 'rgba(59,130,246,0.06)' : i % 2 === 0 ? '#0d1117' : '#111827', borderBottom: '1px solid #1a2438', cursor: 'pointer' }}
              >
                <td style={tdStyle}>
                  <input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggleSelect(c.id)} onClick={e => e.stopPropagation()} style={{ accentColor: '#3b82f6' }} />
                </td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{ width: 32, height: 32, borderRadius: 8, background: 'rgba(59,130,246,0.12)', color: '#60a5fa', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 13, flexShrink: 0 }}>
                      {c.name[0]}
                    </div>
                    <div>
                      <div style={{ fontWeight: 500, color: 'white' }}>{c.name}</div>
                      <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{c.location} · {c.size}</div>
                    </div>
                  </div>
                </td>
                <td style={{ ...tdStyle, color: '#94a3b8' }}>{c.industry}</td>
                <td style={tdStyle}>
                  <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, fontWeight: 500, background: phaseColor(c.phase).bg, color: phaseColor(c.phase).color }}>
                    {c.phase}
                  </span>
                </td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, padding: '2px 8px', borderRadius: 6, background: `${scoreColor(c.score)}18`, color: scoreColor(c.score) }}>{c.score}</span>
                    <div style={{ width: 60, height: 5, borderRadius: 999, background: '#1f2d45', overflow: 'hidden' }}>
                      <div style={{ width: `${c.score}%`, height: '100%', borderRadius: 999, background: scoreColor(c.score) }} />
                    </div>
                  </div>
                </td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#94a3b8', fontSize: 13 }}>
                    <Zap size={12} color="#f59e0b" /> {c.signals}
                  </div>
                </td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#94a3b8', fontSize: 13 }}>
                    <Users size={12} color="#6366f1" /> {c.contacts}
                  </div>
                </td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', gap: 2 }}>
                    <button title="View signals" onClick={() => toast.info(`Viewing signals for ${c.name}`)} style={{ width: 28, height: 28, borderRadius: 6, border: 'none', background: 'transparent', cursor: 'pointer', color: '#475569', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                      onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.08)'; e.currentTarget.style.color = '#e2e8f0' }}
                      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#475569' }}>
                      <ArrowUpRight size={13} />
                    </button>
                    <button
                      ref={el => { if (el) menuRefs.current.set(c.id, el) }}
                      title="More actions"
                      onClick={() => setOpenMenu(openMenu === c.id ? null : c.id)}
                      style={{ width: 28, height: 28, borderRadius: 6, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', background: openMenu === c.id ? 'rgba(59,130,246,0.15)' : 'transparent', color: openMenu === c.id ? '#60a5fa' : '#475569' }}
                      onMouseEnter={e => { if (openMenu !== c.id) { e.currentTarget.style.background = 'rgba(255,255,255,0.08)'; e.currentTarget.style.color = '#e2e8f0' } }}
                      onMouseLeave={e => { if (openMenu !== c.id) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#475569' } }}>
                      <MoreHorizontal size={14} />
                    </button>
                    {openMenu === c.id && <CompanyMenu onClose={() => setOpenMenu(null)} anchorRef={{ current: menuRefs.current.get(c.id) ?? null }} />}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: '#161b27', borderTop: '1px solid #1f2d45', fontSize: 12, color: '#475569' }}>
          <span>Showing {filtered.length} of {companies.length} companies</span>
          <div style={{ display: 'flex', gap: 4 }}>
            {['← Prev', '1', 'Next →'].map((l, i) => (
              <button key={l} style={{ padding: '4px 10px', borderRadius: 6, border: 'none', background: i === 1 ? '#3b82f6' : 'transparent', color: i === 1 ? 'white' : '#475569', cursor: 'pointer', fontSize: 12 }}>{l}</button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
