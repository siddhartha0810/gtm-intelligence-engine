# Inoapps Intelligence Hub — End-to-End Workflow Flowchart

---

## WORKED EXAMPLE
**Goal:** Discover that "Accenture" is evaluating Oracle Cloud ERP, find the right contacts, enrich their emails, review them, and push to HubSpot.

---

## STAGE 0 — LOGIN & ACCESS

```
User opens http://localhost:8000
         |
         v
    [ Login Page ]
    Enter email + password
         |
    POST /api/auth/login
         |
    ┌────┴────┐
    │ PASS    │ FAIL
    │         └──> "Invalid credentials" — stay on Login
    v
  JWT token stored in localStorage
         |
         v
  Redirected to → Dashboard
         |
  Role check applied to all nav items:
    viewer      → read-only (Companies, Contacts, Reports)
    analyst     → + scans, enrichment, exports
    admin       → + user mgmt, purge, reset
    owner       → full access, cannot be demoted
```

---

## STAGE 1 — CONFIGURE (one-time setup)

```
Nav: Configuration → Technology Profiles / HubSpot Sync / Engine Control
                  |
                  v
┌─────────────────────────────────────────────────────┐
│ TECHNOLOGY PROFILES  (GET/POST /api/technology-     │
│                        profiles)                    │
│                                                     │
│  Create a profile e.g. "Oracle ERP Stack"           │
│  Add keywords: "Oracle Cloud ERP", "Fusion",        │
│                "JD Edwards", "Oracle HCM"           │
│  Add target websites: linkedin.com, indeed.com      │
│  Add product taxonomy entries (canonical names +    │
│  aliases + confidence weights)                      │
│                                                     │
│  → This profile is linked to scan runs and          │
│    companies, drives signal classification          │
└─────────────────────────────────────────────────────┘
                  |
                  v
┌─────────────────────────────────────────────────────┐
│ HUBSPOT SYNC — Save API Key                         │
│  POST /api/hubspot/config                           │
│  { api_key: "pat-na1-...", portal_id: "12345" }     │
│                                                     │
│  POST /api/hubspot/test  → verifies live connection │
│  Status shows: apollo ✓  zerobounce ✓  hubspot ✓   │
└─────────────────────────────────────────────────────┘
```

---

## STAGE 2 — ORACLE INTENT SCAN

```
Nav: Engine Control → "Start Scan" button
                  |
         POST /scan/start
         { sources: ["linkedin","indeed","google_jobs","news"],
           max_pages: 3,
           technology_profile_id: 1 }
                  |
                  v
    ┌─────────────────────────────────┐
    │  ORACLE INTENT ENGINE (Python   │
    │  subprocess, runs in bg)        │
    │                                 │
    │  For each keyword/site combo:   │
    │  1. Scrape job postings &       │
    │     news for Oracle signals     │
    │  2. Extract company name,       │
    │     oracle_product, phase,      │
    │     confidence, evidence text   │
    │  3. Write → oracle_signals      │
    │  4. Upsert → companies          │
    │     (with unique_key generated) │
    └─────────────────────────────────┘
                  |
    GET /scan/status  ← frontend polls every 3s
    GET /scan/log     ← live log lines streamed
                  |
                  v
    ┌───────────────────────────────────────────────┐
    │ EXAMPLE OUTPUT                                │
    │                                               │
    │ oracle_signals:                               │
    │   company: "Accenture Federal Services"       │
    │   oracle_product: "Oracle Cloud ERP"          │
    │   phase: "hiring"                             │
    │   confidence: 0.87                            │
    │   source: "indeed"                            │
    │   evidence: "seeking Oracle Cloud ERP         │
    │              implementation lead..."          │
    │                                               │
    │ companies:                                    │
    │   name: "Accenture Federal Services"          │
    │   domain: "accenture.com"                     │
    │   status: "staged"                            │
    │   unique_key: "xK9mP2..."  (auto-generated)   │
    └───────────────────────────────────────────────┘
                  |
    On scan complete:
    → aggregate_product_intel() runs automatically
      (classifies cloud vs on-premise per company)
```

---

