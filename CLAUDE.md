# DATA TOOL — Intent Intelligence Platform

## What this actually does (GTM context first)

This is a full-stack **intent-driven outreach platform** built to solve one specific GTM problem: by the time a company appears on a standard vendor intent list, they've already shortlisted 3–4 consultants and issued an RFP. The window to influence is 60–90 days before that.

**The platform detects that window** by watching 15+ real-time sources for companies that are quietly hiring for a product implementation, scoping a rollout, or appearing in procurement activity — before they go public. It then enriches those companies with decision-maker contacts, validates emails, predicts formats where data is missing, scores every lead for priority, and routes contacts into sequences.

The platform is **taxonomy-driven, not hardcoded to one vendor**: the active product list, phase keywords, and scoring rules load at runtime from a `product_taxonomy` DB table (or a campaign's own `icp_profiles/*.yaml`). Oracle/JD Edwards is the default, most-mature taxonomy — it has the deepest signal coverage (dedicated Oracle-website/community/event scrapers) — but campaigns are not limited to it. `icp_profiles/quadsci.yaml` and `icp_profiles/endex.yaml` are live examples of fully independent, non-Oracle ICP definitions running in production today. See [.claude/rules/signals.md](.claude/rules/signals.md) for how the taxonomy layer works.

### End-to-end GTM pipeline

```
Signal Detection (15+ sources)
  → Buying Phase Classification (hiring / implementing / evaluating / upgrading / supporting)
    → Lead Scoring (signal_count × confidence × phase_weight)
      → Contact Enrichment (Apollo → ZoomInfo → Apify waterfall)
        → Email Validation (ZeroBounce, or pattern prediction for gaps)
          → HubSpot CRM Sync / Apollo Sequence Export / CSV for Clay
```

### Campaign Builder — AI-powered outreach in 4 steps

A separate mode for campaigns against a defined ICP (currently Weave's ICP: YC-backed AI/dev-tool startups):

```
Step 1 — Find ICP Companies   → YC OSS API, filtered by tags + batch recency + team size
Step 2 — Find Decision-Makers → Apollo people search, title-matched (CTO / VP Eng)
Step 3 — Generate Hooks       → Claude Haiku, PAS framework, 5 tension angles (Risk/Effort/Time/Cost/Identity)
Step 4 — Export               → CSV with subject + body + LinkedIn URL, ready for sequence upload
```

Hooks are grounded in real ICP research: LinearB (6.1M PR dataset), ICONIQ board research, Jellyfish 2025 AI tool adoption study, Charity Majors / Laura Tacho quotes. Not generic AI copy.

### Buying phase taxonomy (maps to sales stage awareness)

| Phase | What it means | Example signal |
|-------|---------------|----------------|
| `hiring` | Actively recruiting Oracle talent → early implementation prep | JDE CNC Admin job on Indeed |
| `implementing` | Live rollout underway | Press release: "go-live Q3" |
| `evaluating` | RFP/RFI stage | Procurement portal notice |
| `upgrading` | Cloud migration or version upgrade | "Oracle Fusion migration" LinkedIn post |
| `supporting` | Long-term run-state maintenance | "manage existing Oracle environment" JD |

### Integration surface (what it plugs into)

| Tool | How |
|------|-----|
| **HubSpot** | Bidirectional sync — contacts pushed with intent score + Oracle product tag |
| **Apollo sequences** | Export contacts directly into sequences via Apollo API |
| **Clay** | CSV export (signal-enriched, validated) as pre-qualified input for Clay waterfalls |
| **ZeroBounce** | Email validation before any send — `ready_for_outreach` flag set per contact |

### Scale
- **15+ signal sources**: Indeed, LinkedIn, Google Jobs, Adzuna, ZipRecruiter, SerpAPI, NewsAPI, Bing News, Oracle community/events/website, procurement portals, SEC filings, partner case studies
- **3-vendor enrichment waterfall**: Apollo (primary) → ZoomInfo → Apify (fallback)
- **280K contact CSV** as local enrichment fallback
- **Email prediction engine**: infers `{first}.{last}@domain.com` patterns from domain history when direct data is unavailable
- **Permanent lead database** (`master_leads`): accumulates contacts across all runs — never reset

---

## Running on macOS (this machine)

```bash
# One command, one process, one port — builds the frontend and serves it
# from the same FastAPI process on :8000. This is the mac equivalent of the
# old start.bat and is the preferred way to run the app: there's no separate
# dev server to fall out of sync with the backend.
./start.sh
# → http://localhost:8000
```

Dev mode (hot-reload frontend on its own port, if you're actively editing
frontend code) still works, but remember BOTH processes need to be running —
if the backend dies, the frontend will still answer and every API call will
fail with a cryptic `Unexpected end of JSON input` instead of a clear error:

```bash
# Terminal 1
.venv/bin/python -m uvicorn unified_app:app --host 0.0.0.0 --port 8000

# Terminal 2
cd "/Users/sid/Desktop/DATA TOOL/frontend"
npm run dev
# → http://localhost:5173
```

> The CLAUDE.md below was originally written for Windows (`venv\Scripts\activate`). On this Mac, the working venv is `.venv/bin/activate` — the `venv/` folder in this repo is a stale Windows-layout copy (`Scripts/`, not `bin/`) and won't run here.

## PostgreSQL quick check
```bash
.venv/bin/python -c "import psycopg2; c = psycopg2.connect('host=127.0.0.1 port=5432 dbname=oracle_intent user=postgres password=postgres'); print('DB OK'); c.close()"
```
This machine runs Postgres locally (`intent_engine/.env` has `DB_HOST=127.0.0.1`), not against the office DB at `10.0.0.149`. If you're pointed at the office DB instead, you need to be on the office network or VPN.

---

## Automatic Behavior (always active — no prompting needed)

### Agent auto-delegation
| Situation | What Claude does automatically |
|-----------|-------------------------------|
| Error / traceback / "not working" | Invokes **pipeline-debugger** agent immediately |
| "Add a new signal" / new scraper request | Invokes **signal-writer** agent |
| Code review / pre-merge check | Invokes **code-reviewer** agent |
| Security question / audit request | Invokes **security-auditor** agent |
| "Write tests" / "add coverage" | Invokes **test-writer** agent |
| "Refactor" / "clean up" | Invokes **refactorer** agent |
| "Document" / "add docstrings" | Invokes **doc-writer** agent |

### Rule auto-loading
| File being edited | Rule loaded automatically |
|-------------------|--------------------------|
| Any `*.py` in `intent_engine/src/signals/` | `rules/signals.md` + `rules/backend.md` |
| Any `*.py` in either engine | `rules/backend.md` |
| Any `*.ts` or `*.tsx` in `frontend/` | `rules/frontend.md` |
| `database.py`, `pg_*.py`, SQL anywhere | `rules/database.md` |

### PostToolUse hook (runs on every file save automatically)
After every Write or Edit, the hook at `.claude/hooks/post-edit-check.ps1` runs and checks:
- Python: syntax errors, bare `except:`, hardcoded secrets, cross-engine imports, signal class validity, SQL injection
- TypeScript: `console.log`, `any` types, missing auth headers, hardcoded secrets

If the hook finds issues, Claude fixes them immediately — task is not "done" until hook is clean.

---

## What this is
A full-stack, taxonomy-driven intent intelligence platform for B2B lead generation. It detects companies actively hiring, implementing, or buying products matched against a configurable product taxonomy, and enriches those companies with decision-maker contact data. The default taxonomy is Oracle products (JD Edwards, Oracle Cloud ERP, NetSuite, HCM, SCM, EPM, OCI, etc.) — the platform's original and most mature vertical — but campaigns can run against entirely different ICPs via `icp_profiles/*.yaml` (see `quadsci.yaml`, `endex.yaml` for live examples).

**Business purpose:** Find qualified prospects before competitors do, by detecting hiring signals, news, procurement activity, and vendor-community presence across 15+ data sources.

---

## Architecture

```
DATA TOOL/
├── intent_engine/       ← Flask app (port 5001) — signal detection engine
│   ├── app.py                  ← Main Flask app, ALL API routes
│   ├── src/
│   │   ├── database.py         ← All PostgreSQL queries (companies, signals, contacts, runs)
│   │   ├── pipeline.py         ← Orchestrates all signals in parallel threads
│   │   ├── signals/            ← 15+ signal scrapers (job boards, news, Oracle sites, etc.)
│   │   │   ├── base_signal.py  ← Base class every signal must inherit
│   │   │   ├── indeed_signal.py
│   │   │   ├── linkedin_signal.py
│   │   │   ├── news_signal.py
│   │   │   ├── adzuna_signal.py
│   │   │   └── ...13 more signals
│   │   ├── lead_scorer.py      ← Priority score = signal_count × confidence × phase_weight
│   │   ├── contact_finder.py   ← Hunter.io + Apollo contact discovery
│   │   ├── phase_classifier.py ← Detects Oracle adoption phase (hiring/implementing/evaluating)
│   │   ├── firmographics.py    ← Company size/industry enrichment
│   │   ├── exporter.py         ← CSV + Excel export
│   │   ├── staffing_filter.py  ← Removes staffing/consulting firms from results
│   │   ├── icp_hunter.py       ← Fetches YC-backed companies matching a defined ICP (yc-oss API)
│   │   ├── hook_generator.py   ← Claude Haiku: PAS-framework cold email hooks, 5 tension angles
│   │   ├── company_researcher.py ← Enriches ICP companies with context for hook grounding
│   │   └── config.py           ← ALL env vars and Oracle search queries
│   └── templates/index.html    ← Legacy Flask template (superseded by React)
│
├── lead_enrichment_engine/     ← FastAPI app — CSV lead enrichment pipeline
│   ├── src/
│   │   ├── pipeline.py         ← Multi-stage: validate → score → enrich → validate email
│   │   ├── orchestrator.py     ← Routes leads to Apollo/Apify/ZoomInfo based on logic
│   │   ├── database.py         ← PostgreSQL caching (reuses oracle_intent DB)
│   │   ├── pg_master.py        ← master_leads table: permanent cross-run accumulation
│   │   ├── pg_connector.py     ← PostgreSQL input/output for batch pipeline runs
│   │   ├── scoring.py          ← Lead quality scoring algorithm
│   │   ├── cleaner.py          ← Data normalization and deduplication
│   │   ├── email_pattern_engine.py ← Infers email patterns from domain history
│   │   ├── domain_resolver.py  ← Maps company names to domains via DNS/MX records
│   │   ├── zerobounce_client.py ← ZeroBounce email validation API client
│   │   ├── checkpoint.py       ← Parquet checkpoints for resumable pipeline runs
│   │   └── config.py           ← ALL env vars and file paths
│   ├── input/                  ← leads.csv, domain_lookup.csv, suppression_list.csv
│   └── output/                 ← final_outreach_ready.csv, audit_log.csv
│
├── frontend/                   ← React 18 + TypeScript + Vite (port 5173)
│   └── src/
│       ├── App.tsx             ← Router + JWT auth guard + layout shell
│       ├── pages/              ← 18 pages (see list below)
│       └── components/         ← Sidebar, Topbar, Toast, ConfirmDialog, CommandPalette
│
└── venv/                       ← Shared Python 3.13 virtualenv for both engines
```

---

## Frontend Pages

| Route | File | Purpose |
|-------|------|---------|
| `/dashboard` | Dashboard.tsx | KPIs + real-time scan log + engine start/stop |
| `/companies` | Companies.tsx | Companies table with phase/product filters |
| `/contacts` | Contacts.tsx | Enriched contacts with Apollo/master_leads badges |
| `/engine` | EngineControl.tsx | Configure scan sources, max pages, location |
| `/review` | ReviewQueue.tsx | Human review queue for flagged leads |
| `/intent` | IntentData.tsx | Raw intent signals browser |
| `/reporting` | Reporting.tsx | Charts and analytics |
| `/metrics` | Metrics.tsx | System-level pipeline metrics |
| `/technology-profiles` | TechnologyProfiles.tsx | Company tech stack intelligence |
| `/list-import` | ListImport.tsx | CSV import for bulk lead enrichment |
| `/events` | Events.tsx | Oracle events signal data |
| `/audit-logs` | AuditLogs.tsx | System audit trail |
| `/user-management` | UserManagement.tsx | Admin-only: manage users and roles |
| `/hubspot-sync` | HubSpotSync.tsx | HubSpot CRM integration |
| `/product-intelligence` | ProductIntelligence.tsx | Oracle product adoption analytics |
| `/decision-intelligence` | DecisionIntelligence.tsx | InRule glass-box lead scoring, contacts, outreach |
| `/prediction-engine` | PredictionEngine.tsx | Search a company, see its learned email format + contacts |
| `/profile` | Profile.tsx | User profile |
| `/settings` | Settings.tsx | App settings |
| `/campaign-builder` | CampaignBuilder.tsx | 4-step ICP → Contacts → AI Hooks → Export wizard |
| `/campaign-emails` | CampaignEmails.tsx | Signal → Angle → Hook → Email methodology + live campaign metrics |
| `/campaigns` | Campaigns.tsx | Signal-driven campaign management |
| `/people-search` | PeopleSearch.tsx | Apollo-powered people search with email status |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Vite, react-router-dom v6, Lucide React icons |
| Oracle Intent Backend | Python 3.13, Flask, Flask-CORS, port 5001 |
| Lead Enrichment Backend | Python 3.13, FastAPI + uvicorn, port 8000 |
| Primary Database | **PostgreSQL on 10.0.0.149:5432**, database: `oracle_intent`, user: `postgres` |
| Local cache | SQLite (intent_engine/oracle_intent.db, auto-created) |
| Email enrichment | Apollo.io (primary), Apify (fallback), ZeroBounce (validation), ZoomInfo (optional) |
| Intent signals | Indeed, LinkedIn, Google Jobs, Adzuna, ZipRecruiter, SerpAPI/NewsAPI/Bing News, Oracle community/events/website, procurement, SEC filings, partner case studies |
| LLM extraction | Anthropic Claude or Ollama/llama3.2 (local) via ScrapeGraphAI |
| Hook generation | **Claude Haiku** (Anthropic API) — PAS-framework cold email copy, ICP-grounded |
| Contact finding | Hunter.io, Apollo people search |
| ICP discovery | YC OSS public API — tag + batch + team size filters |

---

## How to Run

```powershell
# Terminal 1 — Oracle Intent Engine (Flask)
cd "C:\Users\sidhartha\OneDrive\Desktop\DATA TOOL"
venv\Scripts\activate
cd intent_engine
python app.py
# → http://localhost:5001  (legacy Flask UI)
# → APIs consumed by React frontend

# Terminal 2 — Frontend (Vite dev server)
cd "C:\Users\sidhartha\OneDrive\Desktop\DATA TOOL\frontend"
npm run dev
# → http://localhost:5173  (main UI)

# Terminal 3 — Lead Enrichment Engine (when running batch pipeline)
cd "C:\Users\sidhartha\OneDrive\Desktop\DATA TOOL\lead_enrichment_engine"
..\venv\Scripts\activate
python -m uvicorn main:app --reload --port 8000
```

### Pre-flight checks
```powershell
# Check PostgreSQL reachable
venv\Scripts\python.exe -c "import psycopg2; c = psycopg2.connect('host=10.0.0.149 port=5432 dbname=oracle_intent user=postgres'); print('DB OK'); c.close()"

# Check venv has Flask
venv\Scripts\pip show flask
```

---

## Environment Variables

### intent_engine/.env
| Variable | Required | Notes |
|----------|----------|-------|
| DB_HOST | ✅ | `10.0.0.149` |
| DB_PORT | ✅ | `5432` |
| DB_NAME | ✅ | `oracle_intent` |
| DB_USER | ✅ | `postgres` |
| DB_PASSWORD | ✅ | the postgres password |
| JWT_SECRET | ✅ | random string for JWT signing (auth.py) — falls back to a persisted random key at `intent_engine/.jwt_fallback_key` if unset, but set this explicitly in production |
| APOLLO_API_KEY | ✅ | from app.apollo.io → Settings → API |
| ZEROBOUNCE_API_KEY | ✅ | from app.zerobounce.net |
| HUNTER_API_KEY | ✅ | from hunter.io/api |
| ADZUNA_APP_ID | ✅ | from developer.adzuna.com |
| ADZUNA_APP_KEY | ✅ | from developer.adzuna.com |
| NEWSAPI_KEY | optional | News signal source |
| BING_NEWS_KEY | optional | Bing news search |
| SCRAPEGRAPH_MODEL | optional | `anthropic/claude-haiku-4-5-20251001` or `ollama/llama3.1` |
| SCRAPEGRAPH_API_KEY | optional | Anthropic API key if using Claude |
| CONTACTS_CSV_PATH | optional | Path to 280K contacts CSV |

### lead_enrichment_engine/.env
| Variable | Required | Notes |
|----------|----------|-------|
| APOLLO_API_KEY | ✅ | Same key as above |
| ZEROBOUNCE_API_KEY | ✅ | Same key as above |
| APIFY_TOKEN | ✅ | from console.apify.com |
| PG_HOST / PG_PORT / PG_DB / PG_USER / PG_PASSWORD | ✅ | Same PostgreSQL |

---

## Database Schema (key tables in oracle_intent DB)

### companies
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| name | VARCHAR UNIQUE | Normalized company name |
| domain | VARCHAR | website domain |
| location, industry, size | VARCHAR | firmographics |
| run_id | INTEGER | FK → scan_runs.id |

### signals
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| company_id | INTEGER FK | → companies.id |
| signal_type | VARCHAR | hiring / news / procurement / event / partner |
| signal_detail | TEXT | raw signal description |
| source_url | VARCHAR | |
| confidence | FLOAT | 0.0–1.0 |
| oracle_products | TEXT[] | detected product names |
| phases | TEXT[] | detected Oracle adoption phases |
| run_id | INTEGER | FK → scan_runs.id |

### contacts
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| company_id | INTEGER FK | → companies.id |
| first_name, last_name | VARCHAR | |
| email | VARCHAR | |
| title | VARCHAR | |
| linkedin_url | VARCHAR | |
| source | VARCHAR | apollo / master_leads / hunter |

### master_leads (PERMANENT — never delete)
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| first_name, last_name | VARCHAR | |
| email | VARCHAR UNIQUE | |
| title | VARCHAR | |
| company, domain | VARCHAR | |
| phone, linkedin_url | VARCHAR | |
| source | VARCHAR | apollo / master_leads / manual |
| ready_for_outreach | BOOLEAN | ZeroBounce validated |
| target_product | VARCHAR | Oracle product for outreach targeting |

### users (auth)
| Column | Notes |
|--------|-------|
| id, email, password_hash | JWT auth |
| role | owner / admin / viewer / recruitment |

---

## Rules Claude MUST Follow

1. **NEVER commit .env files** — they contain real API keys for paid services (Apollo, ZeroBounce, Apify cost real money per credit)
2. **NEVER delete from master_leads** — this is the permanent lead database, irreplaceable data
3. **NEVER drop or truncate any table** — always ask the user before any destructive DB operation
4. **Venv is shared** at `C:\Users\sidhartha\OneDrive\Desktop\DATA TOOL\venv` — both engines use it
5. **Cross-engine imports are FORBIDDEN** — intent_engine and lead_enrichment_engine are independent services
6. **All new signals must inherit BaseSignal** — no standalone scrapers
7. **All config via src/config.py** — never hardcode API keys, hostnames, or paths in logic files
8. **Frontend auth header** — every fetch call needs `Authorization: Bearer <token>` (use authH() pattern)
9. **PostgreSQL is on local network** — if you get a connection error, verify 10.0.0.149 is reachable before blaming code
10. **Apollo API auth** — uses `X-Api-Key` header, NOT `Authorization: Bearer`. This is a common mistake.
11. **Rate limits are real** — ZeroBounce charges per email, Apollo charges per reveal. Never validate/reveal in a loop without confirmation
12. **The staffing_filter.py must always run** — never skip it; it prevents staffing agencies from polluting results

---

## Common Tasks

| Task | How |
|------|-----|
| Add new Oracle intent signal | `/add-signal <name>` command or signal-writer agent |
| Add new frontend page | `/add-page <PageName>` command |
| Debug pipeline error | pipeline-debugger agent + the full error message |
| Review code before merge | code-reviewer agent |
| Security audit | security-auditor agent |
| Run everything | `/run-engine` command |

---

## API Routes Reference (intent_engine/app.py)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/` | Dashboard HTML |
| POST | `/scan/start` | Start a signal scan |
| GET | `/scan/status` | Get current scan progress |
| POST | `/scan/stop` | Stop a running scan |
| GET | `/scan/log` | Get scan log entries |
| GET | `/api/companies` | List companies (filter by phase/product) |
| GET | `/api/company/<id>/signals` | Signals for a company |
| GET | `/api/company/<id>/contacts` | Contacts for a company |
| POST | `/api/company/<id>/contacts/enrich` | Trigger contact enrichment |
| POST | `/admin/purge-invalid` | Remove invalid company names |
| POST | `/admin/reset-all` | Clear all data (use with extreme caution) |
| GET | `/export/csv` | Export current run as CSV |
| GET | `/export/excel` | Export current run as Excel |
| GET | `/export/excel/all` | Export ALL runs as Excel |
| GET | `/export/csv/all` | Export ALL runs as CSV |
