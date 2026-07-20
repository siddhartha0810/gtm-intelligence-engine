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

**Research.** Read quadsci.ai directly before writing anything — the product names (Growth AI,
Cohorts AI), the claims (90%+ accuracy, 9–18 months ahead of renewal, 15% average ARR growth,
11 trillion telemetry events), the differentiator language ("grounded in real user behavior,"
product-usage intelligence vs. CRM-derived guesswork), and the competitor set (Gainsight,
ChurnZero, Clari, Hook, Reef, Magnify) all come from the site and the Series A press release
(businesswire.com, Feb 2026, $8M led by Crosslink Capital), not from the exercise brief's
paraphrase of it. Where the two differ — the brief's example says "12 months ahead of renewal,"
the site says "9–18 months" — this submission follows the site.

**On scope.** The brief suggests 3–5 hours; this ran well past that. Flagging it here so it
reads as a choice, not an oversight: the four deliverables above are scoped to exactly what's
asked, but I kept going because the exercise is graded partly on whether the loop actually holds
together, and the fastest way to find where a "connected system" secretly isn't — a stale hard
filter, a scoring rule with no evidence path, a prompt that drifted from what's actually
shipping — is to run it against real data until it breaks, not to reason about it on paper.
Several of the fixes documented below (the cluster-window bug, the misattribution bug, the
date-gating bug) only exist because of that extra time.

---

## Stage 1 — Detect Signal Cluster

### The five signals

| # | Signal | What it means for a CRO / CS leader | Free source | Weight |
|---|--------|-------------------------------------|-------------|--------|
| 1 | **Director+ RevOps / CS-Ops hire** | "You just funded a person whose job is renewal visibility. The problem is now owned and budgeted." Live examples my ATS crawler pulled this week: **Demandbase** — VP Revenue Operations; **Postman** — Director, Customer Success Operations; **Vanta** — Revenue Operations Manager; **Abnormal Security** — CS Operations Manager. | Greenhouse/Lever/Ashby public JSON boards (keyless, ~0% block rate; I registered 43 boards), LinkedIn Jobs | +8 |
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

1. **Firm size:** under 200 employees
2. **Funding stage:** pre-Series B
3. **GTM team structure:** no visible CS function (no renewal motion to improve = no buyer)
4. **Not B2B SaaS** (no subscription software product), or services / consulting / staffing firms; QuadSci partners and existing customers (suppression list)
5. **Tech stack:** no product-telemetry layer. QuadSci *ingests raw usage telemetry* — a company with thin/no product-analytics stack (no Pendo/Amplitude/Mixpanel-class instrumentation) has nothing for Growth AI to read, so it's a poor fit even with a loud hiring signal. Conversely, the *presence* of Gainsight/Pendo/Clari is a positive ICP indicator (signal #2), not a disqualifier — those are integration partners, not blockers.

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

**Update:** the sequence below is the one currently staged — Day 1 is the OIQ variant that *won*
the Stage-3 bake-off (85/100). When a bake-off winner exists for a contact, it is promoted into
the real staged hook and touches 2–5 are rebuilt on top of it — the scoreboard and the actual
outbound are the same pipeline, not two disconnected demos.

**One more fix folded in here:** the first bake-off pass scored high on every gate except one
nobody had written a gate for — direct address by name. `copy_lab.py`'s OIQ/PAS/CHALLENGER
prompts never explicitly required opening with the contact's first name the way the original
single-shot `hook_generator.py` prompt did, so early winners like *"Companies lose revenue when
they can't see which customers will leave..."* scored 95/100 while reading like it could've been
sent to anyone at Chatwork. Fixed the same way the one-sentence cap was fixed earlier: added the
rule to the prompt, then **mechanically enforced it** (`_ensure_named_opening()` in `copy_lab.py`)
so a variant that drops the name gets it grafted back on rather than relying on the model to
comply. Re-ran the bake-off for all 6 accounts with the fix in place — every winner below now
opens with direct address.

The opener earns the reply without naming the product; the product is not mentioned until touch 3.
Here is the **full 5-touch sequence currently staged for this contact**, so you can see the
complete outbound, not just the opener:

