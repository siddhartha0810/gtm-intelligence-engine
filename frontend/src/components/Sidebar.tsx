import type React from 'react'
import { NavLink } from 'react-router-dom'
import type { User } from '../types'
import {
  LayoutDashboard, Building2, Users, Cpu, ClipboardCheck,
  BarChart3, Settings, ChevronLeft, ChevronRight,
  Zap, Target, Layers, Upload, CalendarDays,
  ScrollText, UserCog, RefreshCw, PackageSearch, Search, Rocket, Crosshair, Activity, Sparkles
} from 'lucide-react'

interface NavItem {
  to: string
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; color?: string; style?: React.CSSProperties }>
  label: string
  badge?: string
}

interface NavItemG extends NavItem { min: number }        // min role rank to see
interface NavGroup {
  label: string
  stage?: number          // workflow stage number (rendered as a chip)
  items: NavItemG[]
}

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
  user?: User
}

// Role hierarchy: owner > admin > analyst > viewer/recruitment
const RANK: Record<string, number> = { owner: 4, admin: 3, analyst: 2, viewer: 1, recruitment: 1 }
const rankOf = (role?: string) => RANK[role ?? ''] ?? 0

// Workflow-oriented IA: the nav mirrors the GTM funnel — Hunt → Pipeline →
// Reach → Intelligence — so the sidebar reads as the process, not a module dump.
function buildNavGroups(user?: User): NavGroup[] {
  const r = rankOf(user?.role)
  const groups: NavGroup[] = [
    { label: 'OVERVIEW', items: [
      { to: '/dashboard', icon: LayoutDashboard, label: 'Command Center', min: 1 },
      { to: '/decision-intelligence', icon: Sparkles, label: 'Decision Intelligence', min: 1 },
    ]},
    { label: 'HUNT', stage: 1, items: [
      { to: '/campaign-builder', icon: Rocket,    label: 'Campaign Builder', min: 1 },
      { to: '/campaigns',        icon: Crosshair, label: 'Signal Campaigns', min: 2 },
      { to: '/engine-control',   icon: Cpu,       label: 'Engine Control',   min: 3 },
    ]},
    { label: 'PIPELINE', stage: 2, items: [
      { to: '/companies',    icon: Building2,     label: 'Companies',    min: 1 },
      { to: '/contacts',     icon: Users,         label: 'Contacts',     min: 1 },
      { to: '/review-queue', icon: ClipboardCheck, label: 'Review Queue', min: 2 },
    ]},
    { label: 'REACH', stage: 3, items: [
      { to: '/people-search', icon: Search,    label: 'People Search', min: 1 },
      { to: '/list-import',   icon: Upload,    label: 'List Import',   min: 2 },
      { to: '/hubspot-sync',  icon: RefreshCw, label: 'HubSpot Sync',  min: 3 },
    ]},
    { label: 'INTELLIGENCE', items: [
      { to: '/reporting',            icon: BarChart3,     label: 'Reporting',      min: 2 },
      { to: '/metrics',              icon: Activity,      label: 'System Metrics', min: 2 },
      { to: '/product-intelligence', icon: PackageSearch, label: 'Product Intel',  min: 1 },
      { to: '/intent-data',          icon: Target,        label: 'Intent Data',    min: 1 },
      { to: '/events',               icon: CalendarDays,  label: 'Events',         min: 1 },
    ]},
    { label: 'CONFIGURE', items: [
      { to: '/technology-profiles', icon: Layers,     label: 'Technology Profiles', min: 2 },
      { to: '/settings',            icon: Settings,   label: 'Settings & API',      min: 3 },
      { to: '/audit-logs',          icon: ScrollText, label: 'Audit Logs',          min: 3 },
      { to: '/user-management',     icon: UserCog,    label: 'User Management',     min: 4 },
    ]},
  ]

  return groups
    .map(g => ({ ...g, items: g.items.filter(it => r >= it.min) }))
    .filter(g => g.items.length > 0)
}

export default function Sidebar({ collapsed, onToggle, user }: SidebarProps) {
  const w = collapsed ? 64 : 240
  const groups = buildNavGroups(user)

  return (
    <aside style={{
      width: w, minWidth: w, maxWidth: w,
      height: '100vh',
      background: '#0f1e36',
      borderRight: '1px solid #1a3050',
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
        borderBottom: '1px solid #1a3050', flexShrink: 0,
        background: '#0a1628',
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
            <div style={{ fontSize: 13, fontWeight: 600, color: 'white', lineHeight: 1 }}>GTM Data Tool</div>
            <div style={{ fontSize: 11, color: '#4a7ab5', marginTop: 3 }}>Intelligence Hub</div>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, overflowY: 'auto', padding: '16px 8px' }}>
        {groups.map(group => (
          <div key={group.label} style={{ marginBottom: 20 }}>
            {!collapsed && (
              <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', color: '#4a7ab5', padding: '0 8px', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                {group.stage != null && (
                  <span style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    width: 14, height: 14, borderRadius: 4, fontSize: 9, fontWeight: 800,
                    background: 'rgba(59,130,246,0.22)', color: '#93c5fd', flexShrink: 0,
                  }}>{group.stage}</span>
                )}
                {group.label}
              </div>
            )}
            {collapsed && group.stage != null && (
              <div style={{ height: 1, background: '#1a3050', margin: '6px 8px 8px' }} />
            )}
            {group.items.map(item => (
              <NavLink
                key={item.to}
                to={item.to}
                style={({ isActive }: { isActive: boolean }) => ({
                  display: 'flex', alignItems: 'center',
                  gap: collapsed ? 0 : 10,
                  justifyContent: collapsed ? 'center' : 'flex-start',
                  padding: collapsed ? '10px 0' : '8px 10px',
                  borderRadius: 8,
                  textDecoration: 'none',
                  marginBottom: 2,
                  position: 'relative',
                  background: isActive ? 'rgba(59,130,246,0.18)' : 'transparent',
                  color: isActive ? '#93c5fd' : '#94b8d9',
                  transition: 'background 0.15s',
                })}
                onMouseEnter={(e: React.MouseEvent<HTMLAnchorElement>) => { const el = e.currentTarget as HTMLElement; if (!el.classList.contains('active')) el.style.background = 'rgba(255,255,255,0.06)' }}
                onMouseLeave={(e: React.MouseEvent<HTMLAnchorElement>) => { const el = e.currentTarget as HTMLElement; if (!el.classList.contains('active')) el.style.background = 'transparent' }}
              >
                {({ isActive }: { isActive: boolean }) => (
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
                    {!collapsed && item.badge && (
                      <span style={{ fontSize: 11, fontWeight: 600, padding: '1px 6px', borderRadius: 999, background: 'rgba(59,130,246,0.2)', color: '#93c5fd' }}>
                        {item.badge}
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
          height: 40, borderTop: '1px solid #1a3050',
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: '#7aadd4', fontSize: 12, flexShrink: 0,
          width: '100%'
        }}
      >
        {collapsed ? <ChevronRight size={14} /> : <><ChevronLeft size={14} /><span>Collapse</span></>}
      </button>
    </aside>
  )
}
