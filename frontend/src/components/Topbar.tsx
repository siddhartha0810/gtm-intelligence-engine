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
    <div ref={ref} style={{ position: 'fixed', top: rect ? rect.bottom + 8 : 64, right: rect ? window.innerWidth - rect.right : 16, zIndex: 500, background: '#1c2333', border: '1px solid #253047', borderRadius: 12, boxShadow: '0 12px 40px rgba(0,0,0,0.5)', minWidth: 260 }}>
      {children}
    </div>
  )
}

interface TopbarProps { onCmdK: () => void }

export default function Topbar({ onCmdK }: TopbarProps) {
  const [notifOpen, setNotifOpen] = useState(false)
  const [userOpen, setUserOpen] = useState(false)
  const [unread, setUnread] = useState(3)
  const notifRef = useRef<HTMLButtonElement>(null)
  const userRef = useRef<HTMLButtonElement>(null)
  const navigate = useNavigate()

  return (
    <header style={{ height: 56, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', background: '#111827', borderBottom: '1px solid #1f2d45', flexShrink: 0, position: 'relative', zIndex: 100 }}>

      {/* Search */}
      <button onClick={onCmdK} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px', borderRadius: 8, cursor: 'pointer', background: 'rgba(255,255,255,0.04)', border: '1px solid #1f2d45', color: '#64748b', width: 280 }}
        onMouseEnter={e => e.currentTarget.style.borderColor = '#3b82f6'}
        onMouseLeave={e => e.currentTarget.style.borderColor = '#1f2d45'}>
        <Search size={13} color="#64748b" />
        <span style={{ flex: 1, textAlign: 'left', fontSize: 13 }}>Search or jump to...</span>
        <kbd style={{ fontSize: 11, padding: '1px 6px', borderRadius: 4, fontFamily: 'monospace', background: '#1e293b', color: '#475569', border: '1px solid #253047' }}>⌘K</kbd>
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>

        {/* Notification bell */}
        <button
          ref={notifRef}
          onClick={() => { setNotifOpen(v => !v); setUserOpen(false); if (unread) setUnread(0) }}
          style={{ position: 'relative', width: 34, height: 34, borderRadius: 8, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', background: notifOpen ? 'rgba(59,130,246,0.15)' : 'transparent', color: notifOpen ? '#60a5fa' : '#64748b', transition: 'background 0.15s' }}
          onMouseEnter={e => { if (!notifOpen) e.currentTarget.style.background = 'rgba(255,255,255,0.06)' }}
          onMouseLeave={e => { if (!notifOpen) e.currentTarget.style.background = 'transparent' }}
        >
          <Bell size={15} />
          {unread > 0 && <span style={{ position: 'absolute', top: 5, right: 5, width: 7, height: 7, borderRadius: '50%', background: '#3b82f6', border: '1.5px solid #111827' }} />}
        </button>

        {notifOpen && (
          <Dropdown onClose={() => setNotifOpen(false)} anchorRef={notifRef}>
            <div style={{ padding: '14px 16px', borderBottom: '1px solid #253047', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: 'white' }}>Notifications</span>
              <button onClick={() => setUnread(0)} style={{ fontSize: 11, color: '#3b82f6', background: 'none', border: 'none', cursor: 'pointer' }}>Mark all read</button>
            </div>
            {NOTIFICATIONS.map((n, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '12px 16px', borderBottom: i < NOTIFICATIONS.length - 1 ? '1px solid #1a2438' : 'none', cursor: 'pointer' }}
                onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                <div style={{ width: 28, height: 28, borderRadius: 7, background: `${n.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <n.icon size={13} color={n.color} />
                </div>
                <div>
                  <div style={{ fontSize: 12, color: '#e2e8f0' }}>{n.msg}</div>
                  <div style={{ fontSize: 11, color: '#374151', marginTop: 3 }}>{n.time}</div>
                </div>
              </div>
            ))}
            <div style={{ padding: '10px 16px' }}>
              <button onClick={() => setNotifOpen(false)} style={{ width: '100%', padding: '7px 0', borderRadius: 7, border: '1px solid #253047', background: 'transparent', color: '#64748b', fontSize: 12, cursor: 'pointer' }}>View all notifications</button>
            </div>
          </Dropdown>
        )}

        <div style={{ width: 1, height: 20, background: '#1f2d45' }} />

        {/* User */}
        <button
          ref={userRef}
          onClick={() => { setUserOpen(v => !v); setNotifOpen(false) }}
          style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px', borderRadius: 8, border: 'none', cursor: 'pointer', background: userOpen ? 'rgba(255,255,255,0.06)' : 'transparent', transition: 'background 0.15s' }}
          onMouseEnter={e => { if (!userOpen) e.currentTarget.style.background = 'rgba(255,255,255,0.06)' }}
          onMouseLeave={e => { if (!userOpen) e.currentTarget.style.background = 'transparent' }}
        >
          <div style={{ width: 28, height: 28, borderRadius: '50%', background: 'linear-gradient(135deg, #3b82f6, #6366f1)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, color: 'white' }}>S</div>
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: '#e2e8f0', lineHeight: 1 }}>Sid</div>
            <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>Admin</div>
          </div>
          <ChevronDown size={12} color="#475569" style={{ transition: 'transform 0.2s', transform: userOpen ? 'rotate(180deg)' : 'rotate(0deg)' }} />
        </button>

        {userOpen && (
          <Dropdown onClose={() => setUserOpen(false)} anchorRef={userRef}>
            <div style={{ padding: '14px 16px', borderBottom: '1px solid #253047' }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'white' }}>Sidhartha</div>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>siddharthakothi@gmail.com</div>
              <span style={{ display: 'inline-block', marginTop: 6, fontSize: 11, padding: '2px 8px', borderRadius: 999, background: 'rgba(59,130,246,0.15)', color: '#60a5fa' }}>Admin</span>
            </div>
            {[
              { icon: User, label: 'My Profile', action: () => {} },
              { icon: Settings, label: 'Settings & API', action: () => { navigate('/settings'); setUserOpen(false) } },
            ].map((item, i) => (
              <button key={i} onClick={item.action} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', fontSize: 13, textAlign: 'left' }}
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; e.currentTarget.style.color = 'white' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = '#94a3b8' }}>
                <item.icon size={14} /> {item.label}
              </button>
            ))}
            <div style={{ borderTop: '1px solid #253047', marginTop: 4 }}>
              <button style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444', fontSize: 13, textAlign: 'left' }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.08)'}
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
