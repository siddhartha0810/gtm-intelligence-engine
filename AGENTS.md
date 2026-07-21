# DATA TOOL — Intent Intelligence Platform

## What this actually does (GTM context first)

This is a full-stack **intent-driven outreach platform** built to solve one specific GTM problem: by the time a company appears on a standard vendor intent list, they've already shortlisted 3–4 consultants and issued an RFP. The window to influence is 60–90 days before that.

**The platform detects that window** by watching 15+ real-time sources for companies that are quietly hiring for a product implementation, scoping a rollout, or appearing in procurement activity — before they go public. It then enriches those companies with decision-maker contacts, validates emails, predicts formats where data is missing, scores every lead for priority, and routes contacts into sequences.

The platform is **taxonomy-driven, not hardcoded to one vendor**: the active product list, phase keywords, and scoring rules load at runtime from a `product_taxonomy` DB table (or a campaign's own `icp_profiles/*.yaml`). Oracle/JD Edwards is the default, most-mature taxonomy, but campaigns are not limited to it — `icp_profiles/quadsci.yaml` and `icp_profiles/endex.yaml` are live non-Oracle ICP examples running in production.

### End-to-end GTM pipeline

```
Signal Detection (15+ sources)
  → Buying Phase Classification (hiring / implementing / evaluating / upgrading / supporting)
    → Lead Scoring (signal_count × confidence × phase_weight)
      → Contact Enrichment (Apollo → ZoomInfo → Apify waterfall)
        → Email Validation (ZeroBounce, or pattern prediction for gaps)
          → HubSpot CRM Sync / Apollo Sequence Export / CSV for Clay
```

### Campaign Builder — AI-powered outreach in 5 steps

A separate mode for campaigns against a defined ICP:

```
Step 1 — Find ICP Companies   → YC OSS API, filtered by tags + batch recency + team size
Step 2 — Find Decision-Makers → Apollo people search, title-matched (CTO / VP Eng)
                                 + pre-launch checks: Apollo credit estimate, ZeroBounce deliverability
Step 3 — Generate Hooks       → Claude Haiku (via llm_gateway), PAS framework, 5 tension angles
                                 (Risk/Effort/Time/Cost/Identity), personalization-bucket gated
Step 4 — Export               → CSV with subject + body + LinkedIn URL, ready for sequence upload
Step 5 — Cadence              → 5-touch sequence builder from successful hooks
```

Hooks are grounded in real research (not generic AI copy) and gated by a grounding-check that holds back any body whose specifics don't trace to real evidence.

### Buying phase taxonomy (maps to sales stage awareness)

| Phase | What it means | Example signal |
|-------|---------------|----------------|
| `hiring` | Actively recruiting Oracle talent → early implementation prep | JDE CNC Admin job on Indeed |
| `implementing` | Live rollout underway | Press release: "go-live Q3" |
| `evaluating` | RFP/RFI stage | Procurement portal notice |
| `upgrading` | Cloud migration or version upgrade | "Oracle Fusion migration" LinkedIn post |
| `supporting` | Long-term run-state maintenance | "manage existing Oracle environment" JD |

(`intent_engine/src/phase_classifier.py` also detects `researching`, `budgeting`, `post_live` — see that file for the full 6-phase keyword taxonomy actually used by signal classification.)

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
# from the same FastAPI process on :8000. Preferred way to run the app.
./start.sh
# → http://localhost:8000
```

Dev mode (hot-reload frontend on its own port) still works, but both processes need to be running:

```bash
# Terminal 1
.venv/bin/python -m uvicorn unified_app:app --host 0.0.0.0 --port 8000

# Terminal 2
cd "/Users/sid/Desktop/DATA TOOL/frontend"
npm run dev
# → http://localhost:5173
```

> The working venv on this Mac is `.venv/bin/activate` — the `venv/` folder in this repo is a stale Windows-layout copy (`Scripts/`, not `bin/`) and won't run here.

## PostgreSQL quick check
```bash
.venv/bin/python -c "import psycopg2; c = psycopg2.connect('host=127.0.0.1 port=5432 dbname=oracle_intent user=postgres password=postgres'); print('DB OK'); c.close()"
```
This machine runs Postgres locally (`intent_engine/.env` has `DB_HOST=127.0.0.1`), not against the office DB at `10.0.0.149`. If you're pointed at the office DB instead, you need to be on the office network or VPN.

---

## Automatic Behavior (always active — no prompting needed)

### Agent auto-delegation
| Situation | What the agent does automatically |
|-----------|-------------------------------|
| Error / traceback / "not working" | Invokes **pipeline-debugger** agent immediately |
| "Add a new signal" / new scraper request | Invokes **signal-writer** agent |
| Code review / pre-merge check | Invokes **code-reviewer** agent |
| Security question / audit request | Invokes **security-auditor** agent |

### Rule auto-loading
| File being edited | Rule loaded automatically |
|-------------------|--------------------------|
| Any `*.py` in `intent_engine/src/signals/` | `rules/signals.md` + `rules/backend.md` |
| Any `*.py` in either engine | `rules/backend.md` |
| Any `*.ts` or `*.tsx` in `frontend/` | `rules/frontend.md` |
| `database.py`, `pg_*.py`, SQL anywhere | `rules/database.md` |

If a hook or lint check finds issues, fix them immediately — a task is not "done" until the check is clean.

---

## What this is
A full-stack Oracle intent intelligence platform for B2B lead generation. It detects companies actively hiring, implementing, or buying Oracle products (JD Edwards, Oracle Cloud ERP, NetSuite, HCM, SCM, EPM, OCI, etc.) and enriches those companies with decision-maker contact data.

**Business purpose:** Find Oracle prospects before competitors do, by detecting hiring signals, news, procurement activity, and Oracle community presence across 15+ data sources.

---

## Architecture

```
DATA TOOL/
├── unified_app.py               ← FastAPI app (port 8000) — serves the built React frontend
│                                    AND all API routes for both engines. This is the entry point.
│
├── intent_engine/        ← signal detection engine (imported as `src` by unified_app.py)
│   ├── src/
│   │   ├── database.py          ← All PostgreSQL queries (companies, oracle_signals, contacts, scan_runs)
│   │   ├── pipeline.py          ← Orchestrates all signals in parallel threads
│   │   ├── signals/             ← 15+ signal scrapers (job boards, news, Oracle sites, etc.)
│   │   │   ├── base_signal.py   ← Base class every signal must inherit
│   │   │   └── ...
│   │   ├── lead_scorer.py       ← Priority score (phase + tier + diversity + volume + confidence) + fit/intent routing
│   │   ├── phase_classifier.py  ← Detects Oracle adoption phase from job/article text
│   │   ├── apollo_enrichment.py ← Apollo + ZeroBounce contact enrichment pipeline
│   │   ├── icp_hunter.py        ← Fetches YC-backed companies matching an ICP (yc-oss API)
│   │   ├── hook_generator.py    ← PAS-framework cold email hooks, grounding + personalization gates
│   │   ├── llm_gateway.py       ← Multi-provider LLM routing (Groq/Gemini/Ollama/Anthropic) + budget/cache
│   │   ├── company_researcher.py ← Enriches ICP companies with context for hook grounding
│   │   ├── account_brief.py     ← On-demand per-company brief (phase trajectory, score delta, narrative)
│   │   └── config.py            ← ALL env vars and Oracle search queries
│   └── staffing_filter.py       ← Removes staffing/consulting firms from results
│
├── lead_enrichment_engine/      ← separate CLI pipeline for CSV lead enrichment (own venv-adjacent src/)
│   ├── src/
│   │   ├── orchestrator.py      ← Routes leads to Apollo/Apify/ZoomInfo, credit/rate-limit checks
│   │   ├── zerobounce_client.py ← ZeroBounce batch email validation
│   │   ├── pg_master.py         ← master_leads table: permanent cross-run accumulation
│   │   └── config.py            ← ALL env vars and file paths
│   ├── input/                   ← leads.csv, domain_lookup.csv, suppression_list.csv
│   └── output/                  ← final_outreach_ready.csv, audit_log.csv
│
├── frontend/                    ← React 18 + TypeScript + Vite (dev port 5173, built into unified_app.py for prod)
│   └── src/
│       ├── App.tsx              ← Router + JWT auth guard + layout shell
│       ├── pages/                ← 23 pages: Dashboard, Companies, Contacts, EngineControl, ReviewQueue,
│       │                           IntentData, Reporting, Metrics, TechnologyProfiles, ListImport, Events,
│       │                           AuditLogs, UserManagement, HubSpotSync, ProductIntelligence,
│       │                           DecisionIntelligence(+Live), PredictionEngine, Profile, Settings,
│       │                           CampaignBuilder, CampaignEmails, Campaigns, PeopleSearch
│       └── components/          ← Sidebar, Topbar, Toast, ConfirmDialog, CommandPalette
│
└── .venv/                       ← Shared Python 3.13 virtualenv for both engines (Mac-native — `venv/` is a stale Windows copy)
```

**Cross-engine imports are FORBIDDEN** — `intent_engine` and `lead_enrichment_engine` are independent services; `unified_app.py` imports from both but they never import from each other.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Vite, react-router-dom v6, Lucide React icons, inline styles (no Tailwind) |
| Backend | Python 3.13, FastAPI + uvicorn, single process on port 8000 (`unified_app.py`) |
| Primary Database | PostgreSQL, database: `oracle_intent`, user: `postgres` (local on this machine, `10.0.0.149` on the office network) |
| Email enrichment | Apollo.io (primary), ZoomInfo → Apify (fallback), ZeroBounce (validation) |
| Intent signals | Indeed, LinkedIn, Google Jobs, Adzuna, ZipRecruiter, SerpAPI/NewsAPI/Bing News, Oracle community/events/website, procurement, SEC filings, partner case studies |
| LLM routing | `llm_gateway.py` — Groq / Gemini / Ollama / Anthropic waterfall, budget + cache aware |
| Hook generation | Claude Haiku via `llm_gateway` — PAS-framework cold email copy, grounding-gated |
| ICP discovery | YC OSS public API — tag + batch + team size filters |

---

## Environment Variables

### intent_engine/.env
| Variable | Required | Notes |
|----------|----------|-------|
| DB_HOST | ✅ | `127.0.0.1` locally, `10.0.0.149` on office network |
| DB_PORT | ✅ | `5432` |
| DB_NAME | ✅ | `oracle_intent` |
| DB_USER | ✅ | `postgres` |
| DB_PASSWORD | ✅ | the postgres password |
| JWT_SECRET | ✅ | random string for JWT signing — falls back to a persisted random key if unset |
| APOLLO_API_KEY | ✅ | from app.apollo.io → Settings → API |
| ZEROBOUNCE_API_KEY | ✅ | from app.zerobounce.net |
| HUNTER_API_KEY | ✅ | from hunter.io/api |
| ADZUNA_APP_ID / ADZUNA_APP_KEY | ✅ | from developer.adzuna.com |
| ANTHROPIC_API_KEY | optional | for `llm_gateway` Claude tier / hook generation |
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
`id, name (UNIQUE), domain, industry, size, location, website, first_scan_run_id, first_seen, last_updated`

### oracle_signals
`id, company_id (FK), scan_run_id, oracle_product, phase, source, signal_type, job_title, evidence, url, confidence, detected_at, content_hash`. Signals **accumulate** across scan runs — never overwritten, deduped only by `content_hash`.

### company_contacts
`id, company_id (FK), full_name, first_name, last_name, title, email, linkedin_url, seniority, confidence, is_target, source, email_validation_status, fetched_at`

### master_leads (PERMANENT — never delete, in lead_enrichment_engine's DB surface)
`id, first_name, last_name, email (UNIQUE), title, company, domain, phone, linkedin_url, source, ready_for_outreach, target_product`

### users (auth)
`id, email, password_hash, role` — role values: `owner`, `admin`, `viewer`, `recruitment`

---

## Rules the agent MUST follow

1. **NEVER commit .env files** — they contain real API keys for paid services (Apollo, ZeroBounce, Apify cost real money per credit)
2. **NEVER delete from master_leads** — this is the permanent lead database, irreplaceable data
3. **NEVER drop or truncate any table** — always ask the user before any destructive DB operation
4. **Cross-engine imports are FORBIDDEN** — `intent_engine` and `lead_enrichment_engine` are independent services
5. **All new signals must inherit BaseSignal** — no standalone scrapers
6. **All config via src/config.py** — never hardcode API keys, hostnames, or paths in logic files
7. **Frontend auth header** — every fetch call needs `Authorization: Bearer <token>` (use the `authH()` pattern)
8. **Apollo API auth** — uses `X-Api-Key` header, NOT `Authorization: Bearer`. This is a common mistake.
9. **Rate limits are real** — ZeroBounce charges per email, Apollo charges per reveal. Never validate/reveal in a loop without confirmation
10. **The staffing_filter must always run** — never skip it; it prevents staffing agencies from polluting results

---

## Common Tasks

| Task | How |
|------|-----|
| Add new Oracle intent signal | `/add-signal <name>` skill or signal-writer agent |
| Add new frontend page | `/add-page <PageName>` skill |
| Debug pipeline error | pipeline-debugger agent + the full error message |
| Run everything | `/run-engine` skill or `./start.sh` |

---

# GTM Context System (reference pattern — not yet implemented here)

Source: Matteo Tittarelli's ["How I build and refresh my GTM system with Claude"](https://github.com/matteotitta/claude-code-marketing-quickstart) — a starter template for running a marketing team's context/strategy/execution loop through Claude Code skills.

**The pattern:** four stages, each feeding the next, with the last stage looping back to refresh the first.

```
1. Research   → input (URLs, sales-call transcripts, survey templates)
                → skills (win-loss, competitor-research, icp-research, positioning,
                  messaging, brand-kit/tov-guidelines)
                → output: CLAUDE.md-style context docs (icp.md, positioning.md, messaging.md, brand.html)

2. Strategy   → input: the context docs above
                → skills (content-strategy, linkedin-ads-strategy, lifecycle-strategy,
                  outbound-strategy, product-launch, vibe-coding-strategy)
                → output: per-channel strategy docs

3. Execution  → input: the strategy docs above
                → skills (thought-leadership, linkedin-ads-copy, churn-emails,
                  outbound-emails, product-launch-blog, vibe-coding)
                → output: shippable assets (articles, ad copy, email sequences, landing pages)

4. Refresh    → new inputs from execution (sales calls, lead-form data, competitor URLs,
                all-hands transcripts, SEO/AEO reports) flow back into stage 1,
                keeping context current instead of static.
```

**Repo structure** (`claude-code-marketing-quickstart`): a `marketing/` workspace of structured Markdown files, `.claude/skills/` with ten pre-seeded research skills (`brand-kit`, `competitor-research`, `competitor-aggregate`, `funnel-strategy`, `icp-research`, `positioning`, `product-messaging`, `tov-guidelines`, `win-loss-analysis`, `expert-pov`), a `level` skill that scores Claude Code maturity 0–10, and a convention of one-page `CLAUDE.md` pointer files per folder rather than storing full content in `CLAUDE.md` itself ("every artifact has a named owner").

**Why this is here, not implemented:** DATA TOOL is the *product* that acts on GTM signals (detection, enrichment, outreach), not a marketing team's own context-authoring workspace. The relevant overlap is narrow — Campaign Builder's `icp_hunter.py`/`company_researcher.py` already do a lightweight version of "ICP research → grounded messaging" for hook generation. If DATA TOOL's own GTM/PMM documentation (ICP definition for Weave, competitor positioning, messaging library) ever needs to be built out formally, this repo's skill set and Research→Strategy→Execution→Refresh loop is the reference pattern to adopt — not signal-detection logic to copy.
