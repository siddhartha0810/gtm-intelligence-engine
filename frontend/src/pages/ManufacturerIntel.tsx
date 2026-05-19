import { useState, useEffect } from 'react'
import { Plus, Trash2, Edit2, X, Search, Link, RefreshCw } from 'lucide-react'
import { toast } from '../components/Toast'

const authH = (): Record<string, string> => ({
  'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
  'Content-Type': 'application/json',
})

interface MfgContact {
  id: number
  first_name: string
  last_name: string
  email: string
  phone: string
  company: string
  job_title: string
  oracle_alignment: string
  oracle_department: string
  oracle_team: string
  linkedin_url: string
  linked_companies: number
}

const thStyle: React.CSSProperties = { padding: '11px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#475569', letterSpacing: '0.03em', whiteSpace: 'nowrap' }
const tdStyle: React.CSSProperties = { padding: '13px 16px', fontSize: 13, verticalAlign: 'middle', color: '#374151' }

function SlideOver({ contact, onClose, onSave }: { contact: Partial<MfgContact> | null; onClose: () => void; onSave: () => void }) {
  const isEdit = !!(contact?.id)
  const [form, setForm] = useState({
    first_name: contact?.first_name ?? '',
    last_name: contact?.last_name ?? '',
    email: contact?.email ?? '',
    phone: contact?.phone ?? '',
    company: contact?.company ?? '',
    job_title: contact?.job_title ?? '',
    oracle_alignment: contact?.oracle_alignment ?? '',
    oracle_department: contact?.oracle_department ?? '',
    oracle_team: contact?.oracle_team ?? '',
    linkedin_url: contact?.linkedin_url ?? '',
  })
  const [saving, setSaving] = useState(false)
  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const save = async () => {
    if (!form.first_name.trim() || !form.last_name.trim()) { toast.error('First and last name are required'); return }
    setSaving(true)
    try {
      const url = isEdit ? `/api/manufacturer-contacts/${contact!.id}` : '/api/manufacturer-contacts'
      const r = await fetch(url, { method: isEdit ? 'PATCH' : 'POST', headers: authH(), body: JSON.stringify(form) })
      if (!r.ok) throw new Error()
      toast.success(isEdit ? 'Contact updated' : 'Contact created')
      onSave()
    } catch { toast.error('Save failed') } finally { setSaving(false) }
  }

  const inp: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 13, outline: 'none', boxSizing: 'border-box' }
  const lbl: React.CSSProperties = { fontSize: 12, color: '#64748b', fontWeight: 600, letterSpacing: '0.04em', display: 'block', marginBottom: 6 }
  const row2: React.CSSProperties = { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 500, display: 'flex', justifyContent: 'flex-end' }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)' }} />
      <div style={{ position: 'relative', width: 500, background: '#ffffff', borderLeft: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column', overflow: 'hidden', zIndex: 1, boxShadow: '-4px 0 24px rgba(0,0,0,0.08)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px', borderBottom: '1px solid #e2e8f0' }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#0f172a' }}>{isEdit ? 'Edit Manufacturer Contact' : 'New Manufacturer Contact'}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', padding: 4 }}><X size={18} /></button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={row2}>
            <div><label style={lbl}>First Name *</label><input style={inp} value={form.first_name} onChange={e => set('first_name', e.target.value)} /></div>
            <div><label style={lbl}>Last Name *</label><input style={inp} value={form.last_name} onChange={e => set('last_name', e.target.value)} /></div>
          </div>
          <div style={row2}>
            <div><label style={lbl}>Email</label><input style={inp} type="email" value={form.email} onChange={e => set('email', e.target.value)} /></div>
            <div><label style={lbl}>Phone</label><input style={inp} value={form.phone} onChange={e => set('phone', e.target.value)} /></div>
          </div>
          <div style={row2}>
            <div><label style={lbl}>Company</label><input style={inp} value={form.company} onChange={e => set('company', e.target.value)} /></div>
            <div><label style={lbl}>Job Title</label><input style={inp} value={form.job_title} onChange={e => set('job_title', e.target.value)} /></div>
          </div>
          <div style={row2}>
            <div><label style={lbl}>Oracle Alignment</label><input style={inp} value={form.oracle_alignment} onChange={e => set('oracle_alignment', e.target.value)} placeholder="e.g. Partner, Reseller" /></div>
            <div><label style={lbl}>Oracle Department</label><input style={inp} value={form.oracle_department} onChange={e => set('oracle_department', e.target.value)} /></div>
          </div>
          <div><label style={lbl}>Oracle Team</label><input style={inp} value={form.oracle_team} onChange={e => set('oracle_team', e.target.value)} /></div>
          <div><label style={lbl}>LinkedIn URL</label><input style={inp} type="url" value={form.linkedin_url} onChange={e => set('linkedin_url', e.target.value)} placeholder="https://linkedin.com/in/..." /></div>
        </div>
        <div style={{ padding: '16px 24px', borderTop: '1px solid #e2e8f0', display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '8px 20px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>Cancel</button>
          <button onClick={save} disabled={saving} style={{ padding: '8px 20px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.7 : 1 }}>{saving ? 'Saving...' : 'Save Contact'}</button>
        </div>
      </div>
    </div>
  )
}

function LinkCompanyRow({ contactId, onDone }: { contactId: number; onDone: () => void }) {
  const [companyId, setCompanyId] = useState('')
  const [linking, setLinking] = useState(false)

  const link = async () => {
    if (!companyId.trim()) { toast.error('Enter a company ID'); return }
    setLinking(true)
    try {
      const r = await fetch(`/api/manufacturer-contacts/${contactId}/link/${companyId}`, { method: 'POST', headers: authH() })
      if (!r.ok) throw new Error()
      toast.success('Company linked')
      onDone()
    } catch { toast.error('Link failed') } finally { setLinking(false) }
  }

  return (
    <div style={{ display: 'flex', gap: 6, marginTop: 4 }} onClick={e => e.stopPropagation()}>
      <input value={companyId} onChange={e => setCompanyId(e.target.value)} placeholder="Company ID" type="number"
        style={{ width: 120, padding: '5px 10px', borderRadius: 6, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 12, outline: 'none' }} />
      <button onClick={link} disabled={linking} style={{ padding: '5px 12px', borderRadius: 6, border: 'none', background: '#3b82f6', color: 'white', fontSize: 12, cursor: linking ? 'not-allowed' : 'pointer', opacity: linking ? 0.7 : 1 }}>Link</button>
      <button onClick={onDone} style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid #e2e8f0', background: 'transparent', color: '#64748b', fontSize: 12, cursor: 'pointer' }}><X size={12} /></button>
    </div>
  )
}

export default function ManufacturerIntel() {
  const [contacts, setContacts] = useState<MfgContact[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [slideOver, setSlideOver] = useState<Partial<MfgContact> | null | false>(false)
  const [linkingId, setLinkingId] = useState<number | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const r = await fetch('/api/manufacturer-contacts', { headers: authH() })
      if (!r.ok) throw new Error()
      setContacts(await r.json())
    } catch { toast.error('Failed to load manufacturer contacts') } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const deleteContact = async (c: MfgContact) => {
    if (!window.confirm(`Delete ${c.first_name} ${c.last_name}?`)) return
    try {
      const r = await fetch(`/api/manufacturer-contacts/${c.id}`, { method: 'DELETE', headers: authH() })
      if (!r.ok) throw new Error()
      toast.success('Contact deleted')
      setContacts(cs => cs.filter(x => x.id !== c.id))
    } catch { toast.error('Delete failed') }
  }

  const filtered = contacts.filter(c =>
    `${c.first_name} ${c.last_name}`.toLowerCase().includes(search.toLowerCase()) ||
    (c.company || '').toLowerCase().includes(search.toLowerCase()) ||
    (c.job_title || '').toLowerCase().includes(search.toLowerCase())
  )

  const AVATAR_COLORS = ['#3b82f6', '#6366f1', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']

  const alignBadge = (a: string) => {
    if (!a) return null
    const colors: Record<string, { bg: string; color: string }> = {
      Partner: { bg: 'rgba(59,130,246,0.12)', color: '#60a5fa' },
      Reseller: { bg: 'rgba(16,185,129,0.12)', color: '#34d399' },
      Distributor: { bg: 'rgba(245,158,11,0.12)', color: '#fbbf24' },
    }
    return colors[a] ?? { bg: 'rgba(107,114,128,0.12)', color: '#9ca3af' }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      {slideOver !== false && <SlideOver contact={slideOver} onClose={() => setSlideOver(false)} onSave={() => { setSlideOver(false); load() }} />}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>Manufacturer Intel</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>{loading ? 'Loading...' : `${contacts.length} manufacturer contacts`}</p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={load} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>
            <RefreshCw size={13} />
          </button>
          <button onClick={() => setSlideOver({})} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>
            <Plus size={14} /> New Contact
          </button>
        </div>
      </div>

      <div style={{ position: 'relative', maxWidth: 380 }}>
        <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#475569' }} />
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search contacts, companies..."
          style={{ width: '100%', padding: '8px 12px 8px 36px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 13, outline: 'none', boxSizing: 'border-box' }} />
      </div>

      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 820 }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                <th style={thStyle}>Contact</th>
                <th style={thStyle}>Company</th>
                <th style={thStyle}>Title</th>
                <th style={thStyle}>Email</th>
                <th style={thStyle}>Alignment</th>
                <th style={thStyle}>Department</th>
                <th style={thStyle}>Linked Co.</th>
                <th style={{ ...thStyle, width: 130 }}></th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={8} style={{ padding: '40px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>Loading contacts...</td></tr>}
              {!loading && filtered.length === 0 && <tr><td colSpan={8} style={{ padding: '40px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>No manufacturer contacts found.</td></tr>}
              {!loading && filtered.map((c, i) => {
                const ab = alignBadge(c.oracle_alignment)
                const avatarColor = AVATAR_COLORS[i % AVATAR_COLORS.length]
                return (
                  <tr key={c.id} style={{ background: '#ffffff', borderBottom: '1px solid #f1f5f9' }}
                    onMouseEnter={e => e.currentTarget.style.background = 'rgba(37,99,235,0.04)'}
                    onMouseLeave={e => e.currentTarget.style.background = '#ffffff'}>
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ width: 34, height: 34, borderRadius: '50%', background: avatarColor, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, color: 'white', flexShrink: 0 }}>
                          {(c.first_name || '?')[0].toUpperCase()}
                        </div>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 500, color: '#0f172a' }}>{c.first_name} {c.last_name}</div>
                          {c.linkedin_url && <a href={c.linkedin_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: '#3b82f6', textDecoration: 'none' }} onClick={e => e.stopPropagation()}>LinkedIn ↗</a>}
                        </div>
                      </div>
                    </td>
                    <td style={{ ...tdStyle, color: '#94a3b8' }}>{c.company || '—'}</td>
                    <td style={{ ...tdStyle, color: '#94a3b8', maxWidth: 160 }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.job_title || '—'}</div>
                    </td>
                    <td style={{ ...tdStyle, fontSize: 12, color: '#64748b' }}>{c.email || '—'}</td>
                    <td style={tdStyle}>
                      {ab ? <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, background: ab.bg, color: ab.color }}>{c.oracle_alignment}</span> : <span style={{ color: '#475569' }}>—</span>}
                    </td>
                    <td style={{ ...tdStyle, color: '#94a3b8', fontSize: 12 }}>{c.oracle_department || '—'}</td>
                    <td style={tdStyle}>
                      <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, background: 'rgba(107,114,128,0.12)', color: '#9ca3af' }}>
                        {c.linked_companies ?? 0}
                      </span>
                    </td>
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button onClick={() => setSlideOver(c)} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}
                            onMouseEnter={e => { e.currentTarget.style.borderColor = '#3b82f6'; e.currentTarget.style.color = '#60a5fa' }}
                            onMouseLeave={e => { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.color = '#94a3b8' }}>
                            <Edit2 size={11} />Edit
                          </button>
                          <button onClick={() => setLinkingId(linkingId === c.id ? null : c.id)} style={{ padding: '4px 8px', borderRadius: 6, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                            onMouseEnter={e => { e.currentTarget.style.borderColor = '#10b981'; e.currentTarget.style.color = '#34d399' }}
                            onMouseLeave={e => { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.color = '#94a3b8' }}>
                            <Link size={11} />
                          </button>
                          <button onClick={() => deleteContact(c)} style={{ padding: '4px 8px', borderRadius: 6, border: '1px solid rgba(239,68,68,0.2)', background: 'transparent', color: '#f87171', fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                            onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.08)'}
                            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                            <Trash2 size={11} />
                          </button>
                        </div>
                        {linkingId === c.id && <LinkCompanyRow contactId={c.id} onDone={() => { setLinkingId(null); load() }} />}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div style={{ padding: '12px 16px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', fontSize: 12, color: '#64748b' }}>
          {filtered.length} of {contacts.length} contacts
        </div>
      </div>
    </div>
  )
}
