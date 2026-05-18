import { useState, useEffect, useCallback } from 'react'
import { Filter, RefreshCw, Search, Eye } from 'lucide-react'
import { toast } from '../components/Toast'

interface AuditLog {
  id: number
  timestamp: string
  user_email: string
  action: string
  entity_type: string
  entity_id: string | number
  old_value: unknown
  new_value: unknown
}

const ACTION_COLORS: Record<string, { bg: string; color: string }> = {
  create:  { bg: 'rgba(16,185,129,0.12)', color: '#34d399' },
  update:  { bg: 'rgba(59,130,246,0.12)', color: '#60a5fa' },
  delete:  { bg: 'rgba(239,68,68,0.12)', color: '#f87171' },
  login:   { bg: 'rgba(245,158,11,0.12)', color: '#fbbf24' },
  export:  { bg: 'rgba(99,102,241,0.12)', color: '#a5b4fc' },
  import:  { bg: 'rgba(236,72,153,0.12)', color: '#f472b6' },
}

function actionBadge(action: string) {
  const key = action.split('_')[0]?.toLowerCase()
  return ACTION_COLORS[key] ?? { bg: 'rgba(107,114,128,0.12)', color: '#9ca3af' }
}

function JsonPreview({ value, maxLen = 80 }: { value: unknown; maxLen?: number }) {
  const [expanded, setExpanded] = useState(false)
  if (value == null) return <span style={{ color: '#475569' }}>—</span>
  const str = typeof value === 'string' ? value : JSON.stringify(value)
  const truncated = str.length > maxLen && !expanded
  return (
    <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#94a3b8', wordBreak: 'break-all' }}>
      {truncated ? str.slice(0, maxLen) + '…' : str}
      {str.length > maxLen && (
        <button onClick={() => setExpanded(e => !e)} style={{ marginLeft: 6, background: 'none', border: 'none', cursor: 'pointer', color: '#3b82f6', fontSize: 11, padding: 0 }}>
          {expanded ? 'less' : 'more'}
        </button>
      )}
    </span>
  )
}

const PAGE_SIZE = 200