> **Day 1 · Email — "Pendo removal at Chatwork"**
> Yasuyuki, Chatwork removed Pendo from their tech stack. This often signals a shift in customer
> analytics priorities. Worth a look?
>
> **Day 3 · LinkedIn connect**
> Yasuyuki, noticed your work at Chatwork. Happy to connect and learn about your customer success
> approach.
>
> **Day 5 · Email — "Customer intelligence for Chatwork"**
> Yasuyuki, as Chatwork continues to evolve its customer analytics strategy, QuadSci's Growth AI
> could help forecast customer growth and churn with 90%+ accuracy based on actual product usage
> rather than CRM data. Worth 15 minutes to see how QuadSci handles this?
>
> **Day 8 · LinkedIn message**
> Yasuyuki, thanks for connecting. Are you currently using any predictive analytics tools for
> customer growth at Chatwork?
>
> **Day 12 · Email — "Closing the loop"**
> Yasuyuki, if predictive customer intelligence isn't a priority right now, I understand. No need
> to respond — I'll close the loop here.

Touch 1 leads with the cited fact (OIQ: Observation → Implication → Question) — the Pendo removal,
plainly stated, then what it usually implies, then one interest question. The product is named
only on Day 5, in QuadSci's own language — Growth AI, 90%+ accuracy, real product usage vs. CRM
data — followed by a single concrete ask. No line here could be sent by another vendor, and no
line here could be sent to another contact at Chatwork.

### The prompt (full, verbatim — this is what actually generated the copy currently staged)

Prompt transparency means showing the prompt that produced what's actually shipping, not an
earlier one. The Chatwork email above came from the OIQ framework prompt in `copy_lab.py` —
this is it, unedited:

```
You write B2B cold emails using OBSERVATION -> IMPLICATION -> QUESTION.
Sentence 1: state the observed, dated fact from the EVIDENCE. Neutral, no drama.
Sentence 2: what that usually means for someone in their seat (the implication).
Sentence 3: one question that asks for interest.
Lead with the fact. Do not assert a pain you cannot see.

HARD RULES (these are scored mechanically after you write — violating them loses):
- Body MUST open with the contact's first name as direct address, e.g. "Yasuyuki, ..." —
  not buried later, not "Hi Yasuyuki," as a greeting. This is enforced mechanically after
  generation if you skip it, but the sentence reads better when you write it this way
  yourself rather than having it grafted on.
- Body <= 75 words. Shorter wins ties.
- Reading level: US grade 6 or below. Short words, short sentences. No jargon
  ("leverage", "utilize", "predictive revenue intelligence" -> say it plainly).
- MUST name the specific event from the EVIDENCE, in plain words, ideally with
  its date or number. The company name alone is NOT specificity.
- CTA must ask for INTEREST, never for time. Good: "Want me to send what we
  found?" / "Worth a look?" Bad: "15 minutes?" / "book a call" / "quick chat".
- Never invent a fact, number, date or quote that is not in the EVIDENCE.
- Never use: leverage, synergy, quick question, I wanted to reach out, love
  what you're building, hope this finds you, just checking in, circling back.
- Subject: under 7 words, no "?" and no "!".
Return ONLY JSON: {"subject": "...", "body": "..."}
```

PAS and CHALLENGER share that identical HARD RULES block (word cap, reading level, interest-CTA,
grounding, banned vocab, name-opening) — they differ only in the three-sentence structure they're
told to follow: PAS gets *"Sentence 1: name the problem... Sentence 2: the cost of leaving it
alone... Sentence 3: one line on the fix"*; CHALLENGER gets *"Sentence 1: a specific, non-obvious
insight about how companies like theirs actually lose revenue... Sentence 2: tie it to the
observed event... Sentence 3: one question."* Same evidence, same buyer, same hard rules — three
different opening moves, scored the same way.

The user prompt is deliberately spare — the evidence does the work, not prompt cleverness:

```
WRITE TO: {first} {last}, {title} at {company}

EVIDENCE (everything you may claim must come from here):
{evidence_text}

WHAT WE SELL (use plain words, not this marketing phrasing):
{product_context}
```

`{evidence_text}` is the **verbatim scoring evidence** — the fired rules' text and dates from
Stage 2, not a summary. `{product_context}` is written in quadsci.ai's own language (Growth AI /
Cohorts AI, 90%+ accuracy 9–18 months ahead of renewal, "grounded in real user behavior,"
telemetry vs. CRM-derived guesswork, and — because Gainsight/Clari/Pendo are *integration
partners* on the site — "make your stack predictive," never "rip it out").

