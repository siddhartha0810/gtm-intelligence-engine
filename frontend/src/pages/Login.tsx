import { useState } from 'react'
import type { User } from '../types'
import { Eye, EyeOff, Zap } from 'lucide-react'

interface Props { onLogin: (token: string, user: User) => void }

export default function Login({ onLogin }: Props) {
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw]     = useState(false)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const [isRegister, setIsRegister] = useState(false)
  const [name, setName]         = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      const url  = isRegister ? '/api/auth/register' : '/api/auth/login'
      const body: { email: string; password: string; name?: string } = { email, password }
      if (isRegister) body.name = name
      const res  = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.error || 'Authentication failed'); return }
      localStorage.setItem('token', data.token)
      localStorage.setItem('user', JSON.stringify(data.user))
      onLogin(data.token, data.user)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Network error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', width: '100vw', background: '#f1f5f9', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ width: '100%', maxWidth: 420 }}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 56, height: 56, borderRadius: 16, background: 'linear-gradient(135deg,#3b82f6,#6366f1)', marginBottom: 16 }}>
            <Zap size={28} color="#fff" />
          </div>
          <h1 style={{ color: '#0f172a', fontSize: 24, fontWeight: 700, margin: 0 }}>Inoapps Data Tool</h1>
          <p style={{ color: '#64748b', fontSize: 14, marginTop: 6 }}>Oracle Intelligence Platform</p>
        </div>

        {/* Card */}
        <div style={{ background: '#ffffff', borderRadius: 16, border: '1px solid #e2e8f0', padding: '32px 28px', boxShadow: '0 4px 24px rgba(0,0,0,0.08)' }}>
          <h2 style={{ color: '#0f172a', fontSize: 18, fontWeight: 600, margin: '0 0 24px' }}>
            {isRegister ? 'Create account' : 'Sign in to your account'}
          </h2>

          {error && (
            <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '10px 14px', color: '#ef4444', fontSize: 13, marginBottom: 16 }}>
              {error}
            </div>
          )}

          <form onSubmit={submit}>
            {isRegister && (
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: 'block', color: '#374151', fontSize: 13, fontWeight: 500, marginBottom: 6 }}>Full Name</label>
                <input
                  value={name} onChange={e => setName(e.target.value)}
                  placeholder="Jane Smith" required
                  style={{ width: '100%', boxSizing: 'border-box', background: '#ffffff', border: '1px solid #d1d5db', borderRadius: 8, padding: '10px 14px', color: '#0f172a', fontSize: 14, outline: 'none' }}
                  onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
                  onBlur={e => e.currentTarget.style.borderColor = '#d1d5db'}
                />
              </div>
            )}

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', color: '#374151', fontSize: 13, fontWeight: 500, marginBottom: 6 }}>Email address</label>
              <input
                type="email" value={email} onChange={e => setEmail(e.target.value)}
                placeholder="you@yourcompany.com" required autoFocus
                style={{ width: '100%', boxSizing: 'border-box', background: '#ffffff', border: '1px solid #d1d5db', borderRadius: 8, padding: '10px 14px', color: '#0f172a', fontSize: 14, outline: 'none' }}
                onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
                onBlur={e => e.currentTarget.style.borderColor = '#d1d5db'}
              />
            </div>

            <div style={{ marginBottom: 24, position: 'relative' }}>
              <label style={{ display: 'block', color: '#374151', fontSize: 13, fontWeight: 500, marginBottom: 6 }}>Password</label>
              <input
                type={showPw ? 'text' : 'password'} value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••" required minLength={8}
                style={{ width: '100%', boxSizing: 'border-box', background: '#ffffff', border: '1px solid #d1d5db', borderRadius: 8, padding: '10px 40px 10px 14px', color: '#0f172a', fontSize: 14, outline: 'none' }}
                onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
                onBlur={e => e.currentTarget.style.borderColor = '#d1d5db'}
              />
              <button type="button" onClick={() => setShowPw(v => !v)}
                style={{ position: 'absolute', right: 12, top: 34, background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', padding: 0 }}>
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>

            <button type="submit" disabled={loading}
              style={{ width: '100%', background: loading ? '#cbd5e1' : 'linear-gradient(135deg,#3b82f6,#6366f1)', border: 'none', borderRadius: 8, padding: '11px 0', color: '#fff', fontSize: 15, fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer' }}>
              {loading ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in'}
            </button>
          </form>

          <div style={{ textAlign: 'center', marginTop: 20 }}>
            <button onClick={() => { setIsRegister(v => !v); setError('') }}
              style={{ background: 'none', border: 'none', color: '#2563eb', fontSize: 13, cursor: 'pointer' }}>
              {isRegister ? 'Already have an account? Sign in' : "Don't have an account? Register"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
