import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Play, Square, RotateCcw, Download, Trash2, Factory, Users, CheckCircle,
         Mail, X, ChevronRight, Zap, Clock, CreditCard, Building2, Database,
         ExternalLink, Globe, BarChart2 } from 'lucide-react'
import { toast } from '../components/Toast'

const authH = (): Record<string, string> => ({
  Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
  'Content-Type': 'application/json',
})

// ── Role definitions ──────────────────────────────────────────────────────────

const EXACT_ROLES = [
  'Oracle Apps DBA',
  'Oracle Business Analyst',
  'Finance Project Manager',
  'Oracle Cloud HCM Support Analyst',
  'Oracle Cloud Support Analyst',
  'Senior System Analyst',
  'Oracle Fusion Senior Support Agent',
  'Oracle Fusion Test Manager',
  'Oracle Change & Release Manager',
  'Head of Oracle Support',
  'Senior Transformation Leader',
  'Group Programme Director',
  'Senior Project Manager',
  'Project and Programme Delivery',
  'Head of Finance Systems',
]

const KEYWORD_ROLES = [
  'Oracle / ERP / HCM / Cloud / Fusion',
  'CIO / Chief Information Officer',
  'IT / Information Technology',
  'CTO / Chief Technology Officer',
  'Architect / Architecture',
  'Business System / Business Systems',
  'Financial System / Financial Systems',
  'Application / Applications',
  'Transformation',
  'Project Manager',
  'CFO / Chief Financial Officer',
  'Oracle ERP', 'Oracle Fusion', 'Oracle EBS', 'Oracle HCM',
  'JD Edwards', 'JDE', 'ERP Manager', 'ERP Director', 'ERP Consultant',
  'Finance Director', 'Financial Controller', 'VP Finance',
  'IT Director', 'CIO', 'CTO', 'IT Manager',
  'Enterprise Applications Manager', 'Business Systems Manager',
  'Digital Transformation Manager', 'Oracle Developer',
  'Head of Finance', 'Head of IT', 'IT Architect', 'Solutions Architect',
]

// All roles flat — used when "Select All" is clicked
const ALL_ROLES = [...EXACT_ROLES, ...KEYWORD_ROLES]

// ── Engines + Sources ─────────────────────────────────────────────────────────

const ENGINES = [
  { id: 'oracle',     label: 'Oracle Intent Engine',   desc: 'Scans job boards, oracle.com, news & case studies for Oracle/JDE signals', color: '#3b82f6', modules: 18 },
  { id: 'enrichment', label: 'Lead Enrichment Engine', desc: '7-stage: contacts_master → Apollo → ZeroBounce → prediction → HubSpot',    color: '#6366f1', modules: 7 },
  { id: 'hubspot',    label: 'HubSpot Sync Engine',    desc: 'Pushes approved contacts from Review Queue to CRM',                         color: '#f59e0b', modules: 1 },
]

// Sources are split into active (proven signal generators) and experimental (0 signals to date).
// Experimental sources are hidden by default but can be expanded if needed.
const ACTIVE_SOURCES = [
  { id: 'linkedin',       label: 'LinkedIn Jobs',    desc: '787 signals · 664 companies — primary signal source (ALL Oracle products)' },
  { id: 'oracle_website', label: 'Oracle.com',       desc: '95 signals · 94 companies — customer stories + press releases' },
  { id: 'erp_today',      label: 'ERP News (Multi)', desc: 'ERP Today + Diginomica + Bing RSS — EBS, PeopleSoft, Siebel, Hyperion, JDE go-lives' },
  { id: 'news',           label: 'Oracle News',      desc: 'Bing RSS — go-live announcements for ALL Oracle products' },
  { id: 'g2_reviews',     label: 'G2 / Capterra',   desc: 'Software review sites — confirms active Oracle deployments (post_live signals)' },
]

const EXPERIMENTAL_SOURCES = [
  { id: 'partner_casestudy', label: 'Partner Stories',        desc: 'Oracle Gold/Platinum SI case studies' },
  { id: 'si_casestudy',      label: 'SI Case Studies',        desc: 'Accenture, Deloitte, PwC, KPMG client names' },
  { id: 'oracle_community',  label: 'Oracle Community',       desc: 'Migration stories + oracle.com news' },
  { id: 'oracle_event',      label: 'Oracle Events',          desc: 'CloudWorld / OpenWorld attendance signals' },
  { id: 'home_builders',     label: 'Home Builders',          desc: 'JDE construction signals (1,000+ closing builders)' },
  { id: 'company_pages',     label: 'Company Press Releases', desc: 'Company IR pages + announcements' },
  { id: 'procurement',       label: 'Procurement Tenders',    desc: 'Contracts Finder (UK) + USASpending.gov + Bing procurement RSS' },
  { id: 'sec_filing',        label: 'SEC Filings (EDGAR)',    desc: 'Free EDGAR search — 10-K/10-Q/8-K filings mentioning Oracle, EBS, PeopleSoft' },
  { id: 'indeed',            label: 'Indeed',                 desc: 'Job postings — limited by bot detection' },
]

const DEFAULT_SOURCES = ['linkedin', 'oracle_website', 'erp_today', 'news', 'g2_reviews']

const card = { background:'#ffffff', border:'1px solid #e2e8f0', borderRadius:12, padding:20, boxShadow:'0 1px 3px rgba(0,0,0,0.06)' }
const now  = () => new Date().toLocaleTimeString('en-GB', { hour12: false })
const levelColor = (l: string) =>
  l === 'SUCCESS' ? '#10b981' : l === 'ERROR' ? '#ef4444' : l === 'WARN' ? '#f59e0b' : '#64748b'

interface LogEntry  { t: string; level: string; msg: string }
interface Preflight {
  total: number; from_contacts_master: number; need_apollo: number;
  est_credits: number; est_minutes: number;
  apollo_configured: boolean; zerobounce_configured: boolean;
  zoominfo_configured: boolean;
}

type EnrichProvider = 'apollo' | 'zoominfo'

interface PendingCompany {
  id: number
  name: string
  domain: string | null
  target_product: string
  signal_count: number
}
interface EnrichStats {
  total_companies?: number; enriched_companies?: number; pending_companies?: number;
  total_contacts?: number; contacts_with_email?: number; contacts_valid_email?: number;
  apollo_configured?: boolean; zerobounce_configured?: boolean;
}
interface EnrichStatus {
  status?: string; progress?: string;
  companies_processed?: number; companies_total?: number;
  contacts_found?: number; contacts_validated?: number;
}

// ── Pre-flight modal ──────────────────────────────────────────────────────────

