import { useState, useRef, useEffect } from 'react'
import { Search, Bell, ChevronDown, Settings, LogOut, User, CheckCircle2, Zap, Users } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

const NOTIFICATIONS = [
  { icon: CheckCircle2, color: '#10b981', msg: 'Enrichment complete: Rolls-Royce', time: '2m ago' },
  { icon: Zap, color: '#f59e0b', msg: 'Oracle scan found 14 new signals', time: '8m ago' },
  { icon: Users, color: '#3b82f6', msg: '23 contacts pushed to HubSpot', time: '15m ago' },
]

function Dropdown({ onClose, children, anchorRef }: { onClose: () => void; children: React.ReactNode; anchorRef: React.RefObject<HTMLElement | null> }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node) && !anchorRef.current?.contains(e.target as Node)) onClose() }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [onClose, anchorRef])
  const rect = anchorRef.current?.getBoundingClientRect()
  return (
    <div ref={ref} style={{ position: 'fixed', top: rect ? rect.bottom + 8 : 64, right: rect ? window.innerWidth - rect.right : 16, zIndex: 500, background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, boxShadow: '0 12px 40px rgba(0,0,0,0.12)', minWidth: 260 }}>
      {children}
    </div>
  )
}

interface TopbarProps {
  onCmdK: () => void
  user?: any
  onLogout?: () => void
}

