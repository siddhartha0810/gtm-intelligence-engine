# Signal-to-Campaign Workflow — QuadSci GTM Engineer Exercise

**Siddhartha Kothi**

One note before the four stages: I didn't design this workflow on paper — I built and ran it.
Every number, prospect, email, and failure in this document comes from a live pipeline that
scanned real sources this week, targeting QuadSci's stated ICP: **B2B SaaS, 200+ employees,
Series B or later, ideally $50M+ ARR, with existing CS and Sales teams — the CRO org (SVPs,
VPs, RevOps leaders) as primary buyers, CS second.** All discovery sources are free. The
design principle is borrowed from QuadSci itself: predictions grounded in real behavior —
public behavioral exhaust instead of bought intent data — with every score traceable to a
dated, clickable source. *"See risk early. Act while there's still time."* applies to
pipeline, too.

---

## Stage 1 — Detect Signal Cluster

### The five signals

| # | Signal | What it means for a CRO / CS leader | Free source | Weight |
|---|--------|-------------------------------------|-------------|--------|
| 1 | **Director+ RevOps / CS-Ops hire** | "You just funded a person whose job is renewal visibility. The problem is now owned and budgeted." | Greenhouse/Lever/Ashby public JSON boards (keyless, ~0% block rate; I registered 43 boards), LinkedIn Jobs | +8 |
| 2 | **Legacy CS-platform friction** | "You're paying for Gainsight/ChurnZero/Clari and still hiring humans to make it predictive — human-built rules on lagging data." Job posts requiring platform admin/migration work; community threads about migrating off. Plus my **competitor churn watch**: Wayback Machine diffs of vendors' own customer-logo walls — a quietly removed logo is a churned customer with budget, category need, and an open vacancy. | ATS boards, Reddit via site-search (date-gated), web.archive.org CDX API | +12 |
| 3 | **Public NRR / forecast pain** | "Your buyer is saying out loud that renewals surprise them." Earnings-call retention language (public cos), CRO/VP-CS LinkedIn posts, G2 reviews mentioning churn surprises or forecast blind spots. | Free transcript APIs (EarningsCall.dev, API Ninjas), G2/Reddit via web search — **all third-party pain evidence is date-gated ≤18 months** (see Stage 4 risk) | +10 |
| 4 | **New CRO / CCO in seat** | "New revenue leaders audit the forecast stack in their first 90 days." | SEC 8-K **Item 5.02** via data.sec.gov (legally mandated disclosure, free, citable) for public accounts; press for private | +10, 365-day decay |
| 5 | ⭐ **Renewal-window entry** (USP-tied) | The account signed/went live on its CS or revenue platform **9–18 months ago** — meaning it is *right now* inside the only window where QuadSci's 90%+ churn/growth prediction changes the outcome instead of explaining it afterward. "Your next renewal cycle is already being decided in this quarter's usage data — you just can't see it yet." | Dated press releases, case-study publish dates, first appearance of the logo on a vendor's customer wall (Wayback) | +8 |

### Cluster definition

- **Trigger per account:** ≥2 signals of **different types** within **90 days**, at least one
  being a pain or displacement signal (two job posts = one budget event, not a cluster).
- One signal → account enters *monitor*; nothing else happens.
- **Batch trigger:** 5+ clustered accounts in a week → campaign run.
- Rationale: any single signal has a terrible base rate (every growing company hires; every
  startup raises). Independent evidence streams converging in a short window is what converts
  coincidence into intent — the same logic QuadSci applies to telemetry.

**Live funnel from this week's run:** ~11,000 raw signals → 681 classified → 115 candidates →
7 hard-filtered out → 108 scored → **6 TIER 2/3, of which 3 are QUALIFIED for outreach**. The
system's job is killing 99.9% of signals.

---

## Stage 2 — Score and Filter Accounts

### Hard filters (disqualify regardless of signals)

Checked before any scoring, via LinkedIn headcount, Crunchbase free profiles, and careers pages:

1. Not B2B SaaS (no subscription software product)
2. Under 200 employees
3. Pre-Series B
4. No visible CS function (no renewal motion to improve = no buyer)
5. Services / consulting / staffing firms; QuadSci partners and existing customers (suppression list)

