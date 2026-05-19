import { useState } from 'react'
import { User, Mail, Shield, Key, Save, CheckCircle2, AlertCircle } from 'lucide-react'
import { toast } from '../components/Toast'

interface ProfileProps {
  user?: any
}

export default function Profile({ user }: ProfileProps) {
  const displayName  = user?.name  || user?.email || 'User'
  const displayEmail = user?.email || ''
  const displayRole  = user?.role  ? user.role.charAt(0).toUpperCase() + user.role.slice(1) : 'User'
  const displayShort = displayName.charAt(0).toUpperCase()

  const [currentPw,  setCurrentPw]  = useState('')
  const [newPw,      setNewPw]      = useState('')
  const [confirmPw,  setConfirmPw]  = useState('')
  const [saving,     setSaving]     = useState(false)
  const [pwError,    setPwError]    = useState('')

  const ROLE_COLORS: Record<string, { bg: string; color: string }> = {
    owner:       { bg: 'rgba(124,58,237,0.12)',  color: '#7c3aed' },
    admin:       { bg: 'rgba(99,102,241,0.12)',  color: '#6366f1' },
    analyst:     { bg: 'rgba(59,130,246,0.12)',  color: '#2563eb' },
    recruitment: { bg: 'rgba(239,68,68,0.12)',   color: '#dc2626' },
    viewer:      { bg: 'rgba(107,114,128,0.12)', color: '#6b7280' },
  }
  const roleStyle = ROLE_COLORS[user?.role || ''] ?? { bg: 'rgba(59,130,246,0.12)', color: '#2563eb' }

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault()
    setPwError('')
    if (!currentPw || !newPw || !confirmPw) { setPwError('All fields are required.'); return }
    if (newPw.length < 8) { setPwError('New password must be at least 8 characters.'); return }
    if (newPw !== confirmPw) { setPwError('New passwords do not match.'); return }

    setSaving(true)
    try {
      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
        },
        body: JSON.stringify({ old_password: currentPw, new_password: newPw }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setPwError(err.detail || 'Password change failed.')
      } else {
        toast.success('Password updated successfully')
        setCurrentPw(''); setNewPw(''); setConfirmPw('')
      }
    } catch {
      setPwError('Network error. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const cardStyle: React.CSSProperties = {
    background: '#ffffff',
    border: '1px solid #e2e8f0',
    borderRadius: 16,
    padding: 28,
    boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
  }
  const labelStyle: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#64748b', letterSpacing: '0.04em', marginBottom: 6 }
  const valueStyle: React.CSSProperties = { fontSize: 14, color: '#0f172a', fontWeight: 500 }
  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '9px 14px', borderRadius: 8,
    border: '1px solid #d1d5db', background: '#f8fafc',
    fontSize: 13, color: '#0f172a', outline: 'none',
    boxSizing: 'border-box',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 760, width: '100%' }}>

      {/* Header */}
      <div>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>My Profile</h1>
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>View your account information and manage your password.</p>
      </div>

      {/* Identity card */}
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
          <div style={{
            width: 72, height: 72, borderRadius: '50%',
            background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 28, fontWeight: 700, color: 'white', flexShrink: 0,
          }}>{displayShort}</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>{displayName}</div>
            <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>{displayEmail}</div>
            <span style={{
              display: 'inline-block', marginTop: 8, fontSize: 12, padding: '3px 12px',
              borderRadius: 999, fontWeight: 600,
              background: roleStyle.bg, color: roleStyle.color,
            }}>{displayRole}</span>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 20, marginTop: 28, paddingTop: 24, borderTop: '1px solid #f1f5f9' }}>
          <div>
            <div style={labelStyle}><User size={11} style={{ marginRight: 5, verticalAlign: 'middle' }} />DISPLAY NAME</div>
            <div style={valueStyle}>{displayName}</div>
          </div>
          <div>
            <div style={labelStyle}><Mail size={11} style={{ marginRight: 5, verticalAlign: 'middle' }} />EMAIL ADDRESS</div>
            <div style={valueStyle}>{displayEmail || '—'}</div>
          </div>
          <div>
            <div style={labelStyle}><Shield size={11} style={{ marginRight: 5, verticalAlign: 'middle' }} />ROLE</div>
            <div style={valueStyle}>{displayRole}</div>
          </div>
        </div>
      </div>

      {/* Change password card */}
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 22 }}>
          <div style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(59,130,246,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Key size={16} color="#3b82f6" />
          </div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: '#0f172a' }}>Change Password</div>
            <div style={{ fontSize: 12, color: '#64748b' }}>Use a strong password of at least 8 characters</div>
          </div>
        </div>

        <form onSubmit={handlePasswordChange} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <label style={labelStyle}>CURRENT PASSWORD</label>
            <input type="password" value={currentPw} onChange={e => setCurrentPw(e.target.value)}
              placeholder="Enter current password" style={inputStyle}
              onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
              onBlur={e => e.currentTarget.style.borderColor = '#d1d5db'} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div>
              <label style={labelStyle}>NEW PASSWORD</label>
              <input type="password" value={newPw} onChange={e => setNewPw(e.target.value)}
                placeholder="Min 8 characters" style={inputStyle}
                onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
                onBlur={e => e.currentTarget.style.borderColor = '#d1d5db'} />
            </div>
            <div>
              <label style={labelStyle}>CONFIRM NEW PASSWORD</label>
              <input type="password" value={confirmPw} onChange={e => setConfirmPw(e.target.value)}
                placeholder="Repeat new password" style={inputStyle}
                onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
                onBlur={e => e.currentTarget.style.borderColor = '#d1d5db'} />
            </div>
          </div>

          {pwError && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderRadius: 8, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', color: '#ef4444', fontSize: 13 }}>
              <AlertCircle size={14} /> {pwError}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button type="submit" disabled={saving}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 20px', borderRadius: 9, background: saving ? '#93c5fd' : '#3b82f6', border: 'none', color: 'white', fontSize: 13, fontWeight: 600, cursor: saving ? 'not-allowed' : 'pointer', transition: 'background 0.15s' }}>
              {saving ? <><RefreshCwIcon /> Saving...</> : <><Save size={14} /> Update Password</>}
            </button>
          </div>
        </form>
      </div>

      {/* Permissions card */}
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
          <div style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(99,102,241,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Shield size={16} color="#6366f1" />
          </div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: '#0f172a' }}>Permissions</div>
            <div style={{ fontSize: 12, color: '#64748b' }}>Access rights granted to your role</div>
          </div>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {getPermissions(user?.role).map(p => (
            <div key={p} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', borderRadius: 8, background: '#f8fafc', border: '1px solid #e2e8f0', fontSize: 12, color: '#374151' }}>
              <CheckCircle2 size={12} color="#10b981" /> {p}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function RefreshCwIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ animation: 'spin 1s linear infinite' }}>
      <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  )
}

function getPermissions(role?: string): string[] {
  const base = ['View Companies', 'View Contacts', 'View Reports', 'Search & Export']
  const analyst = [...base, 'Edit Records', 'Import Lists', 'Review Queue', 'Intent Data']
  const admin   = [...analyst, 'Manage Users', 'Engine Control', 'HubSpot Sync', 'Audit Logs', 'API Settings']
  const owner   = [...admin, 'Delete Records', 'Role Management', 'System Configuration']
  const rec     = [...base, 'Recruitment Module']
  switch (role) {
    case 'owner':       return owner
    case 'admin':       return admin
    case 'analyst':     return analyst
    case 'recruitment': return rec
    default:            return base
  }
}