export default function AuditLogs() {
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [loading, setLoading] = useState(true)
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [total, setTotal] = useState(0)

  // Filters
  const [entityType, setEntityType] = useState('')
  const [action, setAction] = useState('')
  const [userEmail, setUserEmail] = useState('')

  const ENTITY_TYPES = ['', 'Company', 'Contact', 'Event', 'TechProfile', 'User', 'ImportBatch', 'ManufacturerContact']

  const buildUrl = useCallback((off: number) => {
    const params = new URLSearchParams()
    params.set('limit', String(PAGE_SIZE))
    params.set('offset', String(off))
    if (entityType) params.set('entity_type', entityType)
    if (action) params.set('action', action)
    if (userEmail) params.set('user_email', userEmail)
    return `/api/audit-logs?${params}`
  }, [entityType, action, userEmail])

  const load = useCallback(async (off = 0, append = false) => {
    setLoading(true)
    try {
      const r = await fetch(buildUrl(off))
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      const items: AuditLog[] = data.logs ?? data
      const tot: number = data.total ?? items.length
      setTotal(tot)
      setHasMore(off + items.length < tot)
      setLogs(prev => append ? [...prev, ...items] : items)
      setOffset(off + items.length)
    } catch { toast.error('Failed to load audit logs') } finally { setLoading(false) }
  }, [buildUrl])

  // Reload on filter change
  useEffect(() => { load(0, false) }, [load])

  const loadMore = () => { load(offset, true) }

  const thStyle: React.CSSProperties = { padding: '11px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#475569', letterSpacing: '0.03em', whiteSpace: 'nowrap' }
  const tdStyle: React.CSSProperties = { padding: '12px 16px', fontSize: 13, verticalAlign: 'middle', color: '#374151' }

  const inp: React.CSSProperties = { padding: '7px 12px 7px 12px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 13, outline: 'none' }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>Audit Logs</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
            {loading ? 'Loading...' : `${total.toLocaleString()} total entries`}
          </p>
        </div>
        <button onClick={() => load(0, false)} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#64748b', fontSize: 13 }}>
          <Filter size={14} /> Filters:
        </div>
        <select value={entityType} onChange={e => setEntityType(e.target.value)}
          style={{ ...inp, cursor: 'pointer', minWidth: 160 }}>
          <option value="">All entity types</option>
          {ENTITY_TYPES.filter(Boolean).map(et => <option key={et} value={et}>{et}</option>)}
        </select>
        <div style={{ position: 'relative' }}>
          <Search size={13} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#475569' }} />
          <input value={action} onChange={e => setAction(e.target.value)} placeholder="Action (e.g. create)"
            style={{ ...inp, paddingLeft: 30, width: 180 }} />
        </div>
        <div style={{ position: 'relative' }}>
          <Search size={13} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#475569' }} />
          <input value={userEmail} onChange={e => setUserEmail(e.target.value)} placeholder="User email"
            style={{ ...inp, paddingLeft: 30, width: 200 }} />
        </div>
        {(entityType || action || userEmail) && (
          <button onClick={() => { setEntityType(''); setAction(''); setUserEmail('') }}
            style={{ padding: '7px 12px', borderRadius: 8, border: '1px solid rgba(239,68,68,0.2)', background: 'transparent', color: '#f87171', fontSize: 13, cursor: 'pointer' }}>
            Clear filters
          </button>
        )}
      </div>

      {/* Table */}
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 860 }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                <th style={thStyle}>Timestamp</th>
                <th style={thStyle}>User</th>
                <th style={thStyle}>Action</th>
                <th style={thStyle}>Entity Type</th>
                <th style={thStyle}>Entity ID</th>
                <th style={{ ...thStyle, minWidth: 260 }}>New Value</th>
                <th style={{ ...thStyle, width: 40 }}><Eye size={13} /></th>
              </tr>
            </thead>
            <tbody>
              {loading && logs.length === 0 && (
                <tr><td colSpan={7} style={{ padding: '40px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>Loading audit logs...</td></tr>
              )}
              {!loading && logs.length === 0 && (
                <tr><td colSpan={7} style={{ padding: '40px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>No audit log entries found.</td></tr>
              )}
              {logs.map((log) => {
                const ab = actionBadge(log.action)
                const ts = new Date(log.timestamp)
                return (
                  <tr key={log.id} style={{ background: '#ffffff', borderBottom: '1px solid #f1f5f9' }}
                    onMouseEnter={e => e.currentTarget.style.background = 'rgba(37,99,235,0.04)'}
                    onMouseLeave={e => e.currentTarget.style.background = '#ffffff'}>
                    <td style={{ ...tdStyle, whiteSpace: 'nowrap' }}>
                      <div style={{ fontSize: 13, color: '#94a3b8' }}>{ts.toLocaleDateString()}</div>
                      <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{ts.toLocaleTimeString()}</div>
                    </td>
                    <td style={{ ...tdStyle, fontSize: 12, color: '#94a3b8', maxWidth: 180 }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{log.user_email || '—'}</div>
                    </td>
                    <td style={tdStyle}>
                      <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, background: ab.bg, color: ab.color, whiteSpace: 'nowrap' }}>{log.action}</span>
                    </td>
                    <td style={{ ...tdStyle, color: '#64748b', fontSize: 12 }}>{log.entity_type || '—'}</td>
                    <td style={{ ...tdStyle, color: '#475569', fontSize: 12, fontFamily: 'monospace' }}>{log.entity_id ?? '—'}</td>
                    <td style={tdStyle}><JsonPreview value={log.new_value} /></td>
                    <td style={tdStyle}>
                      <button onClick={() => {
                        const msg = JSON.stringify({ action: log.action, entity_type: log.entity_type, entity_id: log.entity_id, old_value: log.old_value, new_value: log.new_value }, null, 2)
                        alert(msg)
                      }} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#475569', padding: 4, borderRadius: 4 }}
                        onMouseEnter={e => { e.currentTarget.style.color = '#60a5fa'; e.currentTarget.style.background = 'rgba(59,130,246,0.08)' }}
                        onMouseLeave={e => { e.currentTarget.style.color = '#475569'; e.currentTarget.style.background = 'none' }}>
                        <Eye size={13} />
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', fontSize: 12, color: '#64748b' }}>
          <span>Showing {logs.length} of {total.toLocaleString()} entries</span>
          {hasMore && (
            <button onClick={loadMore} disabled={loading}
              style={{ padding: '6px 16px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1 }}>
              {loading ? 'Loading...' : `Load more (${total - logs.length} remaining)`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
