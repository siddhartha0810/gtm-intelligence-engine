import { useState, useEffect, useCallback } from 'react'
import { Plus, RefreshCw, X, Shield, UserCheck, UserX, ChevronDown, Search, KeyRound, Copy, Check } from 'lucide-react'
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

interface Me { id: number; email: string; role: Role }

const ROLES: Role[] = ['owner', 'admin', 'analyst', 'recruitment', 'viewer']

const ROLE_META: Record<Role, { bg: string; color: string; desc: string; icon: string }> = {
  owner:       { bg: 'rgba(139,92,246,0.15)', color: '#a78bfa', desc: 'Full platform control',        icon: '👑' },
  admin:       { bg: 'rgba(239,68,68,0.15)',  color: '#f87171', desc: 'User & data management',       icon: '🛡️' },
  analyst:     { bg: 'rgba(59,130,246,0.15)', color: '#60a5fa', desc: 'Read/write all data modules',   icon: '📊' },
  recruitment: { bg: 'rgba(245,158,11,0.15)', color: '#fbbf24', desc: 'Recruitment module only',       icon: '💼' },
  viewer:      { bg: 'rgba(107,114,128,0.15)',color: '#9ca3af', desc: 'Read-only access',              icon: '👁️' },
}

// ── single source of truth for auth headers ────────────────────────────────
const authH = (): Record<string, string> => ({
  'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
  'Content-Type': 'application/json',
})

