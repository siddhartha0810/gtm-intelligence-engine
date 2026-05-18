import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Building2, Users, Cpu, ClipboardCheck,
  BarChart3, Settings, ChevronLeft, ChevronRight,
  Zap, Target, Layers, Upload, CalendarDays, Factory,
  ScrollText, UserCog, Shield
} from 'lucide-react'

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
  user?: any
  isAdmin?: boolean
}

const NAV_STATIC = [
  {
    label: 'OVERVIEW',
    items: [
      { to: '/dashboard',   icon: LayoutDashboard, label: 'Control Panel' },
      { to: '/review',      icon: ClipboardCheck,  label: 'Review Queue', badge: '12' },
    ]
  },
  {
    label: 'DATA MODULES',
    items: [
      { to: '/companies',         icon: Building2,   label: 'Companies' },
      { to: '/contacts',          icon: Users,        label: 'Contacts' },
      { to: '/intent',            icon: Target,       label: 'Intent Data' },
      { to: '/list-import',       icon: Upload,       label: 'List Import' },
      { to: '/events',            icon: CalendarDays, label: 'Events' },
      { to: '/manufacturer-intel',icon: Factory,      label: 'Manufacturer Intel' },
      { to: '/engine',            icon: Cpu,          label: 'Engine Control' },
    ]
  },
  {
    label: 'CONFIGURATION',
    items: [
      { to: '/technology-profiles', icon: Layers, label: 'Technology Profiles' },
    ]
  },
  {
    label: 'ANALYTICS',
    items: [
      { to: '/reporting', icon: BarChart3, label: 'Reporting' },
    ]
  },
  {
    label: 'SYSTEM',
    items: [
      { to: '/settings', icon: Settings, label: 'Settings & API' },
    ]
  },
]

const ADMIN_GROUP = {
  label: 'ADMIN',
  items: [
    { to: '/audit-logs',      icon: ScrollText, label: 'Audit Logs' },
    { to: '/user-management', icon: UserCog,    label: 'User Management' },
  ]
}

export default function Sidebar({ collapsed, onToggle, user, isAdmin }: SidebarProps) {
  const w = collapsed ? 64 : 240

  const groups = isAdmin ? [...NAV_STATIC, ADMIN_GROUP] : NAV_STATIC

  return (
    <aside style={{
      width: w, minWidth: w, maxWidth: w,
      height: '100vh',
      background: '#111827',
      borderRight: '1px solid #1f2d45',
      display: 'flex',
      flexDirection: 'column',
      transition: 'width 0.3s ease',
      overflow: 'hidden',
      flexShrink: 0,
    }}>
      {/* Logo */}
      <div style={{
        height: 56, display: 'flex', alignItems: 'center',
        gap: 12, padding: '0 16px',
        borderBottom: '1px solid #1f2d45', flexShrink: 0
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: 8, flexShrink: 0,
          background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
          display: 'flex', alignItems: 'center', justifyContent: 'center'
        }}>
          <Zap size={16} color="white" strokeWidth={2.5} />
        </div>
        {!collapsed && (
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'white', lineHeight: 1 }}>Inoapps</div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>Intelligence Hub</div>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, overflowY: 'auto', padding: '16px 8px' }}>
        {groups.map(group => (
          <div key={group.label} style={{ marginBottom: 20 }}>
            {!collapsed && (
              <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', color: group.label === 'ADMIN' ? '#7c3aed' : '#374151', padding: '0 8px', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
                {group.label === 'ADMIN' && <Shield size={9} color="#7c3aed" />}
                {group.label}
              </div>
            )}
            {group.items.map(item => (
              <NavLink
                key={item.to}
                to={item.to}
                style={({ isActive }) => ({
                  display: 'flex', alignItems: 'center',
                  gap: collapsed ? 0 : 10,
                  justifyContent: collapsed ? 'center' : 'flex-start',
                  padding: collapsed ? '10px 0' : '8px 10px',
                  borderRadius: 8,
                  textDecoration: 'none',
                  marginBottom: 2,
                  position: 'relative',
                  background: isActive ? 'rgba(59,130,246,0.15)' : 'transparent',
                  color: isActive ? '#93c5fd' : '#94a3b8',
                  transition: 'background 0.15s',
                })}
              >
                {({ isActive }) => (
                  <>
                    {isActive && !collapsed && (
                      <div style={{
                        position: 'absolute', left: 0, top: '50%', transform: 'translateY(-50%)',
                        width: 3, height: 20, background: '#3b82f6', borderRadius: '0 2px 2px 0'
                      }} />
                    )}
                    <item.icon size={16} strokeWidth={isActive ? 2 : 1.75} color={isActive ? '#60a5fa' : undefined} style={{ flexShrink: 0 }} />
                    {!collapsed && (
                      <span style={{ fontSize: 13, fontWeight: 500, flex: 1 }}>{item.label}</span>
                    )}
                    {!collapsed && (item as any).badge && (
                      <span style={{ fontSize: 11, fontWeight: 600, padding: '1px 6px', borderRadius: 999, background: 'rgba(59,130,246,0.2)', color: '#93c5fd' }}>
                        {(item as any).badge}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* Status */}
      {!collapsed && (
        <div style={{ padding: '0 10px 10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)' }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981', flexShrink: 0 }} className="animate-pulse-dot" />
            <span style={{ fontSize: 12, fontWeight: 500, color: '#34d399' }}>All systems operational</span>
          </div>
        </div>
      )}

      {/* Collapse toggle */}
      <button
        onClick={onToggle}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
          height: 40, borderTop: '1px solid #1f2d45',
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: '#475569', fontSize: 12, flexShrink: 0,
          width: '100%'
        }}
      >
        {collapsed ? <ChevronRight size={14} /> : <><ChevronLeft size={14} /><span>Collapse</span></>}
      </button>
    </aside>
  )
}