## STAGE 3 — REVIEW COMPANIES

```
Nav: DATA MODULES → Companies
                  |
         GET /api/companies
                  |
    ┌────────────────────────────────────────┐
    │ COMPANIES LIST                         │
    │ Search: "Accenture"          [Search]  │
    │ Filter: Phase ▼  Status ▼             │
    │                                        │
    │ ┌─────────────────────────────────┐   │
    │ │ Accenture Federal Services      │   │
    │ │ domain: accenture.com           │   │
    │ │ 3 signals | Phase: Hiring       │   │
    │ │ Status: staged                  │   │
    │ │ [View Signals] [Enrich] [Push]  │   │
    │ └─────────────────────────────────┘   │
    └────────────────────────────────────────┘
                  |
    Click company row → Slide-over panel opens
                  |
         GET /api/company/{id}/signals
         GET /api/company/{id}/contacts
                  |
    ┌────────────────────────────────────────┐
    │ SLIDE-OVER PANEL                       │
    │                                        │
    │ SIGNALS TAB                            │
    │   Signal 1: "Oracle Cloud ERP"         │
    │   Phase: hiring  Conf: 87%             │
    │   Source: indeed.com                   │
    │   Evidence: "seeking Oracle Cloud..."  │
    │                                        │
    │ CONTACTS TAB                           │
    │   (empty until enrichment runs)        │
    │                                        │
    │ Status: [staged ▼] → change to         │
    │         approved / rejected /          │
    │         pending_review                 │
    │   PATCH /api/companies/{id}/status     │
    └────────────────────────────────────────┘
```

---

## STAGE 4 — ENRICH CONTACTS

```
Nav: Engine Control → Enrichment tab
                  |
    GET /api/enrich/preflight
    → shows: 500 companies need enrichment
             158 already done
             342 need Apollo lookup
                  |
    [ Start Enrichment ] modal opens:
    ┌──────────────────────────────────────┐
    │ Preflight Check                      │
    │ Companies to enrich: 500             │
    │ From master_leads cache: 120         │
    │ Need Apollo API call: 380            │
    │                                      │
    │ Batch size: [50  ▼]                  │
    │ Max contacts/company: [10 ▼]         │
    │ Role filters: [x] C-Suite            │
    │               [x] VP / Director      │
    │               [ ] Manager           │
    │                                      │
    │ [Cancel]  [Start Enrichment]         │
    └──────────────────────────────────────┘
                  |
         POST /api/enrich/start
         { limit: 500, max_per_company: 10,
           role_filters: ["C-Suite","VP"] }
                  |
                  v
    ┌────────────────────────────────────────────┐
    │  ENRICHMENT ENGINE (subprocess)            │
    │                                            │
    │  For each company batch:                   │
    │  1. Check master_leads cache first         │
    │     → if hit, skip Apollo call             │
    │  2. Apollo API: search by domain           │
    │     GET people at accenture.com            │
    │     filter: title contains "Oracle"        │
    │  3. For each contact:                      │
    │     a. Predict email pattern               │
    │        (first.last@domain.com)             │
    │     b. ZeroBounce validate email           │
    │     c. Classify: is_target = true/false    │
    │  4. Save → company_contacts                │
    │     (with unique_key generated)            │
    │  5. Cache → enrichment_cache (30d TTL)     │
    └────────────────────────────────────────────┘
                  |
    GET /api/enrich/status  ← polls every 5s
    GET /api/enrich/log
                  |
    EXAMPLE RESULT for Accenture:
    ┌────────────────────────────────────────────┐
    │ company_contacts:                          │
    │   first_name: "Sarah"                      │
    │   last_name: "Mitchell"                    │
    │   title: "VP Oracle Cloud Practice"        │
    │   email: "sarah.mitchell@accenture.com"    │
    │   email_validation_status: "valid"         │
    │   confidence: 0.91                         │
    │   is_target: true                          │
    │   status: "staged"                         │
    │   unique_key: "aB3nX7..."                  │
    └────────────────────────────────────────────┘
```

---

## STAGE 5 — DATA QUALITY ENGINE