function PreflightModal({
  preflight, enrichLimit, enrichPerCo, batchSize, selectedRoles, provider,
  pendingCompanies, selectedCompanyIds,
  onClose, onStart,
  setEnrichLimit, setEnrichPerCo, setBatchSize, setSelectedRoles, setProvider,
  setSelectedCompanyIds,
}: {
  preflight: Preflight
  enrichLimit: number; enrichPerCo: number; batchSize: number; selectedRoles: string[]
  provider: EnrichProvider
  pendingCompanies: PendingCompany[]
  selectedCompanyIds: number[]
  onClose: () => void; onStart: () => void
  setEnrichLimit: (v: number) => void; setEnrichPerCo: (v: number) => void
  setBatchSize: (v: number) => void; setSelectedRoles: (v: string[]) => void
  setProvider: (v: EnrichProvider) => void
  setSelectedCompanyIds: (v: number[]) => void
}) {
  const [roleTab, setRoleTab] = useState<'exact' | 'keyword'>('exact')
  const [coQuery, setCoQuery] = useState('')

  const visibleCompanies = pendingCompanies.filter(c =>
    !coQuery || c.name.toLowerCase().includes(coQuery.toLowerCase()))
  const toggleCompany = (id: number) =>
    setSelectedCompanyIds(selectedCompanyIds.includes(id)
      ? selectedCompanyIds.filter(x => x !== id)
      : [...selectedCompanyIds, id])
  const toggleRole = (r: string) =>
    setSelectedRoles(selectedRoles.includes(r) ? selectedRoles.filter(x => x !== r) : [...selectedRoles, r])
  const selectAll  = () => setSelectedRoles(ALL_ROLES)
  const clearAll   = () => setSelectedRoles([])

  const numBatches = batchSize > 0 ? Math.ceil(Math.min(enrichLimit, preflight.total) / batchSize) : 1
  const apolloNeeded = Math.min(preflight.need_apollo, enrichLimit)
  const masterNeeded = Math.min(preflight.from_contacts_master, enrichLimit)
  const creditsNeeded = apolloNeeded * 2

  const stat = (icon: React.ReactNode, label: string, val: string | number, color: string, sub?: string) => (
    <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '14px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ color }}>{icon}</span>
        <span style={{ fontSize: 11, color: '#64748b' }}>{label}</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: '#0f172a' }}>{val}</div>
      {sub && <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>{sub}</div>}
    </div>
  )

  return (
    <>
      {/* Backdrop */}
      <div onClick={onClose} style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.4)', zIndex:999, backdropFilter:'blur(2px)' }} />

      {/* Modal */}
      <div style={{ position:'fixed', top:'50%', left:'50%', transform:'translate(-50%,-50%)', width:'min(820px, 95vw)', maxHeight:'90vh', overflowY:'auto', background:'#ffffff', borderRadius:16, boxShadow:'0 24px 80px rgba(0,0,0,0.2)', zIndex:1000 }}>
        {/* Header */}
        <div style={{ padding:'20px 24px', borderBottom:'1px solid #e2e8f0', display:'flex', alignItems:'center', justifyContent:'space-between', position:'sticky', top:0, background:'#fff', zIndex:1 }}>
          <div>
            <div style={{ fontSize:16, fontWeight:700, color:'#0f172a' }}>Enrichment Pre-Flight Check</div>
            <div style={{ fontSize:12, color:'#64748b', marginTop:3 }}>Review estimates and configure before launching</div>
          </div>
          <button onClick={onClose} style={{ width:32, height:32, borderRadius:8, border:'1px solid #e2e8f0', background:'transparent', display:'flex', alignItems:'center', justifyContent:'center', cursor:'pointer', color:'#64748b' }}>
            <X size={14} />
          </button>
        </div>

        <div style={{ padding:'20px 24px', display:'flex', flexDirection:'column', gap:20 }}>

          {/* Summary stats */}
          <div>
            <div style={{ fontSize:12, fontWeight:600, color:'#94a3b8', letterSpacing:'0.06em', marginBottom:10 }}>ENRICHMENT ESTIMATE</div>
            <div style={{ display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:10 }}>
              {stat(<Building2 size={14}/>, 'Companies to enrich', Math.min(enrichLimit, preflight.total), '#3b82f6', `of ${preflight.total} total pending`)}
              {stat(<Database size={14}/>, 'From master DB', masterNeeded, '#10b981', 'no Apollo credits used')}
              {stat(<Zap size={14}/>, 'Need Apollo', apolloNeeded, '#6366f1', 'will use API credits')}
              {stat(<CreditCard size={14}/>, 'Est. credits', creditsNeeded, '#f59e0b', `~${Math.ceil(preflight.est_minutes * (enrichLimit / preflight.total || 1))} min`)}
            </div>
          </div>

          {/* Key notices */}
          <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
            {masterNeeded > 0 && (
              <div style={{ padding:'10px 14px', background:'rgba(16,185,129,0.08)', border:'1px solid rgba(16,185,129,0.2)', borderRadius:8, fontSize:12, color:'#10b981' }}>
                ✓ <strong>{masterNeeded} companies</strong> will be served from your 221k-contact master database — <strong>zero Apollo credits</strong> used.
              </div>
            )}
            {apolloNeeded > 0 && !preflight.apollo_configured && (
              <div style={{ padding:'10px 14px', background:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.2)', borderRadius:8, fontSize:12, color:'#f87171' }}>
                ✗ Apollo API key not configured — {apolloNeeded} companies cannot be enriched. Add <code style={{ background:'rgba(239,68,68,0.15)', padding:'1px 4px', borderRadius:3 }}>APOLLO_API_KEY</code> to oracle_intent_engine/.env
              </div>
            )}
          </div>

          {/* Companies to enrich — pick from intent scan results */}
          {pendingCompanies.length > 0 && (
            <div>
              <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:10 }}>
                <div style={{ fontSize:12, fontWeight:600, color:'#94a3b8', letterSpacing:'0.06em' }}>COMPANIES TO ENRICH</div>
                <div style={{ display:'flex', gap:8, alignItems:'center' }}>
                  <span style={{ fontSize:11, padding:'2px 8px', borderRadius:999, background:'rgba(59,130,246,0.12)', color:'#3b82f6' }}>
                    {selectedCompanyIds.length} of {pendingCompanies.length} selected
                  </span>
                  <button onClick={() => setSelectedCompanyIds(pendingCompanies.map(c => c.id))}
                    style={{ fontSize:11, color:'#3b82f6', background:'none', border:'none', cursor:'pointer', textDecoration:'underline' }}>All</button>
                  <button onClick={() => setSelectedCompanyIds([])}
                    style={{ fontSize:11, color:'#94a3b8', background:'none', border:'none', cursor:'pointer', textDecoration:'underline' }}>None</button>
                </div>
              </div>
              <input value={coQuery} onChange={e => setCoQuery(e.target.value)}
                placeholder="Search companies..."
                style={{ width:'100%', boxSizing:'border-box', padding:'7px 12px', borderRadius:8, border:'1px solid #e2e8f0', fontSize:12, outline:'none', background:'#f8fafc', marginBottom:8 }} />
              <div style={{ maxHeight:200, overflowY:'auto', border:'1px solid #e2e8f0', borderRadius:8 }}>
                {visibleCompanies.map(c => {
                  const on = selectedCompanyIds.includes(c.id)
                  return (
                    <label key={c.id}
                      style={{ display:'flex', alignItems:'center', gap:10, padding:'7px 12px', cursor:'pointer',
                        borderBottom:'1px solid #f1f5f9', background: on ? 'rgba(59,130,246,0.04)' : 'transparent' }}>
                      <input type="checkbox" checked={on} onChange={() => toggleCompany(c.id)}
                        style={{ accentColor:'#3b82f6', cursor:'pointer', flexShrink:0 }} />
                      <span style={{ fontSize:12, fontWeight:500, color:'#0f172a', flex:1, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>
                        {c.name}
                      </span>
                      {c.target_product && (
                        <span style={{ fontSize:10, padding:'2px 8px', borderRadius:999, background:'rgba(16,185,129,0.1)', color:'#10b981', whiteSpace:'nowrap', flexShrink:0 }}>
                          {c.target_product}
                        </span>
                      )}
                      <span style={{ fontSize:10, padding:'2px 7px', borderRadius:999, background:'rgba(99,102,241,0.1)', color:'#818cf8', whiteSpace:'nowrap', flexShrink:0 }}>
                        {c.signal_count} signals
                      </span>
                    </label>
                  )
                })}
                {visibleCompanies.length === 0 && (
                  <div style={{ padding:'14px 12px', fontSize:12, color:'#94a3b8', textAlign:'center' }}>No companies match your search.</div>
                )}
              </div>
            </div>
          )}

          {/* Enrichment tool selector */}
          <div>
            <div style={{ fontSize:12, fontWeight:600, color:'#94a3b8', letterSpacing:'0.06em', marginBottom:10 }}>ENRICHMENT TOOL</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10 }}>
              {([
                { id: 'apollo' as const,   label: 'Apollo.io', desc: 'People search + email reveal', ok: preflight.apollo_configured,   envHint: 'APOLLO_API_KEY' },
                { id: 'zoominfo' as const, label: 'ZoomInfo',  desc: 'Contact search + enrich API',  ok: preflight.zoominfo_configured, envHint: 'ZOOMINFO_USERNAME / PASSWORD' },
              ]).map(p => {
                const on = provider === p.id
                return (
                  <button key={p.id} onClick={() => setProvider(p.id)} disabled={!p.ok}
                    title={p.ok ? `Use ${p.label} for contact discovery` : `Add ${p.envHint} to oracle_intent_engine/.env`}
                    style={{ padding:'12px 14px', borderRadius:10, textAlign:'left', cursor: p.ok ? 'pointer' : 'not-allowed',
                      border:`1px solid ${on ? 'rgba(99,102,241,0.45)' : '#e2e8f0'}`,
                      background: on ? 'rgba(99,102,241,0.08)' : p.ok ? '#f8fafc' : '#f1f5f9',
                      opacity: p.ok ? 1 : 0.55, transition:'all 0.15s' }}>
                    <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
                      <span style={{ fontSize:13, fontWeight:600, color: on ? '#6366f1' : '#0f172a' }}>
                        {on && <span style={{ marginRight:6 }}>✓</span>}{p.label}
                      </span>
                      <span style={{ fontSize:10, fontWeight:600, padding:'2px 8px', borderRadius:999,
                        background: p.ok ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.1)',
                        color: p.ok ? '#10b981' : '#f87171' }}>
                        {p.ok ? 'Configured' : 'Not configured'}
                      </span>
                    </div>
                    <div style={{ fontSize:11, color:'#64748b', marginTop:4 }}>{p.desc}</div>
                  </button>
                )
              })}
            </div>
            <div style={{ fontSize:11, color:'#94a3b8', marginTop:6 }}>
              contacts_master (Salesforce export) is always checked first — the selected tool is only called on a miss.
            </div>
          </div>

          {/* Config row */}
          <div>
            <div style={{ fontSize:12, fontWeight:600, color:'#94a3b8', letterSpacing:'0.06em', marginBottom:10 }}>BATCH CONFIGURATION</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12 }}>
              <div>
                <div style={{ fontSize:12, color:'#374151', fontWeight:500, marginBottom:6 }}>
                  Companies per run <span style={{ color:'#3b82f6', fontWeight:700 }}>{enrichLimit}</span>
                </div>
                <select value={enrichLimit} onChange={e => setEnrichLimit(+e.target.value)}
                  style={{ width:'100%', padding:'8px 10px', borderRadius:8, border:'1px solid #d1d5db', fontSize:13, color:'#0f172a', background:'#fff' }}>
                  {[20,50,100,200,500].map(v => <option key={v} value={v}>{v} companies</option>)}
                </select>
                <div style={{ fontSize:11, color:'#94a3b8', marginTop:4 }}>Total to process this run</div>
              </div>
              <div>
                <div style={{ fontSize:12, color:'#374151', fontWeight:500, marginBottom:6 }}>
                  Contacts per company <span style={{ color:'#6366f1', fontWeight:700 }}>{enrichPerCo}</span>
                </div>
                <select value={enrichPerCo} onChange={e => setEnrichPerCo(+e.target.value)}
                  style={{ width:'100%', padding:'8px 10px', borderRadius:8, border:'1px solid #d1d5db', fontSize:13, color:'#0f172a', background:'#fff' }}>
                  {[2,5,10,15,20].map(v => <option key={v} value={v}>{v} contacts max</option>)}
                </select>
                <div style={{ fontSize:11, color:'#94a3b8', marginTop:4 }}>Apollo results per company</div>
              </div>
              <div>
                <div style={{ fontSize:12, color:'#374151', fontWeight:500, marginBottom:6 }}>
                  Batch size <span style={{ color:'#f59e0b', fontWeight:700 }}>{batchSize === 0 ? 'No batching' : `${batchSize} / batch`}</span>
                </div>
                <select value={batchSize} onChange={e => setBatchSize(+e.target.value)}
                  style={{ width:'100%', padding:'8px 10px', borderRadius:8, border:'1px solid #d1d5db', fontSize:13, color:'#0f172a', background:'#fff' }}>
                  <option value={0}>No batching</option>
                  {[5,10,20,50].map(v => <option key={v} value={v}>{v} per batch</option>)}
                </select>
                <div style={{ fontSize:11, color:'#94a3b8', marginTop:4 }}>
                  {batchSize > 0 ? `${numBatches} batch${numBatches > 1 ? 'es' : ''} with 5s pause` : 'Runs continuously'}
                </div>
              </div>
            </div>
          </div>

          {/* Role filters */}
          <div>
            <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:10 }}>
              <div style={{ fontSize:12, fontWeight:600, color:'#94a3b8', letterSpacing:'0.06em' }}>ROLE FILTERS — APOLLO PASS 1 (TARGETED)</div>
              <div style={{ display:'flex', gap:8 }}>
                <span style={{ fontSize:11, padding:'2px 8px', borderRadius:999, background:'rgba(99,102,241,0.12)', color:'#818cf8' }}>
                  {selectedRoles.length} selected
                </span>
                <button onClick={selectAll}  style={{ fontSize:11, color:'#3b82f6', background:'none', border:'none', cursor:'pointer', textDecoration:'underline' }}>All</button>
                <button onClick={clearAll}   style={{ fontSize:11, color:'#94a3b8', background:'none', border:'none', cursor:'pointer', textDecoration:'underline' }}>None</button>
              </div>
            </div>

            {/* Tab selector */}
            <div style={{ display:'flex', gap:0, marginBottom:10, borderRadius:8, background:'#f1f5f9', padding:3 }}>
              {(['exact','keyword'] as const).map(tab => (
                <button key={tab} onClick={() => setRoleTab(tab)}
                  style={{ flex:1, padding:'6px 0', borderRadius:6, border:'none', fontSize:12, fontWeight:500, cursor:'pointer',
                    background: roleTab === tab ? '#ffffff' : 'transparent',
                    color: roleTab === tab ? '#0f172a' : '#64748b',
                    boxShadow: roleTab === tab ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                    transition:'all 0.15s' }}>
                  {tab === 'exact' ? `Exact Roles (${EXACT_ROLES.length})` : `Oracle Keywords (${KEYWORD_ROLES.length})`}
                </button>
              ))}
            </div>

            <div style={{ display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:6, maxHeight:200, overflowY:'auto' }}>
              {(roleTab === 'exact' ? EXACT_ROLES : KEYWORD_ROLES).map(role => {
                const on = selectedRoles.includes(role)
                return (
                  <button key={role} onClick={() => toggleRole(role)}
                    style={{ padding:'7px 10px', borderRadius:7, border:`1px solid ${on ? 'rgba(99,102,241,0.35)' : '#e2e8f0'}`,
                      background: on ? 'rgba(99,102,241,0.08)' : '#f8fafc',
                      color: on ? '#6366f1' : '#475569',
                      fontSize:11, fontWeight: on ? 600 : 400, cursor:'pointer', textAlign:'left',
                      transition:'all 0.12s' }}>
                    {on && <span style={{ marginRight:4 }}>✓</span>}{role}
                  </button>
                )
              })}
            </div>
            <div style={{ fontSize:11, color:'#94a3b8', marginTop:6 }}>
              Selected roles are sent as Apollo <code>person_titles</code> filter. Pass 2 (broad) uses keyword matching as fallback.
            </div>
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding:'16px 24px', borderTop:'1px solid #e2e8f0', display:'flex', alignItems:'center', justifyContent:'space-between', position:'sticky', bottom:0, background:'#fff' }}>
          <div style={{ display:'flex', alignItems:'center', gap:12, fontSize:12, color:'#64748b' }}>
            <Clock size={13} />
            Est. <strong style={{ color:'#0f172a' }}>{Math.ceil(preflight.est_minutes * (enrichLimit / (preflight.total || 1)))}</strong> min &nbsp;·&nbsp;
            <CreditCard size={13} />
            ~<strong style={{ color:'#0f172a' }}>{creditsNeeded}</strong> Apollo credits &nbsp;·&nbsp;
            {numBatches > 1 && <><ChevronRight size={12} /><strong style={{ color:'#0f172a' }}>{numBatches} batches</strong></>}
          </div>
          <div style={{ display:'flex', gap:10 }}>
            <button onClick={onClose}
              style={{ padding:'9px 20px', borderRadius:8, border:'1px solid #e2e8f0', background:'transparent', color:'#64748b', fontSize:13, fontWeight:500, cursor:'pointer' }}>
              Cancel
            </button>
            <button onClick={onStart}
              disabled={(provider === 'apollo' ? !preflight.apollo_configured : !preflight.zoominfo_configured)
                        || (pendingCompanies.length > 0 && selectedCompanyIds.length === 0)}
              style={{ padding:'9px 24px', borderRadius:8, border:'none',
                background: '#6366f1', color:'white',
                fontSize:13, fontWeight:600, cursor:'pointer',
                display:'flex', alignItems:'center', gap:8 }}>
              <Play size={13} /> Launch Enrichment
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

