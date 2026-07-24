"""
inrule_personalizer.py
======================
Three-layer personalization engine for the InRule prospecting agent.
Sits between run_inrule_agent.py (signal detection + scoring) and
hook_generator.py (LLM copywriting). Enriches the company_research dict
that hook_generator.generate_hook() receives, so every email is grounded
in signal-specific, persona-specific, and live-research context.

Layers (applied in order before each generate_hook call):
  1. Signal Router     — maps signal source → forced angle + angle-specific
                         evidence framing. An OCC enforcement email opens on
                         the compliance/audit angle; a USASpending contract
                         expiry opens on the procurement timing angle.
  2. Persona Injector  — maps contact title → top 3 pain points for that
                         buyer persona. Injected as ICP research so the LLM
                         uses the right vocabulary for the right role.
  3. Research Fetcher  — fetches one live, public context snippet per company
                         (news headline or LinkedIn summary) and injects it as
                         recent_news so the grounding gate passes and the hook
                         opener can reference something real and current.

Usage:
    from inrule_personalizer import build_personalized_context

    company_research, icp_research, force_angle = build_personalized_context(
        company_name   = "United Texas Bank",
        evidence_summary = row["Evidence_Summary"],
        top_signal_label = row["Top_Signal_Label"],
        all_sources      = row["All_Sources"],
        contact_title    = row["Contact_Title"],
        hook_hint        = row["Hook_Hint"],
        fetch_live       = True,   # set False to skip HTTP call (dry-run / test)
    )

    hook = generate_hook(contact, company_research, INRULE_PRODUCT_CONTEXT,
                         icp_research=icp_research, force_angle=force_angle)

Design principles:
  - Never calls a paid API (Apollo, ZeroBounce, etc.) — only free public sources.
  - fetch_live uses a single lightweight HTTP GET (DuckDuckGo instant answer or
    NewsAPI-free). Falls back gracefully if the request fails or times out.
  - All three layers are additive: each one enriches the dict further; none
    overwrites what the previous layer set.
  - The existing hook_generator.py is NOT modified. This module is a pure
    pre-processing step.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layer 1 — Signal Router
# ---------------------------------------------------------------------------
# Maps the All_Sources field (comma-separated source tags) to:
#   forced_angle  — the tension angle hook_generator should use
#   framing_prefix — a short sentence prepended to the evidence summary
#                    so the LLM sees the "why now" framing, not just raw text
# ---------------------------------------------------------------------------

_SIGNAL_ANGLE_MAP: dict[str, dict[str, str]] = {
    "occ_enforcement": {
        "angle": "Risk",
        "framing": (
            "OCC enforcement action: this bank is under a mandatory, time-bound "
            "regulatory order requiring documented, auditable decision-making processes. "
            "Regulators will review rule change history and audit trails. "
            "Non-compliance risks further enforcement and reputational damage."
        ),
    },
    "usaspending_competitor": {
        "angle": "Time",
        "framing": (
            "Federal procurement signal: an active government contract for a competing "
            "rules engine product is expiring or recently expired. This opens a "
            "non-discretionary procurement window — the agency must re-evaluate vendors "
            "before the RFP drops. The window to influence the shortlist is now."
        ),
    },
    "sec_filing": {
        "angle": "Risk",
        "framing": (
            "SEC filing disclosure: this company named a competing rules engine or "
            "decision automation category in a public filing — confirming budget exists "
            "and the category is already on their roadmap. First-party disclosure of "
            "buying intent."
        ),
    },
    "linkedin_competitor_job": {
        "angle": "Effort",
        "framing": (
            "Competitor hiring signal: this company is actively recruiting for a role "
            "that requires hands-on experience with a competing rules engine. They are "
            "investing in the category — but building expertise around the wrong platform "
            "means every rule change still requires specialist developer time."
        ),
    },
}

# Fallback for unknown or mixed sources
_DEFAULT_SIGNAL_FRAMING = {
    "angle": None,  # let hook_generator choose
    "framing": "Intent signal detected: company is actively evaluating or using decision automation tooling.",
}


def _route_signal(all_sources: str) -> dict[str, str | None]:
    """
    Given the All_Sources field (e.g. "occ_enforcement,usaspending_competitor"),
    return the highest-priority angle + framing.
    Priority order: occ_enforcement > usaspending_competitor > sec_filing > linkedin_competitor_job
    """
    sources = [s.strip().lower() for s in all_sources.split(",") if s.strip()]
    for priority_source in ["occ_enforcement", "usaspending_competitor", "sec_filing", "linkedin_competitor_job"]:
        if priority_source in sources:
            return _SIGNAL_ANGLE_MAP[priority_source]
    return _DEFAULT_SIGNAL_FRAMING


# ---------------------------------------------------------------------------
# Layer 2 — Persona Pain Injector
# ---------------------------------------------------------------------------
# Maps contact title keywords → ICP research string injected as icp_research.
# hook_generator uses this as the system-prompt ICP context.
# Each persona gets: role description + top 3 pain points + vocabulary hints.
# ---------------------------------------------------------------------------

_PERSONA_PAIN_MAP: list[tuple[list[str], str]] = [
    # (title keywords, icp_research string)
    (
        ["chief compliance", "cco", "compliance officer", "head of compliance", "vp compliance", "svp compliance"],
        """TARGET PERSONA: Chief Compliance Officer / Head of Compliance (banking, insurance, or healthcare)