These are **enforced in code** (`hard_filter()`, driven by `quadsci.yaml`), not just asserted —
a matching account is recorded as DISQUALIFIED and skips scoring entirely. They ran against my
live board and disqualified **7 accounts my own detectors had surfaced**: **Rivian** (layoff
fired — but an EV maker), **Surf Air Mobility** (aviation), **Skydio** (drone hardware),
**Patreon** and **Whatnot** (B2C), **ClarityQ** (seed-stage, <200 employees), and **Interface** —
which briefly rode to #1 on a *misattributed* funding article before I caught it (see iteration
note in Stage 3); it's a carpet manufacturer (NYSE TILE). The board shows all 7 with their reason
rather than deleting them: a filter you can't audit is a filter you can't trust.

### Scoring rubric

Signal points per the Stage-1 table, plus **firmographic fit +6** (200–500 employee sweet spot;
>2,000 employees scores −2: enterprise cycles are a mismatch for an early-stage vendor's
sales capacity), **cluster bonus +8** (2+ types in 90 days), **named buyer on file +4**.
Time decay on every dated trigger (linear over 365 days; stale funding rounds earn zero).

**Tier = points as a share of evaluable weight** (rules with no evidence source available are
excluded from the denominator, not counted against the account):

| Tier | Threshold | Action |
|------|-----------|--------|
| TIER 1 — PRIORITY | ≥60% | Outreach this week |
| TIER 2 — QUALIFIED | ≥40% | Outreach this cycle |
| TIER 3 — MONITOR | ≥20% | Watch for the cluster to complete |
| TIER 4 | <20% or <3 evaluable rules | Ignore without guilt |

Every point carries a clickable, dated citation. An unsourced point is a claim a rep can't
defend on a live call, so it doesn't exist.

### Finding the buyers (free)

Title matrix — primary: CRO, SVP/VP Sales, VP/Head/Director of RevOps. Secondary (CC/ally,
per the brief): CCO, VP CS, CS Ops. Methods, in cost order: company /about and team pages →
LinkedIn people search (free, manual) → Apollo **free tier** for name/title only → **email
pattern inference**: learn `first.last@domain` from any one confirmed company email and apply
it to colleagues, flagged `pattern_inferred` until validated. This filled ~90 emails across my
board at zero cost; paid credits were spent only on accounts that had zero contacts, capped at
4 per account, and only above TIER 3.

### Threshold for Stage 3

Copy is generated only when: hard filters passed **and** tier ≥ TIER 2 **and** ≥2 independent
evidence citations **and** a named primary-org buyer exists. The honest insight: AI copy costs
pennies — the real cost of a premature send is domain reputation and a burned account. The
gate is evidence quality, not token budget.

---

## Stage 3 — Generate Personalized Copy

### Worked example (real account, real signals, generated by the pipeline)

**Account:** Chatwork — Tokyo-listed B2B SaaS (workplace messaging), ~350 employees, public,
existing Sales and CS orgs. Passes every hard filter; ICP sweet spot.
**Signals fired:** (1) removed from Pendo's public customer wall between Sept 2024 and Mar 2025
— while that wall *grew* 118→127, so a specific takedown, not a redesign (before/after archive
links attached); (2) analytics-stack friction corroborated by hiring activity.
**Buyer:** Yasuyuki Iwata, Head of Sales & Customer Success (the revenue org).

> **Subject:** Pendo's blind spot
> **Body:** Yasuyuki, Pendo records what happened but can't predict what's coming with your
> customers.

The signal is the first line; the site's differentiator (telemetry that *predicts* vs. tooling
that *records*) is the tension; no product mention — touch 3 of the 5-touch sequence names
Growth AI and makes the one concrete ask. Full sequence in the appendix.

### The prompt (full, verbatim — this is the production system prompt)

