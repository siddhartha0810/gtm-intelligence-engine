import { useState, useEffect } from 'react'
import { RefreshCw, Key, Globe, CheckCircle2, XCircle, ArrowDown, ArrowUp, Eye, EyeOff, Loader2 } from 'lucide-react'

const card: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: 24,
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
  marginBottom: 20,
}

const token = () => localStorage.getItem('token') || ''
const authHeaders = () => ({
  'Content-Type': 'application/json',
  'Authorization': `Bearer ${token()}`,
})

interface HubSpotConfig {
  hasSavedKey?: boolean
  maskedKey?: string
  portalId?: string
  lastSync?: string
  companiesSynced?: number
  contactsSynced?: number
  syncStatus?: 'idle' | 'running' | 'error' | 'success'
}

interface SyncResult {
  companiesPulled?: number
  companiesPushed?: number
  contactsPulled?: number
  contactsPushed?: number
  errors?: number
  message?: string
}

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  idle:    { bg: '#f1f5f9', text: '#64748b' },
  running: { bg: '#eff6ff', text: '#2563eb' },
  error:   { bg: '#fef2f2', text: '#ef4444' },
  success: { bg: '#f0fdf4', text: '#10b981' },
}

export default function HubSpotSync() {
  const [config, setConfig]       = useState<HubSpotConfig>({})
  const [apiKey, setApiKey]       = useState('')
  const [portalId, setPortalId]   = useState('')
  const [showKey, setShowKey]     = useState(false)
  const [saving, setSaving]       = useState(false)
  const [testing, setTesting]     = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [pulling, setPulling]     = useState(false)
  const [pushingCo, setPushingCo] = useState(false)
  const [pushingCt, setPushingCt] = useState(false)
  const [result, setResult]       = useState<SyncResult | null>(null)
  const [loadingConfig, setLoadingConfig] = useState(true)

  useEffect(() => {
    fetch('/api/hubspot/config', { headers: authHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) {
          setConfig(data)
          setPortalId(data.portalId || '')
        }
      })
      .catch(() => {})
      .finally(() => setLoadingConfig(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await fetch('/api/hubspot/config', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ apiKey: apiKey || undefined, portalId }),
      })
      const data = await res.json()
      setConfig(prev => ({ ...prev, ...data, hasSavedKey: apiKey ? true : prev.hasSavedKey }))
      setApiKey('')
    } catch {
      // silent
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await fetch('/api/hubspot/test', { method: 'POST', headers: authHeaders() })
      const data = await res.json()
      setTestResult({ ok: res.ok, message: data.message || (res.ok ? 'Connection successful' : 'Connection failed') })
    } catch {
      setTestResult({ ok: false, message: 'Network error' })
    } finally {
      setTesting(false)
    }
  }

  const handlePull = async () => {
    setPulling(true)
    setResult(null)
    try {
      const res = await fetch('/api/hubspot/sync-pull', { method: 'POST', headers: authHeaders() })
      const data = await res.json()
      setResult(data)
    } catch {
      setResult({ message: 'Pull failed' })
    } finally {
      setPulling(false)
    }
  }

  const handlePushCompanies = async () => {
    setPushingCo(true)
    setResult(null)
    try {
      const res = await fetch('/api/hubspot/bulk-push/companies', { method: 'POST', headers: authHeaders() })
      const data = await res.json()
      setResult(data)
    } catch {
      setResult({ message: 'Push failed' })
    } finally {
      setPushingCo(false)
    }
  }

  const handlePushContacts = async () => {
    setPushingCt(true)
    setResult(null)
    try {
      const res = await fetch('/api/hubspot/bulk-push/contacts', { method: 'POST', headers: authHeaders() })
      const data = await res.json()
      setResult(data)
    } catch {
      setResult({ message: 'Push failed' })
    } finally {
      setPushingCt(false)
    }
  }

  const statusStyle = STATUS_COLORS[config.syncStatus || 'idle']
  const anyLoading = pulling || pushingCo || pushingCt

  return (
    <div style={{ maxWidth: 860, margin: '0 auto' }}>
      {/* Page header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
          <RefreshCw size={22} color="#2563eb" />
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>HubSpot Sync</h1>
        </div>
        <p style={{ margin: 0, fontSize: 14, color: '#64748b' }}>
          Configure your HubSpot integration and manage bi-directional data synchronisation.
        </p>
      </div>

      {/* Config card */}
      <div style={card}>
        <div style={{ fontWeight: 600, fontSize: 15, color: '#0f172a', marginBottom: 18, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Key size={16} color="#2563eb" /> Credentials
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          {/* API Key */}
          <div>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: '#374151', marginBottom: 6 }}>
              API Key {config.hasSavedKey && <span style={{ color: '#10b981', fontWeight: 400 }}>(key saved)</span>}
            </label>
            <div style={{ position: 'relative' }}>
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder={config.hasSavedKey ? '••••••••••••••••' : 'Enter HubSpot private app key'}
                style={{
                  width: '100%', padding: '9px 40px 9px 12px', borderRadius: 8,
                  border: '1px solid #d1d5db', fontSize: 14, color: '#0f172a',
                  background: '#fff', boxSizing: 'border-box', outline: 'none',
                }}
              />
              <button
                onClick={() => setShowKey(v => !v)}
                style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280', padding: 0 }}
              >
                {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {/* Portal ID */}
          <div>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: '#374151', marginBottom: 6 }}>
              Portal ID
            </label>
            <div style={{ position: 'relative' }}>
              <Globe size={14} color="#9ca3af" style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }} />
              <input
                type="text"
                value={portalId}
                onChange={e => setPortalId(e.target.value)}
                placeholder="e.g. 12345678"
                style={{
                  width: '100%', padding: '9px 12px 9px 32px', borderRadius: 8,
                  border: '1px solid #d1d5db', fontSize: 14, color: '#0f172a',
                  background: '#fff', boxSizing: 'border-box', outline: 'none',
                }}
              />
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button
            onClick={handleSave}
            disabled={saving}
            style={{
              padding: '9px 20px', borderRadius: 8, background: '#2563eb', color: '#fff',
              border: 'none', cursor: saving ? 'not-allowed' : 'pointer', fontSize: 14,
              fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6, opacity: saving ? 0.7 : 1,
            }}
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : null}
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button
            onClick={handleTest}
            disabled={testing}
            style={{
              padding: '9px 20px', borderRadius: 8, background: '#fff', color: '#374151',
              border: '1px solid #d1d5db', cursor: testing ? 'not-allowed' : 'pointer', fontSize: 14,
              fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6, opacity: testing ? 0.7 : 1,
            }}
          >
            {testing ? <Loader2 size={14} /> : null}
            {testing ? 'Testing…' : 'Test Connection'}
          </button>
          {testResult && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: testResult.ok ? '#10b981' : '#ef4444', fontWeight: 500 }}>
              {testResult.ok ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
              {testResult.message}
            </span>
          )}
        </div>
      </div>

      {/* Sync Status card */}
      <div style={card}>
        <div style={{ fontWeight: 600, fontSize: 15, color: '#0f172a', marginBottom: 18 }}>Sync Status</div>
        {loadingConfig ? (
          <div style={{ color: '#94a3b8', fontSize: 14 }}>Loading…</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
            {[
              { label: 'Last Sync', value: config.lastSync ? new Date(config.lastSync).toLocaleString() : '—' },
              { label: 'Companies Synced', value: config.companiesSynced?.toLocaleString() ?? '—' },
              { label: 'Contacts Synced', value: config.contactsSynced?.toLocaleString() ?? '—' },
              {
                label: 'Status',
                value: (
                  <span style={{ padding: '3px 12px', borderRadius: 999, fontSize: 13, fontWeight: 600, background: statusStyle.bg, color: statusStyle.text, textTransform: 'capitalize' }}>
                    {config.syncStatus || 'idle'}
                  </span>
                ),
              },
            ].map(({ label, value }) => (
              <div key={label} style={{ background: '#f8fafc', borderRadius: 8, padding: '14px 16px', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: 12, color: '#64748b', marginBottom: 6, fontWeight: 500 }}>{label}</div>
                <div style={{ fontSize: 15, fontWeight: 600, color: '#0f172a' }}>{value}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div style={card}>
        <div style={{ fontWeight: 600, fontSize: 15, color: '#0f172a', marginBottom: 18 }}>Actions</div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <button
            onClick={handlePull}
            disabled={anyLoading}
            style={{
              padding: '10px 22px', borderRadius: 8, background: '#eff6ff', color: '#2563eb',
              border: '1px solid #bfdbfe', cursor: anyLoading ? 'not-allowed' : 'pointer',
              fontSize: 14, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8,
              opacity: anyLoading ? 0.6 : 1,
            }}
          >
            {pulling ? <Loader2 size={15} /> : <ArrowDown size={15} />}
            Pull from HubSpot
          </button>
          <button
            onClick={handlePushCompanies}
            disabled={anyLoading}
            style={{
              padding: '10px 22px', borderRadius: 8, background: '#f0fdf4', color: '#10b981',
              border: '1px solid #bbf7d0', cursor: anyLoading ? 'not-allowed' : 'pointer',
              fontSize: 14, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8,
              opacity: anyLoading ? 0.6 : 1,
            }}
          >
            {pushingCo ? <Loader2 size={15} /> : <ArrowUp size={15} />}
            Push Companies
          </button>
          <button
            onClick={handlePushContacts}
            disabled={anyLoading}
            style={{
              padding: '10px 22px', borderRadius: 8, background: '#fdf4ff', color: '#9333ea',
              border: '1px solid #e9d5ff', cursor: anyLoading ? 'not-allowed' : 'pointer',
              fontSize: 14, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8,
              opacity: anyLoading ? 0.6 : 1,
            }}
          >
            {pushingCt ? <Loader2 size={15} /> : <ArrowUp size={15} />}
            Push Contacts
          </button>
        </div>
      </div>

      {/* Results panel */}
      {result && (
        <div style={{ ...card, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
          <div style={{ fontWeight: 600, fontSize: 15, color: '#0f172a', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
            <CheckCircle2 size={16} color="#10b981" /> Operation Result
          </div>
          {result.message && (
            <p style={{ margin: '0 0 12px', fontSize: 14, color: '#374151' }}>{result.message}</p>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
            {result.companiesPulled != null && (
              <div style={{ background: '#fff', borderRadius: 8, padding: '12px 14px', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>Companies Pulled</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#2563eb' }}>{result.companiesPulled}</div>
              </div>
            )}
            {result.companiesPushed != null && (
              <div style={{ background: '#fff', borderRadius: 8, padding: '12px 14px', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>Companies Pushed</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#10b981' }}>{result.companiesPushed}</div>
              </div>
            )}
            {result.contactsPulled != null && (
              <div style={{ background: '#fff', borderRadius: 8, padding: '12px 14px', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>Contacts Pulled</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#2563eb' }}>{result.contactsPulled}</div>
              </div>
            )}
            {result.contactsPushed != null && (
              <div style={{ background: '#fff', borderRadius: 8, padding: '12px 14px', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>Contacts Pushed</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#10b981' }}>{result.contactsPushed}</div>
              </div>
            )}
            {result.errors != null && (
              <div style={{ background: '#fef2f2', borderRadius: 8, padding: '12px 14px', border: '1px solid #fecaca' }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>Errors</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#ef4444' }}>{result.errors}</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
