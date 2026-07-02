import { useState, useEffect } from 'react'
import {
  Crosshair, Plus, Trash2, Play, Eye, ChevronDown, ChevronUp,
  Search, Zap, BarChart3, Clock, CheckCircle, XCircle, Pencil
} from 'lucide-react'
import { toast } from '../components/Toast'

const authH = () => ({ Authorization: `Bearer ${localStorage.getItem('token') || ''}` })

const card: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: 20,
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}

const btnPrimary: React.CSSProperties = {
  background: '#3b82f6', color: '#fff',
  border: 'none', borderRadius: 8, padding: '8px 16px',
  cursor: 'pointer', fontWeight: 600, fontSize: 14,
  display: 'inline-flex', alignItems: 'center', gap: 6,
}

const btnSecondary: React.CSSProperties = {
  background: 'transparent', color: '#64748b',
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '7px 14px',
  cursor: 'pointer', fontWeight: 500, fontSize: 14,
  display: 'inline-flex', alignItems: 'center', gap: 6,
}

const btnGreen: React.CSSProperties = {
  ...btnPrimary, background: '#10b981',
}

const INPUT: React.CSSProperties = {
  width: '100%', padding: '8px 12px', borderRadius: 8,
  border: '1px solid #e2e8f0', fontSize: 14, color: '#0f172a',
  background: '#fff', boxSizing: 'border-box',
  outline: 'none',
}

const SOURCES = [
  { id: 'indeed',       label: 'Indeed' },
  { id: 'linkedin',     label: 'LinkedIn' },
  { id: 'adzuna',       label: 'Adzuna' },
  { id: 'ziprecruiter', label: 'ZipRecruiter' },
  { id: 'news',         label: 'News' },
  { id: 'google_jobs',  label: 'Google Jobs' },
]

interface Campaign {
  id: number
  name: string
  description: string
  keywords: string[]
  extra_job_suffixes: string[]
  extra_news_templates: string[]
  custom_job_queries: string[]
  custom_news_queries: string[]
  location: string
  max_pages: number
  sources: string[]
  query_tier: number
  is_active: number
  last_run_at: string | null
  last_run_id: number | null
  total_signals: number
  total_companies: number
  created_at: string
  updated_at: string
}

interface PreviewResult {
  job_query_count: number
  news_query_count: number
  job_queries: string[]
  news_queries: string[]
  estimates: { keywords: number; job_queries: number; news_queries: number; total: number }
}

const EMPTY_FORM = {
  name: '',
  description: '',
  keywords: '',
  extra_job_suffixes: '',
  location: '',
  max_pages: 3,
  sources: [] as string[],
  query_tier: 1,
}