```
You are a senior GTM engineer writing hyper-personalised cold email HOOKS.
A hook is the opening 1-2 sentences only — not a full email. It earns the right to be read.

ICP RESEARCH (ground your angles in this):
{icp_research}

HOOK RULES (non-negotiable):
- EXACTLY ONE SENTENCE. Never more. Period.
- The hook NAMES THE PROBLEM only. It does not solve it. It does not mention the product.
- Start with their first name
- Maximum 20 words after the name
- Plain vocabulary — every word a 14-year-old understands
- Pick ONE angle from these six tension categories:
    Risk / Effort / Time / Cost / Identity / TwoTimelines
- ANGLE SELECTION: TwoTimelines is ELIGIBLE ONLY IF the evidence itself is a peer-group or
  industry-wide claim. If the evidence is a single fact about this one company only,
  TwoTimelines is NOT ELIGIBLE — do not generalize a single-company fact into an invented
  industry-wide pattern.
- PHRASING: External villain — blame a shared enemy ("the spreadsheet," "the legacy
  system"), never "you". BUT/THEREFORE structure, not AND — contrast reads as a real
  observation; a flat list of facts reads dead.
- GROUNDING: never invent a specific detail — a report name, a dollar figure, a deadline —
  that is not present in the evidence given. A generic-but-true sentence beats a
  specific-but-invented one; the invented one gets rejected downstream anyway.
- SPECIFICITY: if the evidence contains an exact dollar figure, investor name, or proper
  noun specific to THIS company, anchor on it — it should be obvious from the hook alone
  which company it's about.
- NEVER use: "leverage", "synergy", "quick question", "I wanted to reach out",
  "love what you're building", "hope this finds you", "just checking in"
- Subject line: under 8 words, no question mark, no exclamation mark
```