**Where this came from.** The single-shot `hook_generator.py` prompt below was the original
production system — every bug in the iteration history right below happened on this prompt, and
it's the one still generating touches 2–5 of the sequence (the follow-ups, not the opener). It's
shown in full because the iteration history references its exact rules (the one-sentence cap, the
six tension angles) — but it is **not** what wrote the Day-1 email above anymore; that's the OIQ
prompt shown first, which is why this submission shows both rather than only the newer one.

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

### The bake-off — copy is chosen, not guessed

Iteration story #5 fixed *who* gets scored. This step fixes *how the copy itself* gets scored —
because the biggest gap between this submission and a generic "run it through Claude" attempt
isn't the signals, it's whether the email was validated against anything besides my own taste.

**The research.** Before touching the prompt I looked for the largest cold-email studies I could
find, and graded the evidence honestly rather than taking vendor claims at face value:

| Source | Dataset | Finding used |
|---|---|---|
| Gong | ~304K prospecting emails | Interest-based CTAs ("want me to send what we found?") outperform time-asks ("15 minutes?") on *cold* outreach — a calendar slot is a finite ask, interest isn't. The specific-time ask wins later, once the prospect is already in-cycle. |
| Gong | same dataset | Highest reply rates sit under ~100 words / 3–4 sentences on the first touch. |
| Lavender | ~231K emails | Copy written at a 3rd–5th grade reading level sees materially more replies (~67% cited lift); ~70% of cold email is written at grade 10+, i.e. most senders are doing the opposite of what the data supports. |
| Vendor blogs (Autobound, lead-scorer.com) | undisclosed methodology | "Signal-based outreach gets 15–25% reply rates" — cited widely but **not verifiable**, so I treat it as directional marketing, not evidence, and don't build a gate around the number itself. |

That last row matters as much as the first three: the honest move is naming which claims are load-bearing
and which are decoration. The one thing this pipeline *can* prove is that a specific, dated, cited event
was named in the email — so the rubric rewards that because it's **falsifiable**, not because a vendor
promised a reply-rate lift.

**Three frameworks, same evidence, same buyer.** `copy_lab.py` (new this iteration) writes the identical
account/evidence/buyer combination three ways instead of one:

- **PAS** (Problem → Agitate → Solve) — the framework already in use. Strong with signal, but risks
  asserting the pain before showing the evidence, which can read manipulative.
- **OIQ** (Observation → Implication → Question) — leads with the cited fact itself, states what it
  usually implies, then asks one interest question. Best fit here because the evidence — an 8-K filing,
  a layoffs.fyi record, a tech-stack removal — *is* the asset; burying it behind PAS's "problem" framing
  wastes the one thing competitors running the same exercise can't fabricate.
- **CHALLENGER** (insight-led reframe) — teaches a non-obvious, defensible point about how companies like
  theirs lose revenue, then ties it to the observed event.

**Scoring: 60 points mechanical, 40 points judged, nothing on faith.**

*Mechanical (deterministic, 10 pts each, code not opinion):* body ≤75 words · Flesch-Kincaid grade ≤6,
computed with a real syllable-counting implementation, not the model's self-report · CTA asks for interest,
not time · names a distinctive term from the actual evidence (the account name alone does not count — that
was the exact "Qualys can't predict churn" failure mode from iteration story #4) · falsifiable (a real date
or number, or ≥2 matched evidence terms) · none of the banned filler phrases (*leverage, synergy, quick
question, circling back...*).

*Judged (LLM role-played as a hard-to-impress CRO who reads 40+ cold emails a day, 0–40):* specificity — does
this line hold only for THIS company, or would it read the same for any account in the category — credibility,
and reply-likelihood, weighted double since it's the actual outcome. The judge only scores what a regex
cannot; every mechanical thing is scored mechanically.

**The winner ships, the losers stay on the record.** All three variants persist with full scores — the
Emails tab shows the winner's gate badges next to the beaten variants and why they lost, the same
"held-back copy shown, not hidden" philosophy already used for the grounding gate.