export default function Campaigns() {
  const [campaigns, setCampaigns]         = useState<Campaign[]>([])
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState('')
  const [showForm, setShowForm]           = useState(false)
  const [editId, setEditId]               = useState<number | null>(null)
  const [form, setForm]                   = useState({ ...EMPTY_FORM })
  const [saving, setSaving]               = useState(false)
  const [launching, setLaunching]         = useState<number | null>(null)
  const [expanded, setExpanded]           = useState<number | null>(null)
  const [preview, setPreview]             = useState<{ id: number; data: PreviewResult } | null>(null)
  const [previewLoading, setPreviewLoading] = useState<number | null>(null)

  useEffect(() => { load() }, [])

  function load() {
    setLoading(true)
    fetch('/api/campaigns', { headers: authH() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => setCampaigns(data))
      .catch(e => { setError(e.message); toast.error(e.message) })
      .finally(() => setLoading(false))
  }

  function openCreate() {
    setEditId(null)
    setForm({ ...EMPTY_FORM })
    setShowForm(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function openEdit(c: Campaign) {
    setEditId(c.id)
    setForm({
      name: c.name,
      description: c.description,
      keywords: (c.keywords || []).join(', '),
      extra_job_suffixes: (c.extra_job_suffixes || []).join(', '),
      location: c.location,
      max_pages: c.max_pages,
      sources: c.sources || [],
      query_tier: c.query_tier,
    })
    setShowForm(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function toggleSource(id: string) {
    setForm(f => ({
      ...f,
      sources: f.sources.includes(id)
        ? f.sources.filter(s => s !== id)
        : [...f.sources, id],
    }))
  }

  async function handleSave() {
    if (!form.name.trim()) { toast.error('Campaign name is required'); return }
    if (!form.keywords.trim()) { toast.error('At least one keyword is required'); return }

    setSaving(true)
    const body = {
      name: form.name.trim(),
      description: form.description.trim(),
      keywords: form.keywords.split(',').map(k => k.trim()).filter(Boolean),
      extra_job_suffixes: form.extra_job_suffixes.split(',').map(s => s.trim()).filter(Boolean),
      location: form.location.trim(),
      max_pages: form.max_pages,
      sources: form.sources,
      query_tier: form.query_tier,
    }

    const url    = editId ? `/api/campaigns/${editId}` : '/api/campaigns'
    const method = editId ? 'PUT' : 'POST'

    fetch(url, {
      method,
      headers: { ...authH(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => {
        if (!r.ok) return r.json().then(d => { throw new Error(d.error || `HTTP ${r.status}`) })
        return r.json()
      })
      .then(() => {
        toast.success(editId ? 'Campaign updated' : 'Campaign created')
        setShowForm(false)
        load()
      })
      .catch(e => toast.error(e.message))
      .finally(() => setSaving(false))
  }

  async function handleDelete(id: number, name: string) {
    if (!confirm(`Delete campaign "${name}"? This cannot be undone.`)) return
    fetch(`/api/campaigns/${id}`, { method: 'DELETE', headers: authH() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(() => { toast.success('Campaign deleted'); load() })
      .catch(e => toast.error(e.message))
  }

  async function handleLaunch(c: Campaign) {
    const kws  = c.keywords?.join(', ') || ''
    const loc  = c.location || 'Global'
    if (!confirm(`Launch scan for "${c.name}"?\n\nKeywords: ${kws}\nLocation: ${loc}\nMax pages: ${c.max_pages}`)) return
    setLaunching(c.id)
    fetch(`/api/campaigns/${c.id}/scan`, {
      method: 'POST',
      headers: { ...authH(), 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
      .then(r => {
        if (!r.ok) return r.json().then(d => { throw new Error(d.error || `HTTP ${r.status}`) })
        return r.json()
      })
      .then(data => {
        toast.success(`Scan started — ${data.job_queries} job queries + ${data.news_queries} news queries`)
        load()
      })
      .catch(e => toast.error(e.message))
      .finally(() => setLaunching(null))
  }

  async function handlePreview(id: number) {
    if (preview?.id === id) { setPreview(null); return }
    setPreviewLoading(id)
    fetch(`/api/campaigns/${id}/preview-queries`, {
      method: 'POST',
      headers: authH(),
    })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => setPreview({ id, data }))
      .catch(e => toast.error(e.message))
      .finally(() => setPreviewLoading(null))
  }

  if (loading) return (
    <div style={{ padding: 40, textAlign: 'center', color: '#64748b' }}>Loading campaigns…</div>
  )
  if (error) return (
    <div style={{ padding: 40, color: '#ef4444' }}>Error: {error}</div>
  )

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: '#0f172a', margin: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
            <Crosshair size={24} color="#3b82f6" />
            Signal Campaigns
          </h1>
          <p style={{ color: '#64748b', marginTop: 4 }}>
            Track buying intent signals for any product or technology — not just Oracle.
          </p>
        </div>
        <button style={btnPrimary} onClick={openCreate}>
          <Plus size={16} /> New Campaign
        </button>
      </div>

      {/* Stats row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {[
          { label: 'Total Campaigns',  value: campaigns.length,                                          icon: <Crosshair size={18} color="#3b82f6" /> },
          { label: 'Active',           value: campaigns.filter(c => c.is_active).length,                 icon: <CheckCircle size={18} color="#10b981" /> },
          { label: 'Total Signals',    value: campaigns.reduce((s, c) => s + (c.total_signals || 0), 0), icon: <Zap size={18} color="#f59e0b" /> },
          { label: 'Companies Found',  value: campaigns.reduce((s, c) => s + (c.total_companies || 0), 0), icon: <BarChart3 size={18} color="#6366f1" /> },
        ].map(stat => (
          <div key={stat.label} style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#0f172a' }}>{stat.value}</div>
                <div style={{ fontSize: 13, color: '#64748b', marginTop: 2 }}>{stat.label}</div>
              </div>
              {stat.icon}
            </div>
          </div>
        ))}
      </div>

      {/* Create / Edit Form */}
      {showForm && (
        <div style={{ ...card, marginBottom: 24, borderColor: '#3b82f6', boxShadow: '0 0 0 3px rgba(59,130,246,0.1)' }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', marginTop: 0, marginBottom: 20 }}>
            {editId ? 'Edit Campaign' : 'Create Campaign'}
          </h2>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            <div>
              <label style={{ fontSize: 13, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 6 }}>
                Campaign Name *
              </label>
              <input
                style={INPUT}
                placeholder="e.g. Salesforce Prospects, SAP Migration Targets"
                value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div>
              <label style={{ fontSize: 13, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 6 }}>
                Description
              </label>
              <input
                style={INPUT}
                placeholder="What is this campaign targeting?"
                value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              />
            </div>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 13, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 6 }}>
              Target Keywords *{' '}
              <span style={{ fontWeight: 400, color: '#64748b' }}>(comma-separated — these drive all your queries)</span>
            </label>
            <input
              style={INPUT}
              placeholder="Salesforce, SFDC, Salesforce CRM, Salesforce Sales Cloud"
              value={form.keywords}
              onChange={e => setForm(f => ({ ...f, keywords: e.target.value }))}
            />
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
              Each keyword × ~14 role suffixes = job board queries. Add aliases for better coverage.
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            <div>
              <label style={{ fontSize: 13, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 6 }}>
                Location Filter
              </label>
              <input
                style={INPUT}
                placeholder="United States (leave blank for global)"
                value={form.location}
                onChange={e => setForm(f => ({ ...f, location: e.target.value }))}
              />
            </div>
            <div>
              <label style={{ fontSize: 13, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 6 }}>
                Max Pages per Source
              </label>
              <input
                type="number"
                style={INPUT}
                min={1} max={10}
                value={form.max_pages}
                onChange={e => setForm(f => ({ ...f, max_pages: parseInt(e.target.value) || 3 }))}
              />
            </div>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 13, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 6 }}>
              Extra Role Suffixes{' '}
              <span style={{ fontWeight: 400, color: '#64748b' }}>(optional — appended to keywords for more targeted queries)</span>
            </label>
            <input
              style={INPUT}
              placeholder="revenue operations manager, sales ops analyst, RevOps lead"
              value={form.extra_job_suffixes}
              onChange={e => setForm(f => ({ ...f, extra_job_suffixes: e.target.value }))}
            />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label style={{ fontSize: 13, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 8 }}>
              Signal Sources <span style={{ fontWeight: 400, color: '#64748b' }}>(none selected = all sources)</span>
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {SOURCES.map(s => {
                const active = form.sources.includes(s.id)
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => toggleSource(s.id)}
                    style={{
                      padding: '6px 14px', borderRadius: 20, fontSize: 13, cursor: 'pointer',
                      border: active ? '1px solid #3b82f6' : '1px solid #e2e8f0',
                      background: active ? '#eff6ff' : '#fff',
                      color: active ? '#3b82f6' : '#64748b',
                      fontWeight: active ? 600 : 400,
                      transition: 'all 150ms ease-out',
                    }}
                  >
                    {s.label}
                  </button>
                )
              })}
            </div>
          </div>

          <div style={{ marginBottom: 20 }}>
            <label style={{ fontSize: 13, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 8 }}>
              Query Breadth
            </label>
            <div style={{ display: 'flex', gap: 10 }}>
              {[
                { value: 1, label: 'Tier 1 — Focused', desc: '~14 high-signal role suffixes' },
                { value: 2, label: 'Tier 2 — Broad',   desc: '~27 suffixes including general roles' },
              ].map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setForm(f => ({ ...f, query_tier: opt.value }))}
                  style={{
                    flex: 1, padding: '10px 16px', borderRadius: 8, cursor: 'pointer',
                    border: form.query_tier === opt.value ? '2px solid #3b82f6' : '1px solid #e2e8f0',
                    background: form.query_tier === opt.value ? '#eff6ff' : '#fff',
                    textAlign: 'left',
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 600, color: form.query_tier === opt.value ? '#3b82f6' : '#0f172a' }}>
                    {opt.label}
                  </div>
                  <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{opt.desc}</div>
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <button style={btnPrimary} onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : (editId ? 'Save Changes' : 'Create Campaign')}
            </button>
            <button style={btnSecondary} onClick={() => setShowForm(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Campaign list */}
      {campaigns.length === 0 ? (
        <div style={{ ...card, textAlign: 'center', padding: 60 }}>
          <Crosshair size={40} color="#94a3b8" style={{ marginBottom: 16 }} />
          <div style={{ fontSize: 18, fontWeight: 600, color: '#0f172a', marginBottom: 8 }}>
            No campaigns yet
          </div>
          <p style={{ color: '#64748b', marginBottom: 20 }}>
            Create a campaign to detect buying intent signals for any product or technology.
          </p>
          <button style={btnPrimary} onClick={openCreate}>
            <Plus size={16} /> Create your first campaign
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {campaigns.map(c => (
            <div key={c.id} style={{ ...card, padding: 0, overflow: 'hidden' }}>
              {/* Header row — click to expand */}
              <div
                style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '16px 20px', cursor: 'pointer', userSelect: 'none' }}
                onClick={() => setExpanded(expanded === c.id ? null : c.id)}
              >
                <div style={{
                  width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                  background: c.is_active ? '#10b981' : '#94a3b8',
                }} />

                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>{c.name}</span>
                    {c.description && (
                      <span style={{ fontSize: 13, color: '#64748b' }}>— {c.description}</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                    {(c.keywords || []).slice(0, 6).map(kw => (
                      <span key={kw} style={{
                        fontSize: 12, padding: '2px 8px', borderRadius: 12,
                        background: '#eff6ff', color: '#3b82f6', border: '1px solid #bfdbfe', fontWeight: 500,
                      }}>{kw}</span>
                    ))}
                    {(c.keywords || []).length > 6 && (
                      <span style={{ fontSize: 12, color: '#64748b', alignSelf: 'center' }}>
                        +{c.keywords.length - 6} more
                      </span>
                    )}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 24, flexShrink: 0 }}>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>{c.total_signals || 0}</div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>Signals</div>
                  </div>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>{c.total_companies || 0}</div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>Companies</div>
                  </div>
                </div>

                <div style={{ flexShrink: 0, textAlign: 'right', minWidth: 110 }}>
                  {c.last_run_at ? (
                    <div>
                      <div style={{ fontSize: 12, color: '#64748b', display: 'flex', alignItems: 'center', gap: 4, justifyContent: 'flex-end' }}>
                        <Clock size={12} /> Last run
                      </div>
                      <div style={{ fontSize: 12, color: '#0f172a', fontWeight: 500 }}>
                        {new Date(c.last_run_at).toLocaleDateString()}
                      </div>
                    </div>
                  ) : (
                    <div style={{ fontSize: 12, color: '#94a3b8' }}>Never run</div>
                  )}
                </div>

                {expanded === c.id
                  ? <ChevronUp size={18} color="#94a3b8" />
                  : <ChevronDown size={18} color="#94a3b8" />
                }
              </div>

              {/* Expanded panel */}
              {expanded === c.id && (
                <div style={{ borderTop: '1px solid #e2e8f0', padding: '16px 20px', background: '#f8fafc' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 16 }}>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 4 }}>Location</div>
                      <div style={{ fontSize: 14, color: '#0f172a' }}>{c.location || 'Global'}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 4 }}>Max Pages</div>
                      <div style={{ fontSize: 14, color: '#0f172a' }}>{c.max_pages}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 4 }}>Query Tier</div>
                      <div style={{ fontSize: 14, color: '#0f172a' }}>
                        {c.query_tier === 1 ? 'Tier 1 (focused)' : 'Tier 2 (broad)'}
                      </div>
                    </div>
                  </div>

                  {c.sources && c.sources.length > 0 && (
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 6 }}>Sources</div>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        {c.sources.map(s => (
                          <span key={s} style={{
                            fontSize: 12, padding: '3px 10px', borderRadius: 12,
                            background: '#f0fdf4', color: '#10b981', border: '1px solid #bbf7d0',
                          }}>{s}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Query Preview */}
                  {preview?.id === c.id && (
                    <div style={{
                      background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8,
                      padding: 16, marginBottom: 16,
                    }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <Search size={14} /> Query Preview
                        <span style={{ fontWeight: 400, color: '#64748b', fontSize: 13 }}>
                          — {preview.data.job_query_count} job queries, {preview.data.news_query_count} news queries
                        </span>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 6 }}>
                            Job queries (first 10 of {preview.data.job_query_count})
                          </div>
                          {preview.data.job_queries.slice(0, 10).map((q, i) => (
                            <div key={i} style={{ fontSize: 13, color: '#374151', padding: '3px 0', borderBottom: '1px solid #f1f5f9' }}>{q}</div>
                          ))}
                        </div>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 6 }}>
                            News queries (first 8 of {preview.data.news_query_count})
                          </div>
                          {preview.data.news_queries.slice(0, 8).map((q, i) => (
                            <div key={i} style={{ fontSize: 13, color: '#374151', padding: '3px 0', borderBottom: '1px solid #f1f5f9' }}>{q}</div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Actions */}
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <button
                      style={btnGreen}
                      onClick={e => { e.stopPropagation(); handleLaunch(c) }}
                      disabled={launching === c.id}
                    >
                      {launching === c.id
                        ? <><Zap size={14} /> Launching…</>
                        : <><Play size={14} /> Launch Scan</>
                      }
                    </button>

                    <button
                      style={btnSecondary}
                      onClick={e => { e.stopPropagation(); handlePreview(c.id) }}
                      disabled={previewLoading === c.id}
                    >
                      {previewLoading === c.id
                        ? 'Loading…'
                        : preview?.id === c.id
                          ? <><XCircle size={14} /> Hide Queries</>
                          : <><Eye size={14} /> Preview Queries</>
                      }
                    </button>

                    <button
                      style={btnSecondary}
                      onClick={e => { e.stopPropagation(); openEdit(c) }}
                    >
                      <Pencil size={14} /> Edit
                    </button>

                    <button
                      style={{ ...btnSecondary, color: '#ef4444', borderColor: '#fca5a5' }}
                      onClick={e => { e.stopPropagation(); handleDelete(c.id, c.name) }}
                    >
                      <Trash2 size={14} /> Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
