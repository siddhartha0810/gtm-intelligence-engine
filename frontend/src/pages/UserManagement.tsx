import { useState, useEffect } from 'react'
import { Plus, RefreshCw, X, Shield } from 'lucide-react'
import { toast } from '../components/Toast'

type Role = 'owner' | 'admin' | 'analyst' | 'viewer' | 'recruitment'

interface AppUser {
  id: number
  email: string
  name: string
  role: Role
  is_active: boolean
  last_login: string | null
  created_at: string
}

interface Me {
  id: number
  email: string
  role: Role
}

const ROLES: Role[] = ['owner', 'admin', 'analyst', 'viewer', 'recruitment']

const roleBadge = (role: Role): { bg: string; color: string } => {
  const m: Record<Role, { bg: string; color: string }> = {
    owner:       { bg: 'rgba(139,92,246,0.15)', color: '#a78bfa' },
    admin:       { bg: 'rgba(239,68,68,0.15)', color: '#f87171' },
    analyst:     { bg: 'rgba(59,130,246,0.15)', color: '#60a5fa' },
    viewer:      { bg: 'rgba(107,114,128,0.15)', color: '#9ca3af' },
    recruitment: { bg: 'rgba(245,158,11,0.15)', color: '#fbbf24' },
  }
  return m[role] ?? m.viewer
}

