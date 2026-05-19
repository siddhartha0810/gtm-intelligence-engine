# Inoapps Intelligence Hub — Technical Document
**Version:** 2.0 (as-built)
**Date:** May 2026
**Stack:** Python 3.11 · FastAPI · PostgreSQL · React 18 · TypeScript · Vite

---

## 1. OVERVIEW

The Inoapps Intelligence Hub is an internal sales intelligence platform that discovers, enriches, qualifies, and synchronises company and contact data into HubSpot CRM. It replaces ad-hoc spreadsheet workflows with a structured pipeline covering web scraping, data enrichment, human review, and automated HubSpot push — governed by RBAC and a full audit trail.

**Core principles:**
1. HubSpot as the system of record — all data flows into HubSpot CRM
2. Human-in-the-loop quality control — no record reaches HubSpot without DQE + human approval
3. Single server — one FastAPI process serves the React SPA and all API endpoints

---

## 2. ARCHITECTURE

```
┌──────────────────────────────────────────────────────────────────┐
│                    unified_app.py (FastAPI)                      │
│                    http://localhost:8000                          │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────────┐ │
│  │  React SPA  │  │  REST API   │  │  Background Subprocesses  │ │
│  │  (Vite      │  │  (FastAPI   │  │                          │ │
│  │  build →    │  │   routes)   │  │  Oracle Intent Engine    │ │
│  │  /dist)     │  │             │  │  (oracle_intent_engine/) │ │
│  └─────────────┘  └─────────────┘  │                          │ │
│                                    │  Lead Enrichment Engine   │ │
│                                    │  (lead_enrichment_engine/)│ │
│                                    └──────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │  PostgreSQL          │
                   │  10.0.0.149:5432     │
                   │  db: oracle_intent   │
                   └──────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
            ┌───────┴──────┐   ┌────────┴────────┐
            │ HubSpot CRM  │   │ Apollo.io API   │
            │ (push/pull)  │   │ ZeroBounce API  │
            └──────────────┘   │ Apify API       │
                               └─────────────────┘
```

---

## 3. DATABASE SCHEMA

**Host:** 10.0.0.149:5432  |  **Database:** oracle_intent  |  **User:** postgres

### 3.1 Core Tables

#### `companies`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `name` | TEXT UNIQUE | Company name |
| `domain` | TEXT | Website domain |
| `website` | TEXT | Full website URL |
| `industry` | TEXT | Industry classification |
| `size` | TEXT | Employee size band |
| `location` | TEXT | HQ location |
| `about_us` | TEXT | Company description |
| `number_of_employees` | INTEGER | |
| `billing_street/city/state/postal_code/country` | TEXT | Billing address |
| `duns_number` | TEXT | D&B DUNS identifier |
| `holding_type` | TEXT | Public / Private / etc |
| `number_of_locations` | INTEGER | |
| `oracle_cloud_solutions` | TEXT[] | Detected cloud products |
| `oracle_on_premise_solutions` | TEXT[] | Detected on-prem products |
| `oracle_relationship_type` | TEXT | partner / customer / prospect |
| `oracle_support_end_date` | DATE | |
| `oracle_version` | TEXT | |
| `number_of_oracle_users` | INTEGER | |
| `detected_products` | TEXT[] | All products (cloud + onprem) |
| `product_confidence_scores` | JSONB | `{product: score}` |
| `technology_profile_id` | BIGINT FK | → technology_profiles |
| `inoapps_services_summary` | TEXT | |
| `inoapps_account_manager` | TEXT | |
| `inoapps_account_tier` | TEXT | |
| `inoapps_relationship_type` | TEXT | |
| `status` | TEXT | staged/pending_review/approved/pushed_to_hubspot/rejected |
| `hubspot_id` | TEXT | HubSpot CRM object ID |
| `hubspot_synced_at` | TIMESTAMPTZ | |
| `unique_key` | TEXT | 64-char URL-safe dedup key |
| `source` | TEXT | oracle_scan / hubspot_pull / csv / manual |
| `first_scan_run_id` | BIGINT FK | |
| `first_seen` / `last_updated` | TIMESTAMPTZ | |

