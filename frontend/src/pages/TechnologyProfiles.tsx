import { useState, useEffect } from 'react'
import { Plus, Trash2, Edit2, ChevronDown, RefreshCw, X, CheckCircle2, XCircle } from 'lucide-react'
import { toast } from '../components/Toast'

interface TechProfile {
  id: number
  name: string
  description: string
  keywords: string[]
  target_websites: string[]
  oracle_products: string[]
  manufacturer_domain: string
  is_active: boolean
}

interface TaxonomyItem {
  id: number
  canonical_name: string
  aliases: string[]
  category: string
  confidence_weight: number
}

const thStyle: React.CSSProperties = { padding: '11px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#475569', letterSpacing: '0.03em', whiteSpace: 'nowrap' }
const tdStyle: React.CSSProperties = { padding: '13px 16px', fontSize: 13, verticalAlign: 'middle', color: '#374151' }

function SlideOver({ profile, onClose, onSave }: { profile: Partial<TechProfile> | null; onClose: () => void; onSave: () => void }) {
  const isEdit = !!(profile && profile.id)
  const [form, setForm] = useState({
    name: profile?.name ?? '',
    description: profile?.description ?? '',
    keywords: (profile?.keywords ?? []).join(', '),
    target_websites: (profile?.target_websites ?? []).join(', '),
    oracle_products: (profile?.oracle_products ?? []).join(', '),
    manufacturer_domain: profile?.manufacturer_domain ?? '',
  })
  const [saving, setSaving] = useState(false)

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const save = async () => {
    if (!form.name.trim()) { toast.error('Name is required'); return }
    setSaving(true)
    const body = {
      name: form.name.trim(),
      description: form.description.trim(),
      keywords: form.keywords.split(',').map(s => s.trim()).filter(Boolean),
      target_websites: form.target_websites.split(',').map(s => s.trim()).filter(Boolean),
      oracle_products: form.oracle_products.split(',').map(s => s.trim()).filter(Boolean),
      manufacturer_domain: form.manufacturer_domain.trim(),
    }
    try {
      const url = isEdit ? `/api/technology-profiles/${profile!.id}` : '/api/technology-profiles'
      const method = isEdit ? 'PATCH' : 'POST'
      const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      toast.success(isEdit ? 'Profile updated' : 'Profile created')
      onSave()
    } catch { toast.error('Save failed') } finally { setSaving(false) }
  }

  const inp: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 13, outline: 'none', boxSizing: 'border-box' }
  const lbl: React.CSSProperties = { fontSize: 12, color: '#64748b', fontWeight: 600, letterSpacing: '0.04em', display: 'block', marginBottom: 6 }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 500, display: 'flex', justifyContent: 'flex-end' }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)' }} />
      <div style={{ position: 'relative', width: 480, background: '#ffffff', borderLeft: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column', overflow: 'hidden', zIndex: 1, boxShadow: '-4px 0 24px rgba(0,0,0,0.08)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px', borderBottom: '1px solid #e2e8f0' }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#0f172a' }}>{isEdit ? 'Edit Profile' : 'New Technology Profile'}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', padding: 4 }}><X size={18} /></button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div><label style={lbl}>Name *</label><input style={inp} value={form.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Oracle ERP" /></div>
          <div><label style={lbl}>Description</label><textarea style={{ ...inp, minHeight: 80, resize: 'vertical' }} value={form.description} onChange={e => set('description', e.target.value)} placeholder="Brief description..." /></div>
          <div><label style={lbl}>Keywords (comma-separated)</label><textarea style={{ ...inp, minHeight: 72, resize: 'vertical' }} value={form.keywords} onChange={e => set('keywords', e.target.value)} placeholder="oracle, erp, cloud..." /></div>
          <div><label style={lbl}>Target Websites (comma-separated)</label><textarea style={{ ...inp, minHeight: 64, resize: 'vertical' }} value={form.target_websites} onChange={e => set('target_websites', e.target.value)} placeholder="oracle.com, netsuite.com..." /></div>
          <div><label style={lbl}>Oracle Products (comma-separated)</label><textarea style={{ ...inp, minHeight: 64, resize: 'vertical' }} value={form.oracle_products} onChange={e => set('oracle_products', e.target.value)} placeholder="Oracle EBS, NetSuite..." /></div>
          <div><label style={lbl}>Manufacturer Domain</label><input style={inp} value={form.manufacturer_domain} onChange={e => set('manufacturer_domain', e.target.value)} placeholder="oracle.com" /></div>
        </div>
        <div style={{ padding: '16px 24px', borderTop: '1px solid #e2e8f0', display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '8px 20px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>Cancel</button>
          <button onClick={save} disabled={saving} style={{ padding: '8px 20px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.7 : 1 }}>{saving ? 'Saving...' : 'Save Profile'}</button>
        </div>
      </div>
    </div>
  )
}

function TaxonomyRow({ profileId, onClose }: { profileId: number; onClose: () => void }) {
  const [items, setItems] = useState<TaxonomyItem[]>([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ canonical_name: '', aliases: '', category: '', confidence_weight: '1.0' })

  const load = async () => {
    setLoading(true)
    try {
      const r = await fetch(`/api/technology-profiles/${profileId}/taxonomy`)
      if (!r.ok) throw new Error()
      setItems(await r.json())
    } catch { toast.error('Failed to load taxonomy') } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [profileId])

  const addTaxonomy = async () => {
    if (!form.canonical_name.trim()) { toast.error('Canonical name required'); return }
    try {
      const r = await fetch(`/api/technology-profiles/${profileId}/taxonomy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ canonical_name: form.canonical_name.trim(), aliases: form.aliases.split(',').map(s => s.trim()).filter(Boolean), category: form.category.trim(), confidence_weight: parseFloat(form.confidence_weight) || 1.0 }),
      })
      if (!r.ok) throw new Error()
      toast.success('Taxonomy item added')
      setForm({ canonical_name: '', aliases: '', category: '', confidence_weight: '1.0' })
      setAdding(false)
      load()
    } catch { toast.error('Failed to add taxonomy') }
  }

  const deleteTaxonomy = async (id: number) => {
    if (!window.confirm('Delete this taxonomy item?')) return
    try {
      const r = await fetch(`/api/taxonomy/${id}`, { method: 'DELETE' })
      if (!r.ok) throw new Error()
      toast.success('Deleted')
      setItems(i => i.filter(x => x.id !== id))
    } catch { toast.error('Delete failed') }
  }

  const inp: React.CSSProperties = { padding: '6px 10px', borderRadius: 6, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 12, outline: 'none' }

  return (
    <tr>
      <td colSpan={6} style={{ padding: 0, background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
        <div style={{ padding: '14px 24px 14px 56px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: '#64748b', letterSpacing: '0.04em' }}>PRODUCT TAXONOMY</span>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => setAdding(a => !a)} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 6, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 12, cursor: 'pointer' }}><Plus size={12} />Add</button>
              <button onClick={onClose} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 6, border: '1px solid #e2e8f0', background: 'transparent', color: '#64748b', fontSize: 12, cursor: 'pointer' }}><X size={12} />Close</button>
            </div>
          </div>
          {adding && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
              <input style={{ ...inp, flex: '1 1 140px' }} value={form.canonical_name} onChange={e => setForm(f => ({ ...f, canonical_name: e.target.value }))} placeholder="Canonical name" />
              <input style={{ ...inp, flex: '2 1 160px' }} value={form.aliases} onChange={e => setForm(f => ({ ...f, aliases: e.target.value }))} placeholder="Aliases (comma-separated)" />
              <input style={{ ...inp, flex: '1 1 100px' }} value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))} placeholder="Category" />
              <input style={{ ...inp, width: 80 }} type="number" step="0.1" min="0" max="1" value={form.confidence_weight} onChange={e => setForm(f => ({ ...f, confidence_weight: e.target.value }))} placeholder="Weight" />
              <button onClick={addTaxonomy} style={{ padding: '6px 14px', borderRadius: 6, border: 'none', background: '#3b82f6', color: 'white', fontSize: 12, cursor: 'pointer' }}>Add</button>
              <button onClick={() => setAdding(false)} style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid #e2e8f0', background: 'transparent', color: '#64748b', fontSize: 12, cursor: 'pointer' }}>Cancel</button>
            </div>
          )}
          {loading ? <p style={{ fontSize: 12, color: '#475569', margin: '8px 0' }}>Loading...</p> : items.length === 0 ? <p style={{ fontSize: 12, color: '#475569', margin: '8px 0' }}>No taxonomy items yet.</p> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #1f2d45' }}>
                  {['Canonical Name', 'Aliases', 'Category', 'Weight', ''].map(h => (
                    <th key={h} style={{ padding: '6px 10px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map(item => (
                  <tr key={item.id}>
                    <td style={{ padding: '7px 10px', fontSize: 12, color: '#0f172a' }}>{item.canonical_name}</td>
                    <td style={{ padding: '7px 10px', fontSize: 12, color: '#64748b' }}>{(item.aliases || []).join(', ') || '—'}</td>
                    <td style={{ padding: '7px 10px', fontSize: 12, color: '#64748b' }}>{item.category || '—'}</td>
                    <td style={{ padding: '7px 10px', fontSize: 12, color: '#64748b' }}>{item.confidence_weight}</td>
                    <td style={{ padding: '7px 10px' }}>
                      <button onClick={() => deleteTaxonomy(item.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444', padding: 4, borderRadius: 4 }}
                        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(239,68,68,0.1)') }
                        onMouseLeave={e => (e.currentTarget.style.background = 'none') }>
                        <Trash2 size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </td>
    </tr>
  )
}

export default function TechnologyProfiles() {
  const [profiles, setProfiles] = useState<TechProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [slideOver, setSlideOver] = useState<Partial<TechProfile> | null | false>(false)
  const [expanded, setExpanded] = useState<number | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const r = await fetch('/api/technology-profiles')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setProfiles(await r.json())
    } catch { toast.error('Failed to load technology profiles') } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const toggleActive = async (p: TechProfile) => {
    try {
      const r = await fetch(`/api/technology-profiles/${p.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: !p.is_active }) })
      if (!r.ok) throw new Error()
      setProfiles(ps => ps.map(x => x.id === p.id ? { ...x, is_active: !p.is_active } : x))
      toast.success(`Profile ${!p.is_active ? 'activated' : 'deactivated'}`)
    } catch { toast.error('Update failed') }
  }

  const deleteProfile = async (p: TechProfile) => {
    if (!window.confirm(`Delete "${p.name}"?`)) return
    try {
      const r = await fetch(`/api/technology-profiles/${p.id}`, { method: 'DELETE' })
      if (!r.ok) throw new Error()
      toast.success('Profile deleted')
      setProfiles(ps => ps.filter(x => x.id !== p.id))
    } catch { toast.error('Delete failed') }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      {slideOver !== false && (
        <SlideOver profile={slideOver} onClose={() => setSlideOver(false)} onSave={() => { setSlideOver(false); load() }} />
      )}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>Technology Profiles</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
            {loading ? 'Loading...' : `${profiles.length} profiles · ${profiles.filter(p => p.is_active).length} active`}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={load} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>
            <RefreshCw size={13} />
          </button>
          <button onClick={() => setSlideOver({})} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>
            <Plus size={14} /> New Profile
          </button>
        </div>
      </div>

      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
              <th style={{ ...thStyle, width: 36 }}></th>
              <th style={thStyle}>Name</th>
              <th style={thStyle}>Description</th>
              <th style={thStyle}>Keywords</th>
              <th style={thStyle}>Products</th>
              <th style={thStyle}>Active</th>
              <th style={{ ...thStyle, width: 120 }}></th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} style={{ padding: '40px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>Loading profiles...</td></tr>}
            {!loading && profiles.length === 0 && <tr><td colSpan={7} style={{ padding: '40px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>No profiles yet. Create one to get started.</td></tr>}
            {!loading && profiles.map((p) => (
              <>
                <tr key={p.id} style={{ background: '#ffffff', borderBottom: expanded === p.id ? 'none' : '1px solid #f1f5f9' }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(37,99,235,0.04)')}
                  onMouseLeave={e => (e.currentTarget.style.background = '#ffffff')}>
                  <td style={tdStyle}>
                    <button onClick={() => setExpanded(expanded === p.id ? null : p.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#475569', padding: 4, display: 'flex', alignItems: 'center' }}>
                      <ChevronDown size={14} style={{ transform: expanded === p.id ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
                    </button>
                  </td>
                  <td style={tdStyle}>
                    <div style={{ fontWeight: 500, color: '#0f172a' }}>{p.name}</div>
                    {p.manufacturer_domain && <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{p.manufacturer_domain}</div>}
                  </td>
                  <td style={{ ...tdStyle, color: '#94a3b8', maxWidth: 240 }}>
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.description || '—'}</div>
                  </td>
                  <td style={tdStyle}><span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, background: 'rgba(59,130,246,0.1)', color: '#60a5fa' }}>{(p.keywords || []).length}</span></td>
                  <td style={tdStyle}><span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, background: 'rgba(99,102,241,0.1)', color: '#a5b4fc' }}>{(p.oracle_products || []).length}</span></td>
                  <td style={tdStyle}>
                    <button onClick={() => toggleActive(p)} style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, color: p.is_active ? '#10b981' : '#475569' }}>
                      {p.is_active ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                      <span style={{ fontSize: 12 }}>{p.is_active ? 'Active' : 'Inactive'}</span>
                    </button>
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: 'flex', gap: 4 }}>
                      <button onClick={() => setSlideOver(p)} title="Edit" style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = '#3b82f6'; e.currentTarget.style.color = '#60a5fa' }}
                        onMouseLeave={e => { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.color = '#94a3b8' }}>
                        <Edit2 size={12} /> Edit
                      </button>
                      <button onClick={() => deleteProfile(p)} title="Delete" style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid rgba(239,68,68,0.2)', background: 'transparent', color: '#f87171', fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                        onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.08)'}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </td>
                </tr>
                {expanded === p.id && <TaxonomyRow key={`tax-${p.id}`} profileId={p.id} onClose={() => setExpanded(null)} />}
              </>
            ))}
          </tbody>
        </table>
        <div style={{ padding: '12px 16px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', fontSize: 12, color: '#64748b' }}>
          {profiles.length} technology profiles
        </div>
      </div>
    </div>
  )
}