function InviteModal({ onClose, onSave }: { onClose: () => void; onSave: () => void }) {
  const [form, setForm] = useState({ email: '', name: '', password: '', role: 'viewer' as Role })
  const [saving, setSaving] = useState(false)
  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const save = async () => {
    if (!form.email.trim()) { toast.error('Email is required'); return }
    if (!form.password.trim()) { toast.error('Password is required'); return }
    setSaving(true)
    try {
      const r = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        throw new Error(err.detail || err.message || `HTTP ${r.status}`)
      }
      toast.success(`${form.email} invited successfully`)
      onSave()
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Invite failed')
    } finally { setSaving(false) }
  }

  const inp: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 13, outline: 'none', boxSizing: 'border-box' }
  const lbl: React.CSSProperties = { fontSize: 12, color: '#64748b', fontWeight: 600, letterSpacing: '0.04em', display: 'block', marginBottom: 6 }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 500, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)' }} />
      <div style={{ position: 'relative', width: 420, background: '#ffffff', borderRadius: 14, border: '1px solid #e2e8f0', zIndex: 1, boxShadow: '0 8px 40px rgba(0,0,0,0.12)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px', borderBottom: '1px solid #e2e8f0' }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#0f172a' }}>Invite User</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', padding: 4 }}><X size={18} /></button>
        </div>
        <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div><label style={lbl}>Email *</label><input style={inp} type="email" value={form.email} onChange={e => set('email', e.target.value)} placeholder="user@example.com" /></div>
          <div><label style={lbl}>Full Name</label><input style={inp} value={form.name} onChange={e => set('name', e.target.value)} placeholder="Jane Smith" /></div>
          <div><label style={lbl}>Password *</label><input style={inp} type="password" value={form.password} onChange={e => set('password', e.target.value)} /></div>
          <div>
            <label style={lbl}>Role</label>
            <select style={{ ...inp, cursor: 'pointer' }} value={form.role} onChange={e => set('role', e.target.value)}>
              {ROLES.map(r => <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>)}
            </select>
          </div>
        </div>
        <div style={{ padding: '16px 24px', borderTop: '1px solid #e2e8f0', display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '8px 20px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>Cancel</button>
          <button onClick={save} disabled={saving} style={{ padding: '8px 20px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.7 : 1 }}>{saving ? 'Inviting...' : 'Send Invite'}</button>
        </div>
      </div>
    </div>
  )
}

export default function UserManagement() {
  const [users, setUsers] = useState<AppUser[]>([])
  const [loading, setLoading] = useState(true)
  const [me, setMe] = useState<Me | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)

  const loadMe = async () => {
    try {
      const r = await fetch('/api/auth/me')
      if (r.ok) setMe(await r.json())
    } catch { }
  }

  const load = async () => {
    setLoading(true)
    try {
      const r = await fetch('/api/users')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setUsers(await r.json())
    } catch { toast.error('Failed to load users') } finally { setLoading(false) }
  }

  useEffect(() => { loadMe(); load() }, [])

  const changeRole = async (u: AppUser, role: Role) => {
    try {
      const r = await fetch(`/api/users/${u.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role }) })
      if (!r.ok) throw new Error()
      toast.success(`${u.email} role changed to ${role}`)
      setUsers(us => us.map(x => x.id === u.id ? { ...x, role } : x))
    } catch { toast.error('Role change failed') }
  }

  const deactivate = async (u: AppUser) => {
    if (!window.confirm(`Deactivate ${u.email}?`)) return
    try {
      const r = await fetch(`/api/users/${u.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: false }) })
      if (!r.ok) throw new Error()
      toast.success(`${u.email} deactivated`)
      setUsers(us => us.map(x => x.id === u.id ? { ...x, is_active: false } : x))
    } catch { toast.error('Deactivate failed') }
  }

  const reactivate = async (u: AppUser) => {
    try {
      const r = await fetch(`/api/users/${u.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: true }) })
      if (!r.ok) throw new Error()
      toast.success(`${u.email} reactivated`)
      setUsers(us => us.map(x => x.id === u.id ? { ...x, is_active: true } : x))
    } catch { toast.error('Reactivate failed') }
  }

  const thStyle: React.CSSProperties = { padding: '11px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#475569', letterSpacing: '0.03em', whiteSpace: 'nowrap' }
  const tdStyle: React.CSSProperties = { padding: '13px 16px', fontSize: 13, verticalAlign: 'middle', color: '#cbd5e1' }

  const activeCount = users.filter(u => u.is_active).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%' }}>
      {inviteOpen && <InviteModal onClose={() => setInviteOpen(false)} onSave={() => { setInviteOpen(false); load() }} />}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Shield size={20} color="#3b82f6" />
            <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>User Management</h1>
          </div>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
            {loading ? 'Loading...' : `${users.length} users · ${activeCount} active`}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={load} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>
            <RefreshCw size={13} />
          </button>
          <button onClick={() => setInviteOpen(true)} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>
            <Plus size={14} /> Invite User
          </button>
        </div>
      </div>

      {me && (
        <div style={{ padding: '10px 16px', background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.2)', borderRadius: 8, fontSize: 13, color: '#60a5fa', display: 'flex', alignItems: 'center', gap: 8 }}>
          <Shield size={14} /> Logged in as <strong>{me.email}</strong> ({me.role})
        </div>
      )}

      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                <th style={thStyle}>User</th>
                <th style={thStyle}>Role</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Last Login</th>
                <th style={thStyle}>Created</th>
                <th style={{ ...thStyle, width: 200 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={6} style={{ padding: '40px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>Loading users...</td></tr>}
              {!loading && users.length === 0 && <tr><td colSpan={6} style={{ padding: '40px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>No users found.</td></tr>}
              {!loading && users.map((u, i) => {
                const rb = roleBadge(u.role)
                const isSelf = me?.id === u.id
                const AVATAR_COLORS = ['#3b82f6', '#6366f1', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']
                const avatarColor = AVATAR_COLORS[i % AVATAR_COLORS.length]
                return (
                  <tr key={u.id} style={{ background: '#ffffff', borderBottom: '1px solid #f1f5f9' }}
                    onMouseEnter={e => e.currentTarget.style.background = 'rgba(37,99,235,0.04)'}
                    onMouseLeave={e => e.currentTarget.style.background = '#ffffff'}>
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ width: 34, height: 34, borderRadius: '50%', background: avatarColor, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, color: 'white', flexShrink: 0 }}>
                          {(u.name || u.email || '?')[0].toUpperCase()}
                        </div>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 500, color: '#0f172a' }}>{u.name || '—'} {isSelf && <span style={{ fontSize: 11, color: '#3b82f6', fontWeight: 400 }}>(you)</span>}</div>
                          <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{u.email}</div>
                        </div>
                      </div>
                    </td>
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, background: rb.bg, color: rb.color, fontWeight: 500 }}>{u.role}</span>
                        <select
                          value={u.role}
                          onChange={e => changeRole(u, e.target.value as Role)}
                          onClick={e => e.stopPropagation()}
                          style={{ padding: '4px 8px', borderRadius: 6, background: '#ffffff', border: '1px solid #d1d5db', color: '#64748b', fontSize: 11, outline: 'none', cursor: 'pointer' }}>
                          {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                        </select>
                      </div>
                    </td>
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                        <div style={{ width: 8, height: 8, borderRadius: '50%', background: u.is_active ? '#10b981' : '#ef4444', flexShrink: 0 }} />
                        <span style={{ fontSize: 12, color: u.is_active ? '#34d399' : '#f87171' }}>{u.is_active ? 'Active' : 'Inactive'}</span>
                      </div>
                    </td>
                    <td style={{ ...tdStyle, fontSize: 12, color: '#64748b' }}>
                      {u.last_login ? new Date(u.last_login).toLocaleDateString() : 'Never'}
                    </td>
                    <td style={{ ...tdStyle, fontSize: 12, color: '#475569' }}>
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                    </td>
                    <td style={tdStyle}>
                      {u.is_active ? (
                        <button
                          onClick={() => deactivate(u)}
                          disabled={isSelf}
                          title={isSelf ? 'Cannot deactivate yourself' : 'Deactivate user'}
                          style={{ padding: '5px 12px', borderRadius: 7, border: '1px solid rgba(239,68,68,0.25)', background: 'transparent', color: isSelf ? '#374151' : '#f87171', fontSize: 12, cursor: isSelf ? 'not-allowed' : 'pointer', opacity: isSelf ? 0.4 : 1 }}
                          onMouseEnter={e => { if (!isSelf) e.currentTarget.style.background = 'rgba(239,68,68,0.08)' }}
                          onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}>
                          Deactivate
                        </button>
                      ) : (
                        <button
                          onClick={() => reactivate(u)}
                          style={{ padding: '5px 12px', borderRadius: 7, border: '1px solid rgba(16,185,129,0.25)', background: 'transparent', color: '#34d399', fontSize: 12, cursor: 'pointer' }}
                          onMouseEnter={e => e.currentTarget.style.background = 'rgba(16,185,129,0.08)'}
                          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                          Reactivate
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div style={{ padding: '12px 16px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', fontSize: 12, color: '#64748b' }}>
          {users.length} users · {activeCount} active · {users.length - activeCount} inactive
        </div>
      </div>

      {/* Role legend */}
      <div style={{ padding: '16px 20px', background: '#ffffff', borderRadius: 10, border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        <div style={{ fontSize: 12, color: '#475569', fontWeight: 600, letterSpacing: '0.04em', marginBottom: 12 }}>ROLE PERMISSIONS</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {[
            { role: 'owner' as Role, desc: 'Full access, can manage all settings' },
            { role: 'admin' as Role, desc: 'Manage users and all data' },
            { role: 'analyst' as Role, desc: 'Read/write access to data' },
            { role: 'recruitment' as Role, desc: 'Access to recruitment features' },
            { role: 'viewer' as Role, desc: 'Read-only access' },
          ].map(({ role, desc }) => {
            const rb = roleBadge(role)
            return (
              <div key={role} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
                <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 999, background: rb.bg, color: rb.color, fontWeight: 500 }}>{role}</span>
                <span style={{ fontSize: 12, color: '#64748b' }}>{desc}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
