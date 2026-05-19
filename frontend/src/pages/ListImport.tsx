import { useState, useEffect, useRef } from 'react'
import { Upload, CheckCircle2, XCircle, AlertCircle, Trash2, RefreshCw, ChevronDown } from 'lucide-react'
import { toast } from '../components/Toast'

const authH = (): Record<string, string> => ({
  'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
})

type EntityType = 'Company' | 'Contact'
type Step = 1 | 2 | 3 | 4

interface ParsedHeader { csv_header: string; suggested_field: string }
interface HubSpotField { value: string; label: string }
interface ImportBatch { id: number; file_name: string; entity_type: string; status: string; record_count: number; success_count: number; created_at: string }
interface Template { id: number; name: string; entity_type: string; mappings: Record<string, string> }
interface ImportResult { success_count: number; error_count: number; errors: string[] }

const statusColor = (s: string) => {
  if (s === 'completed') return { bg: 'rgba(16,185,129,0.1)', color: '#34d399' }
  if (s === 'failed') return { bg: 'rgba(239,68,68,0.1)', color: '#f87171' }
  if (s === 'processing') return { bg: 'rgba(59,130,246,0.1)', color: '#60a5fa' }
  return { bg: 'rgba(107,114,128,0.1)', color: '#9ca3af' }
}

const entityBadge = (t: string) => t === 'Company'
  ? { bg: 'rgba(99,102,241,0.12)', color: '#a5b4fc' }
  : { bg: 'rgba(59,130,246,0.12)', color: '#60a5fa' }