#### `oracle_signals`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `company_id` | BIGINT FK | → companies |
| `company_name` | TEXT | Denormalised for speed |
| `oracle_product` | TEXT | e.g. "Oracle Cloud ERP" |
| `phase` | TEXT | hiring/budgeting/implementing/post_live |
| `signal_type` | TEXT | job_posting/news/event |
| `source` | TEXT | linkedin/indeed/google_jobs/news |
| `url` | TEXT | Source URL |
| `job_title` | TEXT | If signal is a job posting |
| `evidence` | TEXT | Raw text snippet |
| `confidence` | NUMERIC(4,3) | 0.0 → 1.0 |
| `scan_run_id` | BIGINT FK | |
| `detected_at` | TIMESTAMPTZ | |

#### `company_contacts`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `company_id` | BIGINT FK | → companies |
| `salutation` | TEXT | |
| `first_name` | TEXT | |
| `last_name` | TEXT | |
| `suffix` | TEXT | |
| `full_name` | TEXT | |
| `title` | TEXT | Job title |
| `job_function` | TEXT | |
| `level` | TEXT | C-Suite / VP / Director / Manager |
| `email` | TEXT | |
| `email_validation_status` | TEXT | valid/invalid/catch-all/do_not_mail |
| `email_validation_sub_status` | TEXT | |
| `email_source` | TEXT | apollo/predicted/manual |
| `email_prediction_pattern` | TEXT | e.g. first.last |
| `phone` | TEXT | |
| `mobile_phone` | TEXT | |
| `linkedin_url` | TEXT | |
| `city/state/country` | TEXT | |
| `do_not_call` | BOOLEAN | |
| `do_not_email` | BOOLEAN | |
| `creation_source` | TEXT | |
| `person_has_moved` | BOOLEAN | |
| `oracle_alignment` | TEXT | (manufacturer contacts) |
| `oracle_department` | TEXT | |
| `oracle_team` | TEXT | |
| `confidence` | NUMERIC(4,3) | |
| `is_target` | BOOLEAN | |
| `seniority` | TEXT | |
| `source` | TEXT | apollo/hubspot_pull/manual |
| `status` | TEXT | staged/approved/pushed_to_hubspot/rejected |
| `hubspot_id` | TEXT | |
| `hubspot_synced_at` | TIMESTAMPTZ | |
| `unique_key` | TEXT | 64-char dedup key |

#### `hubspot_config`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `api_key` | TEXT | HubSpot private app token |
| `portal_id` | TEXT | HubSpot portal ID |
| `sync_status` | TEXT | idle/running/error/success |
| `last_sync_at` | TIMESTAMPTZ | |
| `companies_synced` | INT | Count from last push |
| `contacts_synced` | INT | |

#### `technology_profiles`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `name` | TEXT | e.g. "Oracle ERP Stack" |
| `description` | TEXT | |
| `keywords` | TEXT[] | Search keywords |
| `target_websites` | TEXT[] | Sites to scrape |
| `is_active` | BOOLEAN | |

#### `product_taxonomy`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `technology_profile_id` | BIGINT FK | |
| `canonical_name` | TEXT | e.g. "Oracle Cloud ERP" |
| `aliases` | TEXT[] | Alternative names |
| `category` | TEXT | cloud/on_premise |
| `confidence_weight` | NUMERIC | |

#### `scan_runs`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `search_queries` | TEXT | Queries used |
| `started_at` | TIMESTAMPTZ | |
| `completed_at` | TIMESTAMPTZ | |
| `status` | TEXT | running/completed/failed |
| `total_signals` | INT | |
| `total_companies` | INT | |
| `technology_profile_id` | BIGINT FK | |

#### `users`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `email` | TEXT UNIQUE | |
| `name` | TEXT | |
| `password_hash` | TEXT | bcrypt |
| `role` | TEXT | viewer/analyst/recruitment/admin/owner |
| `is_active` | BOOLEAN | |
| `last_login` | TIMESTAMPTZ | |

#### `audit_logs`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `user_id` | INT | |
| `user_email` | TEXT | |
| `action` | TEXT | e.g. push_to_hubspot, enrich, login |
| `entity_type` | TEXT | company/contact/user |
| `entity_id` | TEXT | |
| `detail` | JSONB | |
| `created_at` | TIMESTAMPTZ | |

#### `events`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `name` | TEXT | Event name |
| `event_type` | TEXT | conference/webinar/roundtable/other |
| `event_date` | DATE | |
| `location` | TEXT | |
| `description` | TEXT | |
| `technology_profile_id` | BIGINT FK | |

