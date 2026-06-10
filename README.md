# Inoapps Intelligence Platform

> AI-powered B2B sales intelligence tool for the Inoapps Oracle/JDE go-to-market team.
> Automatically identifies companies that are buying, implementing, or upgrading Oracle products,
> enriches them with verified decision-maker contacts, and surfaces them in a React dashboard
> ready for outreach or HubSpot CRM push.

[![Python](https://img.shields.io/badge/Python-3.13+-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-blue)](https://postgresql.org)
[![React](https://img.shields.io/badge/React-18+-61DAFB)](https://react.dev)
[![License](https://img.shields.io/badge/License-Proprietary-red)]()

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [System Architecture](#system-architecture)
3. [Repository Structure](#repository-structure)
4. [Oracle Intent Engine](#oracle-intent-engine)
5. [Lead Enrichment Engine](#lead-enrichment-engine)
6. [Contacts Master — Salesforce Export](#contacts-master--salesforce-export)
7. [Database Schema](#database-schema)
8. [React Frontend Pages](#react-frontend-pages)
9. [Environment Setup](#environment-setup)
10. [Running the Application](#running-the-application)
11. [Signal Sources & Confidence Scoring](#signal-sources--confidence-scoring)
12. [User Roles](#user-roles)
13. [Contributing / KT Notes](#contributing--kt-notes)

---

## What It Does

The platform answers one question for the Inoapps sales team:

> **Which companies are actively buying, implementing, or upgrading Oracle/JDE right now — and who should we call?**

It works in two automated stages:

| Stage | Module | What it does |
|-------|--------|-------------|
| **1. Signal Detection** | Oracle Intent Engine | Scrapes job boards, Oracle's website, news, case studies, and community forums to find companies showing Oracle buying intent |
| **2. Contact Enrichment** | Lead Enrichment Engine | For every detected company, finds and validates the email + LinkedIn of decision-makers (IT Directors, Finance Managers, Oracle Admins) |
| **3. Dashboard + CRM** | React UI + HubSpot Sync | Sales team reviews prospects, exports contacts, and pushes approved leads into HubSpot CRM |

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Inoapps Intelligence Platform                    │
│                                                                      │
│  ┌───────────────────────────┐    ┌───────────────────────────────┐  │
│  │   Oracle Intent Engine    │    │   Lead Enrichment Engine      │  │
│  │   (Signal Detection)      │    │   (Contact Enrichment)        │  │
│  │                           │    │                               │  │
│  │  Scrapes 13 sources:      │    │  7-stage pipeline:            │  │
│  │  • Indeed / ZipRecruiter  │    │  1. Clean + deduplicate       │  │
│  │  • Adzuna / TotalJobs     │    │  2. Resolve company domains   │  │
│  │  • CWJobs                 │    │  3. Apollo enrichment         │  │
│  │  • Oracle.com customers   │    │  4. ZeroBounce validate       │  │
│  │  • Oracle Community       │    │  5. Predict missing emails    │  │
│  │  • Oracle Events          │    │  6. ZeroBounce validate       │  │
│  │  • News (Bing/Google RSS) │    │  7. Score readiness           │  │
│  │  • SI/Partner case studies│    │                               │  │
│  │  • Company pages          │    │  Input:  Excel/CSV of leads   │  │
│  │                           │    │  Output: Enriched CSV + HubSpot│ │
│  └─────────────┬─────────────┘    └──────────────┬────────────────┘  │
│                │                                  │                   │
│                ▼                                  ▼                   │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │           PostgreSQL — Inoapps-Data-DB (10.0.0.149:5432)        │  │
│  │                                                                 │  │
│  │  companies · signals · company_contacts · contacts_master       │  │
│  │  scan_runs · enrichment_cache · domain_knowledge · users        │  │
│  └──────────────────────────────┬──────────────────────────────────┘  │
│                                 │                                     │
│                                 ▼                                     │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │              unified_app.py  (FastAPI — port 8000)              │  │
│  │  Launches both engines as background threads on startup.        │  │
│  │  Serves all REST API endpoints consumed by the React UI.        │  │
│  └──────────────────────────────┬──────────────────────────────────┘  │
│                                 │                                     │
│                                 ▼                                     │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │           React 18 + TypeScript Frontend (Vite)                 │  │
│  │  Dashboard · Companies · Contacts · Reporting                   │  │
│  │  Engine Control · HubSpot Sync · Review Queue · Settings        │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

**External APIs:**

| API | Purpose | Auth Header |
|-----|---------|------------|
| Apollo.io | Find contacts (email + LinkedIn) at companies | `X-Api-Key` (NOT Bearer) |
| ZeroBounce | Validate email addresses before outreach | `api_key` query param |
| HubSpot | CRM push — approved contacts | `Authorization: Bearer` |
| NewsAPI | News article signals | `apiKey` query param |
| Bing News | News article signals (fallback) | `Ocp-Apim-Subscription-Key` |
| Ollama (local LLM) | Extract company names from news articles | Local — free |

---

## Repository Structure

```
DATA TOOL/
│
├── unified_app.py              ← Single FastAPI app — backend + engine launcher
├── scan_worker.py              ← Background thread for Oracle Intent Engine
├── enrichment_worker.py        ← Background thread for Lead Enrichment Engine
│
├── oracle_intent_engine/
│   └── src/
│       ├── config.py               ← All env vars and constants
│       ├── database.py             ← PostgreSQL: companies, signals, contacts, users
│       ├── apollo_enrichment.py    ← Find contacts: contacts_master first → Apollo fallback
│       ├── auth.py                 ← JWT helpers
│       ├── lead_scorer.py          ← Score companies 0-100 by signal strength
│       ├── phase_classifier.py     ← Classify Oracle buying phase
│       ├── llm_extractor.py        ← Ollama LLM for company name extraction
│       ├── exporter.py             ← CSV/Excel export
│       ├── firmographics.py        ← Company size/industry enrichment
│       ├── domain_enricher.py      ← Find company email domain
│       └── signals/
│           ├── base_signal.py              ← Abstract base — all signals inherit this
│           ├── indeed_signal.py            ← Indeed job board
│           ├── ziprecruiter_signal.py      ← ZipRecruiter job board
│           ├── adzuna_signal.py            ← Adzuna job board
│           ├── totaljobs_signal.py         ← TotalJobs (UK)
│           ├── cwjobs_signal.py            ← CWJobs (UK)
│           ├── oracle_website_signal.py    ← Oracle.com customer stories
│           ├── oracle_community_signal.py  ← Oracle community forums
│           ├── oracle_event_signal.py      ← Oracle events/conferences
│           ├── news_signal.py              ← NewsAPI + Bing + Google RSS
│           ├── si_casestudy_signal.py      ← SI partner case studies
│           ├── partner_casestudy_signal.py ← Oracle partner case studies
│           ├── home_builders_signal.py     ← Home builders industry
│           └── company_pages_signal.py     ← Company LinkedIn/website pages
│
├── lead_enrichment_engine/
│   └── src/
│       ├── config.py               ← All env vars
│       ├── pipeline.py             ← MAIN ENTRY POINT — runs all 7 stages
│       ├── orchestrator.py         ← Stage 3: Apollo bulk enrichment
│       ├── domain_resolver.py      ← Stage 2: Company email domain resolution
│       ├── zerobounce_client.py    ← Stages 4 & 6: Email validation
│       ├── email_pattern_engine.py ← Stage 5: Predict emails from name patterns
│       ├── pg_master.py            ← Read-only interface to contacts_master
│       ├── database.py             ← domain_knowledge, enrichment_cache tables
│       ├── pg_connector.py         ← PostgreSQL connection pool
│       ├── scoring.py              ← Stage 7: ready_for_outreach scoring
│       ├── cleaner.py              ← Stage 1: normalise + deduplicate input
│       ├── audit.py                ← Audit log CSV after each stage
│       └── checkpoint.py          ← Save/load pipeline checkpoints
│
├── frontend/
│   └── src/
│       ├── App.tsx                 ← Router + layout wrapper
│       ├── pages/
│       │   ├── Dashboard.tsx       ← KPI overview (signals, companies, contacts)
│       │   ├── Companies.tsx       ← Browse/filter prospect companies + signals
│       │   ├── Contacts.tsx        ← All enriched contacts across all companies
│       │   ├── EngineControl.tsx   ← Start/stop engines, live log viewer
│       │   ├── Reporting.tsx       ← Charts: signal sources, phases, contact coverage
│       │   ├── ReviewQueue.tsx     ← Approve contacts before HubSpot push
│       │   ├── HubSpotSync.tsx     ← Configure CRM + push approved contacts
│       │   └── Settings.tsx        ← API keys, user management, scan config
│       └── components/
│           ├── Sidebar.tsx         ← Navigation
│           └── Toast.tsx           ← Notification toasts
│
└── tests/                          ← pytest test suite
```

---

## Oracle Intent Engine

### What it does
Detects companies that are **actively buying, implementing, hiring for, or upgrading Oracle/JDE products**. Each scan produces companies with confidence-scored signals, ready for the sales team to act on.

### How a scan works

```
scan_worker.py triggers scan
    │
    ▼
For each signal class (IndeedSignal, NewsSignal, OracleWebsiteSignal, …):
    fetch() → scrape source → return list of SignalResult objects
    │
    ▼
Staffing agency filter
    → Remove consulting/staffing firms (they are NOT Oracle end-users)
    │
    ▼
Write to PostgreSQL
    companies table (ON CONFLICT DO UPDATE — no duplicates)
    signals table (one row per signal per company)
    │
    ▼
apollo_enrichment.py — for each new company:
    1. Check contacts_master first (Salesforce export — free)
    2. If no contacts found → call Apollo API (costs credits)
    3. Save contacts to company_contacts table
```

### Oracle products detected
```
JD Edwards · JDE EnterpriseOne · JDE E1 · Oracle Cloud ERP · Oracle Fusion
Oracle HCM · Oracle HCM Cloud · Oracle SCM · Oracle SCM Cloud
Oracle EPM · Oracle Hyperion · Oracle Planning Cloud
Oracle CX · Oracle Sales Cloud · NetSuite · Oracle NetSuite
Oracle OCI · Oracle Cloud Infrastructure
Oracle Integration Cloud (OIC) · Oracle Database · Oracle Autonomous Database
```

### Buying phases detected

| Phase | Signals that trigger it |
|-------|------------------------|
| `hiring` | Job postings for Oracle/JDE roles (CNC Admin, Functional Consultant, Developer) |
| `implementing` | "go-live", "deployment", "rollout", "implementation", "launch" |
| `evaluating` | "RFP", "procurement", "evaluating ERP", "ERP selection" |
| `upgrading` | "migration", "cloud migration", "modernize", "upgrade from" |
| `supporting` | "maintain", "administer", "manage existing Oracle system" |

---

## Lead Enrichment Engine

### What it does
Takes a list of raw leads (name + company, no email) and produces a fully-enriched, ZeroBounce-validated list with emails and LinkedIn URLs.

### The 7 Pipeline Stages

```
Input: Excel/CSV file with lead names and companies
│
▼ Stage 1 — CLEAN                    (cleaner.py)
│ Normalise column names, strip whitespace, deduplicate, validate formats
│
▼ Stage 2 — DOMAIN RESOLUTION        (domain_resolver.py — 8 parallel workers)
│ Find each company's email domain using an 8-step cascade:
│   contacts_master → domain_knowledge cache → Clearbit API
│   → MX DNS lookup → Apollo → Hunter → Google → skip
│
▼ Stage 3 — ENRICHMENT               (orchestrator.py — 10 parallel workers)
│ Three-layer lookup (cheapest first, to protect API credits):
│   Layer 1 — enrichment_cache  (30-day TTL, instant, FREE)
│   Layer 2 — contacts_master   (Salesforce export, instant, FREE)
│   Layer 3 — Apollo.io API     (costs credits — only if layers 1+2 miss)
│
▼ Stage 4 — VENDOR EMAIL VALIDATION  (zerobounce_client.py)
│ ZeroBounce validates all Apollo/Apify-sourced emails
│ Automatically skips emails already validated in contacts_master
│
▼ Stage 5 — EMAIL PREDICTION         (email_pattern_engine.py)
│ For leads still missing an email, predicts it using domain + name patterns
│ Common patterns: firstname.lastname@, f.lastname@, firstname@, etc.
│ Assigns a confidence score based on pattern frequency for that domain
│
▼ Stage 6 — PREDICTED EMAIL VALIDATION (zerobounce_client.py)
│ ZeroBounce validates the pattern-predicted emails
│ (Higher failure rate than Stage 4 — predictions are best-guess)
│
▼ Stage 7 — SCORING                  (scoring.py)
│ Mark each lead: ready_for_outreach = True / False
│ Pass criteria: valid email OR (catch-all email + LinkedIn URL present)
│
▼
Output: output/final_outreach_ready.csv
        output/audit_log.csv
        [original .xlsx file updated in-place with new columns]
```

### Checkpoint / Resume

Each stage saves a `.pkl` checkpoint. Runs can be interrupted and resumed safely:

```bash
# From the lead_enrichment_engine directory:
python -m src.pipeline "path/to/leads.xlsx" --restart   # fresh start
python -m src.pipeline "path/to/leads.xlsx" --resume    # continue from checkpoint
```

---

## Contacts Master — Salesforce Export

`contacts_master` is a **read-only table** populated from Salesforce CRM exports. The pipeline uses it as a **free first-check** before spending Apollo or ZeroBounce credits.

### Why it matters
Every time the pipeline needs a contact or email validation, it checks `contacts_master` first. A hit here costs nothing and is instant. Only on a miss does it call Apollo (credits) or ZeroBounce (credits).

### Key column rules

| Column | Notes |
|--------|-------|
| `zb_valid_email` | **Yes/No text flag** — NOT an email address. Filter: `WHERE UPPER(TRIM(zb_valid_email)) = 'YES'` |
| `validated_email` | ZeroBounce-confirmed email — takes priority over `email` |
| `email` | Raw email from Salesforce — fallback if `validated_email` is empty |
| **Correct email read** | `COALESCE(NULLIF(validated_email,''), NULLIF(email,''))` |
| `linkedin_url__c` | Primary LinkedIn URL |
| `linkedin_url_enriched` | Fallback LinkedIn URL |
| `new_company` | Current company — takes priority over `existing_company` |
| `hasoptedoutemail` | Do not email if `TRUE` |

### All column names are PostgreSQL-lowercased
Salesforce fields like `FirstName`, `LinkedIn_URL__c`, `HasOptedOutOfEmail` all become lowercase in PostgreSQL: `firstname`, `linkedin_url__c`, `hasoptedoutemail`.

---

## Database Schema

**Database:** `Inoapps-Data-DB` · **Host:** `10.0.0.149:5432` · **User:** `postgres`

| Table | Purpose | Key Rules |
|-------|---------|-----------|
| `companies` | Detected Oracle prospect companies | `name` is UNIQUE — use `ON CONFLICT DO UPDATE` |
| `signals` | Raw buying-intent evidence per company | Multiple signals per company allowed; has `confidence`, `oracle_products[]`, `phases[]` |
| `company_contacts` | Enriched contacts per company | `source` = `contacts_master`, `apollo`, `apollo.io` |
| `contacts_master` | **READ-ONLY** Salesforce CRM export | Never write to this table. Filter by `zb_valid_email = 'Yes'` |
| `scan_runs` | History of every scan execution | Links to `companies` and `signals` via `run_id` |
| `enrichment_cache` | Apollo/ZeroBounce result cache | Apollo TTL: 30 days · ZeroBounce TTL: 7 days |
| `domain_knowledge` | Company → email domain map | Persists across all runs; never wipe |
| `email_patterns` | Domain → email format frequency table | Built up over time from confirmed emails |
| `users` | Authentication users | Roles: `owner` > `admin` > `viewer` > `recruitment` |

---

## React Frontend Pages

| Page | Route | What it shows |
|------|-------|--------------|
| **Dashboard** | `/` | KPI cards: total signals, companies, contacts, recent scan activity |
| **Companies** | `/companies` | Browse and filter prospect companies; click to see all signals and contacts for that company |
| **Contacts** | `/contacts` | All enriched contacts; filter by source (Contacts Master vs Apollo) and validation status |
| **Engine Control** | `/engine` | Start/stop Oracle Intent Engine and Lead Enrichment Engine; view live log stream |
| **Reporting** | `/reporting` | Charts: signal sources, Oracle buying phases, contact coverage by source |
| **Review Queue** | `/review` | Approve or reject contacts before pushing to HubSpot |
| **HubSpot Sync** | `/hubspot` | Configure HubSpot API key, sync approved contacts to CRM |
| **Settings** | `/settings` | Manage API keys, create/manage users, configure scan parameters |

---

## Environment Setup

### Oracle Intent Engine — `oracle_intent_engine/.env`
```env
# ─── Database (must be on-site or VPN to reach 10.0.0.149) ───────────────────
DB_HOST=10.0.0.149
DB_PORT=5432
DB_NAME=Inoapps-Data-DB
DB_USER=postgres
DB_PASSWORD=your_password_here

# ─── Apollo.io ────────────────────────────────────────────────────────────────
# IMPORTANT: Apollo uses X-Api-Key header — NOT Authorization: Bearer
APOLLO_API_KEY=your_apollo_key_here

# ─── Optional signal sources ──────────────────────────────────────────────────
NEWSAPI_KEY=your_newsapi_key_here        # newsapi.org
BING_NEWS_KEY=your_bing_key_here         # Azure Cognitive Services

# ─── HubSpot CRM ──────────────────────────────────────────────────────────────
HUBSPOT_API_KEY=your_hubspot_private_app_key_here

# ─── Authentication ───────────────────────────────────────────────────────────
FLASK_SECRET_KEY=any_long_random_string_here
```

### Lead Enrichment Engine — `lead_enrichment_engine/.env`
```env
# ─── Database ─────────────────────────────────────────────────────────────────
DB_HOST=10.0.0.149
DB_PORT=5432
DB_NAME=Inoapps-Data-DB
DB_USER=postgres
DB_PASSWORD=your_password_here

# ─── ZeroBounce (email validation — each email costs 1 credit) ───────────────
ZEROBOUNCE_API_KEY=your_zerobounce_key_here

# ─── Apollo.io (same key as oracle intent engine) ────────────────────────────
APOLLO_API_KEY=your_apollo_key_here
```

> ⚠️ **Never commit `.env` files to git.** Both are listed in `.gitignore`.

---

## Running the Application

### Prerequisites
- Python 3.13+
- Node.js 18+
- Access to `10.0.0.149:5432` (on-site or VPN)

### Start the full platform

```bash
# 1. Activate the shared virtual environment
cd "C:/Users/sidhartha/OneDrive/Desktop/DATA TOOL"
venv\Scripts\activate

# 2. Build the frontend (first time or after UI changes)
cd frontend
npm install
npm run build
cd ..

# 3. Start the unified backend
#    This starts unified_app.py which launches both engine workers
#    and serves the React UI from frontend/dist/
python unified_app.py
```

Open **http://localhost:8000** in your browser.

### Development mode (with hot reload)

```bash
# Terminal 1 — Backend
python unified_app.py

# Terminal 2 — Frontend (hot reload)
cd frontend
npm run dev          # Vite dev server on http://localhost:5173
```

### Run engines manually (for testing)

```bash
# Oracle Intent Engine — trigger a scan directly
cd oracle_intent_engine
python -m src.pipeline

# Lead Enrichment Engine — enrich a specific file
cd lead_enrichment_engine
python -m src.pipeline "path/to/leads.xlsx" --restart   # fresh start
python -m src.pipeline "path/to/leads.xlsx" --resume    # continue from checkpoint
```

### Run tests

```bash
pytest tests/ -v
```

---

## Signal Sources & Confidence Scoring

### Confidence score scale (0.40 – 0.90)

| Score | Meaning | Example |
|-------|---------|---------|
| **0.90** | Explicit Oracle product name + company name found together | "Acme Corp — JD Edwards EnterpriseOne CNC Administrator" |
| **0.80** | Oracle product in job title, company is clear | "Oracle Cloud ERP Implementation Consultant at TechCo" |
| **0.75** | Strong Oracle indicator in job description text | Job body mentions "JD Edwards" or "Oracle Fusion" by name |
| **0.60** | Generic Oracle context — end-user vs consulting is unclear | "Oracle ERP Consultant" (could be staffing agency posting) |
| **0.50** | Weak signal — Oracle mentioned but context is vague | News article mentions Oracle in passing |
| **< 0.40** | Not stored — too weak to be useful | Vague "ERP" mention with no Oracle specifics |

> **Rule:** Never set confidence > 0.75 unless the Oracle product name can be confirmed by exact string match in the source text.

### Signal sources

| Signal Class | Source | Method |
|-------------|--------|--------|
| `IndeedSignal` | indeed.com | HTML scraping of job search results |
| `ZipRecruiterSignal` | ziprecruiter.com | HTML scraping |
| `AdzunaSignal` | api.adzuna.com | REST API |
| `TotalJobsSignal` | totaljobs.com | HTML scraping (UK) |
| `CWJobsSignal` | cwjobs.co.uk | HTML scraping (UK IT) |
| `OracleWebsiteSignal` | oracle.com/customers | JSON-LD + HTML parsing |
| `OracleCommunitySignal` | community.oracle.com | HTML scraping |
| `OracleEventSignal` | oracle.com/events | HTML scraping |
| `NewsSignal` | NewsAPI + Bing + Google RSS | API + RSS feed parsing |
| `SICasestudySignal` | SI partner websites | HTML scraping |
| `PartnerCasestudySignal` | Oracle partner sites | HTML scraping |
| `CompanyPagesSignal` | Company websites | HTML scraping |
| `HomeBuildersSignal` | Home builder directories | HTML scraping |

### Staffing agency filter
All signals pass through a staffing filter. If the company posting a job is a staffing or consulting firm (e.g. Randstad, Accenture, Infosys), it is **excluded** — these are not Oracle end-users and are not valid prospects for Inoapps.

---

## User Roles

| Role | Permissions |
|------|------------|
| `owner` | Full access including user management and all configuration |
| `admin` | Run scans, enrichment, HubSpot sync; manage data; cannot manage users |
| `viewer` | Read-only — view companies, signals, contacts, and reports |
| `recruitment` | Limited access — contacts and reporting pages only |

---

## Contributing / KT Notes

### Adding a new signal source
1. Create `oracle_intent_engine/src/signals/my_signal.py`
2. Inherit from `BaseSignal` (see `base_signal.py` for the interface)
3. Implement `fetch(query, location, max_pages) → list[dict]`
4. Add to `signals/__init__.py`
5. Register in `pipeline.py` → `SIGNAL_REGISTRY`
6. Reference implementation: `indeed_signal.py`

### Adding a new API endpoint
All routes live in `unified_app.py`. Always use `Depends(oracle_auth.require_analyst)` for authenticated routes. Follow the existing pattern:
```python
@app.get("/api/my-endpoint")
async def my_endpoint(current_user: dict = Depends(oracle_auth.require_analyst)):
    ...
```

### Database changes
Write an `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration. All DDL is in `oracle_intent_engine/src/database.py` → `_CREATE_STATEMENTS`. Never modify production tables without a migration script.

### Frontend pages
- All pages: `frontend/src/pages/` — functional components, TypeScript strict mode
- Shared components: `frontend/src/components/`
- Styling: **inline styles only** — no Tailwind, no CSS files
- Icons: Lucide React only
- Notifications: `toast()` from `../components/Toast` — never `alert()`

### Never do these
- Commit `.env` files
- Use `SELECT *` in production queries — list columns explicitly
- Call Apollo/ZeroBounce in a loop without confirming volume first
- Write to the `contacts_master` table (it's a read-only Salesforce export)
- Cross-import between `oracle_intent_engine` and `lead_enrichment_engine`

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.13, FastAPI, uvicorn |
| Oracle Intent Engine | Python 3.13, psycopg2, requests |
| Lead Enrichment Engine | Python 3.13, pandas, openpyxl, psycopg2 |
| Database | PostgreSQL 15 on local network |
| Frontend | React 18, TypeScript (strict), Vite |
| Auth | JWT (python-jose), bcrypt |
| Contact Discovery | Apollo.io (People Match + Bulk Match API) |
| Email Validation | ZeroBounce (batch + bulk file API) |
| CRM | HubSpot Private App API |
| LLM (optional) | Ollama (local) — llama3 for company name extraction |

---

<br/>

---

> **Built by Inoapps AI Team**
