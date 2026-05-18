import { AlertTriangle } from 'lucide-react'

interface Props {
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export default function ConfirmDialog({ title, message, confirmLabel = 'Confirm', danger = false, onConfirm, onCancel }: Props) {
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }} onClick={onCancel}>
      <div className="animate-fadeIn" style={{ background: '#1c2333', border: '1px solid #253047', borderRadius: 14, padding: 28, maxWidth: 420, width: '90%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 20 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: danger ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <AlertTriangle size={18} color={danger ? '#ef4444' : '#f59e0b'} />
          </div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: 'white', marginBottom: 6 }}>{title}</div>
            <div style={{ fontSize: 13, color: '#94a3b8', lineHeight: 1.6 }}>{message}</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{ padding: '8px 18px', borderRadius: 8, border: '1px solid #253047', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer', fontWeight: 500 }}>
            Cancel
          </button>
          <button onClick={() => { onConfirm(); onCancel() }} style={{ padding: '8px 18px', borderRadius: 8, border: 'none', background: danger ? '#ef4444' : '#3b82f6', color: 'white', fontSize: 13, cursor: 'pointer', fontWeight: 500 }}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