The user prompt injects: contact name/title/company + the **verbatim scoring evidence** (the
fired rules' text and dates from Stage 2) + the product context written in quadsci.ai's own
language (Growth AI / Cohorts AI, 90%+ accuracy 9–18 months ahead of renewal, "grounded in
real user behavior," telemetry vs. CRM-derived guesswork, and — because Gainsight/Clari/Pendo
are *integration partners* on the site — "make your stack predictive," never "rip it out").

### Iteration history (what broke, what changed — all real, all in git)

1. **Ungrounded copy shipped.** Early hooks read plausibly but quoted nothing from the
   evidence. Added a **grounding gate**: generated copy must contain a distinctive term from
   the evidence actually held, or it's held back, unsent. Rejected copy stays visible in the
   review queue — a rep should see what the machine refused to fabricate.
2. **The gate cheated.** A hook passed grounding by matching the contact's *own first name*
   ("casey"). Fixed: name tokens are stripped before the check; generic GTM vocabulary
   ("your recent funding round", "investors will scrutinize") was blocklisted from counting
   as grounding — it reads identically for any funded company.
3. **A three-word email nearly went out.** The one-sentence enforcer cut at the first period —
   *including the decimal in "$3.7M raise"* — shipping "Casey, your $3." as a complete body.
   Fixed the sentence-boundary regex and added a minimum-length gate. Regenerated:
   *"Casey, your $3.7M raise means investors will scrutinize how AI turns usage into retention."*
4. **Truthful copy got held.** A Cloudflare hook wrote "the layoffs" where the evidence said
   "laid off 1,100 employees" — lexically different, semantically identical — and was held
   back. I kept the hold: false-positive holds are the acceptable failure direction. The fix
   (semantic grounding via embeddings) is on the with-more-budget list.
5. **A generic-name account rode misattributed evidence to #1.** "Interface" scored top of the
   board on an *"Aina Raises $5.5M"* funding article — a different company whose blurb merely
   contained the word "interface." Root cause: the news-corroboration pass credited any article
   that matched a signal term, without checking the article was actually *about* the account.
   Fixed: the account's own name must now appear in the article title before the signal is
   credited — the same guard the G2/Reddit passes already used. Interface then dropped out and
   the hard filter caught it as a carpet manufacturer. This is the failure mode I'd watch most
   closely at scale (see Stage 4 risk).

### Personalization at scale

**Per-account variables:** first name · company · verbatim signal evidence + dates · angle
(selected by evidence type) · buyer-org framing (CRO org → Growth AI language; CPO/CMO →
Cohorts AI) · proof point. **Templated:** structure, gates, banned vocabulary, cadence.
**The feed is mechanical:** the Stage-2 scoring trace (JSON of fired rules + citations) is
injected directly into the prompt — the same evidence that scored the account writes its
email. That's what makes this one loop instead of four exercises.

---

## Stage 4 — Stage the Campaign

### Staging mechanism

A review queue (mine is a working web page; the design ports to a Google Sheet in an
afternoon) where each staged row shows **the copy and the full evidence trace that produced
it** — fired signals, dates, links, score, tier, email-validation status. The reviewer judges
the *claim*, not just the prose. Approve → the 5-touch sequence (email → LinkedIn → email
naming Growth AI → LinkedIn → breakup) exports to a free-tier sender or Apollo sequence.

### Auto-send vs. human review

At cold start, **nothing auto-sends** — thresholds without reply data are guesses. Standing rules:

| Condition | Route |
|-----------|-------|
| Copy passed all gates + tier ≥2 + ≥2 citations + validated email + below-C-level recipient | Auto-send *eligible* |
| C-level recipient | Human review, always |
| Copy derived from pain-language evidence (tone risk) | Human review, always |
| Pattern-inferred (unvalidated) email | Human review |
| Copy regenerated after a grounding hold | Human review |
| **Graduation:** a signal type earns auto-send only after ~50 reviewed sends with reply rate above baseline and zero misfires | — |

### Feedback loop

Every send logs reply / meeting / bounce per contact per signal-type (an `outcomes` table in
the working system). Monthly: reply rate **by signal type** reweights the Stage-2 rubric —
signal types whose clusters book meetings gain points; bounces trigger email-pattern
re-learning; "not relevant" replies feed the hard-filter list. Detection → scoring → copy →
outcome → detection. Closed.

### The biggest risk — and it already happened to me

**Stale or misattributed public evidence producing a confidently wrong email.** Mid-build, my
top-scored account (Skydio, 28.2 points) turned out to owe 10 of those points to a customer
complaint posted in **September 2020** — undated third-party evidence was bypassing every
decay rule and scoring like it happened yesterday. I shipped a date gate the same day: all
third-party pain evidence must carry a machine-readable publish date from its own page markup
(the *earliest* date — the original post, not the last reply) and be under 18 months old;
undated pages are dropped, not waved through. My #1 prospect fell ten points and two tiers,
and the fix went in anyway. Residual mitigations: human review on all pain-derived copy,
citations on every point, decay on every trigger.

### With more budget or time

Semantic (embedding-based) grounding to cut false-positive holds · a firmographic data source
for young private companies (site-copy classification; Wikidata coverage is thin) · reply-rate
data before *any* auto-send graduates · productionizing the churn watch across more vendor
walls (the AI-native competitors — Hook, Reef, Magnify — have no archive history yet; the
watch accrues its own from day one) · LinkedIn Sales Navigator for buyer coverage where the
free methods run dry.

---

## Appendix — live artifacts

- **Funnel:** ~11,000 raw signals → 681 classified → 115 candidates → 7 hard-filtered →
  108 scored → 6 TIER 2/3 actionable
- **TIER 2 — QUALIFIED (post hard-filter, post attribution-guard, post date-gate):**
  Cloudflare 27.97 (May 2026 layoff of 1,100 + 8-K officer change + a 3-type cluster within 11
  days) · Qualys 27.01 (SIC-classified security SaaS + 8-K + cluster) · Trimble 26.58 (Gainsight
  user + 8-K + cluster) — every point linked to EDGAR, the layoffs tracker, or a live job post
- **TIER 3 — MONITOR:** Chatwork 22.0 (Pendo customer-wall removal) · AppFolio 21.56 (8-K +
  cluster, VP RevOps on file) · Hush 13.84
- **The cluster rule** fires only on ≥2 *different* signal types within **90 days of each other**,
  window still live — two job posts are one hiring event, not a cluster (matches the brief exactly)
- **Churn watch live catch:** Chatwork removed from Pendo's customer wall (2024-09 → 2025-03,
  wall grew 118→127; before/after archive links). Patreon was removed too but the hard filter
  correctly disqualified it as B2C — the watch surfaces candidates, ICP discipline still governs.
- **7 accounts shown as DISQUALIFIED** with reasons (Rivian, Surf Air, Skydio, Patreon, Whatnot,
  ClarityQ, Interface) — the hard filter is visible on the board, not hidden
- **Held-back copy** left visible in the queue: of the 5 flagship-board hooks, Qualys and Chatwork
  passed grounding; Cloudflare, Trimble, and AppFolio were held for writing generic copy that
  quoted no distinctive evidence term — the gate working as designed