```
After enrichment, DQE runs automatically:
                  |
         POST /api/dqe/check/company
         POST /api/dqe/check/contact
                  |
    ┌────────────────────────────────────────────┐
    │ DATA QUALITY ENGINE checks:                │
    │                                            │
    │ Company checks:                            │
    │   ✓ valid company name                     │
    │   ✓ domain format valid                    │
    │   ✓ not a job board / generic site         │
    │   ✓ Oracle product detected                │
    │                                            │
    │ Contact checks:                            │
    │   ✓ email format valid                     │
    │   ✓ ZeroBounce status = "valid"            │
    │   ✓ not do_not_call / do_not_email         │
    │   ✓ job title matches role filter          │
    └────────────────────────────────────────────┘
                  |
    ┌─────────┴──────────┐
    │ PASS               │ FAIL / FLAGGED
    │ status → approved  │ status → pending_review
    │                    │ → Review Queue
    v                    v
 Ready for           Nav: Review Queue
 HubSpot push
```

---

## STAGE 6 — REVIEW QUEUE

```
Nav: Review Queue
                  |
         GET /api/review-queue
                  |
    ┌────────────────────────────────────────┐
    │ REVIEW QUEUE                           │
    │                                        │
    │ Sarah Mitchell — Accenture             │
    │ Flag: "email catch-all domain"         │
    │                                        │
    │ [Approve → Push HubSpot]               │
    │ [Reject — exclude from pipeline]       │
    └────────────────────────────────────────┘
                  |
    Approve  → POST /api/contacts/push-hubspot
    Reject   → PATCH /api/contacts/{id}
               { is_target: false,
                 email_validation_status: "excluded" }
```

---

## STAGE 7 — HUBSPOT PUSH

```
Two ways to push:

A) PER-RECORD (from Companies slide-over):
   [ Push to HubSpot ] button
        |
   POST /api/companies/{id}/push-hubspot
        |
   → Reads all 27 company fields
   → Resolves technology_profile name
   → Searches HubSpot by domain
   ┌────────────┴─────────────┐
   │ domain found             │ not found
   │ PATCH /crm/v3/companies  │ POST /crm/v3/companies
   │ /{hubspot_id}            │
   └────────────┬─────────────┘
                |
   companies.status → "pushed_to_hubspot"
   companies.hubspot_id → "12345678"
   companies.hubspot_synced_at → NOW()

B) BULK PUSH (from HubSpot Sync page):
   [ Push All Approved Companies ] button
        |
   POST /api/hubspot/bulk-push/companies
        |
   Fetches all companies WHERE status='approved'
   Runs domain-based upsert for each (up to 100)
        |
   [ Push All Approved Contacts ] button
        |
   POST /api/hubspot/bulk-push/contacts
        |
   Fetches all contacts WHERE status='approved'
   Runs email-based upsert for each (up to 100)


EXAMPLE HUBSPOT PAYLOAD for Accenture Federal Services:
┌────────────────────────────────────────────────────┐
│ {                                                  │
│   "properties": {                                  │
│     "name": "Accenture Federal Services",          │
│     "domain": "accenture.com",                     │
│     "website": "https://www.accenture.com",        │
│     "industry": "IT Services",                     │
│     "oracle_cloud_solutions": "Oracle Cloud ERP;   │
│                                Oracle EPM",        │
│     "oracle_relationship_type": "partner",         │
│     "technology_profile": "Oracle ERP Stack",      │
│     "inoapps_account_tier": "enterprise",          │
│     "billing_country": "United States"             │
│   }                                                │
│ }                                                  │
└────────────────────────────────────────────────────┘
```

---

## STAGE 8 — HUBSPOT SYNC PULL (optional, reverse direction)

```
Nav: HubSpot Sync → [ Sync from HubSpot ] button
                  |
         POST /api/hubspot/sync-pull
                  |
    Pulls ALL companies + contacts from HubSpot CRM
    Upserts into local DB:
      source = "hubspot_pull"
      status = "approved"
      hubspot_id = preserved for future pushes (no duplicates)
```

---

## STAGE 9 — ANALYTICS & REPORTING