// ── Role picker dropdown ───────────────────────────────────────────────────
function RolePicker({ user, disabled, onChange }: {
  user: AppUser
  disabled: boolean
  onChange: (role: Role) => void
}) {
  const [open, setOpen] = useState(false)
  const meta = ROLE_META[user.role]

  return (
    <div style={{ position: 'relative' }}>
      <button
        disabled={disabled}
        onClick={() => !disabled && setOpen(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '5px 10px', borderRadius: 8,
          background: meta.bg, border: `1px solid ${meta.color}33`,
          color: meta.color, fontSize: 12, fontWeight: 600,
          cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.5 : 1,
          transition: 'all 0.15s',
        }}>
        <span>{meta.icon}</span>
        {user.role.charAt(0).toUpperCase() + user.role.slice(1)}
        {!disabled && <ChevronDown size={10} style={{ transition: 'transform 0.2s', transform: open ? 'rotate(180deg)' : 'none' }} />}
      </button>

      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 200 }} />
          <div style={{
            position: 'absolute', top: '110%', left: 0, zIndex: 300,
            background: '#ffffff', border: '1px solid #e2e8f0',
            borderRadius: 10, boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
            minWidth: 230, overflow: 'hidden',
          }}>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid #f1f5f9', fontSize: 11, fontWeight: 700, color: '#94a3b8', letterSpacing: '0.06em' }}>
              ASSIGN ROLE
            </div>
            {ROLES.map(r => {
              const m = ROLE_META[r]
              const active = r === user.role
              return (
                <button key={r} onClick={() => { onChange(r); setOpen(false) }}
                  style={{
                    width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                    padding: '10px 14px', background: active ? m.bg : 'transparent',
                    border: 'none', cursor: 'pointer', textAlign: 'left',
                    borderLeft: active ? `3px solid ${m.color}` : '3px solid transparent',
                    transition: 'background 0.12s',
                  }}
                  onMouseEnter={e => { if (!active) e.currentTarget.style.background = '#f8fafc' }}
                  onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent' }}>
                  <span style={{ fontSize: 16 }}>{m.icon}</span>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: active ? m.color : '#0f172a' }}>
                      {r.charAt(0).toUpperCase() + r.slice(1)}
                      {active && <span style={{ fontSize: 10, marginLeft: 6, opacity: 0.7 }}>current</span>}
                    </div>
                    <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{m.desc}</div>
                  </div>
                </button>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

// ── Invite Modal ───────────────────────────────────────────────────────────
function InviteModal({ onClose, onSave }: { onClose: () => void; onSave: () => void }) {
  const [form, setForm] = useState({ email: '', name: '', password: '', role: 'analyst' as Role })
  const [saving, setSaving] = useState(false)
  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const save = async () => {
    if (!form.email.trim()) { toast.error('Email is required'); return }
    if (!form.password.trim()) { toast.error('Password is required'); return }
    setSaving(true)
    try {
      const r = await fetch('/api/auth/register', {
        method: 'POST',
        headers: authH(),
        body: JSON.stringify(form),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(data.detail || data.error || `HTTP ${r.status}`)
      toast.success(`${form.email} added as ${form.role}`)
      onSave()
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Invite failed')
    } finally { setSaving(false) }
  }

  const inp: React.CSSProperties = {
    width: '100%', padding: '9px 12px', borderRadius: 8,
    background: '#f8fafc', border: '1px solid #d1d5db',
    color: '#0f172a', fontSize: 13, outline: 'none', boxSizing: 'border-box',
  }
  const lbl: React.CSSProperties = { fontSize: 11, color: '#64748b', fontWeight: 700, letterSpacing: '0.05em', display: 'block', marginBottom: 5 }

  const selectedMeta = ROLE_META[form.role]

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 500, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(2px)' }} />
      <div style={{ position: 'relative', width: 460, background: '#ffffff', borderRadius: 16, border: '1px solid #e2e8f0', zIndex: 1, boxShadow: '0 20px 60px rgba(0,0,0,0.15)' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px', borderBottom: '1px solid #e2e8f0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(59,130,246,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Plus size={16} color="#3b82f6" />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: '#0f172a' }}>Add New User</h2>
              <p style={{ margin: 0, fontSize: 12, color: '#64748b' }}>Create account and assign role</p>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 4, borderRadius: 6 }}>
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={lbl}>EMAIL *</label>
              <input style={inp} type="email" value={form.email} onChange={e => set('email', e.target.value)} placeholder="user@company.com"
                onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
                onBlur={e => e.currentTarget.style.borderColor = '#d1d5db'} />
            </div>
            <div>
              <label style={lbl}>FULL NAME</label>
              <input style={inp} value={form.name} onChange={e => set('name', e.target.value)} placeholder="Jane Smith"
                onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
                onBlur={e => e.currentTarget.style.borderColor = '#d1d5db'} />
            </div>
          </div>

          <div>
            <label style={lbl}>TEMPORARY PASSWORD *</label>
            <input style={inp} type="password" value={form.password} onChange={e => set('password', e.target.value)} placeholder="Min 8 characters"
              onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
              onBlur={e => e.currentTarget.style.borderColor = '#d1d5db'} />
          </div>

          {/* Role selector */}
          <div>
            <label style={lbl}>ROLE</label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {ROLES.map(r => {
                const m = ROLE_META[r]
                const active = form.role === r
                return (
                  <button key={r} onClick={() => set('role', r)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 12,
                      padding: '10px 14px', borderRadius: 9, border: `1.5px solid ${active ? m.color : '#e2e8f0'}`,
                      background: active ? m.bg : '#f8fafc', cursor: 'pointer',
                      textAlign: 'left', transition: 'all 0.15s',
                    }}>
                    <span style={{ fontSize: 18 }}>{m.icon}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: active ? m.color : '#374151' }}>
                        {r.charAt(0).toUpperCase() + r.slice(1)}
                      </div>
                      <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{m.desc}</div>
                    </div>
                    {active && (
                      <div style={{ width: 16, height: 16, borderRadius: '50%', background: m.color, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#fff' }} />
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Role summary */}
          <div style={{ padding: '10px 14px', borderRadius: 8, background: selectedMeta.bg, border: `1px solid ${selectedMeta.color}33`, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>{selectedMeta.icon}</span>
            <span style={{ fontSize: 12, color: selectedMeta.color, fontWeight: 500 }}>
              {form.email || 'This user'} will have <strong>{form.role}</strong> access — {selectedMeta.desc.toLowerCase()}.
            </span>
          </div>
        </div>

        <div style={{ padding: '16px 24px', borderTop: '1px solid #e2e8f0', display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '9px 20px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#64748b', fontSize: 13, cursor: 'pointer' }}>Cancel</button>
          <button onClick={save} disabled={saving}
            style={{ padding: '9px 22px', borderRadius: 8, border: 'none', background: saving ? '#93c5fd' : '#3b82f6', color: 'white', fontSize: 13, fontWeight: 600, cursor: saving ? 'not-allowed' : 'pointer', transition: 'background 0.15s' }}>
            {saving ? 'Creating...' : 'Create User'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Reset-password result modal ────────────────────────────────────────────
// Shown once, right after a reset — this is the only place the temporary
// password is ever visible, so the admin can hand it to the user out of band.
function ResetPasswordModal({ email, password, onClose }: { email: string; password: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)

  const copy = () => {
    navigator.clipboard.writeText(password).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 500, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(2px)' }} />
      <div style={{ position: 'relative', width: 420, background: '#ffffff', borderRadius: 16, border: '1px solid #e2e8f0', zIndex: 1, boxShadow: '0 20px 60px rgba(0,0,0,0.15)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px', borderBottom: '1px solid #e2e8f0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(16,185,129,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <KeyRound size={16} color="#10b981" />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: '#0f172a' }}>Password reset</h2>
              <p style={{ margin: 0, fontSize: 12, color: '#64748b' }}>{email}</p>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 4, borderRadius: 6 }}>
            <X size={18} />
          </button>
        </div>
        <div style={{ padding: '20px 24px' }}>
          <p style={{ margin: '0 0 10px', fontSize: 12.5, color: '#64748b' }}>
            Shown once — copy it now and hand it to the user out of band. It won't be shown again.
          </p>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderRadius: 8, background: '#f8fafc', border: '1px solid #d1d5db' }}>
            <code style={{ flex: 1, fontSize: 14, fontFamily: 'monospace', color: '#0f172a', wordBreak: 'break-all' }}>{password}</code>
            <button onClick={copy} title="Copy" style={{ background: 'none', border: 'none', cursor: 'pointer', color: copied ? '#10b981' : '#64748b', display: 'flex', flexShrink: 0 }}>
              {copied ? <Check size={16} /> : <Copy size={16} />}
            </button>
          </div>
        </div>
        <div style={{ padding: '16px 24px', borderTop: '1px solid #e2e8f0', display: 'flex', justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '9px 20px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>Done</button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────
export default function UserManagement() {
  const [users, setUsers]       = useState<AppUser[]>([])
  const [loading, setLoading]   = useState(true)
  const [me, setMe]             = useState<Me | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [search, setSearch]     = useState('')
  const [roleFilter, setRoleFilter] = useState<Role | ''>('')
  const [saving, setSaving]     = useState<number | null>(null)   // which user id is being saved
  const [resetResult, setResetResult] = useState<{ email: string; password: string } | null>(null)

  const loadMe = useCallback(async () => {
    try {
      const r = await fetch('/api/auth/me', { headers: authH() })
      if (r.ok) setMe(await r.json())
    } catch { }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch('/api/users', { headers: authH() })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setUsers(await r.json())
    } catch { toast.error('Failed to load users') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { loadMe(); load() }, [loadMe, load])

  const changeRole = async (u: AppUser, role: Role) => {
    if (role === u.role) return
    setSaving(u.id)
    try {
      const r = await fetch(`/api/users/${u.id}`, {
        method: 'PATCH', headers: authH(),
        body: JSON.stringify({ role }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      toast.success(`${u.name || u.email} → ${role}`)
      setUsers(us => us.map(x => x.id === u.id ? { ...x, role } : x))
    } catch { toast.error('Role change failed') }
    finally { setSaving(null) }
  }

  const toggleActive = async (u: AppUser) => {
    if (!window.confirm(`${u.is_active ? 'Deactivate' : 'Reactivate'} ${u.email}?`)) return
    setSaving(u.id)
    try {
      const r = await fetch(`/api/users/${u.id}`, {
        method: 'PATCH', headers: authH(),
        body: JSON.stringify({ is_active: !u.is_active }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      toast.success(`${u.email} ${u.is_active ? 'deactivated' : 'reactivated'}`)
      setUsers(us => us.map(x => x.id === u.id ? { ...x, is_active: !u.is_active } : x))
    } catch { toast.error('Action failed') }
    finally { setSaving(null) }
  }

  const resetPassword = async (u: AppUser) => {
    if (!window.confirm(`Reset ${u.email}'s password? A new temporary password will be generated.`)) return
    setSaving(u.id)
    try {
      const r = await fetch(`/api/users/${u.id}/reset-password`, { method: 'POST', headers: authH(), body: '{}' })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(data.detail || data.error || `HTTP ${r.status}`)
      setResetResult({ email: u.email, password: data.new_password })
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Password reset failed')
    } finally { setSaving(null) }
  }

  // Filters
  const filtered = users.filter(u => {
    const q = search.toLowerCase()
    const matchSearch = !q || u.email.toLowerCase().includes(q) || (u.name || '').toLowerCase().includes(q)
    const matchRole   = !roleFilter || u.role === roleFilter
    return matchSearch && matchRole
  })

  const stats = {
    total:  users.length,
    active: users.filter(u => u.is_active).length,
    byRole: ROLES.reduce((acc, r) => { acc[r] = users.filter(u => u.role === r).length; return acc }, {} as Record<Role, number>),
  }

  const thStyle: React.CSSProperties = { padding: '11px 16px', textAlign: 'left', fontSize: 11, fontWeight: 700, color: '#64748b', letterSpacing: '0.05em', whiteSpace: 'nowrap' }
  const tdStyle: React.CSSProperties = { padding: '13px 16px', fontSize: 13, verticalAlign: 'middle' }
  const AVATAR_COLORS = ['#3b82f6', '#6366f1', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6']

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, width: '100%' }}>
      {inviteOpen && (
        <InviteModal onClose={() => setInviteOpen(false)} onSave={() => { setInviteOpen(false); load() }} />
      )}
      {resetResult && (
        <ResetPasswordModal email={resetResult.email} password={resetResult.password} onClose={() => setResetResult(null)} />
      )}

      {/* Page header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 38, height: 38, borderRadius: 10, background: 'rgba(99,102,241,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Shield size={18} color="#6366f1" />
            </div>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>User Management</h1>
          </div>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 6, marginLeft: 48 }}>
            {loading ? 'Loading...' : `${stats.total} users · ${stats.active} active`}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={load}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#64748b', fontSize: 13, cursor: 'pointer' }}>
            <RefreshCw size={13} />
          </button>
          <button onClick={() => setInviteOpen(true)}
            style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '9px 18px', borderRadius: 9, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 600, cursor: 'pointer', boxShadow: '0 2px 8px rgba(59,130,246,0.35)' }}>
            <Plus size={15} /> Add User
          </button>
        </div>
      </div>

      {/* Stat chips */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {ROLES.map(r => {
          const m = ROLE_META[r]
          const cnt = stats.byRole[r] || 0
          if (!cnt) return null
          return (
            <button key={r} onClick={() => setRoleFilter(roleFilter === r ? '' : r)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px',
                borderRadius: 9, border: `1.5px solid ${roleFilter === r ? m.color : '#e2e8f0'}`,
                background: roleFilter === r ? m.bg : '#fff',
                cursor: 'pointer', transition: 'all 0.15s',
              }}>
              <span>{m.icon}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: roleFilter === r ? m.color : '#374151' }}>
                {r.charAt(0).toUpperCase() + r.slice(1)}
              </span>
              <span style={{ fontSize: 12, padding: '1px 7px', borderRadius: 999, background: m.bg, color: m.color, fontWeight: 700 }}>{cnt}</span>
            </button>
          )
        })}
        {roleFilter && (
          <button onClick={() => setRoleFilter('')}
            style={{ padding: '8px 12px', borderRadius: 9, border: '1px solid rgba(239,68,68,0.2)', background: 'transparent', color: '#f87171', fontSize: 12, cursor: 'pointer' }}>
            Clear filter ×
          </button>
        )}
      </div>

      {/* Search */}
      <div style={{ position: 'relative', maxWidth: 340 }}>
        <Search size={13} style={{ position: 'absolute', left: 11, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8' }} />
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by name or email…"
          style={{ width: '100%', paddingLeft: 32, paddingRight: 12, paddingTop: 8, paddingBottom: 8, borderRadius: 8, border: '1px solid #d1d5db', background: '#fff', fontSize: 13, color: '#0f172a', outline: 'none', boxSizing: 'border-box' }}
          onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
          onBlur={e => e.currentTarget.style.borderColor = '#d1d5db'} />
      </div>

      {/* Table */}
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 14, overflow: 'hidden', boxShadow: '0 1px 4px rgba(0,0,0,0.06)', background: '#fff' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 880 }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                <th style={thStyle}>USER</th>
                <th style={thStyle}>ROLE</th>
                <th style={thStyle}>STATUS</th>
                <th style={thStyle}>LAST LOGIN</th>
                <th style={thStyle}>JOINED</th>
                <th style={{ ...thStyle, width: 230 }}>ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={6} style={{ padding: '50px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>Loading users…</td></tr>
              )}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={6} style={{ padding: '50px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>No users found.</td></tr>
              )}
              {!loading && filtered.map((u, i) => {
                const isSelf    = me?.id === u.id
                const isSaving  = saving === u.id
                const canChange = !isSelf && me?.role === 'owner' || (me?.role === 'admin' && u.role !== 'owner')
                const avatarColor = AVATAR_COLORS[i % AVATAR_COLORS.length]

                return (
                  <tr key={u.id}
                    style={{ borderBottom: '1px solid #f1f5f9', transition: 'background 0.12s', opacity: isSaving ? 0.6 : 1 }}
                    onMouseEnter={e => e.currentTarget.style.background = '#fafbff'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>

                    {/* User */}
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <div style={{ width: 36, height: 36, borderRadius: '50%', background: avatarColor, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700, color: 'white', flexShrink: 0 }}>
                          {(u.name || u.email || '?')[0].toUpperCase()}
                        </div>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>
                            {u.name || '—'}
                            {isSelf && <span style={{ marginLeft: 6, fontSize: 10, padding: '1px 6px', borderRadius: 4, background: 'rgba(59,130,246,0.12)', color: '#3b82f6' }}>you</span>}
                          </div>
                          <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{u.email}</div>
                        </div>
                      </div>
                    </td>

                    {/* Role */}
                    <td style={tdStyle}>
                      <RolePicker
                        user={u}
                        disabled={!canChange || isSaving}
                        onChange={role => changeRole(u, role)}
                      />
                    </td>

                    {/* Status */}
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                        <div style={{ width: 7, height: 7, borderRadius: '50%', background: u.is_active ? '#10b981' : '#ef4444', flexShrink: 0 }} />
                        <span style={{ fontSize: 12, color: u.is_active ? '#10b981' : '#ef4444', fontWeight: 500 }}>
                          {u.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </div>
                    </td>

                    {/* Last login */}
                    <td style={{ ...tdStyle, fontSize: 12, color: '#64748b' }}>
                      {u.last_login ? new Date(u.last_login).toLocaleDateString() : <span style={{ color: '#cbd5e1' }}>Never</span>}
                    </td>

                    {/* Joined */}
                    <td style={{ ...tdStyle, fontSize: 12, color: '#94a3b8' }}>
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                    </td>

                    {/* Actions */}
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        {canChange && (
                          <button
                            onClick={() => resetPassword(u)}
                            disabled={isSaving}
                            title="Reset password"
                            style={{
                              display: 'flex', alignItems: 'center', gap: 5,
                              padding: '6px 12px', borderRadius: 7, fontSize: 12, fontWeight: 500, cursor: isSaving ? 'not-allowed' : 'pointer',
                              border: '1px solid rgba(59,130,246,0.25)',
                              background: 'transparent', color: '#3b82f6',
                              transition: 'background 0.12s',
                            }}
                            onMouseEnter={e => e.currentTarget.style.background = 'rgba(59,130,246,0.07)'}
                            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                            <KeyRound size={12} /> Reset password
                          </button>
                        )}
                        {!isSelf && (
                          <button
                            onClick={() => toggleActive(u)}
                            disabled={isSaving}
                            title={u.is_active ? 'Deactivate user' : 'Reactivate user'}
                            style={{
                              display: 'flex', alignItems: 'center', gap: 5,
                              padding: '6px 12px', borderRadius: 7, fontSize: 12, fontWeight: 500, cursor: isSaving ? 'not-allowed' : 'pointer',
                              border: `1px solid ${u.is_active ? 'rgba(239,68,68,0.25)' : 'rgba(16,185,129,0.25)'}`,
                              background: 'transparent',
                              color: u.is_active ? '#ef4444' : '#10b981',
                              transition: 'background 0.12s',
                            }}
                            onMouseEnter={e => e.currentTarget.style.background = u.is_active ? 'rgba(239,68,68,0.07)' : 'rgba(16,185,129,0.07)'}
                            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                            {u.is_active ? <><UserX size={12} /> Deactivate</> : <><UserCheck size={12} /> Reactivate</>}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div style={{ padding: '12px 18px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', fontSize: 12, color: '#94a3b8', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Showing {filtered.length} of {stats.total} users</span>
          <span>{stats.active} active · {stats.total - stats.active} inactive</span>
        </div>
      </div>

      {/* Role reference card */}
      <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 14, padding: '18px 22px', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', letterSpacing: '0.07em', marginBottom: 14 }}>ROLE REFERENCE</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 }}>
          {ROLES.map(r => {
            const m = ROLE_META[r]
            return (
              <div key={r} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderRadius: 10, background: m.bg, border: `1px solid ${m.color}33` }}>
                <span style={{ fontSize: 18 }}>{m.icon}</span>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: m.color }}>{r.charAt(0).toUpperCase() + r.slice(1)}</div>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{m.desc}</div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