#### `event_attendees`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `event_id` | BIGINT FK | |
| `contact_id` | BIGINT FK | |
| `role` | TEXT | speaker/attendee/sponsor |

#### `manufacturer_contacts`
| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `first_name` / `last_name` | TEXT | |
| `email` / `phone` | TEXT | |
| `title` | TEXT | |
| `oracle_alignment` | TEXT | |
| `oracle_department` | TEXT | |
| `oracle_team` | TEXT | |
| `technology_profile_id` | BIGINT FK | |

#### `enrichment_cache` (in oracle_intent DB)
| Column | Type | Description |
|---|---|---|
| `lead_id` | TEXT PK | |
| `email` | TEXT | |
| `email_source` | TEXT | |
| `email_validation_status` | TEXT | |
| `linkedin_url` | TEXT | |
| `job_title` | TEXT | |
| `cached_at` | TIMESTAMPTZ | |
| `expires_at` | TIMESTAMPTZ | Apollo: 30d TTL, ZB: 7d TTL |

#### `domain_knowledge`
| Column | Type | Description |
|---|---|---|
| `company_normalized` | TEXT PK | |
| `domain` | TEXT | |
| `confidence` | TEXT | high/medium/low |
| `mx_validated` | BOOLEAN | |

---

## 4. API REFERENCE

All endpoints require `Authorization: Bearer <jwt>` except `/api/auth/login` and `/api/auth/register`.

### Auth Roles
| Role | Level | Access |
|---|---|---|
| viewer | 0 | Read-only: companies, contacts, signals, reports |
| recruitment | 1 | Recruitment module only |
| analyst | 2 | All data, scans, enrichment, exports |
| admin | 3 | + user management, purge, reset |
| owner | 4 | Full access, cannot be demoted |

### 4.1 Authentication
| Method | Endpoint | Role | Description |
|---|---|---|---|
| POST | `/api/auth/register` | public (first user = owner) | Create account |
| POST | `/api/auth/login` | public | Returns JWT token |
| GET | `/api/auth/me` | user | Current user info |
| POST | `/api/auth/change-password` | user | Change own password |

### 4.2 Companies
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/companies` | user | List with signals, ?phase=, ?product=, ?show_all= |
| GET | `/api/company/{id}/signals` | user | Signals for one company |
| GET | `/api/company/{id}/contacts` | user | Contacts (with master_leads fallback) |
| POST | `/api/company/{id}/contacts/enrich` | analyst | Trigger single-company enrichment |
| PATCH | `/api/companies/{id}/status` | analyst | Update status |
| POST | `/api/companies/{id}/push-hubspot` | analyst | Push one company to HubSpot |
| DELETE | `/api/companies/{id}` | analyst | Remove company |
| POST | `/admin/purge-invalid` | admin | Remove non-Oracle companies |
| POST | `/admin/reset-all` | admin | Wipe all data |

### 4.3 Contacts
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/contacts` | user | All contacts, ?company=, ?limit= |
| POST | `/api/contacts/push-hubspot` | analyst | Push one contact to HubSpot |

### 4.4 Oracle Intent Engine (Scan)
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/oracle/config` | user | DB connection status |
| POST | `/scan/start` | analyst | Start scraping run |
| POST | `/scan/stop` | analyst | Stop running scan |
| GET | `/scan/status` | user | Current scan progress |
| GET | `/scan/log` | user | Last 200 log lines |
| GET | `/api/stats` | user | Company/signal counts by phase/product |
| GET | `/api/signals` | user | Raw intent signals |

### 4.5 Lead Enrichment Engine
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/enrich/preflight` | analyst | Preview what will be enriched |
| POST | `/api/enrich/start` | analyst | Start enrichment |
| POST | `/api/enrich/stop` | analyst | Stop enrichment |
| GET | `/api/enrich/status` | user | Current enrichment progress |
| GET | `/api/enrich/log` | user | Enrichment log lines |
| GET | `/api/enrich/stats` | user | Enrichment summary stats |

### 4.6 HubSpot
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/hubspot/config` | user | Get saved config |
| POST | `/api/hubspot/config` | admin | Save API key + portal ID |
| POST | `/api/hubspot/test` | admin | Test HubSpot connection |
| POST | `/api/hubspot/sync-pull` | analyst | Pull companies + contacts from HubSpot |
| POST | `/api/hubspot/bulk-push/companies` | analyst | Push all approved companies |
| POST | `/api/hubspot/bulk-push/contacts` | analyst | Push all approved contacts |

### 4.7 Product Intelligence
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/product-intelligence` | user | Company product classifications |
| POST | `/api/product-intelligence/refresh` | analyst | Re-run aggregation from signals |

