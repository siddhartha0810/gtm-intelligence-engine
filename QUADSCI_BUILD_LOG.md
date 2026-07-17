# QuadSci — Complete Build Log, Start to Finish

A plain-language record of every step, why it happened, what came out of it, and where it
lives. Read top to bottom and you can explain the whole system.

---

## Phase 0 — What already existed (the platform)

Before any QuadSci work, the DATA TOOL platform already had a **generic, reusable pipeline**
originally built for Oracle-intent detection and first account-ified for InRule:

- **Campaigns** (`campaigns` table + `query_builder.py`): a campaign = a named keyword set,
  sources list, and exclusions. The scan engine is generic; campaigns point it at a market.
- **Signal scrapers** (`oracle_intent_engine/src/signals/`): one module per source, all
  inheriting `BaseSignal`, returning uniform signal dicts.
- **Scan pipeline** (`pipeline.py`): fetch → filter (staffing agencies removed) → classify →
  aggregate → persist → export, with live progress in the UI.
- **Glassbox scorer** (`glassbox_scorer.py`): rules with weights + decay, each evaluated
  fired / not-fired / no-evidence; score = points ÷ evaluable weight → tiers (≥60% T1,
  ≥40% T2, ≥20% T3). Every fired rule carries a citation. Born from the InRule demo.
- **Hook generator** (`hook_generator.py`): Claude-based one-sentence cold-email openers
  with a PAS framework, angle taxonomy, and quality gates.
- **Cadence builder** (`cadence_builder.py`): expands an approved hook into a 5-touch
  sequence (email → LinkedIn → email → LinkedIn → breakup).
- **Account page pattern**: a per-account dashboard (Overview / Signal Rules / Scored
  Prospects / Live Signals / Contacts / Emails / Sequences).

## Phase 1 — QuadSci account created (commits `59f536d` → `dd31b2e`)

1. **Researched QuadSci** (site, funding news): customer-intelligence AI, churn prediction
   from product telemetry, founders ex-Elastic/ex-MuleSoft, $8M Series A Feb 2026.
2. **Wrote the ICP file** `icp_profiles/quadsci.yaml`: target industries, personas,
   identification criteria, competitors, with cited sources.
3. **Wrote the signal taxonomy** `icp_profiles/quadsci_signal_rules.yaml`: hiring,
   tech-stack tells, funding events, leadership changes, NRR commentary, customer pain
   language, competitor displacement — each with detect-terms and a confidence score.
4. **Seeded the campaign** (`seed_quadsci_campaign.py`): converts the yaml rules into job
   queries + news queries for the generic scan engine. (Found and documented a real bug:
   setting only custom news queries silently zeroed out job queries.)
5. **Built the page + API route**: `/accounts/quadsci` + `/api/decision-intelligence/quadsci`
   (later refactored into a shared `_account_page_payload()` helper used by every account).
6. **Ran real scans**, scored prospects with `run_glassbox.py`, generated hooks and
   sequences (`generate_quadsci_hooks.py`), fixed four real bugs found along the way
   (transaction aborts on duplicate LinkedIn URLs, dropped corroboration on re-score,
   dotenv path resolution, duplicated cadence touches).

## Phase 2 — QuadSci interview scheduled: page re-enabled

The page had been hidden for an InRule demo. Re-enabled the route + sidebar entry
(commit `8cb47b5`), verified all tabs live. Then the directive: **strengthen the signals.**

## Phase 3 — Source audit: what actually works for free

Claimed sources were tested one by one instead of trusted:

| Source | Verdict |
|---|---|
| Indeed | **Dead** — 403 Cloudflare block confirmed live; publisher API discontinued |
| Adzuna | Free API exists but keys never set in `.env` |
| ATS boards (Greenhouse/Lever/Ashby) | Free keyless JSON — but the board registry had **0 rows**, so scans scanned nothing |
| Bing/Google News RSS | Free but soft rate-limits under batch load |
| Crunchbase / PitchBook / CB Insights | Genuinely paid — but funding *announcements* are press releases; free news catches them |
| LinkedIn jobs scrape | The workhorse — ~11k raw signals per scan |

## Phase 4 — Four new free signal sources built

1. **ATS board seeding** (`seed_ats_boards.py`): discovered + registered **43 boards** for
   ICP-lookalike companies via keyless endpoint probing. First run surfaced real intent:
   Demandbase hiring a VP Revenue Operations, Postman a Director of CS Ops, Vanta staffing
   RevOps.
