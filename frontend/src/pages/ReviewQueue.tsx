import { useState, useEffect } from 'react'
import { Check, X, ChevronRight, Mail, ExternalLink, Building2, RefreshCw, Loader } from 'lucide-react'
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
  created_at: string
  company_name: string
  company_domain: string
}

const scoreColor = (conf: number) =>
  conf >= 0.7 ? '#10b981' : conf >= 0.4 ? '#f59e0b' : '#ef4444'

const relativeTime = (iso: string) => {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const h = Math.floor(diff / 3_600_000)
  if (h < 1) return `${Math.floor(diff / 60_000)}m ago`
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export default function ReviewQueue() {
  const [items, setItems]       = useState<Contact[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [pushing, setPushing]   = useState<Record<number, boolean>>({})
  const [done, setDone]         = useState<Record<number, boolean>>({})
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const r = await fetch('/api/review-queue?limit=100')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data: Contact[] = await r.json()
      setItems(data)
      setSelected(data[0]?.id ?? null)
    } catch (e: any) {
      setError(e.message || 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const visible = items.filter(i => !done[i.id])
  const detail  = visible.find(i => i.id === selected) ?? null

  const approve = async (contact: Contact) => {
    setPushing(p => ({ ...p, [contact.id]: true }))
    try {
      const r = await fetch('/api/contacts/push-hubspot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(contact),
      })
      const data = await r.json()
      if (data.ok) {
        toast.success(`${contact.first_name} ${contact.last_name} — ${data.message}`)
      } else {
        toast.error(data.message || 'Push failed')
      }
    } catch {
      toast.error('Network error')
    } finally {
      setPushing(p => ({ ...p, [contact.id]: false }))
      setDone(d => ({ ...d, [contact.id]: true }))
      setItems(prev => {
        const next = prev.filter(x => x.id !== contact.id)
        setSelected(next[0]?.id ?? null)
        return next
      })
    }
  }

  const reject = (contact: Contact) => {
    setDone(d => ({ ...d, [contact.id]: true }))
    setItems(prev => {
      const next = prev.filter(x => x.id !== contact.id)
      setSelected(next[0]?.id ?? null)
      return next
    })
    toast.info(`${contact.first_name} ${contact.last_name} dismissed`)
  }

  const approveAll = async () => {
    for (const c of visible) await approve(c)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      <style>{`@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }`}</style>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: 'white', margin: 0 }}>Review Queue</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>Approve enriched contacts before pushing to HubSpot</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button onClick={load} disabled={loading} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 12px', borderRadius: 8, border: '1px solid #253047', background: 'transparent', color: '#94a3b8', fontSize: 12, cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.5 : 1 }}>
            <RefreshCw size={12} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          </button>
          <span style={{ fontSize: 12, padding: '4px 12px', borderRadius: 999, fontWeight: 500, background: 'rgba(59,130,246,0.12)', color: '#60a5fa' }}>
            {visible.length} pending
          </span>
          <button
            onClick={approveAll}
            disabled={visible.length === 0 || loading}
            style={{ padding: '8px 16px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: (visible.length === 0 || loading) ? 'default' : 'pointer', opacity: (visible.length === 0 || loading) ? 0.4 : 1 }}
          >
            Approve All ({visible.length})
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: '12px 16px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 10, fontSize: 13, color: '#f87171' }}>
          {error}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 16, height: 'calc(100vh - 200px)', minHeight: 480 }}>

        {/* Left list */}
        <div style={{ background: '#161b27', border: '1px solid #1f2d45', borderRadius: 12, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #1f2d45', fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: '#475569' }}>
            PENDING APPROVAL
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {loading ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, color: '#475569', gap: 8 }}>
                <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} /> Loading...
              </div>
            ) : visible.length === 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 200, textAlign: 'center', padding: 24 }}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>🎉</div>
                <div style={{ fontSize: 14, fontWeight: 500, color: 'white' }}>Queue cleared!</div>
                <div style={{ fontSize: 12, color: '#475569', marginTop: 4 }}>
                  {items.length === 0 ? 'No enriched contacts yet. Run a scan first.' : 'All contacts reviewed'}
                </div>
              </div>
            ) : visible.map(item => (
              <button
                key={item.id}
                onClick={() => setSelected(item.id)}
                style={{ width: '100%', padding: '14px 16px', textAlign: 'left', border: 'none', borderBottom: '1px solid #1a2438', cursor: 'pointer', background: selected === item.id ? 'rgba(59,130,246,0.1)' : 'transparent', transition: 'background 0.15s' }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: 'white' }}>{item.first_name} {item.last_name}</div>
                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{item.title || '—'}</div>
                  </div>
                  <span style={{ fontSize: 12, fontWeight: 700, padding: '2px 8px', borderRadius: 6, background: `${scoreColor(item.confidence)}18`, color: scoreColor(item.confidence), flexShrink: 0 }}>
                    {Math.round(item.confidence * 100)}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#475569' }}>
                  <Building2 size={11} /> {item.company_name}
                </div>
                {selected === item.id && (
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
                    <ChevronRight size={13} color="#3b82f6" />
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Detail panel */}
        {detail ? (
          <div style={{ background: '#161b27', border: '1px solid #1f2d45', borderRadius: 12, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style={{ padding: '20px 24px', borderBottom: '1px solid #1f2d45' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                  <div style={{ width: 48, height: 48, borderRadius: 12, background: 'linear-gradient(135deg, #3b82f6, #6366f1)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, fontWeight: 700, color: 'white', flexShrink: 0 }}>
                    {detail.first_name[0]}
                  </div>
                  <div>
                    <div style={{ fontSize: 18, fontWeight: 600, color: 'white' }}>{detail.first_name} {detail.last_name}</div>
                    <div style={{ fontSize: 13, color: '#94a3b8', marginTop: 4 }}>{detail.title || 'Unknown role'} at {detail.company_name}</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
                      {detail.is_target && (
                        <span style={{ fontSize: 12, padding: '2px 10px', borderRadius: 999, background: 'rgba(16,185,129,0.12)', color: '#34d399' }}>Target</span>
                      )}
                      <span style={{ fontSize: 12, color: '#475569' }}>via {detail.source} · {relativeTime(detail.created_at)}</span>
                    </div>
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', width: 60, height: 60, borderRadius: 12, background: `${scoreColor(detail.confidence)}12`, border: `1px solid ${scoreColor(detail.confidence)}30`, flexShrink: 0 }}>
                  <div style={{ fontSize: 22, fontWeight: 700, color: scoreColor(detail.confidence), lineHeight: 1 }}>{Math.round(detail.confidence * 100)}</div>
                  <div style={{ fontSize: 10, color: '#64748b', marginTop: 3 }}>score</div>
                </div>
              </div>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
              <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: '#475569', marginBottom: 12 }}>CONTACT DETAILS</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {[
                  { icon: Mail,         color: '#3b82f6', label: 'Email',    val: detail.email || '—' },
                  { icon: Building2,    color: '#f59e0b', label: 'Company',  val: detail.company_name },
                  { icon: ExternalLink, color: '#6366f1', label: 'LinkedIn', val: detail.linkedin_url ? 'View profile' : '—', href: detail.linkedin_url },
                  { icon: Building2,    color: '#10b981', label: 'Domain',   val: detail.company_domain || '—' },
                ].map(row => (
                  <div key={row.label} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 14, background: '#0d1117', border: '1px solid #1f2d45', borderRadius: 8 }}>
                    <row.icon size={15} color={row.color} />
                    <div>
                      <div style={{ fontSize: 11, color: '#64748b' }}>{row.label}</div>
                      {row.href ? (
                        <a href={row.href} target="_blank" rel="noreferrer" style={{ fontSize: 13, color: '#60a5fa', marginTop: 3, display: 'block' }}>{row.val}</a>
                      ) : (
                        <div style={{ fontSize: 13, color: 'white', marginTop: 3 }}>{row.val}</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ padding: '16px 24px', borderTop: '1px solid #1f2d45', display: 'flex', gap: 12 }}>
              <button
                onClick={() => reject(detail)}
                style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '10px 0', borderRadius: 8, border: '1px solid rgba(239,68,68,0.25)', background: 'rgba(239,68,68,0.08)', color: '#f87171', fontSize: 14, fontWeight: 500, cursor: 'pointer' }}
              >
                <X size={15} /> Dismiss
              </button>
              <button
                onClick={() => approve(detail)}
                disabled={pushing[detail.id]}
                style={{ flex: 2, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '10px 0', borderRadius: 8, border: 'none', background: pushing[detail.id] ? '#065f46' : '#10b981', color: 'white', fontSize: 14, fontWeight: 500, cursor: pushing[detail.id] ? 'default' : 'pointer' }}
              >
                {pushing[detail.id]
                  ? <><Loader size={14} style={{ animation: 'spin 1s linear infinite' }} /> Pushing...</>
                  : <><Check size={15} /> Approve & Push to HubSpot</>}
              </button>
            </div>
          </div>
        ) : (
          <div style={{ background: '#161b27', border: '1px solid #1f2d45', borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
              <div style={{ fontSize: 15, fontWeight: 500, color: 'white' }}>Queue is empty</div>
              <div style={{ fontSize: 13, color: '#475569', marginTop: 4 }}>
                {items.length === 0 && !loading ? 'Run a scan to populate contacts' : 'All contacts reviewed'}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