### 4.8 Analytics
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/dashboard` | user | KPI cards + scan status |
| GET | `/api/reporting` | user | Full pipeline analytics |
| GET | `/export/csv` | analyst | CSV export (current scan) |
| GET | `/export/excel` | analyst | Excel export (current scan) |
| GET | `/export/csv/all` | analyst | CSV export (all scans) |
| GET | `/export/excel/all` | analyst | Excel export (all scans) |

### 4.9 Technology Profiles
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/technology-profiles` | user | List all profiles |
| POST | `/api/technology-profiles` | analyst | Create profile |
| PATCH | `/api/technology-profiles/{id}` | analyst | Update profile |
| DELETE | `/api/technology-profiles/{id}` | analyst | Delete profile |
| GET | `/api/technology-profiles/{id}/taxonomy` | user | Get taxonomy items |
| POST | `/api/technology-profiles/{id}/taxonomy` | analyst | Add taxonomy item |

### 4.10 Events
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/events` | user | List events |
| POST | `/api/events` | analyst | Create event |
| PATCH | `/api/events/{id}` | analyst | Update event |
| DELETE | `/api/events/{id}` | analyst | Delete event |
| GET | `/api/events/{id}/attendees` | user | List attendees |
| POST | `/api/events/{id}/attendees` | analyst | Add attendee |
| DELETE | `/api/events/{id}/attendees/{contact_id}` | analyst | Remove attendee |

### 4.11 Manufacturer Intel
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/manufacturer-contacts` | user | List manufacturer contacts |
| POST | `/api/manufacturer-contacts` | analyst | Create contact |
| PATCH | `/api/manufacturer-contacts/{id}` | analyst | Update |
| DELETE | `/api/manufacturer-contacts/{id}` | analyst | Delete |
| POST | `/api/manufacturer-contacts/{id}/link/{company_id}` | analyst | Link to company |

### 4.12 List Import
| Method | Endpoint | Role | Description |
|---|---|---|---|
| POST | `/api/import/parse-headers` | analyst | Preview CSV/Excel headers |
| GET | `/api/import/fields/{entity_type}` | analyst | Available HubSpot fields |
| POST | `/api/import/upload` | analyst | Run import with field mappings |
| GET | `/api/import/batches` | analyst | Import history |
| GET/POST | `/api/import/templates` | analyst | Saved field mapping templates |

### 4.13 Data Quality Engine
| Method | Endpoint | Role | Description |
|---|---|---|---|
| POST | `/api/dqe/check/company` | analyst | Run DQE on one company |
| POST | `/api/dqe/check/contact` | analyst | Run DQE on one contact |
| POST | `/api/dqe/promote-staged` | analyst | Bulk promote staged→approved |

### 4.14 User Management
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/users` | admin | List all users |
| PATCH | `/api/users/{id}` | admin | Update role/status |
| DELETE | `/api/users/{id}` | admin | Deactivate user |

### 4.15 Audit Logs
| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/audit-logs` | admin | Paginated audit trail |

---

## 5. HUBSPOT FIELD MAPPING

### 5.1 Company Fields (27 total, 25 pushed)

| DB Column | HubSpot Property | Group | Notes |
|---|---|---|---|
| `name` | `name` | Standard | |
| `website` | `website` | Standard | |
| `domain` | `domain` | Standard | |
| `phone` | `phone` | Standard | |
| `industry` | `industry` | Standard | |
| `number_of_employees` | `numberofemployees` | Standard | |
| `about_us` | `about_us` | Standard | |
| `billing_street` | `address` | Billing | |
| `billing_city` | `city` | Billing | |
| `billing_state` | `state` | Billing | |
| `billing_postal_code` | `zip` | Billing | |
| `billing_country` | `country` | Billing | |
| `duns_number` | `duns_number` | Custom | |
| `holding_type` | `holding_type` | Custom | |
| `number_of_locations` | `number_of_locations` | Custom | |
| `oracle_cloud_solutions` | `oracle_cloud_solutions` | Oracle | array → semicolon-joined |
| `oracle_on_premise_solutions` | `oracle_on_premise_solutions` | Oracle | |
| `oracle_relationship_type` | `oracle_relationship_type` | Oracle | |
| `oracle_support_end_date` | `oracle_support_end_date` | Oracle | |
| `oracle_version` | `oracle_version` | Oracle | |
| `number_of_oracle_users` | `number_of_oracle_users` | Oracle | |
| `_technology_profile_name` | `technology_profile` | Oracle | resolved from FK at push time |
| `inoapps_services_summary` | `inoapps_services_summary` | Intel | |
| `inoapps_account_manager` | `inoapps_account_manager` | Inoapps | |
| `inoapps_account_tier` | `inoapps_account_tier` | Inoapps | |
| `inoapps_relationship_type` | `inoapps_relationship_type` | Inoapps | |
| *(calculated)* | `oracleSolutionsSummary` | Oracle | display-only, not pushed |
| *(system)* | `ultimateParentAccountId` | Custom | display-only, not pushed |