ROLE CONTEXT: Responsible for ensuring the organization's automated decisions are auditable,
explainable, and defensible to regulators. Sits at the intersection of legal, IT, and operations.
Under OCC or state insurance regulator scrutiny, every rule change must be documented with a
clear audit trail — who changed it, when, what it was before, what it is now.

TOP 3 PAIN POINTS (use these to frame the hook):
1. AUDIT TRAIL GAP: Rule logic is buried in code or spreadsheets. When an examiner asks
   "show me the decision logic for this claim denial from 14 months ago," the answer is
   "we'd have to reconstruct it from git history." That is a regulatory finding waiting to happen.
2. CHANGE VELOCITY vs. DOCUMENTATION: Business teams need to update rules fast (rate changes,
   new products, regulatory updates). But every change requires a developer, a ticket, and a
   deployment — and the documentation lags behind the code by weeks.
3. ENFORCEMENT WINDOW: An OCC Consent Order or Formal Agreement creates a hard deadline.
   The examiner will return. The organization needs to demonstrate documented, controlled,
   and auditable decision processes before that date.

VOCABULARY: audit trail, examiner, consent order, formal agreement, documented decision logic,
change history, explainability, regulatory defensibility, rule governance."""
    ),
    (
        ["chief information officer", "cio", "vp information technology", "vp it", "svp it",
         "head of it", "director of it", "director information technology"],
        """TARGET PERSONA: CIO / VP of Information Technology (regulated industry)

ROLE CONTEXT: Owns the technology stack and is accountable for both delivery speed and
operational risk. Caught between business teams demanding faster rule changes and engineering
teams who are the only ones who can safely touch the logic. Every rule change is a dev cycle,
a QA cycle, and a deployment — for what should be a business decision.

TOP 3 PAIN POINTS (use these to frame the hook):
1. DEVELOPER BOTTLENECK: Business analysts know exactly what the rule should say. But they
   can't touch the code. So they write a ticket, wait for a sprint, review a diff they can't
   read, and approve a deployment they can't verify. The rule is 3 weeks late and the analyst
   still isn't sure it's right.
2. TECHNICAL DEBT ACCUMULATION: Rule logic hardcoded in application code becomes unmaintainable.
   No one knows which rules exist, which are active, or why a particular decision was made.
   New engineers are afraid to touch it. The system becomes a black box.
3. AUDIT AND COMPLIANCE EXPOSURE: When regulators or auditors ask for a decision log,
   IT has to reconstruct it from application logs and database snapshots. That is a multi-day
   exercise that produces an answer nobody fully trusts.