```
Nav: ANALYTICS section
         |
         ├── Dashboard (/dashboard)
         │     GET /api/dashboard
         │     Shows: companies tracked, contacts enriched,
         │            intent signals, pushed to HubSpot,
         │            scan run history chart
         │
         ├── Reporting (/reporting)
         │     GET /api/reporting
         │     Shows: phase distribution (hiring/budgeting/
         │            implementing/post_live),
         │            top data sources, scan run history,
         │            contacts enriched vs pushed
         │
         ├── Intent Data (/intent-data)
         │     GET /api/signals?limit=200
         │     Shows: every raw oracle_signal with
         │            company, product, phase, evidence
         │
         └── Product Intel (/product-intel)
               GET /api/product-intelligence
               POST /api/product-intelligence/refresh
               Shows: per-company oracle product classification
                      (cloud vs on-premise) with confidence scores
```

---

## STAGE 10 — EXPORTS

```
Nav: Companies page → Export buttons
                  |
    ┌─────────────────────────────────────────┐
    │ GET /export/csv          (current scan) │
    │ GET /export/excel        (current scan) │
    │ GET /export/excel/all    (all scans)    │
    │ GET /export/csv/all      (all scans)    │
    └─────────────────────────────────────────┘
    All require: analyst role or above
    Output: company name, domain, industry,
            signals count, phase, products,
            contacts enriched, status, hubspot_id
```

---

## COMPLETE FLOW DIAGRAM (condensed)

```
[Login] ──────────────────────────────────────────────────────────────────┐
   │                                                                       │
   ▼                                                                       │
[Configure]                                                                │
Technology Profile → keywords, target sites, product taxonomy             │
HubSpot → API key saved, connection tested                                │
   │                                                                       │
   ▼                                                                       │
[SCAN] Oracle Intent Engine                                               │
   Scrapes: LinkedIn Jobs, Indeed, Google Jobs, News                      │
   Extracts: company + oracle_product + phase + confidence                │
   Writes: oracle_signals + companies tables                              │
   Auto-runs: aggregate_product_intel() on completion                    │
   │                                                                       │
   ▼                                                                       │
[REVIEW COMPANIES]                                                        │
   Companies list → signals panel → change status                        │
   staged → approved / rejected / pending_review                         │
   │                                                                       │
   ▼                                                                       │
[ENRICH] Lead Enrichment Engine                                           │
   Cache check → Apollo API → Email prediction → ZeroBounce validate     │
   Writes: company_contacts (email, title, LinkedIn, validation)         │
   │                                                                       │
   ▼                                                                       │
[DATA QUALITY] DQE auto-check                                            │
   Pass → approved   Fail → pending_review → Review Queue               │
   │                                                                       │
   ▼                                                                       │
[REVIEW QUEUE] Human approval gate                                       │
   Approve → push   Reject → exclude                                     │
   │                                                                       │
   ▼                                                                       │
[PUSH TO HUBSPOT]                                                         │
   Companies: domain-based upsert (27 fields)                            │
   Contacts:  email-based upsert (22 fields)                             │
   Local status → "pushed_to_hubspot"                                    │
   │                                                                       │
   ▼                                                                       │
[ANALYTICS] Dashboard / Reporting / Product Intel / Exports ─────────────┘
```

---

## ADDITIONAL MODULES (available from sidebar)

```
Contacts (/contacts)
   Full contact list across all companies
   Filter by company, status, validation
   Per-contact: Push to HubSpot, LinkedIn link

List Import (/list-import)
   Upload CSV/Excel → map columns to HubSpot fields
   Save field mapping as reusable template
   Batch history with import status

Events (/events)
   Create Oracle-related events (conferences, webinars)
   Link attendees (contacts) with roles
   Tied to technology profiles

Manufacturer Intel (/manufacturer-intel)
   Track Oracle manufacturing/partner contacts
   Link to companies, note Oracle alignment/team/dept

User Management (/users)  [admin/owner only]
   Invite users, assign roles, deactivate accounts

Audit Logs (/audit-logs)  [admin/owner only]
   Every action logged: who, what, when, on what record

Profile (/profile)
   Change your own password
```