**Push method:** Domain-based upsert — search HubSpot by domain → PATCH if found, POST if new

### 5.2 Contact Fields (22 total)

| DB Column | HubSpot Property | Group |
|---|---|---|
| `salutation` | `salutation` | Core Identity |
| `first_name` | `firstname` | Core Identity |
| `last_name` | `lastname` | Core Identity |
| `suffix` | `suffix` | Core Identity |
| `email` | `email` | Core Identity |
| `phone` | `phone` | Core Identity |
| `mobile_phone` | `mobilephone` | Core Identity |
| `title` | `jobtitle` | Core Identity |
| `job_function` | `job_function` | Core Identity |
| `level` | `level` | Core Identity |
| `linkedin_url` | `linkedinbio` | Core Identity |
| `city` | `city` | Location |
| `state` | `state` | Location |
| `country` | `country` | Location |
| `do_not_call` | `hs_legal_basis` | Consent |
| `do_not_email` | `hs_email_optout` | Consent |
| `creation_source` | `lead_source` | Data Mgmt |
| `person_has_moved` | `person_has_moved` | Data Mgmt |
| `oracle_alignment` | `oracle_alignment` | Oracle |
| `oracle_department` | `oracle_department` | Oracle |
| `oracle_team` | `oracle_team` | Oracle |

**Push method:** Email-based upsert — search HubSpot by email → PATCH if found, POST if new

---

## 6. AUTHENTICATION & SECURITY

- **JWT tokens** — HS256, 12-hour expiry, secret from `JWT_SECRET` env var
- **bcrypt** — password hashing (work factor 12)
- **RBAC** — enforced via FastAPI `Depends()` on every protected route
- **CORS** — restricted to `localhost:8000` and `localhost:5173` only
- **No hardcoded secrets** — all credentials from `.env` or `hubspot_config` table
- **Audit trail** — every write action logged to `audit_logs` with user, action, entity
- **Account enumeration protection** — registration failure returns generic message

---

## 7. ENVIRONMENT VARIABLES

File: `oracle_intent_engine/.env`

| Variable | Description |
|---|---|
| `ORACLE_PG_DSN` | Full PostgreSQL DSN (overrides DB_* vars) |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | Individual DB config |
| `JWT_SECRET` | 32+ char random string for JWT signing |
| `APOLLO_API_KEY` | Apollo.io API key for contact lookup |
| `ZEROBOUNCE_API_KEY` | ZeroBounce API key for email validation |
| `APIFY_TOKEN` | Apify token for LinkedIn/web scraping |
| `APIFY_LINKEDIN_ACTOR_ID` | Apify actor for LinkedIn |
| `APIFY_EMAIL_ACTOR_ID` | Apify actor for email lookup |
| `HUBSPOT_API_KEY` | Fallback if not set via UI |
| `FLASK_PORT` | Port override (default: 8000) |

---

## 8. FRONTEND PAGES

| Route | Page | Role | Description |
|---|---|---|---|
| `/` | Dashboard | user | KPIs, scan control, live log |
| `/companies` | Companies | user | Company list, slide-over panel |
| `/contacts` | Contacts | user | All contacts across companies |
| `/product-intel` | Product Intel | user | Oracle cloud/on-prem per company |
| `/intent-data` | Intent Data | user | Raw oracle_signals |
| `/events` | Events | user | Oracle events + attendees |
| `/manufacturer-intel` | Manufacturer Intel | user | Oracle partner contacts |
| `/list-import` | List Import | analyst | CSV/Excel import with field mapping |
| `/reporting` | Reporting | user | Pipeline analytics charts |
| `/review-queue` | Review Queue | user | Human approval gate |
| `/hubspot` | HubSpot Sync | user | Push/pull + connection config |
| `/engine-control` | Engine Control | analyst | Scan + enrichment controls |
| `/technology-profiles` | Technology Profiles | analyst | Scan keyword sets |
| `/users` | User Management | admin | Invite + manage users |
| `/audit-logs` | Audit Logs | admin | Full audit trail |
| `/profile` | Profile | user | Change password |
| `/settings` | Settings | admin | Engine configs |