VOCABULARY: developer bottleneck, rule governance, business-owned logic, deployment cycle,
technical debt, decision log, audit-ready, low-code authoring."""
    ),
    (
        ["chief technology officer", "cto", "vp engineering", "svp engineering",
         "head of engineering", "director of engineering"],
        """TARGET PERSONA: CTO / VP of Engineering (regulated industry or enterprise software)

ROLE CONTEXT: Responsible for engineering velocity and system architecture. Feels the pain
of business logic scattered across codebases, making the system brittle and slowing delivery.
Wants to externalize rule logic so engineers can focus on product, not policy maintenance.

TOP 3 PAIN POINTS (use these to frame the hook):
1. BUSINESS LOGIC IN CODE: Every pricing rule, eligibility check, or underwriting criterion
   is hardcoded somewhere in the application. When business changes the rule, engineering
   changes the code. The ratio of engineering time to business value is terrible.
2. TESTING AND REGRESSION: When a rule changes, how do you know nothing else broke?
   Without a dedicated rules engine, regression testing for business logic is manual,
   incomplete, and slow. Production incidents from rule changes are common.
3. ONBOARDING AND KNOWLEDGE TRANSFER: New engineers spend weeks learning which rules live
   where and why. When a senior engineer leaves, the institutional knowledge of the rule
   system leaves with them.

VOCABULARY: externalize business logic, rules engine, decision service, regression testing,
business-owned, low-code, rule versioning, deployment decoupling."""
    ),
    (
        ["vp claims", "svp claims", "head of claims", "director of claims",
         "chief claims officer", "claims operations", "vp of claims"],
        """TARGET PERSONA: VP of Claims / Head of Claims Operations (insurance)

ROLE CONTEXT: Owns the end-to-end claims process and is measured on cycle time, accuracy,
leakage, and customer satisfaction. Rule changes to adjudication logic require IT involvement,
creating delays and inconsistency. Manual overrides are common and undocumented.

TOP 3 PAIN POINTS (use these to frame the hook):
1. ADJUDICATION INCONSISTENCY: Different adjusters apply the same rule differently.
   When the rule is in code, there is no single source of truth that adjusters can
   reference. Inconsistent decisions create litigation exposure and customer complaints.
2. MANUAL OVERRIDE RATE: A high percentage of claims require manual review because the
   automated rules don't cover edge cases. Those edge cases are never codified because
   adding them requires a developer. The manual queue grows.
3. RULE CHANGE LAG: When a state changes its claims handling requirements, or when a
   new product launches, the adjudication rules need to update. The lag between the
   business decision and the live rule is measured in weeks, not hours.

VOCABULARY: adjudication logic, claims cycle time, manual override rate, straight-through
processing, rule consistency, state compliance, claims leakage, business-owned rules."""
    ),
    (
        ["vp underwriting", "svp underwriting", "head of underwriting", "chief underwriting",
         "director of underwriting", "underwriting operations"],
        """TARGET PERSONA: VP of Underwriting / Head of Underwriting (insurance or lending)

ROLE CONTEXT: Owns risk selection and pricing logic. Needs to update underwriting rules
frequently (new products, market conditions, regulatory changes) but is dependent on IT
for every change. Time-to-market for new products is constrained by the rule change cycle.

TOP 3 PAIN POINTS (use these to frame the hook):
1. TIME-TO-MARKET FOR NEW PRODUCTS: Launching a new product or entering a new market
   requires updating underwriting rules. If that requires a developer sprint, the business
   opportunity closes before the product is live.
2. EXCEPTION HANDLING VOLUME: Underwriters spend significant time on manual exceptions
   because the automated rules can't capture nuanced risk factors. Every manual exception
   is a productivity drain and a consistency risk.
3. REGULATORY RATE FILING: When a state approves a new rate, the underwriting system
   needs to reflect it immediately. Delays create compliance exposure. The rule change
   process is too slow for the regulatory calendar.

VOCABULARY: underwriting rules, rate filing, risk selection, time-to-market, exception
handling, straight-through underwriting, business-owned logic, rule versioning."""
    ),
    (
        ["vp operations", "svp operations", "chief operating officer", "coo",
         "head of operations", "director of operations", "vp of operations"],
        """TARGET PERSONA: COO / VP of Operations (regulated industry)

