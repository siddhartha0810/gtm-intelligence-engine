/**
 * theme.ts — shared design tokens
 * One source of truth for colors, spacing, radius, shadow, and reusable style
 * objects. Inline styles only (project rule); this just keeps them consistent
 * across pages instead of each file redefining the same card/palette.
 */
import type React from 'react'

export const colors = {
  pageBg:   '#f1f5f9',
  surface:  '#ffffff',
  primary:  '#3b82f6',
  indigo:   '#6366f1',
  success:  '#10b981',
  warning:  '#f59e0b',
  danger:   '#ef4444',
  text:     '#0f172a',
  textMute: '#64748b',
  textFaint:'#94a3b8',
  border:   '#e2e8f0',
  borderSoft:'#f1f5f9',
}

export const radius = { sm: 8, md: 10, lg: 12, xl: 16, pill: 999 }
export const shadow = {
  sm: '0 1px 3px rgba(0,0,0,0.06)',
  md: '0 4px 12px rgba(0,0,0,0.08)',
  lg: '0 10px 30px rgba(15,23,42,0.10)',
}

export const card: React.CSSProperties = {
  background: colors.surface,
  border: `1px solid ${colors.border}`,
  borderRadius: radius.lg,
  padding: 20,
  boxShadow: shadow.sm,
}

export const btnPrimary: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 8,
  background: colors.primary, color: '#fff', border: 'none',
  borderRadius: radius.sm, padding: '9px 16px', fontSize: 13,
  fontWeight: 600, cursor: 'pointer',
}

export const btnGhost: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  background: 'transparent', color: colors.textMute,
  border: `1px solid ${colors.border}`, borderRadius: radius.sm,
  padding: '8px 14px', fontSize: 12, fontWeight: 500, cursor: 'pointer',
}

export const h1: React.CSSProperties = { fontSize: 22, fontWeight: 700, color: colors.text, margin: 0, letterSpacing: '-0.01em' }
export const sub: React.CSSProperties = { fontSize: 13, color: colors.textMute, marginTop: 4 }

export const fmt = (n: number | undefined | null) => (n ?? 0).toLocaleString()
