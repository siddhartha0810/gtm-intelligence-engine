import { useState, useEffect } from 'react'
import { Eye, EyeOff, Check, AlertCircle, Zap, Loader } from 'lucide-react'
import { toast } from '../components/Toast'
import ConfirmDialog from '../components/ConfirmDialog'

type Status = 'connected' | 'error' | 'unconfigured' | 'testing' | 'loading'

interface TestResponse { status: string; message?: string }

const SERVICES = [
  { id: 'hubspot',     label: 'HubSpot API Token',  desc: 'Required for pushing enriched contacts to your CRM',    placeholder: 'pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx', color: '#f59e0b' },
  { id: 'apollo',      label: 'Apollo.io API Key',   desc: 'Used for contact discovery and company prospecting',     placeholder: 'xxxxxxxxxxxxxxxxxxxxxxxx',                      color: '#3b82f6' },
  { id: 'zerobounce',  label: 'ZeroBounce API Key',  desc: 'Email validation to reduce bounce rates',               placeholder: 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',              color: '#10b981' },
  { id: 'apify',       label: 'Apify Token',          desc: 'Powers LinkedIn and web scraping actors',               placeholder: 'apify_api_xxxxxxxx',                           color: '#6366f1' },
]

const statusStyle: Record<Status, { text: string; bg: string; color: string }> = {
  connected:    { text: 'Connected',     bg: 'rgba(16,185,129,0.12)', color: '#34d399' },
  error:        { text: 'Auth Error',    bg: 'rgba(239,68,68,0.1)',   color: '#f87171' },
  unconfigured: { text: 'Not configured',bg: 'rgba(107,114,128,0.15)',color: '#9ca3af' },
  testing:      { text: 'Testing…',     bg: 'rgba(59,130,246,0.12)', color: '#60a5fa' },
  loading:      { text: 'Loading…',     bg: 'rgba(107,114,128,0.15)',color: '#9ca3af' },
}

function ApiCard({
  svc, status, onTest,
}: {
  svc: typeof SERVICES[0]
  status: Status
  onTest: (key: string) => Promise<void>
}) {
  const [show, setShow]   = useState(false)
  const [key,  setKey]    = useState('')
  const [msg,  setMsg]    = useState('')
  const isTesting = status === 'testing'
  const st = statusStyle[status]

  const handleTest = async () => {
    setMsg('')
    const result: TestResponse = await fetch(`/config/test/${svc.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    }).then(r => r.json()).catch(() => ({ status: 'error', message: 'Network error' }))
    setMsg(result.message || '')
    await onTest(key)
  }

  const borderColor = status === 'error'     ? 'rgba(239,68,68,0.4)'
                    : status === 'connected' ? 'rgba(16,185,129,0.4)'
                    : '#d1d5db'

  return (
    <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 36, height: 36, borderRadius: 8, background: `${svc.color}18`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <Zap size={15} color={svc.color} />
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{svc.label}</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 3 }}>{svc.desc}</div>
          </div>
        </div>
        <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, fontWeight: 500, background: st.bg, color: st.color, flexShrink: 0, marginLeft: 8 }}>
          {st.text}
        </span>
      </div>

      <div style={{ position: 'relative', marginBottom: 12 }}>
        <input
          type={show ? 'text' : 'password'}
          value={key}
          onChange={e => setKey(e.target.value)}
          placeholder={key ? undefined : svc.placeholder}
          style={{ width: '100%', padding: '9px 40px 9px 12px', borderRadius: 8, background: '#ffffff', border: `1px solid ${borderColor}`, color: '#0f172a', fontSize: 13, fontFamily: 'monospace', outline: 'none', boxSizing: 'border-box' }}
        />
        <button onClick={() => setShow(s => !s)} style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#475569', display: 'flex' }}>
          {show ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>

      {msg && (
        <div style={{ fontSize: 12, color: status === 'connected' ? '#34d399' : '#f87171', marginBottom: 10 }}>
          {msg}
        </div>
      )}

      <button
        onClick={handleTest}
        disabled={isTesting || !key.trim()}
        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: status === 'connected' ? '#10b981' : status === 'error' ? '#ef4444' : '#94a3b8', fontSize: 12, cursor: (!key.trim() || isTesting) ? 'not-allowed' : 'pointer', opacity: (!key.trim() || isTesting) ? 0.5 : 1 }}
      >
        {isTesting
          ? <><Loader size={11} style={{ animation: 'spin 1s linear infinite' }} /> Testing...</>
          : status === 'connected'
          ? <><Check size={11} /> Test passed</>
          : status === 'error'
          ? <><AlertCircle size={11} /> Test failed — retry</>
          : <><Zap size={11} /> Test connection</>}
      </button>
    </div>
  )
}

export default function Settings() {
  const [statuses, setStatuses] = useState<Record<string, Status>>(
    Object.fromEntries(SERVICES.map(s => [s.id, 'loading' as Status]))
  )
  const [confirm, setConfirm] = useState<{ title: string; message: string; action: () => void } | null>(null)

  // Load real status on mount
  useEffect(() => {
    fetch('/config/status')
      .then(r => r.json())
      .then(data => setStatuses(prev => ({ ...prev, ...data })))
      .catch(() => setStatuses(prev => Object.fromEntries(Object.keys(prev).map(k => [k, 'error' as Status]))))
  }, [])

  const handleTest = async (serviceId: string, key: string) => {
    setStatuses(prev => ({ ...prev, [serviceId]: 'testing' }))
    const result: TestResponse = await fetch(`/config/test/${serviceId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    }).then(r => r.json()).catch(() => ({ status: 'error', message: 'Could not reach server' }))

    const newStatus: Status = result.status === 'connected' ? 'connected' : 'error'
    setStatuses(prev => ({ ...prev, [serviceId]: newStatus }))

    if (newStatus === 'connected') {
      // Auto-save on success — write to .env and hot-reload in the backend
      await fetch(`/config/save/${serviceId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key }),
      }).catch(() => null)
      toast.success(`${result.message || `${serviceId} connected`} — key saved`)
    } else {
      toast.error(result.message || `${serviceId} auth failed`)
    }
  }

  const dangerAction = (title: string, message: string, action: () => void) =>
    setConfirm({ title, message, action })

  const resetOracle = async () => {
    try {
      await fetch('/admin/reset-all', { method: 'POST' })
      toast.success('Oracle intent database reset successfully')
    } catch {
      toast.error('Reset failed')
    }
  }

  const purgeInvalid = async () => {
    try {
      const r = await fetch('/admin/purge-invalid', { method: 'POST' }).then(r => r.json())
      toast.success(`Purged ${r.deleted} invalid company names`)
    } catch {
      toast.error('Purge failed')
    }
  }

  const [normalizingIndustries, setNormalizingIndustries] = useState(false)
  const normalizeIndustries = async () => {
    setNormalizingIndustries(true)
    try {
      const r = await fetch('/admin/normalize-industries', { method: 'POST', headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` } }).then(r => r.json())
      toast.success(`Normalized ${r.updated} industry names`)
    } catch {
      toast.error('Normalization failed')
    } finally {
      setNormalizingIndustries(false)
    }
  }

