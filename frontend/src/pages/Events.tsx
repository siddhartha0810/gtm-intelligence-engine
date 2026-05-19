import { useState, useEffect } from 'react'
import { Calendar, Plus, Trash2, Edit2, X, Search, Users } from 'lucide-react'
import { toast } from '../components/Toast'

const authH = (): Record<string, string> => ({
  'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
  'Content-Type': 'application/json',
})

type EventType = 'conference' | 'webinar' | 'workshop' | 'meetup' | 'trade_show' | 'other'

interface Event {
  id: number
  name: string
  event_type: EventType
  location: string
  event_date: string
  description: string
  attendee_count: number
}

interface Attendee {
  id: number
  contact_id: number
  contact_name: string
  company: string
  title: string
  role: string
}

const EVENT_TYPES: EventType[] = ['conference', 'webinar', 'workshop', 'meetup', 'trade_show', 'other']

const typeColor = (t: EventType) => {
  const m: Record<EventType, { bg: string; color: string }> = {
    conference: { bg: 'rgba(59,130,246,0.12)', color: '#60a5fa' },
    webinar: { bg: 'rgba(99,102,241,0.12)', color: '#a5b4fc' },
    workshop: { bg: 'rgba(245,158,11,0.12)', color: '#fbbf24' },
    meetup: { bg: 'rgba(16,185,129,0.12)', color: '#34d399' },
    trade_show: { bg: 'rgba(239,68,68,0.12)', color: '#f87171' },
    other: { bg: 'rgba(107,114,128,0.12)', color: '#9ca3af' },
  }
  return m[t] ?? m.other
}

const roleBadge = (role: string) => {
  if (role === 'speaker') return { bg: 'rgba(245,158,11,0.12)', color: '#fbbf24' }
  if (role === 'sponsor') return { bg: 'rgba(59,130,246,0.12)', color: '#60a5fa' }
  if (role === 'organizer') return { bg: 'rgba(99,102,241,0.12)', color: '#a5b4fc' }
  return { bg: 'rgba(107,114,128,0.12)', color: '#9ca3af' }
}