export default function ListImport() {
  const [step, setStep] = useState<Step>(1)
  const [entityType, setEntityType] = useState<EntityType>('Company')
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [headers, setHeaders] = useState<ParsedHeader[]>([])
  const [fields, setFields] = useState<HubSpotField[]>([])
  const [mappings, setMappings] = useState<Record<string, string>>({})
  const [recordCount, setRecordCount] = useState(0)
  const [saveAsTemplate, setSaveAsTemplate] = useState(false)
  const [templateName, setTemplateName] = useState('')
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | undefined>()
  const [result, setResult] = useState<ImportResult | null>(null)
  const [processing, setProcessing] = useState(false)
  const [batches, setBatches] = useState<ImportBatch[]>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [loadingHistory, setLoadingHistory] = useState(true)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadHistory = async () => {
    setLoadingHistory(true)
    try {
      const [bRes, tRes] = await Promise.all([fetch('/api/import/batches', { headers: authH() }), fetch('/api/import/templates', { headers: authH() })])
      if (bRes.ok) setBatches(await bRes.json())
      if (tRes.ok) setTemplates(await tRes.json())
    } catch { } finally { setLoadingHistory(false) }
  }

  useEffect(() => { loadHistory() }, [])

  const handleFile = (f: File) => {
    if (!f.name.endsWith('.csv')) { toast.error('Only CSV files are supported'); return }
    setFile(f)
  }

  const parseHeaders = async () => {
    if (!file) { toast.error('Please select a file'); return }
    setProcessing(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('entity_type', entityType)
      const r = await fetch('/api/import/parse-headers', { method: 'POST', body: fd, headers: { 'Authorization': `Bearer ${localStorage.getItem('token') || ''}` } })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      setHeaders(data.headers || [])
      setRecordCount(data.record_count || 0)
      const initMappings: Record<string, string> = {}
      ;(data.headers || []).forEach((h: ParsedHeader) => { initMappings[h.csv_header] = h.suggested_field || '' })
      setMappings(initMappings)

      const fRes = await fetch(`/api/import/fields/${entityType}`, { headers: authH() })
      if (fRes.ok) { const fd2 = await fRes.json(); setFields(Array.isArray(fd2) ? fd2 : (fd2.fields ?? [])) }

      setStep(2)
    } catch { toast.error('Failed to parse file headers') } finally { setProcessing(false) }
  }

  const applyTemplate = (t: Template) => {
    setSelectedTemplateId(t.id)
    setMappings(t.mappings)
  }

  const runImport = async () => {
    setProcessing(true)
    try {
      const fd = new FormData()
      fd.append('file', file!)
      fd.append('entity_type', entityType)
      fd.append('mappings', JSON.stringify(mappings))
      if (saveAsTemplate && templateName) fd.append('template_name', templateName)
      if (selectedTemplateId) fd.append('template_id', String(selectedTemplateId))
      const r = await fetch('/api/import/upload', { method: 'POST', body: fd, headers: { 'Authorization': `Bearer ${localStorage.getItem('token') || ''}` } })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data: ImportResult = await r.json()
      setResult(data)
      setStep(4)
      loadHistory()
    } catch { toast.error('Import failed') } finally { setProcessing(false) }
  }

  const deleteTemplate = async (id: number) => {
    if (!window.confirm('Delete this template?')) return
    try {
      const r = await fetch(`/api/import/templates/${id}`, { method: 'DELETE', headers: authH() })
      if (!r.ok) throw new Error()
      toast.success('Template deleted')
      setTemplates(ts => ts.filter(t => t.id !== id))
    } catch { toast.error('Delete failed') }
  }

  const reset = () => { setStep(1); setFile(null); setHeaders([]); setMappings({}); setResult(null); setSaveAsTemplate(false); setTemplateName(''); setSelectedTemplateId(undefined) }

  const inp: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: '#0f172a', fontSize: 13, outline: 'none', boxSizing: 'border-box' }
  const stepActive = (n: number) => step === n
  const stepDone = (n: number) => step > n

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, width: '100%' }}>
      {/* Header */}
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 600, color: '#0f172a', margin: 0 }}>List Import</h1>
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>Import contacts and companies from CSV files</p>
      </div>

      {/* Step indicator */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
        {(['Upload', 'Map Fields', 'Confirm', 'Results'] as const).map((label, i) => {
          const n = i + 1
          return (
            <div key={label} style={{ display: 'flex', alignItems: 'center', flex: i < 3 ? '1 1 auto' : 'none' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 600, background: stepDone(n) ? '#10b981' : stepActive(n) ? '#3b82f6' : '#f1f5f9', color: stepDone(n) || stepActive(n) ? 'white' : '#64748b', border: `2px solid ${stepDone(n) ? '#10b981' : stepActive(n) ? '#3b82f6' : '#e2e8f0'}` }}>
                  {stepDone(n) ? <CheckCircle2 size={14} /> : n}
                </div>
                <span style={{ fontSize: 13, fontWeight: stepActive(n) ? 600 : 400, color: stepActive(n) ? '#0f172a' : stepDone(n) ? '#10b981' : '#64748b' }}>{label}</span>
              </div>
              {i < 3 && <div style={{ flex: 1, height: 1, background: stepDone(n) ? '#10b981' : '#e2e8f0', margin: '0 16px' }} />}
            </div>
          )
        })}
      </div>

      {/* Step content */}
      <div style={{ background: '#ffffff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 28, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        {/* Step 1 */}
        {step === 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#0f172a' }}>Select Entity Type & Upload File</h2>
            <div style={{ display: 'flex', gap: 12 }}>
              {(['Company', 'Contact'] as EntityType[]).map(et => (
                <button key={et} onClick={() => setEntityType(et)} style={{ flex: 1, padding: '16px 20px', borderRadius: 10, border: `2px solid ${entityType === et ? '#3b82f6' : '#253047'}`, background: entityType === et ? 'rgba(59,130,246,0.08)' : 'transparent', color: entityType === et ? '#60a5fa' : '#64748b', fontSize: 14, fontWeight: 600, cursor: 'pointer', textAlign: 'center', transition: 'all 0.15s' }}>
                  {et === 'Company' ? '🏢' : '👤'} {et}
                </button>
              ))}
            </div>

            <div
              onDragOver={e => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) handleFile(f) }}
              onClick={() => fileInputRef.current?.click()}
              style={{ border: `2px dashed ${dragging ? '#3b82f6' : file ? '#10b981' : '#d1d5db'}`, borderRadius: 12, padding: '40px 20px', textAlign: 'center', cursor: 'pointer', background: dragging ? 'rgba(59,130,246,0.04)' : file ? 'rgba(16,185,129,0.04)' : '#f8fafc', transition: 'all 0.15s' }}>
              <input ref={fileInputRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={e => { if (e.target.files?.[0]) handleFile(e.target.files[0]) }} />
              {file ? (
                <div>
                  <CheckCircle2 size={32} color="#10b981" style={{ marginBottom: 12 }} />
                  <div style={{ fontSize: 15, fontWeight: 600, color: '#0f172a' }}>{file.name}</div>
                  <div style={{ fontSize: 13, color: '#64748b', marginTop: 6 }}>{(file.size / 1024).toFixed(1)} KB · Click to change</div>
                </div>
              ) : (
                <div>
                  <Upload size={32} color="#475569" style={{ marginBottom: 12 }} />
                  <div style={{ fontSize: 15, fontWeight: 500, color: '#64748b' }}>Drop CSV here or click to browse</div>
                  <div style={{ fontSize: 13, color: '#475569', marginTop: 6 }}>Only .csv files are supported</div>
                </div>
              )}
            </div>

            {templates.length > 0 && (
              <div>
                <label style={{ fontSize: 12, color: '#64748b', fontWeight: 600, letterSpacing: '0.04em', display: 'block', marginBottom: 8 }}>APPLY SAVED TEMPLATE (OPTIONAL)</label>
                <select style={{ ...inp, cursor: 'pointer' }} value={selectedTemplateId ?? ''} onChange={e => { const t = templates.find(x => x.id === Number(e.target.value)); if (t) applyTemplate(t); else setSelectedTemplateId(undefined) }}>
                  <option value="">No template</option>
                  {templates.filter(t => t.entity_type === entityType).map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </div>
            )}

            <button onClick={parseHeaders} disabled={!file || processing} style={{ padding: '10px 24px', borderRadius: 8, border: 'none', background: file ? '#3b82f6' : '#e2e8f0', color: file ? 'white' : '#94a3b8', fontSize: 14, fontWeight: 500, cursor: file ? 'pointer' : 'not-allowed', alignSelf: 'flex-start' }}>
              {processing ? 'Parsing...' : 'Continue →'}
            </button>
          </div>
        )}

        {/* Step 2 */}
        {step === 2 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#0f172a' }}>Map CSV Columns to Fields</h2>
              <span style={{ fontSize: 13, color: '#64748b' }}>{recordCount} records detected</span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 380, overflowY: 'auto' }}>
              {headers.map(h => (
                <div key={h.csv_header} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
                  <span style={{ flex: 1, fontSize: 13, color: '#94a3b8', fontFamily: 'monospace' }}>{h.csv_header}</span>
                  <ChevronDown size={14} color="#475569" />
                  <div style={{ position: 'relative', flex: 1 }}>
                    <select value={mappings[h.csv_header] ?? ''} onChange={e => setMappings(m => ({ ...m, [h.csv_header]: e.target.value }))}
                      style={{ width: '100%', padding: '7px 12px', borderRadius: 8, background: '#ffffff', border: '1px solid #d1d5db', color: mappings[h.csv_header] ? '#0f172a' : '#64748b', fontSize: 13, outline: 'none', cursor: 'pointer' }}>
                      <option value="">— Skip this column —</option>
                      {fields.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
                    </select>
                  </div>
                </div>
              ))}
            </div>

            <div style={{ padding: '14px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
                <input type="checkbox" checked={saveAsTemplate} onChange={e => setSaveAsTemplate(e.target.checked)} style={{ accentColor: '#3b82f6', width: 16, height: 16 }} />
                <span style={{ fontSize: 13, color: '#94a3b8' }}>Save these mappings as a template</span>
              </label>
              {saveAsTemplate && (
                <input style={{ ...inp, marginTop: 10 }} value={templateName} onChange={e => setTemplateName(e.target.value)} placeholder="Template name..." />
              )}
            </div>

            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => setStep(1)} style={{ padding: '9px 20px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>← Back</button>
              <button onClick={() => setStep(3)} style={{ padding: '9px 20px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>Review →</button>
            </div>
          </div>
        )}

        {/* Step 3 */}
        {step === 3 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#0f172a' }}>Confirm Import</h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
              {[{ label: 'File', value: file?.name ?? '' }, { label: 'Entity Type', value: entityType }, { label: 'Records', value: String(recordCount) }].map(stat => (
                <div key={stat.label} style={{ padding: '16px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
                  <div style={{ fontSize: 11, color: '#475569', fontWeight: 600, letterSpacing: '0.04em', marginBottom: 6 }}>{stat.label.toUpperCase()}</div>
                  <div style={{ fontSize: 15, fontWeight: 600, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{stat.value}</div>
                </div>
              ))}
            </div>

            <div>
              <div style={{ fontSize: 12, color: '#64748b', fontWeight: 600, letterSpacing: '0.04em', marginBottom: 10 }}>MAPPED FIELDS</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 240, overflowY: 'auto' }}>
                {Object.entries(mappings).filter(([, v]) => v).map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 14px', background: '#f8fafc', borderRadius: 6, border: '1px solid #e2e8f0' }}>
                    <span style={{ fontSize: 13, color: '#94a3b8', fontFamily: 'monospace' }}>{k}</span>
                    <span style={{ fontSize: 13, color: '#60a5fa' }}>{v}</span>
                  </div>
                ))}
                {Object.values(mappings).filter(Boolean).length === 0 && <div style={{ fontSize: 13, color: '#475569', textAlign: 'center', padding: 16 }}>No fields mapped</div>}
              </div>
            </div>

            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => setStep(2)} style={{ padding: '9px 20px', borderRadius: 8, border: '1px solid #e2e8f0', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>← Back</button>
              <button onClick={runImport} disabled={processing} style={{ padding: '9px 24px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: processing ? 'not-allowed' : 'pointer', opacity: processing ? 0.7 : 1 }}>
                {processing ? 'Importing...' : 'Process Import'}
              </button>
            </div>
          </div>
        )}

        {/* Step 4 */}
        {step === 4 && result && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#0f172a' }}>Import Results</h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div style={{ padding: 20, background: 'rgba(16,185,129,0.08)', borderRadius: 10, border: '1px solid rgba(16,185,129,0.2)', textAlign: 'center' }}>
                <CheckCircle2 size={28} color="#10b981" style={{ marginBottom: 8 }} />
                <div style={{ fontSize: 28, fontWeight: 700, color: '#10b981' }}>{result.success_count}</div>
                <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>Records imported</div>
              </div>
              <div style={{ padding: 20, background: 'rgba(239,68,68,0.08)', borderRadius: 10, border: '1px solid rgba(239,68,68,0.2)', textAlign: 'center' }}>
                <XCircle size={28} color="#ef4444" style={{ marginBottom: 8 }} />
                <div style={{ fontSize: 28, fontWeight: 700, color: '#ef4444' }}>{result.error_count}</div>
                <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>Errors</div>
              </div>
            </div>

            {result.errors && result.errors.length > 0 && (
              <div>
                <div style={{ fontSize: 12, color: '#64748b', fontWeight: 600, letterSpacing: '0.04em', marginBottom: 8 }}>ERRORS</div>
                <div style={{ maxHeight: 200, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {result.errors.map((e, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '8px 12px', background: 'rgba(239,68,68,0.06)', borderRadius: 6, border: '1px solid rgba(239,68,68,0.15)' }}>
                      <AlertCircle size={13} color="#f87171" style={{ marginTop: 1, flexShrink: 0 }} />
                      <span style={{ fontSize: 12, color: '#f87171' }}>{e}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <button onClick={reset} style={{ padding: '9px 20px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontSize: 13, fontWeight: 500, cursor: 'pointer', alignSelf: 'flex-start' }}>
              New Import
            </button>
          </div>
        )}
      </div>

      {/* Import History */}
      <div style={{ background: '#ffffff', borderRadius: 12, border: '1px solid #e2e8f0', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid #f1f5f9' }}>
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: '#0f172a' }}>Import History</h3>
          <button onClick={loadHistory} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', display: 'flex', alignItems: 'center', gap: 5, fontSize: 12 }}>
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
              {['File', 'Type', 'Status', 'Records', 'Success', 'Date'].map(h => (
                <th key={h} style={{ padding: '10px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#475569' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loadingHistory && <tr><td colSpan={6} style={{ padding: '24px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>Loading...</td></tr>}
            {!loadingHistory && batches.length === 0 && <tr><td colSpan={6} style={{ padding: '24px 0', textAlign: 'center', color: '#475569', fontSize: 13 }}>No imports yet.</td></tr>}
            {!loadingHistory && batches.map((b) => {
              const sc = statusColor(b.status)
              const ec = entityBadge(b.entity_type)
              return (
                <tr key={b.id} style={{ background: '#ffffff', borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '11px 16px', fontSize: 13, color: '#0f172a' }}>{b.file_name}</td>
                  <td style={{ padding: '11px 16px' }}><span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, background: ec.bg, color: ec.color }}>{b.entity_type}</span></td>
                  <td style={{ padding: '11px 16px' }}><span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, background: sc.bg, color: sc.color }}>{b.status}</span></td>
                  <td style={{ padding: '11px 16px', fontSize: 13, color: '#94a3b8' }}>{b.record_count}</td>
                  <td style={{ padding: '11px 16px', fontSize: 13, color: '#34d399' }}>{b.success_count}</td>
                  <td style={{ padding: '11px 16px', fontSize: 12, color: '#475569' }}>{new Date(b.created_at).toLocaleDateString()}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Saved Templates */}
      {templates.length > 0 && (
        <div style={{ background: '#ffffff', borderRadius: 12, border: '1px solid #e2e8f0', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
          <div style={{ padding: '16px 20px', borderBottom: '1px solid #f1f5f9' }}>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: '#0f172a' }}>Saved Templates</h3>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                {['Name', 'Entity Type', 'Fields Mapped', ''].map(h => (
                  <th key={h} style={{ padding: '10px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#475569' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {templates.map((t) => {
                const ec = entityBadge(t.entity_type)
                return (
                  <tr key={t.id} style={{ background: '#ffffff', borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '11px 16px', fontSize: 13, color: '#0f172a', fontWeight: 500 }}>{t.name}</td>
                    <td style={{ padding: '11px 16px' }}><span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, background: ec.bg, color: ec.color }}>{t.entity_type}</span></td>
                    <td style={{ padding: '11px 16px', fontSize: 13, color: '#94a3b8' }}>{Object.keys(t.mappings || {}).length} fields</td>
                    <td style={{ padding: '11px 16px' }}>
                      <button onClick={() => deleteTemplate(t.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444', padding: '4px 8px', borderRadius: 6, display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}
                        onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.08)'}
                        onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                        <Trash2 size={12} /> Delete
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