---

## 9. KEY PROCESSES

### 9.1 Oracle Intent Engine
- **Location:** `oracle_intent_engine/`
- **Trigger:** `POST /scan/start` → spawns subprocess
- **Sources:** LinkedIn Jobs, Indeed, Google Jobs, Oracle News
- **Output:** `oracle_signals` + `companies` rows
- **Post-scan:** `aggregate_product_intel()` auto-runs to classify cloud vs on-prem

### 9.2 Product Intel Aggregation
- **Function:** `oracle_db.aggregate_product_intel()`
- **Logic:**
  - Groups `oracle_signals` by `company_id + oracle_product`
  - Classifies: cloud products (Oracle Cloud ERP, HCM, SCM, EPM, CX, NetSuite, OCI, Integration) vs on-prem (JD Edwards, Oracle Database, APEX)
  - Updates `companies.oracle_cloud_solutions`, `oracle_on_premise_solutions`, `detected_products`, `product_confidence_scores`
- **Triggers:** On scan completion + manual `POST /api/product-intelligence/refresh`

### 9.3 Lead Enrichment Engine
- **Location:** `lead_enrichment_engine/`
- **Trigger:** `POST /api/enrich/start`
- **Pipeline stages:**
  1. `master_leads` cache check (local DB)
  2. `enrichment_cache` check (30-day Apollo TTL)
  3. Apollo API people search by domain + role filters
  4. Email pattern prediction (first.last, f.last, etc.)
  5. ZeroBounce email validation (7-day cache TTL)
  6. Save to `company_contacts` with `unique_key`
- **Role filters:** C-Suite, VP, Director, Manager (configurable per run)
- **Batch size:** Configurable, default 50 companies per batch

### 9.4 Data Quality Engine
- **Location:** `oracle_intent_engine/src/data_quality.py`
- **Company checks:** Valid name, domain format, not job board, Oracle signal present
- **Contact checks:** Email format, ZeroBounce valid, not DNC/DNE, title matches filter
- **Output:** Pass → `approved`, Fail → `pending_review` → Review Queue

### 9.5 HubSpot Sync
- **Location:** `oracle_intent_engine/src/hubspot_push.py`
- **Company push:** Domain-based upsert, 27 fields, `technology_profile` resolved from FK
- **Contact push:** Email-based upsert, 22 fields
- **Pull:** Paginates HubSpot `/crm/v3/objects/companies` + `/contacts`, upserts locally
- **Deduplication:** `unique_key` (64-char URL-safe token) generated on every INSERT

---

## 10. LIVE SYSTEM STATS (as of build)

| Metric | Count |
|---|---|
| Companies tracked | 658 |
| Intent signals | 112 (current scan) |
| Contacts total | 4,698 |
| Contacts with email | 4,569 |
| Valid emails | 285 |
| Companies enriched | 158 |
| Pushed to HubSpot | 0 (pending config) |
| Product Intel companies | 658 |

---

## 11. DEPLOYMENT

### Start server
```bash
./restart.bat          # Windows (kills old + starts fresh)
```

### Manual start
```bash
venv/Scripts/python.exe -m uvicorn unified_app:app --host 0.0.0.0 --port 8000
```

### Build frontend (after code changes)
```bash
cd frontend && npm run build
```
Frontend is served as static files from `frontend/dist/` — no separate frontend server needed.

### Git repository
```
https://github.com/Siddhartha-ino/inoapps-intelligence
```

---

## 12. KNOWN GAPS (from original design doc §7)

| Item | Priority | Status |
|---|---|---|
| Products push to HubSpot | Low | Not built |
| Events push to HubSpot | Low | Not built |
| `oracleSolutionsSummary` calculated field | Low | Display-only, not pushed |
| `ultimateParentAccountId` association | Low | System-managed, display-only |