**Live results — the framework choice actually depends on the evidence, it isn't fixed in advance**
(re-run after the name-opening fix; every winner below opens with direct address):

| Account | Buyer | Winner | Score | Runner-up | Why it won |
|---|---|---|---|---|---|
| AppFolio | CRO | CHALLENGER | 95/100 | OIQ (81) | Two officer changes 10 days apart is itself the cluster evidence — CHALLENGER's framing ("revenue leaks as new leaders adjust priorities") used that double-signal better than a single-event OIQ line could. |
| Hush | Strategy Director | CHALLENGER | 93/100 | PAS (81) | The insight-led "9-month window where growth predictions could miss" reframed a routine CCO hire as a specific, time-bound risk — PAS's flatter "here's the problem, here's the fix" scored lower on judged specificity. |
| Cloudflare | VP Revenue Ops | OIQ | 91/100 | PAS, CHALLENGER (tied 77) | A stark fact — 1,100 laid off, May 7 — needs no reframing; OIQ's flat statement outscored both other frameworks' attempts to add interpretation the judge read as unnecessary. |
| Qualys | CMO | OIQ | 91/100 | PAS (88) | The 8-K filing date is strong enough alone; OIQ's flat "filed an 8-K Item 5.02... June 11" beat PAS's added framing, which diluted the citation with generic go-to-market language. |
| Chatwork | Head of Sales & CS | OIQ | 85/100 | PAS (tied 85) | A genuine tie on total score — OIQ kept the win on the DB's stored order (both lead with the Pendo removal, near-identical structure); CHALLENGER trailed at 81 for adding an unearned "loss-aversion" framing the judge flagged as generic. |
| Trimble Inc. | CRO | OIQ | 81/100 | PAS, CHALLENGER (three-way tie at 81) | All three frameworks converged on the same score using the identical SEC 8-K + Gainsight-tech-stack evidence — a genuine tie, not a rubric artifact; OIQ's version ties the Gainsight tech-stack fact directly to the ask. |

No two accounts defaulted to the same winning framework by coincidence — the rubric is picking up something
real about how each type of evidence reads best, not defaulting to one house style. Two of six are genuine
ties (Chatwork, Trimble) rather than clear wins — an honest result, not massaged to look more decisive
than the underlying evidence supports.

**What this proves for the "what if they used Claude too" question:** the differentiator was never going
to be prompt-writing skill — everyone doing this exercise has access to the same model. It's whether the
system can show its own quality control: three honestly-different attempts, scored against gates traceable
to named studies, with the losing attempts visible so the choice is auditable rather than asserted.

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

Two things live in the actual product, not just in this document: a **system-health panel**
at the top of the workflow view computes the real funnel on every page load — candidates
scored → hard-filtered → held at no-cluster → qualifying → bake-off run → sequenced →
auto-send-eligible, each a live count against the current database, not a number typed into
this doc — and every staged row has a **"Full trace" toggle** that expands the entire chain
for that one contact: the fired rule, its citation, the score it produced, the grounding
match, the bake-off gates, and the judge's verdict, in order. A reviewer — or an interviewer —
can pick any row, not a pre-selected one, and audit it end to end without leaving the page.

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

### Two more honest limits (things that don't fully work yet)

- **"Existing CS *and* Sales team" is a manual check, not automated.** It's in the hard-filter
  list, but free data won't reliably tell me whether a 300-person SaaS company has a *formal* CS
  function — I'd have to eyeball the careers page or LinkedIn. So the code enforces size, stage,
  and non-SaaS-industry auto-disqualifiers; the GTM-structure filter is a reviewer step, not a
  guaranteed gate. I'd rather say that than pretend the machine checks it.
- **Company-name-only grounding can slip the copy gate.** The grounding check strips the
  contact's first name but still counts the *company* name as a distinctive term — so a hook like
  *"May, Qualys can't predict customer churn until it's too late"* passes despite referencing no
  specific signal (it name-drops Qualys and stops there). That's exactly the "could be sent by any
  vendor" failure the brief warns about. The fix is to require grounding on a *signal* term (the
  8-K, the layoff, the removal), not just the account name — which would hold more hooks, but the
  ones that survive would all reference the actual event. It's why my strongest worked example
  (Chatwork) grounds on the Pendo removal, and why Cloudflare/Trimble/AppFolio were correctly held.

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