function EventFormModal({ event, onClose, onSave }: { event: Partial<Event> | null; onClose: () => void; onSave: () => void }) {
  const isEdit = !!(event?.id)
  const [form, setForm] = useState({
    name: event?.name ?? '',
    event_type: event?.event_type ?? 'conference' as EventType,
    location: event?.location ?? '',
    event_date: event?.event_date ? event.event_date.slice(0, 10) : '',
    description: event?.description ?? '',
    attendee_count: String(event?.attendee_count ?? ''),
  })
  const [saving, setSaving] = useState(false)
  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const save = async () => {
    if (!form.name.trim()) { toast.error('Name is required'); return }
    setSaving(true)
    const body = { ...form, attendee_count: parseInt(form.attendee_count) || 0 }
    try {
      const url = isEdit ? `/api/events/${event!.id}` : '/api/events'
      const r = await fetch(url, { method: isEdit ? 'PATCH' : 'POST', headers: authH(), body: JSON.stringify(body) })
      if (!r.ok) throw new Error()
      toast.success(isEdit ? 'Event updated' : 'Event created')
      onSave()
    } catch { toast.error('Save failed') } finally { setSaving(false) }
  }

  const inp: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 13, outline: 'none', boxSizing: 'border-box' }
  const lbl: React.CSSProperties = { fontSize: 12, color: '#64748b', fontWeight: 600, letterSpacing: '0.04em', display: 'block', marginBottom: 6 }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 500, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)' }} />
      <div style={{ position: 'relative', width: 480, background: '#ffffff', borderRadius: 14, border: '1px solid #e2e8f0', zIndex: 1, maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 8px 40px rgba(0,0,0,0.12)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px', borderBottom: '1px solid #e2e8f0' }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#0f172a' }}>{isEdit ? 'Edit Event' : 'New Event'}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', padding: 4 }}><X size={18} /></button>
        </div>
        <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div><label style={lbl}>Event Name *</label><input style={inp} value={form.name} onChange={e => set('name', e.target.value)} /></div>
          <div><label style={lbl}>Event Type</label>
            <select style={{ ...inp, cursor: 'pointer' }} value={form.event_type} onChange={e => set('event_type', e.target.value)}>
              {EVENT_TYPES.map(t => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
            </select>
          </div>
          <div><label style={lbl}>Location</label><input style={inp} value={form.location} onChange={e => set('location', e.target.value)} placeholder="City, Country or Online" /></div>
          <div><label style={lbl}>Event Date</label><input style={inp} type="date" value={form.event_date} onChange={e => set('event_date', e.target.value)} /></div>
          <div><label style={lbl}>Expected Attendees</label><input style={inp} type="number" value={form.attendee_count} onChange={e => set('attendee_count', e.target.value)} /></div>
          <div><label style={lbl}>Description</label><textarea style={{ ...inp, minHeight: 80, resize: 'vertical' }} value={form.description} onChange={e => set('description', e.target.value)} /></div>
        </div>
        <div style={{ padding: '16px 24px', borderTop: '1px solid #e2e8f0', display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '8px 20px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>Cancel</button>
          <button onClick={save} disabled={saving} style={{ padding: '8px 20px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.7 : 1 }}>{saving ? 'Saving...' : 'Save Event'}</button>
        </div>
      </div>
    </div>
  )
}

function EventSlideOver({ event, onClose, onUpdated }: { event: Event; onClose: () => void; onUpdated: () => void }) {
  const [attendees, setAttendees] = useState<Attendee[]>([])
  const [loadingA, setLoadingA] = useState(true)
  const [contactId, setContactId] = useState('')
  const [role, setRole] = useState('attendee')
  const [editing, setEditing] = useState(false)

  const loadAttendees = async () => {
    setLoadingA(true)
    try {
      const r = await fetch(`/api/events/${event.id}/attendees`, { headers: authH() })
      if (!r.ok) throw new Error()
      setAttendees(await r.json())
    } catch { } finally { setLoadingA(false) }
  }

  useEffect(() => { loadAttendees() }, [event.id])

  const addAttendee = async () => {
    if (!contactId.trim()) { toast.error('Contact ID is required'); return }
    try {
      const r = await fetch(`/api/events/${event.id}/attendees`, { method: 'POST', headers: authH(), body: JSON.stringify({ contact_id: parseInt(contactId), role }) })
      if (!r.ok) throw new Error()
      toast.success('Attendee added')
      setContactId('')
      loadAttendees()
    } catch { toast.error('Failed to add attendee') }
  }

  const removeAttendee = async (aid: number) => {
    try {
      const r = await fetch(`/api/events/${event.id}/attendees/${aid}`, { method: 'DELETE', headers: authH() })
      if (!r.ok) throw new Error()
      toast.success('Attendee removed')
      setAttendees(a => a.filter(x => x.id !== aid))
    } catch { toast.error('Remove failed') }
  }

  const tc = typeColor(event.event_type)
  const inp: React.CSSProperties = { padding: '7px 12px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 13, outline: 'none' }

  return (
    <>
      {editing && <EventFormModal event={event} onClose={() => setEditing(false)} onSave={() => { setEditing(false); onUpdated() }} />}
      <div style={{ position: 'fixed', inset: 0, zIndex: 400, display: 'flex', justifyContent: 'flex-end' }}>
        <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)' }} />
        <div style={{ position: 'relative', width: 520, background: '#ffffff', borderLeft: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column', overflow: 'hidden', zIndex: 1, boxShadow: '-4px 0 24px rgba(0,0,0,0.08)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px', borderBottom: '1px solid #e2e8f0' }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#0f172a' }}>{event.name}</h2>
              <span style={{ fontSize: 12, padding: '2px 10px', borderRadius: 999, background: tc.bg, color: tc.color, marginTop: 6, display: 'inline-block' }}>{event.event_type.replace('_', ' ')}</span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => setEditing(true)} style={{ background: 'none', border: '1px solid #e2e8f0', cursor: 'pointer', color: '#94a3b8', padding: '6px 12px', borderRadius: 8, fontSize: 13, display: 'flex', alignItems: 'center', gap: 5 }}><Edit2 size={13} />Edit</button>
              <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', padding: 4 }}><X size={18} /></button>
            </div>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
              {[{ label: 'Date', value: event.event_date ? new Date(event.event_date).toLocaleDateString() : '—' }, { label: 'Location', value: event.location || '—' }, { label: 'Expected Attendees', value: String(event.attendee_count || 0) }].map(s => (
                <div key={s.label} style={{ padding: '12px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
                  <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, letterSpacing: '0.04em' }}>{s.label.toUpperCase()}</div>
                  <div style={{ fontSize: 14, color: '#0f172a', fontWeight: 500, marginTop: 4 }}>{s.value}</div>
                </div>
              ))}
            </div>
            {event.description && <p style={{ fontSize: 13, color: '#94a3b8', lineHeight: 1.6, marginBottom: 20 }}>{event.description}</p>}

            <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: '#0f172a' }}>Attendees ({attendees.length})</h3>
              </div>

              <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
                <input style={{ ...inp, flex: '1 1 140px' }} value={contactId} onChange={e => setContactId(e.target.value)} placeholder="Contact ID" type="number" />
                <select style={{ ...inp, cursor: 'pointer' }} value={role} onChange={e => setRole(e.target.value)}>
                  {['attendee', 'speaker', 'sponsor', 'organizer'].map(r => <option key={r} value={r}>{r}</option>)}
                </select>
                <button onClick={addAttendee} style={{ padding: '7px 14px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5 }}><Plus size={13} />Add</button>
              </div>

              {loadingA ? <p style={{ fontSize: 13, color: '#475569' }}>Loading attendees...</p> : attendees.length === 0 ? <p style={{ fontSize: 13, color: '#475569' }}>No attendees yet.</p> : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {attendees.map(a => {
                    const rb = roleBadge(a.role)
                    return (
                      <div key={a.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
                        <div>
                          <div style={{ fontSize: 13, color: '#0f172a', fontWeight: 500 }}>{a.contact_name}</div>
                          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{a.company}{a.title ? ` · ${a.title}` : ''}</div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: rb.bg, color: rb.color }}>{a.role}</span>
                          <button onClick={() => removeAttendee(a.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#475569', padding: 4, borderRadius: 4 }}
                            onMouseEnter={e => { e.currentTarget.style.color = '#ef4444'; e.currentTarget.style.background = 'rgba(239,68,68,0.08)' }}
                            onMouseLeave={e => { e.currentTarget.style.color = '#475569'; e.currentTarget.style.background = 'none' }}>
                            <X size={13} />
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

export default function Events() {
  const [events, setEvents] = useState<Event[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [modal, setModal] = useState<Partial<Event> | null | false>(false)
  const [selected, setSelected] = useState<Event | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const r = await fetch('/api/events', { headers: authH() })
      if (!r.ok) throw new Error()
      setEvents(await r.json())
    } catch { toast.error('Failed to load events') } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const deleteEvent = async (e: Event) => {
    if (!window.confirm(`Delete "${e.name}"?`)) return
    try {
      const r = await fetch(`/api/events/${e.id}`, { method: 'DELETE', headers: authH() })
      if (!r.ok) throw new Error()
      toast.success('Event deleted')
      setEvents(evs => evs.filter(x => x.id !== e.id))
      if (selected?.id === e.id) setSelected(null)
    } catch { toast.error('Delete failed') }
  }

  const filtered = events.filter(e =>
    e.name.toLowerCase().includes(search.toLowerCase()) ||
    (e.location || '').toLowerCase().includes(search.toLowerCase())
  )

  const AVATAR_COLORS = ['#3b82f6', '#6366f1', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      {modal !== false && <EventFormModal event={modal} onClose={() => setModal(false)} onSave={() => { setModal(false); load() }} />}
      {selected && <EventSlideOver event={selected} onClose={() => setSelected(null)} onUpdated={() => { setSelected(null); load() }} />}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>Events</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>{loading ? 'Loading...' : `${events.length} events`}</p>
        </div>
        <button onClick={() => setModal({})} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>
          <Plus size={14} /> New Event
        </button>
      </div>

      <div style={{ position: 'relative', maxWidth: 360 }}>
        <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#475569' }} />
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search events, locations..."
          style={{ width: '100%', padding: '8px 12px 8px 36px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 13, outline: 'none', boxSizing: 'border-box' }} />
      </div>

      {loading && <div style={{ textAlign: 'center', padding: '60px 0', color: '#475569', fontSize: 13 }}>Loading events...</div>}

      {!loading && filtered.length === 0 && (
        <div style={{ textAlign: 'center', padding: '60px 0', color: '#475569', fontSize: 13 }}>
          <Calendar size={40} color="#253047" style={{ marginBottom: 12, display: 'block', margin: '0 auto 12px' }} />
          No events found. Create one to get started.
        </div>
      )}

      {!loading && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
          {filtered.map((ev, i) => {
            const tc = typeColor(ev.event_type)
            const avatarColor = AVATAR_COLORS[i % AVATAR_COLORS.length]
            return (
              <div key={ev.id} onClick={() => setSelected(ev)}
                style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, cursor: 'pointer', transition: 'border-color 0.15s, box-shadow 0.15s', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = '#3b82f6'; e.currentTarget.style.boxShadow = '0 4px 20px rgba(59,130,246,0.1)' }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.boxShadow = '0 1px 3px rgba(0,0,0,0.06)' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14 }}>
                  <div style={{ width: 40, height: 40, borderRadius: 10, background: avatarColor + '22', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Calendar size={20} color={avatarColor} />
                  </div>
                  <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, background: tc.bg, color: tc.color, whiteSpace: 'nowrap' }}>{ev.event_type.replace('_', ' ')}</span>
                </div>
                <div style={{ fontSize: 15, fontWeight: 600, color: '#0f172a', marginBottom: 8, lineHeight: 1.3 }}>{ev.name}</div>
                {ev.description && <div style={{ fontSize: 13, color: '#64748b', marginBottom: 12, lineHeight: 1.5, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>{ev.description}</div>}
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, fontSize: 12, color: '#64748b', borderTop: '1px solid #f1f5f9', paddingTop: 12 }}>
                  {ev.event_date && <span>{new Date(ev.event_date).toLocaleDateString()}</span>}
                  {ev.location && <span>📍 {ev.location}</span>}
                  {ev.attendee_count > 0 && <span><Users size={11} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 3 }} />{ev.attendee_count}</span>}
                </div>
                <div style={{ display: 'flex', gap: 6, marginTop: 12 }} onClick={e => e.stopPropagation()}>
                  <button onClick={() => setModal(ev)} style={{ flex: 1, padding: '6px 0', borderRadius: 7, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}><Edit2 size={11} />Edit</button>
                  <button onClick={() => deleteEvent(ev)} style={{ padding: '6px 10px', borderRadius: 7, border: '1px solid rgba(239,68,68,0.2)', background: 'transparent', color: '#f87171', fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center' }}><Trash2 size={11} /></button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
