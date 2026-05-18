# Oracle Intelligence Platform

A full-stack B2B intent intelligence tool that detects Oracle/JDE buying signals, enriches leads via Apollo.io, validates emails via ZeroBounce, and pushes qualified contacts to HubSpot CRM.

---

## Architecture

```
DATA TOOL/
├── unified_app.py              # Single FastAPI server (port 8000)
├── scan_worker.py              # Oracle intent scan subprocess
├── enrichment_worker.py        # Apollo enrichment subprocess
├── requirements.txt            # Python dependencies
│
├── oracle_intent_engine/       # Signal detection & company intelligence
│   ├── src/
│   │   ├── database.py         # PostgreSQL pool, DDL, all DB operations
│   │   ├── pipeline.py         # Scan orchestration
│   │   ├── lead_scorer.py      # 0-100 priority scoring
│   │   ├── phase_classifier.py # Implementing / Evaluating / Researching
│   │   ├── apollo_enrichment.py# Two-pass Apollo contact enrichment
│   │   ├── exporter.py         # CSV / Excel export
│   │   └── signals/            # 15+ signal scrapers (LinkedIn, Indeed, Oracle.com…)
│   └── .env.example
│
├── lead_enrichment_engine/     # 276k master contacts store
│   ├── src/
│   │   ├── pg_master.py        # PostgreSQL master leads store
│   │   ├── pg_connector.py     # Pipeline I/O connector
│   │   ├── domain_resolver.py  # Email domain resolution
│   │   ├── email_pattern_engine.py  # Pattern-based email prediction
│   │   └── scoring.py          # Lead readiness scoring
│   └── .env.example
│
└── frontend/                   # React + TypeScript + Vite UI
    └── src/pages/
        ├── Dashboard.tsx        # KPI overview
        ├── Companies.tsx        # 566 tracked companies
        ├── Contacts.tsx         # Enriched contacts table
        ├── ReviewQueue.tsx      # Approve → push to HubSpot
        ├── IntentData.tsx       # Raw signal feed
        ├── EngineControl.tsx    # Start/stop engines
        ├── Reporting.tsx        # Analytics & charts
        └── Settings.tsx         # API key management
```

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+ (database: `oracle_intent`)

---

## Setup

### 1. Clone & configure environment

```bash
git clone <repo-url>
cd oracle-intelligence-platform

# Backend credentials
cp oracle_intent_engine/.env.example oracle_intent_engine/.env
cp lead_enrichment_engine/.env.example lead_enrichment_engine/.env
# Edit both .env files with your real values
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install & build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

### 4. Start the server

```bash
# Production (serves built React from /frontend/dist)
python -m uvicorn unified_app:app --host 0.0.0.0 --port 8000

# Development (hot-reload backend + Vite dev server)
python -m uvicorn unified_app:app --reload --port 8000   # terminal 1
cd frontend && npm run dev                                 # terminal 2
```

Open **http://localhost:8000** (prod) or **http://localhost:5173** (dev).

---

## API Keys Required

| Service | Purpose | Get it at |
|---|---|---|
| **Apollo.io** | Contact discovery | app.apollo.io → Settings → API |
| **ZeroBounce** | Email validation | app.zerobounce.net → API |
| **HubSpot** | CRM push | app.hubspot.com → Settings → Private Apps |
| **Apify** *(optional)* | LinkedIn scraping | console.apify.com → Integrations |

Keys can also be set live via **Settings & API** page — tested and saved without a server restart.

---

## How It Works

### 1. Oracle Intent Scan
The scan engine runs 15+ scrapers across LinkedIn Jobs, Indeed, Oracle.com, Oracle Community, news sources, and procurement notices. Each signal is classified by:
- **Phase**: Implementing / Evaluating / Researching / Hiring / Post-live
- **Product**: Oracle ERP, JD Edwards, Oracle HCM, Oracle SCM…
- **Confidence**: 0.0 – 1.0 based on source quality

### 2. Lead Enrichment
For each detected company:
1. **Master leads check** — 276k pre-validated Salesforce contacts checked first (free)
2. **Apollo Pass 1** — targeted search with Oracle/JDE title filter
3. **Apollo Pass 2** — broad search with local relevance keyword filter
4. **ZeroBounce** — batch email validation (valid / invalid / catch-all)

### 3. Review & Push
Enriched contacts appear in the **Review Queue**. Approve one-by-one or bulk push all to HubSpot CRM.

---

## Database Schema

Single PostgreSQL database (`oracle_intent`):

| Table | Purpose |
|---|---|
| `companies` | Detected Oracle prospect companies |
| `oracle_signals` | Individual intent signals per company |
| `company_contacts` | Apollo-enriched contacts per company |
| `scan_runs` | Audit log of each scan run |
| `master_leads` | 276k pre-validated contact master store |
| `domain_knowledge` | Resolved email domains per company |
| `email_patterns` | Discovered email format patterns per domain |

---

## Production Checklist

- [ ] Change `FLASK_SECRET_KEY` to a random 32-byte hex string
- [ ] Set `CORS` `allow_origins` to your specific domain (not `"*"`)
- [ ] Add authentication middleware (the API is currently open)
- [ ] Run behind a reverse proxy (nginx/Caddy) with TLS
- [ ] Set `uvicorn --workers 2` for multi-core throughput
- [ ] Set up PostgreSQL connection pooling (PgBouncer) for high concurrency
- [ ] Configure log rotation for scan/enrichment logs

---

## License

Proprietary — Inoapps. All rights reserved.