2. **SEC 8-K Item 5.02 officer changes** (`fetch_sec_officer_changes()` in
   `run_glassbox.py`): resolves each public company to its CIK via SEC's
   `company_tickers.json`, pulls `data.sec.gov/submissions/`, surfaces 8-Ks whose items
   include 5.02 (legally mandated officer-change disclosures) — plus the authoritative SIC
   industry code from the same fetch. Free, keyless, citable.
3. **Layoff signal** (layoffs.fyi): the site embeds an Airtable; a two-step fetch reads the
   signed shared-view JSON — 4,500+ structured rows (company, headcount, %, date, source
   link). Layoff at a SaaS company = cost pressure = retain-beats-acquire math.
4. **Competitor churn watch** (`competitor_churn_watch.py`): diff Wayback Machine snapshots
   of competitor customer-logo walls; a quietly removed logo ≈ churned customer =
   displacement window. Two honesty guards: only structurally comparable snapshot pairs are
   diffed (a 2025 Pendo redesign made a naive diff report ~117 fake churns), and removals
   feed the existing 0.55-confidence displacement rule — never a qualified prospect alone.
   **Live catch: Patreon and Chatwork removed from Pendo's wall (2024-09 → 2025-03) while
   the wall grew 118→127.**

## Phase 5 — Full rescore with the new sources

`run_glassbox.py --campaign-id 4` over all 113 candidates. Diffed against a snapshot taken
before the run:

- **Up:** Qualys 0→27 (8-K + category language), AppFolio 10→27.6, Trimble 6→22.6,
  Cloudflare 14.5→24 (8-K + layoff), Rivian 0→15 (layoff — later hard-filtered).
- **Down, honestly:** three accounts dropped because the decay function caught that their
  funding "triggers" were years old (re-syndicated RSS dates had made them look fresh).
  One account (Apono) lost a non-reproducible hit; retried individually, still nothing —
  left at zero. No fabricated repairs.

## Phase 6 — industry_fit fixed (three layered bugs)

The user asked why "Industry Fit" showed *checked, absent* on 94/100 prospects:

1. `companies.industry` was **empty** for the whole campaign — backfilled top prospects via
   Wikidata (coverage thin: 4/19 hits — an honest limitation of free firmographics).
2. The synonym table mapping vendor labels to ICP categories was **finance-only** (built for
   another account) — added precise SaaS mappings; deliberately left generic labels
   ("software industry") unmapped, or the rule would fire for every software company.
3. A generic label **blocked** the stronger job-posting-based technographic check behind it —
   restructured so evidence sources fall through until one fires (commit `db4fe2f`).

## Phase 7 — Contacts, emails, enrichment (credit-frugal)

- **Pattern inference filled 87 emails at $0**: learn each company's format
  (`first.last@…`) from its own confirmed emails, apply to colleagues, mark
  `pattern_inferred / not_validated`. Skip-if-duplicate guard added after a real collision.
- **Apollo spent only where justified**: companies with zero contacts, capped 4/company,
  ZeroBounce skipped entirely (empty key = validation stages no-op). Judgment call: refused
  to spend credits on off-ICP boarders (Rivian, Surf Air).
- Hooks + 5-touch sequences generated for the TIER 2/3 board via the real pipeline.

## Phase 8 — The copy-quality incident ("Casey, your $3.")

The user spotted a three-word email body on the page. Root-cause found three stacked bugs:

1. The one-sentence enforcer cut at the first period — **including the decimal point in
   "$3.7M"** — amputating the body. Fixed the regex (punctuation must end a sentence).
2. **No minimum length gate** existed — added: <8 words = held back as truncation.
3. The grounding check had passed on **the contact's own first name** ("casey") — fixed by
   stripping name tokens before grounding.

