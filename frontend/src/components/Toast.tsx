import { useState, useEffect, useCallback } from 'react'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'

export type ToastType = 'success' | 'error' | 'info'
export interface Toast { id: number; message: string; type: ToastType }

let toastId = 0
let externalAdd: ((msg: string, type: ToastType) => void) | null = null

export const toast = {
  success: (msg: string) => externalAdd?.(msg, 'success'),
  error: (msg: string) => externalAdd?.(msg, 'error'),
  info: (msg: string) => externalAdd?.(msg, 'info'),
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([])

  const add = useCallback((message: string, type: ToastType) => {
    const id = ++toastId
    setToasts(t => [...t, { id, message, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3500)
  }, [])

  useEffect(() => { externalAdd = add; return () => { externalAdd = null } }, [add])

  const icons = { success: CheckCircle2, error: AlertCircle, info: Info }
  const colors = { success: '#10b981', error: '#ef4444', info: '#3b82f6' }

  return (
    <div style={{ position: 'fixed', bottom: 24, right: 24, zIndex: 9999, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {toasts.map(t => {
        const Icon = icons[t.type]
        return (
          <div key={t.id} className="animate-fadeIn" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderRadius: 10, background: '#1c2333', border: `1px solid ${colors[t.type]}40`, boxShadow: '0 8px 24px rgba(0,0,0,0.4)', minWidth: 280, maxWidth: 380 }}>
            <Icon size={16} color={colors[t.type]} style={{ flexShrink: 0 }} />
            <span style={{ fontSize: 13, color: '#e2e8f0', flex: 1 }}>{t.message}</span>
            <button onClick={() => setToasts(x => x.filter(i => i.id !== t.id))} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#475569', display: 'flex', padding: 2, flexShrink: 0 }}>
              <X size={13} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
