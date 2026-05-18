import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, LayoutDashboard, Building2, Users, Cpu, ClipboardCheck, Target, BarChart3, Settings, ArrowRight } from 'lucide-react'

const COMMANDS = [
  { label: 'Control Panel', to: '/dashboard', icon: LayoutDashboard, category: 'Navigate' },
  { label: 'Companies', to: '/companies', icon: Building2, category: 'Navigate' },
  { label: 'Contacts', to: '/contacts', icon: Users, category: 'Navigate' },
  { label: 'Engine Control', to: '/engine', icon: Cpu, category: 'Navigate' },
  { label: 'Review Queue', to: '/review', icon: ClipboardCheck, category: 'Navigate' },
  { label: 'Intent Data', to: '/intent', icon: Target, category: 'Navigate' },
  { label: 'Reporting', to: '/reporting', icon: BarChart3, category: 'Navigate' },
  { label: 'Settings & API Keys', to: '/settings', icon: Settings, category: 'Navigate' },
]

export default function CommandPalette({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [idx, setIdx] = useState(0)
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)

  const filtered = COMMANDS.filter(c =>
    c.label.toLowerCase().includes(query.toLowerCase()) ||
    c.category.toLowerCase().includes(query.toLowerCase())
  )

  useEffect(() => { inputRef.current?.focus() }, [])
  useEffect(() => { setIdx(0) }, [query])

  const go = (to: string) => {
    navigate(to)
    onClose()
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setIdx(i => Math.min(i + 1, filtered.length - 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setIdx(i => Math.max(i - 1, 0)) }
    if (e.key === 'Enter' && filtered[idx]) go(filtered[idx].to)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-24"
      style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl overflow-hidden animate-fadeIn shadow-2xl"
        style={{ background: '#1c2333', border: '1px solid #253047' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Input */}
        <div className="flex items-center gap-3 px-4 border-b" style={{ borderColor: '#253047' }}>
          <Search size={16} style={{ color: '#64748b' }} />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Search pages, actions..."
            className="flex-1 py-4 text-sm bg-transparent outline-none"
            style={{ color: '#e2e8f0' }}
          />
          <kbd className="text-xs px-1.5 py-0.5 rounded font-mono" style={{ background: '#0d1117', color: '#475569', border: '1px solid #253047' }}>Esc</kbd>
        </div>

        {/* Results */}
        <div className="py-2 max-h-80 overflow-y-auto">
          {filtered.length === 0 && (
            <div className="px-4 py-8 text-center text-sm" style={{ color: '#475569' }}>No results for "{query}"</div>
          )}
          {filtered.map((cmd, i) => (
            <button
              key={cmd.to}
              onClick={() => go(cmd.to)}
              onMouseEnter={() => setIdx(i)}
              className="w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors cursor-pointer"
              style={{
                background: i === idx ? 'rgba(59,130,246,0.12)' : 'transparent',
                color: i === idx ? '#93c5fd' : '#94a3b8'
              }}
            >
              <div
                className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ background: i === idx ? 'rgba(59,130,246,0.2)' : 'rgba(255,255,255,0.05)' }}
              >
                <cmd.icon size={14} />
              </div>
              <span className="flex-1 text-left font-medium">{cmd.label}</span>
              <span className="text-xs" style={{ color: '#374151' }}>{cmd.category}</span>
              {i === idx && <ArrowRight size={13} />}
            </button>
          ))}
        </div>

        <div className="px-4 py-2.5 border-t flex items-center gap-4 text-xs" style={{ borderColor: '#253047', color: '#374151' }}>
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">↵</kbd> open</span>
          <span><kbd className="font-mono">Esc</kbd> close</span>
        </div>
      </div>
    </div>
  )
}