export default function Topbar({ onCmdK, user, onLogout }: TopbarProps) {
  const [notifOpen, setNotifOpen] = useState(false)
  const [userOpen, setUserOpen]   = useState(false)
  const [unread, setUnread]       = useState(3)
  const notifRef = useRef<HTMLButtonElement>(null)
  const userRef  = useRef<HTMLButtonElement>(null)
  const navigate = useNavigate()

  const displayName  = user?.name  || user?.email || 'User'
  const displayShort = displayName.charAt(0).toUpperCase()
  const displayRole  = user?.role  ? user.role.charAt(0).toUpperCase() + user.role.slice(1) : 'User'
  const displayEmail = user?.email || ''

  return (
    <header style={{ height: 56, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', background: '#ffffff', borderBottom: '1px solid #e2e8f0', flexShrink: 0, position: 'relative', zIndex: 100 }}>

      {/* Search */}
      <button onClick={onCmdK} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px', borderRadius: 8, cursor: 'pointer', background: '#f8fafc', border: '1px solid #e2e8f0', color: '#94a3b8', width: 280 }}
        onMouseEnter={e => e.currentTarget.style.borderColor = '#3b82f6'}
        onMouseLeave={e => e.currentTarget.style.borderColor = '#e2e8f0'}>
        <Search size={13} color="#94a3b8" />
        <span style={{ flex: 1, textAlign: 'left', fontSize: 13 }}>Search or jump to...</span>
        <kbd style={{ fontSize: 11, padding: '1px 6px', borderRadius: 4, fontFamily: 'monospace', background: '#f1f5f9', color: '#64748b', border: '1px solid #d1d5db' }}>⌘K</kbd>
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>

        {/* Notification bell */}
        <button
          ref={notifRef}
          onClick={() => { setNotifOpen(v => !v); setUserOpen(false); if (unread) setUnread(0) }}
          style={{ position: 'relative', width: 34, height: 34, borderRadius: 8, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', background: notifOpen ? 'rgba(59,130,246,0.08)' : 'transparent', color: notifOpen ? '#3b82f6' : '#64748b', transition: 'background 0.15s' }}
          onMouseEnter={e => { if (!notifOpen) e.currentTarget.style.background = '#f8fafc' }}
          onMouseLeave={e => { if (!notifOpen) e.currentTarget.style.background = 'transparent' }}
        >
          <Bell size={15} />
          {unread > 0 && <span style={{ position: 'absolute', top: 5, right: 5, width: 7, height: 7, borderRadius: '50%', background: '#3b82f6', border: '1.5px solid #ffffff' }} />}
        </button>

        {notifOpen && (
          <Dropdown onClose={() => setNotifOpen(false)} anchorRef={notifRef}>
            <div style={{ padding: '14px 16px', borderBottom: '1px solid #f1f5f9', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>Notifications</span>
              <button onClick={() => setUnread(0)} style={{ fontSize: 11, color: '#3b82f6', background: 'none', border: 'none', cursor: 'pointer' }}>Mark all read</button>
            </div>
            {NOTIFICATIONS.map((n, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '12px 16px', borderBottom: i < NOTIFICATIONS.length - 1 ? '1px solid #f1f5f9' : 'none', cursor: 'pointer' }}
                onMouseEnter={e => (e.currentTarget.style.background = '#f8fafc')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                <div style={{ width: 28, height: 28, borderRadius: 7, background: `${n.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <n.icon size={13} color={n.color} />
                </div>
                <div>
                  <div style={{ fontSize: 12, color: '#0f172a' }}>{n.msg}</div>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>{n.time}</div>
                </div>
              </div>
            ))}
            <div style={{ padding: '10px 16px' }}>
              <button onClick={() => setNotifOpen(false)} style={{ width: '100%', padding: '7px 0', borderRadius: 7, border: '1px solid #e2e8f0', background: 'transparent', color: '#64748b', fontSize: 12, cursor: 'pointer' }}
                onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>View all notifications</button>
            </div>
          </Dropdown>
        )}

        <div style={{ width: 1, height: 20, background: '#e2e8f0' }} />

        {/* User */}
        <button
          ref={userRef}
          onClick={() => { setUserOpen(v => !v); setNotifOpen(false) }}
          style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px', borderRadius: 8, border: 'none', cursor: 'pointer', background: userOpen ? '#f8fafc' : 'transparent', transition: 'background 0.15s' }}
          onMouseEnter={e => { if (!userOpen) e.currentTarget.style.background = '#f8fafc' }}
          onMouseLeave={e => { if (!userOpen) e.currentTarget.style.background = 'transparent' }}
        >
          <div style={{ width: 28, height: 28, borderRadius: '50%', background: 'linear-gradient(135deg, #3b82f6, #6366f1)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, color: 'white' }}>{displayShort}</div>
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: '#0f172a', lineHeight: 1 }}>{displayName.split(' ')[0]}</div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{displayRole}</div>
          </div>
          <ChevronDown size={12} color="#64748b" style={{ transition: 'transform 0.2s', transform: userOpen ? 'rotate(180deg)' : 'rotate(0deg)' }} />
        </button>

        {userOpen && (
          <Dropdown onClose={() => setUserOpen(false)} anchorRef={userRef}>
            <div style={{ padding: '14px 16px', borderBottom: '1px solid #f1f5f9' }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{displayName}</div>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{displayEmail}</div>
              <span style={{ display: 'inline-block', marginTop: 6, fontSize: 11, padding: '2px 8px', borderRadius: 999, background: 'rgba(59,130,246,0.12)', color: '#2563eb' }}>{displayRole}</span>
            </div>
            {[
              { icon: User, label: 'My Profile', action: () => {} },
              { icon: Settings, label: 'Settings & API', action: () => { navigate('/settings'); setUserOpen(false) } },
            ].map((item, i) => (
              <button key={i} onClick={item.action} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', fontSize: 13, textAlign: 'left' }}
                onMouseEnter={e => { e.currentTarget.style.background = '#f8fafc'; e.currentTarget.style.color = '#0f172a' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = '#64748b' }}>
                <item.icon size={14} /> {item.label}
              </button>
            ))}
            <div style={{ borderTop: '1px solid #f1f5f9', marginTop: 4 }}>
              <button
                onClick={() => { setUserOpen(false); onLogout?.() }}
                style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444', fontSize: 13, textAlign: 'left' }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.06)'}
                onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                <LogOut size={14} /> Sign out
              </button>
            </div>
          </Dropdown>
        )}
      </div>
    </header>
  )
}