const [normalizingProducts, setNormalizingProducts] = useState(false)
  const normalizeProducts = async () => {
    setNormalizingProducts(true)
    try {
      const r = await fetch('/admin/normalize-products', { method: 'POST', headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` } }).then(r => r.json())
      toast.success(r.message)
    } catch {
      toast.error('Product migration failed')
    } finally {
      setNormalizingProducts(false)
    }
  }

  const [revalidatingEmails, setRevalidatingEmails] = useState(false)
  const revalidateEmails = async () => {
    setRevalidatingEmails(true)
    try {
      const r = await fetch('/api/contacts/revalidate-emails', {
        method: 'POST',
        headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      }).then(r => r.json())
      if (r.queued) toast.success('Email re-validation started in the background')
      else toast.error(r.error || 'Revalidation failed')
    } catch {
      toast.error('Revalidation failed')
    } finally {
      setRevalidatingEmails(false)
    }
  }

  const [resettingTaxonomy, setResettingTaxonomy] = useState(false)
  const resetTaxonomy = async () => {
    setResettingTaxonomy(true)
    try {
      const r = await fetch('/admin/reset-taxonomy', { method: 'POST', headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` } }).then(r => r.json())
      toast.success(r.message)
    } catch {
      toast.error('Taxonomy reset failed')
    } finally {
      setResettingTaxonomy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, width: '100%', maxWidth: 720 }}>
      <style>{`@keyframes spin { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }`}</style>

      <div>
        <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>Settings & API Configuration</h1>
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>Keys are read from .env — enter a key below to test it live</p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {SERVICES.map(svc => (
          <ApiCard
            key={svc.id}
            svc={svc}
            status={statuses[svc.id] || 'unconfigured'}
            onTest={(key) => handleTest(svc.id, key)}
          />
        ))}
      </div>

      {/* Maintenance */}
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, background: '#f8fafc', marginTop: 8 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', marginBottom: 4 }}>Maintenance</div>
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 16 }}>Data cleanup and normalization tasks.</div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            onClick={normalizeIndustries}
            disabled={normalizingIndustries}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: normalizingIndustries ? '#94a3b8' : '#0f172a', fontSize: 13, cursor: normalizingIndustries ? 'not-allowed' : 'pointer', fontWeight: 500 }}
            onMouseEnter={e => { if (!normalizingIndustries) e.currentTarget.style.borderColor = '#3b82f6' }}
            onMouseLeave={e => e.currentTarget.style.borderColor = '#e2e8f0'}
          >
            {normalizingIndustries
              ? <><Loader size={13} style={{ animation: 'spin 1s linear infinite' }} /> Normalizing…</>
              : 'Normalize Industry Names'}
          </button>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>Cleans raw Apollo industry strings to proper English names in the database</span>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginTop: 12 }}>
          <button
            onClick={resetTaxonomy}
            disabled={resettingTaxonomy}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: resettingTaxonomy ? '#94a3b8' : '#0f172a', fontSize: 13, cursor: resettingTaxonomy ? 'not-allowed' : 'pointer', fontWeight: 500 }}
            onMouseEnter={e => { if (!resettingTaxonomy) e.currentTarget.style.borderColor = '#3b82f6' }}
            onMouseLeave={e => e.currentTarget.style.borderColor = '#e2e8f0'}
          >
            {resettingTaxonomy
              ? <><Loader size={13} style={{ animation: 'spin 1s linear infinite' }} /> Resetting…</>
              : 'Reset Product Taxonomy'}
          </button>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>Replaces the product taxonomy with the full 8-product curated set</span>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginTop: 12 }}>
          <button
            onClick={normalizeProducts}
            disabled={normalizingProducts}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: normalizingProducts ? '#94a3b8' : '#0f172a', fontSize: 13, cursor: normalizingProducts ? 'not-allowed' : 'pointer', fontWeight: 500 }}
            onMouseEnter={e => { if (!normalizingProducts) e.currentTarget.style.borderColor = '#3b82f6' }}
            onMouseLeave={e => e.currentTarget.style.borderColor = '#e2e8f0'}
          >
            {normalizingProducts
              ? <><Loader size={13} style={{ animation: 'spin 1s linear infinite' }} /> Migrating…</>
              : 'Migrate Legacy Product Names'}
          </button>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>Updates old product values (e.g. "JD Edwards" → "JD Edwards EnterpriseOne") to match the current taxonomy</span>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginTop: 12 }}>
          <button
            onClick={revalidateEmails}
            disabled={revalidatingEmails}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: revalidatingEmails ? '#94a3b8' : '#0f172a', fontSize: 13, cursor: revalidatingEmails ? 'not-allowed' : 'pointer', fontWeight: 500 }}
            onMouseEnter={e => { if (!revalidatingEmails) e.currentTarget.style.borderColor = '#10b981' }}
            onMouseLeave={e => e.currentTarget.style.borderColor = '#e2e8f0'}
          >
            {revalidatingEmails
              ? <><Loader size={13} style={{ animation: 'spin 1s linear infinite' }} /> Starting…</>
              : 'Revalidate Emails (ZeroBounce)'}
          </button>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>Re-runs ZeroBounce on contacts with unknown/catch-all status — up to 1,000 at a time</span>
        </div>
      </div>

      {/* Danger zone */}
      <div style={{ border: '1px solid rgba(239,68,68,0.2)', borderRadius: 12, padding: 20, background: 'rgba(239,68,68,0.04)', marginTop: 8 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#f87171', marginBottom: 6 }}>Danger Zone</div>
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 16 }}>These actions are irreversible.</div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button
            onClick={() => dangerAction('Purge Invalid Companies', 'Remove all company names that failed validation from the database.', purgeInvalid)}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid rgba(239,68,68,0.25)', background: 'transparent', color: '#f87171', fontSize: 13, cursor: 'pointer' }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(239,68,68,0.08)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >Purge Invalid Companies</button>
          <button
            onClick={() => dangerAction('Reset Oracle Database', 'This will permanently delete all Oracle intent signals, company records, contacts, and scan history.', resetOracle)}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid rgba(239,68,68,0.25)', background: 'transparent', color: '#f87171', fontSize: 13, cursor: 'pointer' }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(239,68,68,0.08)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >Reset Oracle Intent Database</button>
        </div>
      </div>

      {confirm && (
        <ConfirmDialog
          title={confirm.title}
          message={confirm.message}
          confirmLabel="Yes, proceed"
          danger
          onConfirm={() => { confirm.action(); setConfirm(null) }}
          onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  )
}