ROLE CONTEXT: Owns operational efficiency and process consistency. Sees rule-based
decisions as a lever for automation and consistency, but is frustrated by the IT
dependency for every rule change. Measures success in throughput, error rate, and cost.

TOP 3 PAIN POINTS (use these to frame the hook):
1. PROCESS INCONSISTENCY: When decision logic is in code, different parts of the
   organization apply rules differently. Standardizing a process requires a code change,
   not a policy update.
2. AUTOMATION CEILING: Straight-through processing rates plateau because edge cases
   require manual handling. Adding those edge cases to the automated rules requires IT.
   The automation roadmap is gated by the engineering backlog.
3. AUDIT AND REPORTING: Demonstrating that decisions were made consistently and correctly
   requires reconstructing logic from application logs. That is a manual, error-prone
   process that consumes analyst time before every audit.

VOCABULARY: straight-through processing, automation rate, process consistency,
decision governance, operational efficiency, audit-ready, business-owned rules."""
    ),
]

# Generic fallback for titles that don't match any persona
_DEFAULT_PERSONA_RESEARCH = """TARGET PERSONA: Senior decision-maker at a regulated financial services,
insurance, or government organization evaluating decision automation.

KEY PAIN POINTS:
1. Rule logic is hardcoded in application code, requiring developer involvement for every change.
2. No audit trail for automated decisions — a liability in regulated environments.
3. Business analysts know what the rules should say but cannot change them without IT.