Then audited all ~100 stored hooks: 1 truncated (regenerated cleanly →
*"Casey, your $3.7M raise means investors will scrutinize how AI turns usage into
retention"*), 1 relabeled to its real grounding term, 10 held back as genuinely ungrounded
template copy (commit `e476cba`). A Cloudflare hook that wrote "layoffs" where evidence said
"laid off" stayed held — lexical-vs-semantic grounding is a known, documented limit.

## Phase 9 — The 2020 forum post (the defining story)

The user found that Skydio's top-prospect score leaned on a **September 2020** forum
complaint. Root cause: pain-language hits were stored with an empty date, and undated
evidence bypasses every decay rule — scoring like it happened yesterday, forever. Fix
(commit `d3672a8`): every third-party pain hit must carry a machine-readable publish date
from its own page markup (the *earliest* date — the original post, not the last reply) and
be under 18 months old; undated pages are dropped, not waved through. Rescoring the four
affected accounts: Skydio 28.2→18.2, Tebra 25.4→16, Aircall 22→12, Fivetran 10→0. The #1
prospect fell two tiers and the fix shipped anyway. **This is the glass-box philosophy in
one story.**

## Phase 10 — Patreon & Chatwork become prospects (and get honestly demoted)

The churn-watch discoveries were admitted as real prospects: company rows + signals
(source `competitor_churn`, backdated to the true event date, citing both archived pages).
First scoring attempt: 26 points, TIER 2 — **wrong**, because the single removal event was
counted twice (signal + corroboration) and masqueraded as a two-event cluster. Corrected:
one event is not a cluster; they landed at 18, TIER 3 — MONITOR, where a single-signal
prospect belongs (commit `d00215d`). The moment either posts a RevOps job, the cluster
completes automatically.

## Phase 11 — The exercise PDF arrives: alignment + submission

QuadSci's actual take-home defined the ICP precisely and demanded specific deliverables.
Gap analysis first, then five fixes (commit `f79517d`):

1. **ICP corrected to their words**: 200+ employees (sweet spot 200–500), Series B+, $50M+
   ARR, CS *and* Sales teams, CRO org primary / CS secondary — replacing news-derived bands.
   Product language locked to the site: Growth AI / Cohorts AI, **90%+ accuracy, 9–18
   months** ahead of renewal, "grounded in real user behavior," telemetry vs. CRM-derived
   guesswork. Competitor set corrected (Gainsight/ChurnZero/Clari + Hook/Reef/Magnify) with
   the partner nuance: the site lists Gainsight/Clari/Pendo as *integrations*, so copy says
   "make your stack predictive," never "rip it out."
2. **USP-tied signal added**: `renewal_window_entry` — go-live 9–18 months ago = inside the
   only window where QuadSci's prediction changes the outcome.
3. **Hard filters applied to the live board**: Rivian, Surf Air, ClarityQ, Botrista shown
   as HARD-FILTERED with reasons (not deleted — auditable filtering); Patreon kept with a
   flagged B2C2B caveat.
4. **Flagship email regenerated in site language**: Chatwork —
   *"Yasuyuki, Pendo records what happened but can't predict what's coming with your
   customers."* — the churn-watch evidence fused with the site's differentiator.
5. **The submission written**: `SUBMISSION_QUADSCI_GTM.md` — their four stages in order,
   every "what to deliver" bullet answered, the full production system prompt verbatim,
   four real iteration stories, staging/auto-send policy, the closed feedback loop, and
   the biggest-risk section built on Phase 9.

---

## The numbers, end state

- ~11,000 raw signals/scan → 681 classified → 113 candidates → 47 scored → **9 actionable**
- 43 ATS boards registered · 4,500-row layoff dataset · 8-K coverage for all public accounts
- TIER 2 board: Qualys 27.1 · Trimble 26.6 · Chatwork 22 · Patreon 22 (caveat) — every
  point citable
- ~90 emails at $0 via pattern inference; paid credits only for zero-contact accounts, 4 cap
- 100-hook audit: 1 regenerated, 10 held back, gates hardened

## The five stories worth telling out loud

1. **The 2020 forum post** — found a stale signal, shipped the date gate, demoted my own #1.
2. **The churn watch** — QuadSci's product thesis pointed at its competitors; found Patreon
   and Chatwork; the scorer still refused to call them qualified on one signal.
3. **"Casey, your $3."** — three stacked bugs, an audit of every stored email, ten held back.
4. **The empty ATS registry** — "this source needs paid APIs" turned out to be "nobody
   seeded the free one"; 43 boards later it's the best source in the stack.
5. **Hard-filtering my own discoveries** — Rivian's layoff was a real signal; Rivian still
   isn't a prospect. Fit is a filter, signals are events, and neither alone earns an email.
