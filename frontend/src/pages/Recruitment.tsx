import { useState } from 'react'
import { Lock, Users, Briefcase, GitBranch, Calendar, CheckCircle2, Bell } from 'lucide-react'

const card: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: 24,
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}

const FEATURES = [
  { icon: Users,      label: 'Candidate discovery configuration',       desc: 'Configure search criteria, scoring weights, and source integrations.' },
  { icon: Briefcase,  label: 'Role management UI',                       desc: 'Create, edit, and close open roles with full RBAC controls.' },
  { icon: GitBranch,  label: 'Candidate pipeline (RBAC-gated)',          desc: 'Kanban-style pipeline with stage transitions and recruiter assignments.' },
  { icon: Calendar,   label: 'Event-sourced candidate tracking',         desc: 'Full audit trail of every candidate action, note, and status change.' },
]

export default function Recruitment() {
  const [notified, setNotified] = useState(false)

  const handleNotify = () => {
    setNotified(true)
    setTimeout(() => setNotified(false), 4000)
  }

  return (
    <div style={{ minHeight: '70vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 32 }}>
      <div style={{ maxWidth: 560, width: '100%', textAlign: 'center' }}>
        {/* Lock icon */}
        <div style={{
          width: 72, height: 72, borderRadius: 20, background: '#f1f5f9',
          border: '2px solid #e2e8f0', display: 'flex', alignItems: 'center',
          justifyContent: 'center', margin: '0 auto 24px',
        }}>
          <Lock size={30} color="#0f172a" strokeWidth={1.75} />
        </div>

        {/* Title */}
        <h1 style={{ fontSize: 26, fontWeight: 700, color: '#0f172a', margin: '0 0 10px' }}>
          Recruitment Module
        </h1>

        {/* Subtitle */}
        <p style={{ fontSize: 16, color: '#475569', margin: '0 0 8px', fontWeight: 500 }}>
          Candidate discovery, role management, and pipeline — coming in the next sprint.
        </p>

        {/* Description */}
        <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 32px', lineHeight: 1.6 }}>
          This module is restricted to admin, owner, and recruitment roles. Access is granted automatically based on your assigned role.
        </p>

        {/* Feature list card */}
        <div style={{ ...card, textAlign: 'left', marginBottom: 28 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#374151', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 16 }}>
            What's included
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {FEATURES.map(({ icon: Icon, label, desc }) => (
              <div key={label} style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
                <div style={{
                  width: 36, height: 36, borderRadius: 8, background: '#f1f5f9',
                  border: '1px solid #e2e8f0', display: 'flex', alignItems: 'center',
                  justifyContent: 'center', flexShrink: 0,
                }}>
                  <Icon size={16} color="#2563eb" />
                </div>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', marginBottom: 2 }}>{label}</div>
                  <div style={{ fontSize: 13, color: '#64748b', lineHeight: 1.5 }}>{desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Notify button */}
        {notified ? (
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '11px 24px', borderRadius: 8, background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#10b981', fontSize: 14, fontWeight: 600 }}>
            <CheckCircle2 size={16} />
            You'll be notified when this module launches.
          </div>
        ) : (
          <button
            onClick={handleNotify}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 8,
              padding: '11px 24px', borderRadius: 8, background: '#0f172a',
              color: '#fff', border: 'none', cursor: 'pointer', fontSize: 14,
              fontWeight: 600, transition: 'background 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = '#1e293b')}
            onMouseLeave={e => (e.currentTarget.style.background = '#0f172a')}
          >
            <Bell size={15} />
            Notify me when ready
          </button>
        )}
      </div>
    </div>
  )
}