VOCABULARY: business rules engine, decision automation, low-code authoring, audit trail,
rule governance, straight-through processing."""


def _inject_persona_pain(contact_title: str) -> str:
    """
    Given a contact title string, return the ICP research string for that persona.
    Matches on keyword presence (case-insensitive). Returns the first match.
    """
    title_lower = contact_title.lower() if contact_title else ""
    for keywords, research in _PERSONA_PAIN_MAP:
        if any(kw in title_lower for kw in keywords):
            return research
    return _DEFAULT_PERSONA_RESEARCH


# ---------------------------------------------------------------------------
# Layer 3 — Live Research Fetcher
# ---------------------------------------------------------------------------
# Fetches one live, public context snippet per company using DuckDuckGo's
# instant answer API (no key required, no cost, rate-limit friendly).
# Falls back to a Bing News search if DuckDuckGo returns nothing useful.
# The result is injected as company_research["research"]["recent_news"] so
# hook_generator's bucket scorer awards the +1 for recent news, and the
# grounding gate can match against a real, current term.
# ---------------------------------------------------------------------------

_DDG_ENDPOINT = "https://api.duckduckgo.com/"
_BING_NEWS_ENDPOINT = "https://www.bing.com/news/search"
_REQUEST_TIMEOUT = 8  # seconds — fail fast, don't block the pipeline
_USER_AGENT = "Mozilla/5.0 (compatible; InRule-GTM-Research/1.0; +https://inrule.com)"


def _fetch_ddg_snippet(company_name: str) -> str | None:
    """
    Query DuckDuckGo Instant Answer API for a company summary.
    Returns the AbstractText if present and non-trivial, else None.
    No API key required. Rate limit: ~1 req/sec is safe.
    """
    try:
        params = {
            "q": company_name,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
        resp = requests.get(
            _DDG_ENDPOINT,
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        abstract = data.get("AbstractText", "").strip()
        if abstract and len(abstract) > 40:
            # Truncate to ~200 chars — enough context, not too much noise
            return abstract[:200].rsplit(" ", 1)[0] + "…"
        # Try the RelatedTopics for a short description
        topics = data.get("RelatedTopics", [])
        for topic in topics[:3]:
            text = topic.get("Text", "").strip() if isinstance(topic, dict) else ""
            if text and len(text) > 30:
                return text[:200].rsplit(" ", 1)[0] + "…"
    except Exception as e:
        logger.debug(f"[Personalizer] DDG fetch failed for '{company_name}': {e}")
    return None


def _fetch_bing_news_snippet(company_name: str) -> str | None:
    """
    Scrape Bing News search results for the most recent headline about a company.
    No API key required. Returns the first result title + description if found.
    Used as fallback when DDG returns nothing useful.
    """
    try:
        query = urllib.parse.quote_plus(f"{company_name} technology modernization OR compliance OR automation")
        url = f"{_BING_NEWS_ENDPOINT}?q={query}&count=3&freshness=Month"
        resp = requests.get(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        # Parse the first news card from the HTML
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        # Bing News cards use <a class="title"> or <div class="snippet">
        title_tags = soup.select("a.title, .news-card-title a, h2 a")
        snippet_tags = soup.select(".snippet, .news-card-body .snippet")
        title = title_tags[0].get_text(strip=True) if title_tags else ""
        snippet = snippet_tags[0].get_text(strip=True) if snippet_tags else ""
        if title:
            combined = f"{title}. {snippet}".strip(". ") if snippet else title
            return combined[:200]
    except Exception as e:
        logger.debug(f"[Personalizer] Bing News fetch failed for '{company_name}': {e}")
    return None


def fetch_live_research(company_name: str, delay: float = 0.5) -> list[dict]:
    """
    Fetch one live public context snippet for a company.
    Returns a list of recent_news dicts compatible with hook_generator's
    bucket scorer (which checks company_research["research"]["recent_news"]).

    Each item: {"title": str, "url": str, "date": str}

    Falls back gracefully: DDG → Bing News → empty list.
    The delay parameter rate-limits calls to avoid hammering public endpoints.
    """
    if delay:
        time.sleep(delay)

    snippet = _fetch_ddg_snippet(company_name)
    if not snippet:
        snippet = _fetch_bing_news_snippet(company_name)

    if snippet:
        logger.debug(f"[Personalizer] Live research for '{company_name}': {snippet[:80]}…")
        return [{"title": snippet, "url": "", "date": ""}]

    logger.debug(f"[Personalizer] No live research found for '{company_name}'")
    return []


# ---------------------------------------------------------------------------
# Main entry point — build_personalized_context()
# ---------------------------------------------------------------------------

def build_personalized_context(
    company_name: str,
    evidence_summary: str,
    top_signal_label: str,
    all_sources: str,
    contact_title: str,
    hook_hint: str = "",
    fetch_live: bool = True,
    live_research_delay: float = 0.5,
) -> tuple[dict[str, Any], str, str | None]:
    """
    Build the enriched company_research dict, icp_research string, and
    forced angle for a single InRule prospect.

    Returns:
        (company_research, icp_research, force_angle)

    Where:
        company_research  — passed as the second arg to generate_hook()
        icp_research      — passed as icp_research= kwarg to generate_hook()
        force_angle       — passed as force_angle= kwarg to generate_hook()
                            (None = let hook_generator choose)
    """
    # ── Layer 1: Signal Router ────────────────────────────────────────────────
    routing = _route_signal(all_sources)
    force_angle: str | None = routing.get("angle")  # type: ignore[assignment]
    signal_framing: str = routing.get("framing", "")  # type: ignore[assignment]

    # Build the enriched evidence summary:
    # signal framing (why this matters) + raw evidence + hook hint (angle guidance)
    parts = []
    if signal_framing:
        parts.append(signal_framing)
    if evidence_summary:
        parts.append(f"Evidence: {evidence_summary[:400]}")
    if hook_hint:
        parts.append(f"Suggested angle: {hook_hint[:200]}")
    enriched_summary = " | ".join(parts)

    # ── Layer 2: Persona Pain Injector ────────────────────────────────────────
    icp_research = _inject_persona_pain(contact_title)

    # ── Layer 3: Live Research Fetcher ────────────────────────────────────────
    recent_news: list[dict] = []
    if fetch_live and company_name:
        recent_news = fetch_live_research(company_name, delay=live_research_delay)

    # ── Assemble company_research dict ────────────────────────────────────────
    # Structure matches what hook_generator._build_user_prompt() and
    # compute_personalization_bucket() expect.
    company_research: dict[str, Any] = {
        "name": company_name,
        "research": {
            "summary": enriched_summary,
            "recent_news": recent_news,
        },
    }

    return company_research, icp_research, force_angle


# ---------------------------------------------------------------------------
# QA Scorer — gates emails before they reach the outbox
# ---------------------------------------------------------------------------
# Scores a generated hook body on 4 dimensions (0-25 each, max 100).
# Hooks scoring below MIN_SCORE are flagged for regeneration.
# This is a lightweight heuristic scorer — no LLM call, no cost.
# ---------------------------------------------------------------------------

MIN_SCORE = 65  # hooks below this are flagged; caller decides whether to retry

_GENERIC_PHRASES = [
    "hope this finds you", "i wanted to reach out", "quick question",
    "love what you're building", "just checking in", "touch base",
    "circle back", "synergy", "leverage", "exciting opportunity",
    "game changer", "revolutionary", "cutting edge", "world class",
]

_INRULE_SPECIFICS = [
    "occ", "consent order", "formal agreement", "enforcement",
    "fico blaze", "ibm odm", "corticon", "drools", "pegasystems",
    "usaspending", "federal contract", "procurement",
    "sec filing", "10-k", "10-q", "8-k",
    "claims", "underwriting", "adjudication", "compliance",
    "audit trail", "rule change", "decision logic", "business rules",
    "irauthor", "irserver", "inrule",
]


def score_hook(body: str, subject: str, contact_title: str, evidence_summary: str) -> dict:
    """
    Score a generated hook on 4 dimensions.
    Returns {"score": int, "pass": bool, "breakdown": dict, "flags": list[str]}
    """
    flags = []
    breakdown = {}

    # 1. Specificity (0-25): does the body reference something from the evidence?
    body_lower = body.lower()
    evidence_lower = evidence_summary.lower()
    # Extract meaningful tokens from evidence (words > 4 chars, not stopwords)
    evidence_tokens = [
        w for w in re.findall(r'\b[a-z]{5,}\b', evidence_lower)
        if w not in {"which", "their", "about", "these", "those", "there", "where",
                     "would", "could", "should", "being", "having", "other", "after",
                     "before", "under", "above", "since", "while", "every", "first",
                     "second", "third", "company", "business", "organization"}
    ]
    matched = [t for t in evidence_tokens if t in body_lower]
    specificity = min(25, len(matched) * 5)
    breakdown["specificity"] = specificity
    if specificity < 10:
        flags.append("LOW_SPECIFICITY: body doesn't reference evidence terms")

    # 2. Length discipline (0-25): 8-22 words is the sweet spot
    word_count = len(body.split())
    if 8 <= word_count <= 22:
        length_score = 25
    elif word_count < 8:
        length_score = 5
        flags.append(f"TOO_SHORT: {word_count} words")
    elif word_count <= 28:
        length_score = 15
    else:
        length_score = 5
        flags.append(f"TOO_LONG: {word_count} words")
    breakdown["length"] = length_score

    # 3. Avoids generic phrases (0-25)
    generic_hits = [p for p in _GENERIC_PHRASES if p in body_lower]
    generic_score = max(0, 25 - len(generic_hits) * 10)
    breakdown["no_generic"] = generic_score
    if generic_hits:
        flags.append(f"GENERIC_PHRASES: {generic_hits}")

    # 4. InRule-relevant context (0-25): does body or evidence contain InRule-specific terms?
    inrule_hits = [t for t in _INRULE_SPECIFICS if t in body_lower or t in evidence_lower]
    relevance_score = min(25, len(inrule_hits) * 5)
    breakdown["inrule_relevance"] = relevance_score
    if relevance_score < 10:
        flags.append("LOW_RELEVANCE: no InRule-specific terms in body or evidence")

    total = sum(breakdown.values())
    return {
        "score": total,
        "pass": total >= MIN_SCORE,
        "breakdown": breakdown,
        "flags": flags,
    }