// ── Scan Results Modal ────────────────────────────────────────────────────────

interface ScanCompany {
  name:         string
  domain:       string | null
  industry:     string | null
  signal_count: number
  first_seen:   string | null
}

interface ScanRun {
  id:               number
  started_at:       string
  completed_at:     string | null
  total_companies:  number
  total_signals:    number
  status:           string
}

function ScanResultsModal({ onClose, onDeleted }: { onClose: () => void; onDeleted: () => void }) {
  const [companies,     setCompanies]     = useState<ScanCompany[]>([])
  const [scanRuns,      setScanRuns]      = useState<ScanRun[]>([])
  const [selectedId,    setSelectedId]    = useState<number | null>(null)
  const [loading,       setLoading]       = useState(true)
  const [deleting,      setDeleting]      = useState(false)
  const [search,        setSearch]        = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)

  const loadRun = async (runId: number | null) => {
    setLoading(true)
    try {
      const qs  = runId !== null ? `?run_id=${runId}` : ''
      const res = await fetch(`/scan/companies${qs}`, { headers: authH() })
      if (!res.ok) { toast.error('Failed to load scan results'); return }
      const d   = await res.json()
      setCompanies(d.companies || [])
      if (d.scan_runs?.length && scanRuns.length === 0) setScanRuns(d.scan_runs)
      setSelectedId(d.run_id ?? null)
    } catch { toast.error('Network error') }
    finally   { setLoading(false) }
  }

  const removeFromDB = async () => {
    if (!selectedId || selectedId <= 0) {
      toast.error('Select a specific scan run first (not "All time")')
      return
    }
    setConfirmDelete(true)
    return
  }

  const confirmAndDelete = async () => {
    setConfirmDelete(false)
    setDeleting(true)
    try {
      const res = await fetch(`/scan/companies?run_id=${selectedId}`, {
        method: 'DELETE',
        headers: authH(),
      })
      const d = await res.json()
      if (!res.ok) { toast.error(d.detail || 'Delete failed'); return }
      toast.success(`Removed ${d.deleted} companies from the database`)
      setCompanies([])
      setScanRuns(prev => prev.filter(r => r.id !== selectedId))
      setSelectedId(null)
      onDeleted()   // refresh enrichment stats on the parent page
    } catch { toast.error('Network error') }
    finally { setDeleting(false) }
  }

  useEffect(() => { loadRun(null) }, [])

  const filtered = companies.filter(c =>
    !search || c.name.toLowerCase().includes(search.toLowerCase()) ||
    (c.domain || '').toLowerCase().includes(search.toLowerCase())
  )

  const fmtDate = (s: string | null) => s ? new Date(s).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'

  return (
    <>
      <div onClick={onClose} style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.5)', zIndex:1000 }} />
      <div style={{ position:'fixed', top:'50%', left:'50%', transform:'translate(-50%,-50%)',
                    width:'min(900px, 95vw)', maxHeight:'85vh', background:'#fff',
                    borderRadius:14, zIndex:1001, display:'flex', flexDirection:'column',
                    boxShadow:'0 20px 60px rgba(0,0,0,0.25)', overflow:'hidden' }}>

        {/* Header */}
        <div style={{ padding:'18px 24px', borderBottom:'1px solid #e2e8f0', display:'flex', alignItems:'center', justifyContent:'space-between', flexShrink:0 }}>
          <div>
            <div style={{ fontSize:16, fontWeight:600, color:'#0f172a', display:'flex', alignItems:'center', gap:8 }}>
              <BarChart2 size={16} color="#3b82f6" /> Scan Results
            </div>
            <div style={{ fontSize:12, color:'#64748b', marginTop:3 }}>
              Companies discovered by the Oracle Intent scan
            </div>
          </div>
          <button onClick={onClose} style={{ background:'none', border:'none', cursor:'pointer', color:'#94a3b8', padding:4 }}>
            <X size={18} />
          </button>
        </div>

        {/* Scan run selector */}
        {scanRuns.length > 0 && (
          <div style={{ padding:'12px 24px', borderBottom:'1px solid #f1f5f9', display:'flex', alignItems:'center', gap:10, flexShrink:0, overflowX:'auto' }}>
            <span style={{ fontSize:12, color:'#64748b', flexShrink:0 }}>Scan run:</span>
            {scanRuns.map(r => (
              <button key={r.id} onClick={() => loadRun(r.id)}
                style={{ flexShrink:0, padding:'4px 12px', borderRadius:999, fontSize:12, fontWeight:500, cursor:'pointer', border:'none',
                         background: selectedId === r.id ? '#3b82f6' : '#f1f5f9',
                         color:      selectedId === r.id ? 'white'   : '#475569' }}>
                #{r.id} — {fmtDate(r.started_at)}
                {r.total_companies ? <span style={{ opacity:0.8 }}> ({r.total_companies} cos)</span> : null}
              </button>
            ))}
            <button onClick={() => loadRun(0)}
              style={{ flexShrink:0, padding:'4px 12px', borderRadius:999, fontSize:12, fontWeight:500, cursor:'pointer', border:'none',
                       background: selectedId === 0 ? '#3b82f6' : '#f1f5f9',
                       color:      selectedId === 0 ? 'white'   : '#475569' }}>
              All time
            </button>
          </div>
        )}

        {/* Search + summary bar */}
        <div style={{ padding:'10px 24px', borderBottom:'1px solid #f1f5f9', display:'flex', alignItems:'center', gap:12, flexShrink:0 }}>
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search companies..."
            style={{ flex:1, padding:'7px 12px', borderRadius:8, border:'1px solid #e2e8f0', fontSize:13, outline:'none', background:'#f8fafc' }} />
          <span style={{ fontSize:12, color:'#64748b', flexShrink:0 }}>
            {loading ? 'Loading…' : `${filtered.length} companies`}
          </span>
        </div>

        {/* Table */}
        <div style={{ flex:1, overflowY:'auto' }}>
          {loading ? (
            <div style={{ padding:40, textAlign:'center', color:'#94a3b8', fontSize:14 }}>Loading companies…</div>
          ) : filtered.length === 0 ? (
            <div style={{ padding:40, textAlign:'center', color:'#94a3b8', fontSize:14 }}>No companies found for this scan run.</div>
          ) : (
            <table style={{ width:'100%', borderCollapse:'collapse' }}>
              <thead>
                <tr style={{ background:'#f8fafc' }}>
                  {['Company', 'Domain', 'Industry', 'Signals', 'First seen'].map(h => (
                    <th key={h} style={{ padding:'10px 16px', textAlign:'left', fontSize:11, fontWeight:600, color:'#64748b', letterSpacing:'0.05em', borderBottom:'1px solid #e2e8f0' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((c, i) => (
                  <tr key={i} style={{ borderBottom:'1px solid #f1f5f9' }}
                    onMouseEnter={e => (e.currentTarget.style.background = '#f8fafc')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                    <td style={{ padding:'10px 16px', fontSize:13, fontWeight:500, color:'#0f172a' }}>
                      <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                        <Building2 size={13} color="#94a3b8" />
                        {c.name}
                      </div>
                    </td>
                    <td style={{ padding:'10px 16px', fontSize:12, color:'#64748b' }}>
                      {c.domain ? (
                        <a href={`https://${c.domain}`} target="_blank" rel="noreferrer"
                          style={{ display:'flex', alignItems:'center', gap:4, color:'#3b82f6', textDecoration:'none' }}>
                          <Globe size={11} /> {c.domain} <ExternalLink size={10} />
                        </a>
                      ) : '—'}
                    </td>
                    <td style={{ padding:'10px 16px', fontSize:12, color:'#64748b' }}>{c.industry || '—'}</td>
                    <td style={{ padding:'10px 16px', fontSize:12 }}>
                      <span style={{ padding:'2px 8px', borderRadius:999, fontSize:11, fontWeight:600,
                                     background: (c.signal_count || 0) > 0 ? 'rgba(59,130,246,0.12)' : '#f1f5f9',
                                     color:      (c.signal_count || 0) > 0 ? '#2563eb' : '#94a3b8' }}>
                        {c.signal_count || 0}
                      </span>
                    </td>
                    <td style={{ padding:'10px 16px', fontSize:12, color:'#94a3b8' }}>{fmtDate(c.first_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Inline confirm overlay — replaces window.confirm */}
        {confirmDelete && (
          <div style={{ position:'absolute', inset:0, background:'rgba(15,23,42,0.55)', borderRadius:14, zIndex:10, display:'flex', alignItems:'center', justifyContent:'center' }}>
            <div style={{ background:'#fff', borderRadius:12, padding:'24px 28px', width:380, boxShadow:'0 8px 32px rgba(0,0,0,0.2)' }}>
              <div style={{ fontSize:15, fontWeight:700, color:'#0f172a', marginBottom:8 }}>Remove companies from DB?</div>
              <div style={{ fontSize:13, color:'#64748b', lineHeight:1.6, marginBottom:20 }}>
                This will permanently delete <strong style={{ color:'#dc2626' }}>{companies.length} companies</strong> from scan run #{selectedId}, along with their signals and contacts. This cannot be undone.
              </div>
              <div style={{ display:'flex', gap:10, justifyContent:'flex-end' }}>
                <button onClick={() => setConfirmDelete(false)}
                  style={{ padding:'8px 18px', borderRadius:8, border:'1px solid #e2e8f0', background:'transparent', fontSize:13, color:'#64748b', cursor:'pointer' }}>
                  Cancel
                </button>
                <button onClick={confirmAndDelete}
                  style={{ padding:'8px 18px', borderRadius:8, border:'none', background:'#dc2626', color:'#fff', fontSize:13, fontWeight:600, cursor:'pointer', display:'flex', alignItems:'center', gap:6 }}>
                  <Trash2 size={13} /> Yes, remove {companies.length} companies
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div style={{ padding:'12px 24px', borderTop:'1px solid #e2e8f0', display:'flex', alignItems:'center', justifyContent:'space-between', flexShrink:0 }}>
          {selectedId && selectedId > 0 && companies.length > 0 ? (
            <button onClick={removeFromDB} disabled={deleting}
              style={{ display:'flex', alignItems:'center', gap:6, padding:'8px 16px', borderRadius:8,
                       border:'1px solid rgba(239,68,68,0.35)', background:'rgba(239,68,68,0.06)',
                       color:'#dc2626', fontSize:13, fontWeight:500, cursor:'pointer', opacity: deleting ? 0.6 : 1 }}>
              <Trash2 size={13} />
              {deleting ? 'Removing…' : `Remove ${companies.length} companies from DB`}
            </button>
          ) : <span />}
          <button onClick={onClose}
            style={{ padding:'8px 20px', borderRadius:8, border:'1px solid #e2e8f0', background:'transparent', fontSize:13, color:'#64748b', cursor:'pointer' }}>
            Close
          </button>
        </div>
      </div>
    </>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function EngineControl() {
  const navigate = useNavigate()
  const [oracleState,       setOracleState]     = useState<'idle' | 'running' | 'stopping'>('idle')
  const [enrichState,       setEnrichState]     = useState<'idle' | 'running'>('idle')
  const [showScanResults,   setShowScanResults] = useState(false)
  const [showPostScan,      setShowPostScan]    = useState(false)
  const [postScanQuery,     setPostScanQuery]   = useState('')
  const [enrichDone,        setEnrichDone]      = useState(false)
  const [logs,            setLogs]            = useState<LogEntry[]>([{ t: now(), level: 'INFO', msg: 'System ready. Fetching engine status...' }])
  const [enrichLogs,      setEnrichLogs]      = useState<LogEntry[]>([])
  const [selectedSources, setSelectedSources] = useState<string[]>(DEFAULT_SOURCES)
  const [depth,           setDepth]           = useState('medium')
  const [jdeMfg,          setJdeMfg]          = useState(false)
  const [enrichLimit,     setEnrichLimit]     = useState(50)
  const [enrichPerCo,     setEnrichPerCo]     = useState(10)
  const [batchSize,       setBatchSize]       = useState(0)
  const [provider,        setProvider]        = useState<EnrichProvider>('apollo')
  const [pendingCompanies,   setPendingCompanies]   = useState<PendingCompany[]>([])
  const [selectedCompanyIds, setSelectedCompanyIds] = useState<number[]>([])
  const [selectedRoles,   setSelectedRoles]   = useState<string[]>(EXACT_ROLES) // default: exact roles
  const [enrichStats,     setEnrichStats]     = useState<EnrichStats>({})
  const [enrichStatus,    setEnrichStatus]    = useState<EnrichStatus>({})
  const [showEnrichLog,   setShowEnrichLog]   = useState(false)
  const [autoTrigger,     setAutoTrigger]     = useState(false)
  const [showPreflight,   setShowPreflight]   = useState(false)
  const [preflight,       setPreflight]       = useState<Preflight | null>(null)
  const [preflightLoading, setPreflightLoading] = useState(false)

  const [logScrollLocked,      setLogScrollLocked]      = useState(false)
  const [enrichScrollLocked,   setEnrichScrollLocked]   = useState(false)

  const logRef         = useRef<HTMLDivElement>(null)
  const enrichLogRef   = useRef<HTMLDivElement>(null)
  const pollRef        = useRef<ReturnType<typeof setInterval> | null>(null)
  const enrichPoll     = useRef<ReturnType<typeof setInterval> | null>(null)
  const scanStartedAt  = useRef<number>(0)   // timestamp when scan was launched
  const STOP_BTN_MIN_MS = 12000              // keep Stop button visible ≥12 s

  const addLog = (level: string, msg: string) =>
    setLogs(l => [...l.slice(-500), { t: now(), level, msg }])

  const parseLine = (line: string): LogEntry => {
    const m  = line.match(/^\[(\d{2}:\d{2}:\d{2})\]\s+\[(\w+)\]\s+(.+)$/)
    if (m)  return { t: m[1], level: m[2], msg: m[3] }
    const m2 = line.match(/^\[(\w+)\]\s+(.+)$/)
    if (m2) return { t: now(), level: m2[1], msg: m2[2] }
    return { t: now(), level: 'INFO', msg: line }
  }

  const fetchLog = async () => {
    try {
      const r = await fetch('/scan/log', { headers: authH() })
      if (!r.ok) return
      const d = await r.json()
      const entries: LogEntry[] = (d.log || d || []).map((line: string) => parseLine(line))
      if (entries.length > 0) setLogs(entries.slice(-500))
    } catch { /* silent */ }
  }

  const fetchEnrichStats = async () => {
    try {
      const r = await fetch('/api/enrich/stats', { headers: authH() })
      if (r.ok) setEnrichStats(await r.json())
    } catch { /* silent */ }
  }

  const fetchEnrichLog = async () => {
    try {
      const r = await fetch('/api/enrich/log', { headers: authH() })
      if (!r.ok) return
      const lines: string[] = await r.json()
      if (lines.length > 0) setEnrichLogs(lines.map(parseLine).slice(-500))
    } catch { /* silent */ }
  }

  const fetchEnrichStatus = async () => {
    try {
      const r = await fetch('/api/enrich/status', { headers: authH() })
      if (!r.ok) return
      const d = await r.json()
      setEnrichStatus(d)
      if (d.status === 'running') {
        setEnrichState('running')
      } else if (enrichState === 'running') {
        setEnrichState('idle')
        fetchEnrichStats()
      }
    } catch { /* silent */ }
  }

  // ── Post-scan results: load companies discovered by the scan ───────────────
  const loadScanResults = async () => {
    try {
      const r = await fetch('/api/enrich/pending', { headers: authH() })
      if (!r.ok) return
      const d = await r.json()
      const companies: PendingCompany[] = d.companies || []
      setPendingCompanies(companies)
      setSelectedCompanyIds(companies.map(c => c.id))  // default: all selected
      if (companies.length > 0) setShowPostScan(true)
    } catch { /* silent */ }
  }

  // ── Fetch preflight data ────────────────────────────────────────────────────
  // keepSelection: launched from the post-scan panel — preserve the user's
  // company checkboxes instead of resetting to "all selected".
  const fetchPreflight = async (keepSelection = false) => {
    setPreflightLoading(true)
    try {
      const [r, rp] = await Promise.all([
        fetch('/api/enrich/preflight', { headers: authH() }),
        fetch('/api/enrich/pending',   { headers: authH() }),
      ])
      if (r.ok) {
        const d = await r.json()
        setPreflight(d)
        if (rp.ok) {
          const dp = await rp.json()
          const companies: PendingCompany[] = dp.companies || []
          setPendingCompanies(companies)
          if (keepSelection) {
            // keep only selections that still exist in the pending list
            const valid = new Set(companies.map(c => c.id))
            setSelectedCompanyIds(selectedCompanyIds.filter(id => valid.has(id)))
          } else {
            setSelectedCompanyIds(companies.map(c => c.id))
          }
        }
        setShowPreflight(true)
      } else {
        toast.error('Could not load preflight data')
      }
    } catch { toast.error('Network error') }
    finally { setPreflightLoading(false) }
  }

  // ── Start enrichment (called from modal) ────────────────────────────────────
  const startEnrichment = async () => {
    setShowPreflight(false)
    setShowPostScan(false)
    setEnrichDone(false)
    const isSubset = selectedCompanyIds.length > 0 && selectedCompanyIds.length < pendingCompanies.length
    try {
      const res = await fetch('/api/enrich/start', {
        method: 'POST',
        headers: authH(),
        body: JSON.stringify({
          // when the user hand-picked companies, enrich exactly those
          limit:           isSubset ? selectedCompanyIds.length : enrichLimit,
          max_per_company: enrichPerCo,
          batch_size:      batchSize || null,
          role_filters:    selectedRoles.length > 0 ? selectedRoles : null,
          provider,
          company_ids:     isSubset ? selectedCompanyIds : null,
        }),
      })
      if (!res.ok) { toast.error((await res.json()).error || 'Failed to start enrichment'); return }
      setEnrichState('running')
      setShowEnrichLog(true)
      toast.success(`Enrichment started via ${provider === 'zoominfo' ? 'ZoomInfo' : 'Apollo'} — ${enrichLimit} companies, ${enrichPerCo} contacts each${batchSize ? `, ${batchSize}/batch` : ''}`)
      if (enrichPoll.current) clearInterval(enrichPoll.current)
      enrichPoll.current = setInterval(async () => {
        await fetchEnrichLog()
        await fetchEnrichStatus()
        const s = await fetch('/api/enrich/status', { headers: authH() }).then(r => r.json()).catch(() => null)
        if (s && s.status !== 'running') {
          setEnrichState('idle')
          setEnrichDone(true)
          clearInterval(enrichPoll.current!)
          fetchEnrichStats()
          toast.success(`Enrichment done — ${s.contacts_found || 0} contacts, ${s.contacts_validated || 0} valid emails`)
        }
      }, 3000)
    } catch { toast.error('Cannot connect to backend.') }
  }

  const stopEnrichment = async () => {
    try {
      await fetch('/api/enrich/stop', { method: 'POST', headers: authH() })
      setEnrichState('idle')
      if (enrichPoll.current) clearInterval(enrichPoll.current)
      toast.info('Enrichment stopped')
    } catch { toast.error('Failed to stop enrichment') }
  }

  // ── Oracle scan controls ────────────────────────────────────────────────────
  const startEngine = async () => {
    const maxPages = depth === 'shallow' ? 1 : depth === 'deep' ? 5 : 3
    try {
      const res = await fetch('/scan/start', {
        method: 'POST',
        headers: { ...authH(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sources: selectedSources, max_pages: maxPages, jde_manufacturing: jdeMfg,
          auto_enrich: autoTrigger,
          enrich_limit: enrichLimit, enrich_per_company: enrichPerCo,
          enrich_provider: provider,
        }),
      })
      if (res.status === 409) {
        // A scan is already running (e.g. started before a page refresh or
        // left over from a crashed session). Sync the UI so the Stop button
        // appears instead of leaving the user stuck on Start.
        scanStartedAt.current = Date.now() - STOP_BTN_MIN_MS  // already running → no min wait
        setOracleState('running')
        toast.info('A scan is already running — Stop button enabled')
        addLog('WARN', 'Scan already running on the server. Use Stop to cancel it.')
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(async () => {
          await fetchLog()
          const s = await fetch('/scan/status', { headers: authH() }).then(r => r.json()).catch(() => null)
          if (s && s.status !== 'running') {
            setOracleState('idle')
            clearInterval(pollRef.current!)
            fetchEnrichStats()
            await loadScanResults()
          }
        }, 3000)
        return
      }
      if (!res.ok) { toast.error((await res.json()).error || 'Failed to start scan'); return }
      scanStartedAt.current = Date.now()
      setOracleState('running')
      addLog('INFO', `Oracle Intent Engine starting... sources: ${selectedSources.join(', ')}${jdeMfg ? ' [JDE Mfg Focus]' : ''}`)
      toast.success('Oracle Intent scan started')
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(async () => {
        await fetchLog()
        const s = await fetch('/scan/status', { headers: authH() }).then(r => r.json()).catch(() => null)
        const elapsed = Date.now() - scanStartedAt.current
        if (s && s.status !== 'running' && elapsed >= STOP_BTN_MIN_MS) {
          setOracleState('idle')
          const companies = s.companies_found ?? 0
          const msg = companies > 0 ? `Oracle Intent scan completed — ${companies} companies found.` : 'Oracle Intent scan completed (0 companies found — check log for details).'
          addLog(companies > 0 ? 'SUCCESS' : 'WARN', msg)
          if (companies > 0) { toast.success(`Scan completed — ${companies} companies found`) } else { toast.info('Scan done — 0 companies (check Engine Log)') }
          clearInterval(pollRef.current!)
          fetchEnrichStats()
          await loadScanResults()   // show discovered companies for selection
          // Auto-enrich: the backend chains the full enrichment pipeline
          // (stages 1-7) automatically — attach to its log/status stream.
          if (autoTrigger) {
            addLog('INFO', 'Auto-enrich: full pipeline starting on the server...')
            toast.info('Auto-enrichment starting...')
            setEnrichState('running')
            setShowEnrichLog(true)
            if (enrichPoll.current) clearInterval(enrichPoll.current)
            enrichPoll.current = setInterval(async () => {
              await fetchEnrichLog()
              const es = await fetch('/api/enrich/status', { headers: authH() }).then(r => r.json()).catch(() => null)
              if (es) setEnrichStatus(es)
              if (es && es.status !== 'running') {
                setEnrichState('idle')
                setEnrichDone(true)
                clearInterval(enrichPoll.current!)
                fetchEnrichStats()
                toast.success(`Enrichment done — ${es.contacts_found || 0} contacts, ${es.contacts_validated || 0} valid emails`)
              }
            }, 3000)
          }
        }
      }, 3000)
    } catch { toast.error('Cannot connect to backend.') }
  }

  const stopEngine = async () => {
    try {
      await fetch('/scan/stop', { method: 'POST', headers: authH() })
      setOracleState('stopping')
      addLog('INFO', 'Stop signal sent. Engine winding down...')
      toast.info('Oracle scan stopping...')
      setTimeout(() => { setOracleState('idle'); addLog('INFO', 'Engine stopped.'); if (pollRef.current) clearInterval(pollRef.current) }, 2000)
    } catch { toast.error('Failed to send stop signal') }
  }

  const resetEngine = () => {
    if (oracleState === 'running') stopEngine()
    setTimeout(() => { setOracleState('idle'); toast.info('Engine reset') }, oracleState === 'running' ? 2500 : 0)
  }

  // Bootstrap: fetch current state on mount and re-attach polling loops if
  // either engine is already running (handles hard-refresh mid-run).
  useEffect(() => {
    const bootstrap = async () => {
      await fetchLog()
      await fetchEnrichStats()

      // ── Oracle scan ──────────────────────────────────────────────────────────
      try {
        const r = await fetch('/scan/status', { headers: authH() })
        if (r.ok) {
          const d = await r.json()
          if (d.status === 'running') {
            scanStartedAt.current = Date.now() - STOP_BTN_MIN_MS  // already running → no min wait
            setOracleState('running')
            addLog('INFO', 'Scan already running — resuming live log...')
            if (pollRef.current) clearInterval(pollRef.current)
            pollRef.current = setInterval(async () => {
              await fetchLog()
              const s = await fetch('/scan/status', { headers: authH() })
                .then(res => res.json()).catch(() => null)
              if (s && s.status !== 'running') {
                setOracleState('idle')
                addLog('SUCCESS', 'Oracle Intent scan completed.')
                clearInterval(pollRef.current!)
                pollRef.current = null
                fetchEnrichStats()
                await loadScanResults()
              }
            }, 3000)
          }
        }
      } catch { /* silent */ }

      // ── Lead Enrichment ──────────────────────────────────────────────────────
      try {
        const r = await fetch('/api/enrich/status', { headers: authH() })
        if (r.ok) {
          const d = await r.json()
          setEnrichStatus(d)
          if (d.status === 'running') {
            setEnrichState('running')
            setShowEnrichLog(true)
            if (enrichPoll.current) clearInterval(enrichPoll.current)
            enrichPoll.current = setInterval(async () => {
              await fetchEnrichLog()
              const s = await fetch('/api/enrich/status', { headers: authH() })
                .then(res => res.json()).catch(() => null)
              if (s) setEnrichStatus(s)
              if (s && s.status !== 'running') {
                setEnrichState('idle')
                setEnrichDone(true)
                clearInterval(enrichPoll.current!)
                enrichPoll.current = null
                fetchEnrichStats()
              }
            }, 3000)
          }
        }
      } catch { /* silent */ }
    }

    bootstrap()
    return () => {
      if (pollRef.current)    clearInterval(pollRef.current)
      if (enrichPoll.current) clearInterval(enrichPoll.current)
    }
  }, [])

  useEffect(() => { if (!logScrollLocked      && logRef.current)       logRef.current.scrollTop       = logRef.current.scrollHeight }, [logs, logScrollLocked])
  useEffect(() => { if (!enrichScrollLocked   && enrichLogRef.current) enrichLogRef.current.scrollTop = enrichLogRef.current.scrollHeight }, [enrichLogs, enrichScrollLocked])

  const toggleSource = (id: string) =>
    setSelectedSources(ss => ss.includes(id) ? ss.filter(x => x !== id) : [...ss, id])

  const exportLog = () => {
    const text = logs.map(l => `[${l.t}] [${l.level}] ${l.msg}`).join('\n')
    const blob = new Blob([text], { type: 'text/plain' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `scan_log_${new Date().toISOString().slice(0,19).replace(/:/g,'-')}.txt`
    a.click()
    URL.revokeObjectURL(url)
    toast.success('Log downloaded')
  }

  const clearLog = () => { setLogs([{ t: now(), level: 'INFO', msg: 'Log cleared.' }]); toast.info('Log cleared') }

  const pending  = enrichStats.pending_companies   ?? 0
  const enriched = enrichStats.enriched_companies  ?? 0
  const totalCo  = enrichStats.total_companies     ?? 0
  const totalCt  = enrichStats.total_contacts      ?? 0
  const validCt  = enrichStats.contacts_valid_email ?? 0
  const pctDone  = totalCo > 0 ? Math.round((enriched / totalCo) * 100) : 0
  const apolloOk = enrichStats.apollo_configured
  const zbOk     = enrichStats.zerobounce_configured

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:20, width:'100%' }}>
      <style>{`@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}} @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}`}</style>

      {/* Scan results modal */}
      {showScanResults && (
        <ScanResultsModal
          onClose={() => setShowScanResults(false)}
          onDeleted={() => { fetchEnrichStats(); fetchEnrichStatus() }}
        />
      )}

      {/* Pre-flight modal */}
      {showPreflight && preflight && (
        <PreflightModal
          preflight={preflight}
          enrichLimit={enrichLimit} enrichPerCo={enrichPerCo}
          batchSize={batchSize}    selectedRoles={selectedRoles}
          provider={provider}
          pendingCompanies={pendingCompanies}
          selectedCompanyIds={selectedCompanyIds}
          onClose={() => setShowPreflight(false)}
          onStart={startEnrichment}
          setEnrichLimit={setEnrichLimit} setEnrichPerCo={setEnrichPerCo}
          setBatchSize={setBatchSize}     setSelectedRoles={setSelectedRoles}
          setProvider={setProvider}
          setSelectedCompanyIds={setSelectedCompanyIds}
        />
      )}

      <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between' }}>
        <div>
          <h1 style={{ fontSize:20, fontWeight:600, color:'#0f172a', margin:0 }}>Engine Control</h1>
          <p style={{ fontSize:13, color:'#64748b', marginTop:4 }}>Start, stop, and monitor intelligence engines in real time</p>
        </div>
        <button
          onClick={() => setShowScanResults(true)}
          style={{ display:'flex', alignItems:'center', gap:8, padding:'9px 18px', borderRadius:8,
                   border:'1px solid rgba(59,130,246,0.35)', background:'rgba(59,130,246,0.06)',
                   color:'#2563eb', fontSize:13, fontWeight:500, cursor:'pointer', flexShrink:0 }}>
          <BarChart2 size={14} /> View Scan Results
        </button>
      </div>

      {/* Engine cards */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:16 }}>
        {ENGINES.map(engine => {
          const isOracle     = engine.id === 'oracle'
          const isEnrichment = engine.id === 'enrichment'
          const isHubspot    = engine.id === 'hubspot'
          const state        = isOracle ? oracleState : isEnrichment ? enrichState : 'idle'
          const running      = state === 'running'

          // Enrichment card sub-info
          const enrichPending = pending > 0 ? `${pending} companies pending` : enriched > 0 ? `${enriched} enriched` : null

          return (
            <div key={engine.id} style={card}>
              <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between', marginBottom:12 }}>
                <div style={{ flex:1, paddingRight:12 }}>
                  <div style={{ fontSize:14, fontWeight:600, color:'#0f172a' }}>{engine.label}</div>
                  <div style={{ fontSize:12, color:'#64748b', marginTop:4, lineHeight:1.5 }}>{engine.desc}</div>
                </div>
                <div style={{ width:10, height:10, borderRadius:'50%', flexShrink:0, marginTop:4,
                  background: running ? engine.color : isHubspot ? '#e2e8f0' : '#cbd5e1',
                  boxShadow: running ? `0 0 8px ${engine.color}` : 'none',
                  animation: running ? 'pulse 1.5s infinite' : 'none' }} />
              </div>
              <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:16 }}>
                <span style={{ fontSize:12, padding:'2px 10px', borderRadius:999, fontWeight:500,
                  background: running ? `${engine.color}18` : state === 'stopping' ? 'rgba(245,158,11,0.12)' : isHubspot ? 'rgba(203,213,225,0.3)' : 'rgba(203,213,225,0.5)',
                  color:      running ? engine.color : state === 'stopping' ? '#f59e0b' : isHubspot ? '#cbd5e1' : '#94a3b8' }}>
                  {running ? 'Running' : state === 'stopping' ? 'Stopping...' : isHubspot ? 'Not connected' : 'Idle'}
                </span>
                {engine.modules > 1 && <span style={{ fontSize:12, color:'#374151' }}>{engine.modules} modules</span>}
                {isEnrichment && enrichPending && !running && (
                  <span style={{ fontSize:11, padding:'2px 8px', borderRadius:999, background:'rgba(245,158,11,0.12)', color:'#d97706', fontWeight:500 }}>
                    {enrichPending}
                  </span>
                )}
                {isEnrichment && running && enrichStatus.companies_processed != null && (
                  <span style={{ fontSize:11, color:'#94a3b8' }}>
                    {enrichStatus.companies_processed}/{enrichStatus.companies_total ?? '?'} companies
                  </span>
                )}
              </div>
              <div style={{ display:'flex', gap:8 }}>
                {isOracle && (
                  state === 'idle' ? (
                    <button onClick={startEngine} style={{ flex:1, display:'flex', alignItems:'center', justifyContent:'center', gap:8, padding:'9px 0', borderRadius:8, border:'none', background:engine.color, color:'white', fontSize:13, fontWeight:500, cursor:'pointer' }}>
                      <Play size={13} /> Start Scan
                    </button>
                  ) : (
                    <button onClick={stopEngine} disabled={state === 'stopping'} style={{ flex:1, display:'flex', alignItems:'center', justifyContent:'center', gap:8, padding:'9px 0', borderRadius:8, border:'1px solid rgba(239,68,68,0.3)', background:'rgba(239,68,68,0.1)', color:'#ef4444', fontSize:13, fontWeight:500, cursor:'pointer', opacity: state === 'stopping' ? 0.5 : 1 }}>
                      <Square size={13} /> Stop
                    </button>
                  )
                )}
                {isEnrichment && (
                  enrichState === 'idle' ? (
                    <button onClick={() => fetchPreflight()} disabled={preflightLoading}
                      style={{ flex:1, display:'flex', alignItems:'center', justifyContent:'center', gap:8, padding:'9px 0', borderRadius:8, border:'none',
                        background: engine.color,
                        color: 'white',
                        fontSize:13, fontWeight:500, cursor: 'pointer',
                        opacity: preflightLoading ? 0.7 : 1 }}>
                      {preflightLoading
                        ? <><span style={{ animation:'spin 1s linear infinite', display:'inline-block' }}>⟳</span> Loading...</>
                        : <><Zap size={13} /> {pending > 0 ? `Enrich ${pending}` : 'Run Enrichment'}</>}
                    </button>
                  ) : (
                    <button onClick={stopEnrichment} style={{ flex:1, display:'flex', alignItems:'center', justifyContent:'center', gap:8, padding:'9px 0', borderRadius:8, border:'1px solid rgba(239,68,68,0.3)', background:'rgba(239,68,68,0.1)', color:'#ef4444', fontSize:13, fontWeight:500, cursor:'pointer' }}>
                      <Square size={13} /> Stop
                    </button>
                  )
                )}
                {isHubspot && (
                  <button disabled style={{ flex:1, display:'flex', alignItems:'center', justifyContent:'center', gap:8, padding:'9px 0', borderRadius:8, border:'1px solid #e2e8f0', background:'#f8fafc', color:'#cbd5e1', fontSize:13, cursor:'not-allowed' }}>
                    <Play size={13} /> Connect HubSpot
                  </button>
                )}
                <button
                  onClick={isOracle ? resetEngine : undefined}
                  style={{ width:36, height:36, borderRadius:8, border:'1px solid #e2e8f0', background:'transparent',
                    cursor: isOracle ? 'pointer' : 'default',
                    display:'flex', alignItems:'center', justifyContent:'center',
                    color:'#94a3b8', opacity: (isOracle) ? 1 : 0.3 }}>
                  <RotateCcw size={13} />
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Enrichment complete — point the user at the results */}
      {enrichDone && enrichState === 'idle' && (
        <div style={{ ...card, border:'1px solid rgba(16,185,129,0.35)', background:'rgba(16,185,129,0.04)' }}>
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:12 }}>
            <div style={{ display:'flex', alignItems:'center', gap:10 }}>
              <CheckCircle size={18} color="#10b981" />
              <div>
                <div style={{ fontSize:14, fontWeight:600, color:'#0f172a' }}>Enrichment complete</div>
                <div style={{ fontSize:12, color:'#64748b', marginTop:2 }}>
                  Companies and their contacts are now saved in the database — review them on the Companies and Contacts pages.
                </div>
              </div>
            </div>
            <div style={{ display:'flex', gap:8 }}>
              <button onClick={() => navigate('/companies')}
                style={{ display:'flex', alignItems:'center', gap:6, padding:'8px 16px', borderRadius:8, border:'none', background:'#3b82f6', color:'#fff', fontSize:13, fontWeight:600, cursor:'pointer' }}>
                <Building2 size={13} /> View Companies
              </button>
              <button onClick={() => navigate('/contacts')}
                style={{ display:'flex', alignItems:'center', gap:6, padding:'8px 16px', borderRadius:8, border:'none', background:'#6366f1', color:'#fff', fontSize:13, fontWeight:600, cursor:'pointer' }}>
                <Users size={13} /> View Contacts
              </button>
              <button onClick={() => setEnrichDone(false)}
                style={{ padding:'8px 12px', borderRadius:8, border:'1px solid #e2e8f0', background:'transparent', color:'#64748b', fontSize:13, cursor:'pointer' }}>
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Post-scan results — select companies and launch enrichment */}
      {showPostScan && pendingCompanies.length > 0 && enrichState === 'idle' && (
        <div style={{ ...card, border:'1px solid rgba(59,130,246,0.35)' }}>
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:12, flexWrap:'wrap', gap:10 }}>
            <div style={{ display:'flex', alignItems:'center', gap:10 }}>
              <BarChart2 size={16} color="#3b82f6" />
              <div>
                <div style={{ fontSize:14, fontWeight:600, color:'#0f172a' }}>
                  Scan complete — {pendingCompanies.length} companies awaiting enrichment
                </div>
                <div style={{ fontSize:12, color:'#64748b', marginTop:2 }}>
                  Select the companies to enrich, then launch the enrichment workflow.
                  Companies matched in contacts_master or already enriched are excluded automatically.
                </div>
              </div>
            </div>
            <div style={{ display:'flex', gap:8, alignItems:'center' }}>
              <span style={{ fontSize:12, padding:'3px 10px', borderRadius:999, background:'rgba(59,130,246,0.12)', color:'#2563eb', fontWeight:600 }}>
                {selectedCompanyIds.length} selected
              </span>
              <button onClick={() => setSelectedCompanyIds(pendingCompanies.map(c => c.id))}
                style={{ fontSize:12, color:'#3b82f6', background:'none', border:'none', cursor:'pointer', textDecoration:'underline' }}>All</button>
              <button onClick={() => setSelectedCompanyIds([])}
                style={{ fontSize:12, color:'#94a3b8', background:'none', border:'none', cursor:'pointer', textDecoration:'underline' }}>None</button>
            </div>
          </div>

          <input value={postScanQuery} onChange={e => setPostScanQuery(e.target.value)}
            placeholder="Search companies..."
            style={{ width:'100%', boxSizing:'border-box', padding:'8px 12px', borderRadius:8, border:'1px solid #e2e8f0', fontSize:13, outline:'none', background:'#f8fafc', marginBottom:10 }} />

          <div style={{ maxHeight:260, overflowY:'auto', border:'1px solid #e2e8f0', borderRadius:8, marginBottom:14 }}>
            {pendingCompanies
              .filter(c => !postScanQuery || c.name.toLowerCase().includes(postScanQuery.toLowerCase()))
              .map(c => {
                const on = selectedCompanyIds.includes(c.id)
                return (
                  <label key={c.id}
                    style={{ display:'flex', alignItems:'center', gap:10, padding:'8px 12px', cursor:'pointer',
                      borderBottom:'1px solid #f1f5f9', background: on ? 'rgba(59,130,246,0.04)' : 'transparent' }}>
                    <input type="checkbox" checked={on}
                      onChange={() => setSelectedCompanyIds(on ? selectedCompanyIds.filter(x => x !== c.id) : [...selectedCompanyIds, c.id])}
                      style={{ accentColor:'#3b82f6', cursor:'pointer', flexShrink:0 }} />
                    <Building2 size={13} color="#94a3b8" style={{ flexShrink:0 }} />
                    <span style={{ fontSize:13, fontWeight:500, color:'#0f172a', flex:1, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>
                      {c.name}
                    </span>
                    {c.domain && (
                      <span style={{ fontSize:11, color:'#64748b', whiteSpace:'nowrap', flexShrink:0 }}>{c.domain}</span>
                    )}
                    {c.target_product && (
                      <span style={{ fontSize:10, padding:'2px 8px', borderRadius:999, background:'rgba(16,185,129,0.1)', color:'#10b981', whiteSpace:'nowrap', flexShrink:0 }}>
                        {c.target_product}
                      </span>
                    )}
                    <span style={{ fontSize:10, padding:'2px 7px', borderRadius:999, background:'rgba(99,102,241,0.1)', color:'#818cf8', whiteSpace:'nowrap', flexShrink:0 }}>
                      {c.signal_count} signals
                    </span>
                  </label>
                )
              })}
          </div>

          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            <button onClick={() => fetchPreflight(true)} disabled={selectedCompanyIds.length === 0 || preflightLoading}
              style={{ display:'flex', alignItems:'center', gap:8, padding:'10px 22px', borderRadius:8, border:'none',
                background: selectedCompanyIds.length > 0 ? '#6366f1' : '#cbd5e1', color:'#fff',
                fontSize:13, fontWeight:600, cursor: selectedCompanyIds.length > 0 ? 'pointer' : 'not-allowed' }}>
              <Zap size={14} /> Launch Enrichment ({selectedCompanyIds.length} companies)
            </button>
            <button onClick={() => setShowPostScan(false)}
              style={{ padding:'10px 16px', borderRadius:8, border:'1px solid #e2e8f0', background:'transparent', color:'#64748b', fontSize:13, cursor:'pointer' }}>
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Config + Scan Log */}
      <div style={{ display:'grid', gridTemplateColumns:'360px 1fr', gap:16 }}>
        {/* Scan config */}
        <div style={card}>
          <div style={{ fontSize:14, fontWeight:600, color:'#0f172a', marginBottom:16 }}>Scan Configuration</div>

          {/* Auto-trigger enrichment toggle */}
          <div style={{ marginBottom:16, padding:'12px 14px', background: autoTrigger ? 'rgba(99,102,241,0.06)' : '#f8fafc', border:`1px solid ${autoTrigger ? 'rgba(99,102,241,0.25)' : '#e2e8f0'}`, borderRadius:10 }}>
            <div style={{ display:'flex', alignItems:'center', gap:10 }}>
              <button onClick={() => setAutoTrigger(v => !v)}
                style={{ width:36, height:20, borderRadius:10, border:'none', cursor:'pointer', background: autoTrigger ? '#6366f1' : '#cbd5e1', position:'relative', flexShrink:0, transition:'background 0.2s' }}>
                <span style={{ position:'absolute', top:2, left: autoTrigger ? 18 : 2, width:16, height:16, borderRadius:'50%', background:'white', transition:'left 0.2s' }} />
              </button>
              <Zap size={14} color={autoTrigger ? '#6366f1' : '#475569'} />
              <div>
                <div style={{ fontSize:13, fontWeight:600, color: autoTrigger ? '#6366f1' : '#0f172a' }}>Auto-enrich After Scan</div>
                <div style={{ fontSize:11, color:'#475569', marginTop:2 }}>Full pipeline: domains → contacts → validation → target product</div>
              </div>
            </div>
          </div>

          {/* JDE Manufacturing Focus */}
          <div style={{ marginBottom:16, padding:'12px 14px', background: jdeMfg ? 'rgba(16,185,129,0.08)' : '#f8fafc', border:`1px solid ${jdeMfg ? 'rgba(16,185,129,0.3)' : '#e2e8f0'}`, borderRadius:10 }}>
            <div style={{ display:'flex', alignItems:'center', gap:10 }}>
              <button onClick={() => setJdeMfg(v => !v)}
                style={{ width:36, height:20, borderRadius:10, border:'none', cursor:'pointer', background: jdeMfg ? '#10b981' : '#cbd5e1', position:'relative', flexShrink:0, transition:'background 0.2s' }}>
                <span style={{ position:'absolute', top:2, left: jdeMfg ? 18 : 2, width:16, height:16, borderRadius:'50%', background:'white', transition:'left 0.2s' }} />
              </button>
              <Factory size={14} color={jdeMfg ? '#10b981' : '#475569'} />
              <div>
                <div style={{ fontSize:13, fontWeight:600, color: jdeMfg ? '#10b981' : '#0f172a' }}>JDE Manufacturing Focus</div>
                <div style={{ fontSize:11, color:'#475569', marginTop:2 }}>Manufacturing queries + LinkedIn industry filter</div>
              </div>
            </div>
            {jdeMfg && (
              <div style={{ marginTop:10, fontSize:11, color:'#64748b', lineHeight:1.6 }}>
                ✓ 29 manufacturing-specific JDE queries<br/>
                ✓ LinkedIn: Manufacturing, Automotive, Industrial Eng, Construction, Energy, Food & Bev<br/>
                ✓ Home Builders: 36 companies ≥1,000 annual closings
              </div>
            )}
          </div>

          {/* Data Sources */}
          <div style={{ marginBottom:16 }}>
            {/* Active sources */}
            <div style={{ fontSize:12, fontWeight:500, color:'#94a3b8', marginBottom:8 }}>
              Data Sources
              <span style={{ marginLeft:8, fontSize:10, fontWeight:600, padding:'2px 7px', borderRadius:999, background:'rgba(16,185,129,0.12)', color:'#10b981' }}>
                {ACTIVE_SOURCES.filter(s => selectedSources.includes(s.id)).length}/{ACTIVE_SOURCES.length} active
              </span>
            </div>
            <div style={{ display:'flex', flexDirection:'column', gap:6, marginBottom:10 }}>
              {ACTIVE_SOURCES.map(s => {
                const active = selectedSources.includes(s.id)
                return (
                  <button key={s.id} onClick={() => toggleSource(s.id)}
                    style={{ display:'flex', alignItems:'center', gap:10, padding:'8px 10px', borderRadius:8, cursor:'pointer', background: active ? 'rgba(59,130,246,0.08)' : '#f8fafc', color: active ? '#2563eb' : '#64748b', border: active ? '1px solid rgba(59,130,246,0.25)' : '1px solid #e2e8f0', textAlign:'left', transition:'all 0.15s' }}>
                    <div style={{ width:6, height:6, borderRadius:'50%', background: active ? '#10b981' : '#cbd5e1', flexShrink:0 }} />
                    <div style={{ flex:1 }}>
                      <span style={{ fontSize:12, fontWeight:500 }}>{s.label}</span>
                      <span style={{ fontSize:11, color:'#94a3b8', marginLeft:6 }}>{s.desc}</span>
                    </div>
                  </button>
                )
              })}
            </div>

            {/* Experimental sources — collapsed by default */}
            <details style={{ cursor:'pointer' }}>
              <summary style={{ fontSize:11, fontWeight:500, color:'#94a3b8', listStyle:'none', display:'flex', alignItems:'center', gap:6, userSelect:'none', marginBottom:6 }}>
                <span style={{ fontSize:10 }}>▶</span>
                Experimental sources (0 signals to date)
              </summary>
              <div style={{ display:'flex', flexDirection:'column', gap:5, marginTop:6 }}>
                {EXPERIMENTAL_SOURCES.map(s => {
                  const active = selectedSources.includes(s.id)
                  return (
                    <button key={s.id} onClick={() => toggleSource(s.id)}
                      style={{ display:'flex', alignItems:'center', gap:10, padding:'7px 10px', borderRadius:8, cursor:'pointer', background: active ? 'rgba(245,158,11,0.08)' : '#f8fafc', color: active ? '#d97706' : '#94a3b8', border: active ? '1px solid rgba(245,158,11,0.3)' : '1px solid #e2e8f0', textAlign:'left', transition:'all 0.15s', opacity:0.8 }}>
                      <div style={{ width:6, height:6, borderRadius:'50%', background: active ? '#f59e0b' : '#e2e8f0', flexShrink:0 }} />
                      <div style={{ flex:1 }}>
                        <span style={{ fontSize:11, fontWeight:500 }}>{s.label}</span>
                        <span style={{ fontSize:10, color:'#cbd5e1', marginLeft:6 }}>{s.desc}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
            </details>
          </div>

          {/* Scan Depth */}
          <div style={{ marginBottom:16 }}>
            <div style={{ fontSize:12, fontWeight:500, color:'#94a3b8', marginBottom:8 }}>Scan Depth</div>
            <select value={depth} onChange={e => setDepth(e.target.value)} style={{ width:'100%', padding:'8px 12px', borderRadius:8, background:'#ffffff', color:'#0f172a', border:'1px solid #d1d5db', fontSize:13, cursor:'pointer' }}>
              <option value="shallow">Shallow — fast, 1 page per source</option>
              <option value="medium">Medium — balanced, 3 pages</option>
              <option value="deep">Deep — thorough, 5 pages</option>
            </select>
          </div>

          <div style={{ padding:'10px 12px', background:'#f8fafc', border:'1px solid #e2e8f0', borderRadius:8, fontSize:11, color:'#94a3b8' }}>
            {ACTIVE_SOURCES.filter(s => selectedSources.includes(s.id)).length} active + {EXPERIMENTAL_SOURCES.filter(s => selectedSources.includes(s.id)).length} experimental · depth: {depth}
            {jdeMfg && <span style={{ color:'#10b981', marginLeft:8 }}>· JDE Mfg focus ON</span>}
            {autoTrigger && <span style={{ color:'#6366f1', marginLeft:8 }}>· auto-enrich ON</span>}
          </div>
        </div>

        {/* Scan live log */}
        <div style={{ background:'#080c14', border:'1px solid #1f2d45', borderRadius:12, overflow:'hidden', display:'flex', flexDirection:'column' }}>
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'10px 16px', borderBottom:'1px solid #1f2d45' }}>
            <div style={{ display:'flex', alignItems:'center', gap:6 }}>
              <div style={{ width:10, height:10, borderRadius:'50%', background:'#ef4444' }} />
              <div style={{ width:10, height:10, borderRadius:'50%', background:'#f59e0b' }} />
              <div style={{ width:10, height:10, borderRadius:'50%', background:'#10b981' }} />
              <span style={{ marginLeft:8, fontFamily:'JetBrains Mono, monospace', fontSize:12, color:'#475569' }}>scan.log — {logs.length} events</span>
            </div>
            <div style={{ display:'flex', gap:12, alignItems:'center' }}>
              <button
                onClick={() => setLogScrollLocked(v => !v)}
                title={logScrollLocked ? 'Unlock auto-scroll' : 'Lock scroll position'}
                style={{ fontSize:11, display:'flex', alignItems:'center', gap:4,
                  color: logScrollLocked ? '#f59e0b' : '#475569',
                  background: logScrollLocked ? 'rgba(245,158,11,0.12)' : 'none',
                  border: logScrollLocked ? '1px solid rgba(245,158,11,0.3)' : '1px solid transparent',
                  borderRadius:5, padding:'2px 7px', cursor:'pointer' }}>
                {logScrollLocked ? '🔒 Locked' : '🔓 Auto-scroll'}
              </button>
              <button onClick={exportLog} style={{ fontSize:12, display:'flex', alignItems:'center', gap:4, color:'#475569', background:'none', border:'none', cursor:'pointer' }}><Download size={11} /> Export</button>
              <button onClick={clearLog}  style={{ fontSize:12, display:'flex', alignItems:'center', gap:4, color:'#475569', background:'none', border:'none', cursor:'pointer' }}><Trash2 size={11} /> Clear</button>
            </div>
          </div>
          <div ref={logRef} style={{ fontFamily:'JetBrains Mono, monospace', fontSize:12, padding:16, flex:1, minHeight:260, overflowY:'auto', display:'flex', flexDirection:'column', gap:4 }}>
            {logs.map((log, i) => (
              <div key={i} style={{ display:'flex', gap:12, lineHeight:'1.7' }}>
                <span style={{ color:'#374151', flexShrink:0 }}>[{log.t}]</span>
                <span style={{ color:levelColor(log.level), flexShrink:0, minWidth:72 }}>[{log.level}]</span>
                <span style={{ color:'#94a3b8' }}>{log.msg}</span>
              </div>
            ))}
            <div style={{ display:'flex', alignItems:'center', gap:4 }}>
              <span style={{ color:'#374151' }}>›</span>
              <span style={{ display:'inline-block', width:7, height:14, background:'#3b82f6', opacity:0.7 }} />
            </div>
          </div>
        </div>
      </div>

      {/* ── Contact Enrichment Pipeline ────────────────────────────────────── */}
      <div style={card}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:16 }}>
          <div>
            <div style={{ fontSize:14, fontWeight:600, color:'#0f172a' }}>Contact Enrichment Pipeline</div>
            <div style={{ fontSize:12, color:'#475569', marginTop:3 }}>
              contacts_master check → Apollo people search → ZeroBounce → email prediction → store
            </div>
          </div>
          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            <div style={{ display:'flex', gap:6 }}>
              <span style={{ fontSize:11, padding:'3px 8px', borderRadius:6, background: apolloOk ? 'rgba(59,130,246,0.15)' : 'rgba(239,68,68,0.1)', color: apolloOk ? '#60a5fa' : '#f87171', border:`1px solid ${apolloOk ? 'rgba(59,130,246,0.25)' : 'rgba(239,68,68,0.2)'}` }}>
                Apollo {apolloOk ? '✓' : '✗'}
              </span>
              <span style={{ fontSize:11, padding:'3px 8px', borderRadius:6, background: zbOk ? 'rgba(16,185,129,0.12)' : 'rgba(100,116,139,0.1)', color: zbOk ? '#34d399' : '#64748b', border:`1px solid ${zbOk ? 'rgba(16,185,129,0.2)' : '#1f2d45'}` }}>
                ZeroBounce {zbOk ? '✓' : 'optional'}
              </span>
              <span style={{ fontSize:11, padding:'3px 8px', borderRadius:6, background:'rgba(99,102,241,0.1)', color:'#818cf8', border:'1px solid rgba(99,102,241,0.2)' }}>
                {selectedRoles.length} roles selected
              </span>
            </div>
          </div>
        </div>

        {/* Stats row */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(5, 1fr)', gap:10, marginBottom:20 }}>
          {[
            { icon: <Users size={14}/>,        label:'Total Companies', value: totalCo,   color:'#3b82f6' },
            { icon: <CheckCircle size={14}/>,   label:'Enriched',       value: enriched,  color:'#10b981' },
            { icon: <Users size={14}/>,         label:'Pending',        value: pending,   color:'#f59e0b' },
            { icon: <Users size={14}/>,         label:'Contacts Found', value: totalCt,   color:'#8b5cf6' },
            { icon: <Mail size={14}/>,          label:'Valid Emails',   value: validCt,   color:'#06b6d4' },
          ].map(({ icon, label, value, color }) => (
            <div key={label} style={{ background:'#f8fafc', border:'1px solid #e2e8f0', borderRadius:10, padding:'12px 14px' }}>
              <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:6, color }}>
                {icon}
                <span style={{ fontSize:11, color:'#64748b' }}>{label}</span>
              </div>
              <div style={{ fontSize:22, fontWeight:700, color:'#0f172a' }}>{value.toLocaleString()}</div>
            </div>
          ))}
        </div>

        {/* Enrichment progress bar */}
        {totalCo > 0 && (
          <div style={{ marginBottom:16 }}>
            <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6, fontSize:12, color:'#64748b' }}>
              <span>Enrichment coverage</span>
              <span>{enriched} / {totalCo} companies ({pctDone}%)</span>
            </div>
            <div style={{ height:6, background:'#e2e8f0', borderRadius:3, overflow:'hidden' }}>
              <div style={{ height:'100%', width:`${pctDone}%`, background:'linear-gradient(90deg, #3b82f6, #6366f1)', borderRadius:3, transition:'width 0.4s' }} />
            </div>
          </div>
        )}

        {/* Running progress */}
        {enrichState === 'running' && (
          <div style={{ marginBottom:16, padding:'10px 14px', background:'rgba(99,102,241,0.08)', border:'1px solid rgba(99,102,241,0.25)', borderRadius:8 }}>
            <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:8 }}>
              <div style={{ width:8, height:8, borderRadius:'50%', background:'#6366f1', boxShadow:'0 0 6px #6366f1', animation:'pulse 1s infinite' }} />
              <span style={{ fontSize:13, color:'#a5b4fc', fontWeight:500 }}>Enrichment running...</span>
            </div>
            <div style={{ fontSize:12, color:'#64748b' }}>{enrichStatus.progress || 'Processing...'}</div>
            <div style={{ display:'flex', gap:20, marginTop:8, fontSize:12, color:'#94a3b8' }}>
              <span>{enrichStatus.companies_processed ?? 0} / {enrichStatus.companies_total ?? '?'} companies</span>
              <span>{enrichStatus.contacts_found ?? 0} contacts found</span>
              <span>{enrichStatus.contacts_validated ?? 0} valid emails</span>
            </div>
          </div>
        )}

        {/* Controls */}
        <div style={{ display:'flex', alignItems:'center', gap:12, flexWrap:'wrap' }}>
          {enrichState === 'idle' ? (
            <button
              onClick={() => fetchPreflight()}
              disabled={preflightLoading}
              style={{ display:'flex', alignItems:'center', gap:8, padding:'9px 20px', borderRadius:8, border:'none', background: apolloOk ? '#6366f1' : 'rgba(55,65,81,0.4)', color: apolloOk ? 'white' : '#6b7280', fontSize:13, fontWeight:500, cursor: apolloOk ? 'pointer' : 'not-allowed', opacity: preflightLoading ? 0.7 : 1 }}
              title={!apolloOk ? 'Add APOLLO_API_KEY to oracle_intent_engine/.env' : 'Open pre-flight check'}>
              {preflightLoading
                ? <><span style={{ animation:'spin 1s linear infinite', display:'inline-block' }}>⟳</span> Loading...</>
                : <><Zap size={13} /> {pending > 0 ? `Enrich ${pending} companies` : 'Run Enrichment'}</>
              }
            </button>
          ) : (
            <button onClick={stopEnrichment}
              style={{ display:'flex', alignItems:'center', gap:8, padding:'9px 20px', borderRadius:8, border:'1px solid rgba(239,68,68,0.3)', background:'rgba(239,68,68,0.1)', color:'#ef4444', fontSize:13, fontWeight:500, cursor:'pointer' }}>
              <Square size={13} /> Stop Enrichment
            </button>
          )}

          <button onClick={() => { setShowEnrichLog(v => !v); if (!showEnrichLog) fetchEnrichLog() }}
            style={{ display:'flex', alignItems:'center', gap:6, padding:'9px 14px', borderRadius:8, border:'1px solid #e2e8f0', background:'transparent', color:'#64748b', fontSize:12, cursor:'pointer' }}>
            {showEnrichLog ? 'Hide' : 'Show'} log
          </button>

          {!apolloOk && (
            <div style={{ fontSize:11, color:'#f87171', padding:'8px 12px', background:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.2)', borderRadius:8 }}>
              Apollo key not configured — add <code style={{ background:'rgba(239,68,68,0.15)', padding:'1px 4px', borderRadius:3 }}>APOLLO_API_KEY</code> to oracle_intent_engine/.env
            </div>
          )}
        </div>

        {/* Enrichment log */}
        {showEnrichLog && (
          <div style={{ marginTop:16, background:'#080c14', border:'1px solid #1f2d45', borderRadius:10, overflow:'hidden' }}>
            <div style={{ padding:'8px 14px', borderBottom:'1px solid #1f2d45', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
              <span style={{ fontFamily:'JetBrains Mono, monospace', fontSize:11, color:'#475569' }}>enrich.log — {enrichLogs.length} entries</span>
              <div style={{ display:'flex', gap:10, alignItems:'center' }}>
                <button
                  onClick={() => setEnrichScrollLocked(v => !v)}
                  title={enrichScrollLocked ? 'Unlock auto-scroll' : 'Lock scroll position'}
                  style={{ fontSize:11, display:'flex', alignItems:'center', gap:4,
                    color: enrichScrollLocked ? '#f59e0b' : '#475569',
                    background: enrichScrollLocked ? 'rgba(245,158,11,0.12)' : 'none',
                    border: enrichScrollLocked ? '1px solid rgba(245,158,11,0.3)' : '1px solid transparent',
                    borderRadius:5, padding:'2px 7px', cursor:'pointer' }}>
                  {enrichScrollLocked ? '🔒 Locked' : '🔓 Auto-scroll'}
                </button>
                <button onClick={() => setEnrichLogs([])} style={{ fontSize:11, color:'#475569', background:'none', border:'none', cursor:'pointer' }}>Clear</button>
              </div>
            </div>
            <div ref={enrichLogRef} style={{ fontFamily:'JetBrains Mono, monospace', fontSize:11, padding:14, maxHeight:220, overflowY:'auto', display:'flex', flexDirection:'column', gap:3 }}>
              {enrichLogs.length === 0
                ? <span style={{ color:'#374151' }}>No enrichment log yet. Start enrichment to see progress.</span>
                : enrichLogs.map((log, i) => (
                    <div key={i} style={{ display:'flex', gap:10, lineHeight:'1.6' }}>
                      <span style={{ color:'#374151', flexShrink:0 }}>[{log.t}]</span>
                      <span style={{ color:levelColor(log.level), flexShrink:0, minWidth:64 }}>[{log.level}]</span>
                      <span style={{ color:'#94a3b8' }}>{log.msg}</span>
                    </div>
                  ))
              }
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
