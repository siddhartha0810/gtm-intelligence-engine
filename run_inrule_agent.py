"""
run_inrule_agent.py
====================
InRule GTM Prospecting Agent — the main orchestrator.

Pulls buying signals from three high-trust sources specific to InRule's
regulated-industry ICP, scores every account using the glassbox engine,
enriches decision-maker contacts for Tier 1 and Tier 2 accounts, and
exports a ready-to-act prospect list to CSV.

Pipeline:
  1. Signal Fetch
     a. SEC EDGAR — full-text search for InRule category terms and
        competitor product names in 10-K, 10-Q, 8-K filings
     b. USASpending — federal contracts for competitor products expiring
        within 12 months (procurement window signal)
     c. OCC Enforcement Actions — consent orders and formal agreements
        against national banks (mandatory compliance remediation trigger)
     d. LinkedIn Jobs — companies actively hiring for competitor tools
        (displacement signal — budget confirmed, category defined)

  2. Deduplication + Normalization
     Merge all signals by normalized company name. Each company accumulates
     a list of signals across all four sources.

  3. Evidence Building
     For each company, build an evidence dict keyed by rule condition:
       category_language       — R1 (SEC + signals text)
       displacement            — R2 (USASpending + LinkedIn jobs + signals)
       industry_fit            — R3 (SEC SIC + firmographic)
       compliance_trigger      — R4 (OCC enforcement actions)
       competitor_contract_expiring — R5 (USASpending contract expiry)
       buying_window_timing    — R6 (date-math over all signals)
       decision_maker_found    — R7 (Apollo enrichment, if --enrich-top N)

  4. Scoring
     glassbox_scorer.score_company() evaluates each rule in one of three
     states: fired / not_fired / no_evidence. Tiers are % of evaluable
     weight: TIER 1 ≥60%, TIER 2 ≥40%, TIER 3 ≥20%.

  5. Enrichment (optional, --enrich-top N)
     Apollo people search for decision-maker contacts at Tier 1 + Tier 2
     accounts. Email validation via ZeroBounce. Re-scores after enrichment
     so R7 reflects real contacts.

  6. Export
     CSV output: company, tier, score, evidence trace, contacts, hook hints.
     Ready to import into HubSpot, Apollo sequences, or Clay.

Usage:
    python run_inrule_agent.py
    python run_inrule_agent.py --no-sec
    python run_inrule_agent.py --enrich-top 15
    python run_inrule_agent.py --enrich-top 15 --output inrule_prospects.csv
    python run_inrule_agent.py --lookback-days 365 --enrich-top 20

Flags:
    --no-sec          Skip SEC EDGAR search (faster, loses R1/R3 SEC evidence)
    --no-occ          Skip OCC enforcement action scrape
    --no-usaspending  Skip USASpending competitor contract search
    --no-linkedin     Skip LinkedIn competitor job search
    --enrich-top N    Run Apollo enrichment for top N accounts (costs credits)
    --lookback-days N How far back to look for signals (default: 730 days)
    --output FILE     CSV output path (default: inrule_prospects_YYYYMMDD.csv)
    --min-tier N      Only export accounts at tier N or better (1=TIER1 only,
                      2=TIER1+TIER2, 3=all scored, default: 3)
"""

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path setup — same pattern as run_glassbox.py
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
ORACLE_DIR = BASE_DIR / "intent_engine"
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

load_dotenv(ORACLE_DIR / ".env")
load_dotenv(BASE_DIR / "lead_enrichment_engine" / ".env")

from src import config as cfg  # noqa: E402
from src.glassbox_scorer import score_company  # noqa: E402
from src.utils import get_logger  # noqa: E402

logger = get_logger(__name__)

_TODAY = datetime.utcnow().date()
_RUN_TIMESTAMP = datetime.utcnow().strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _load_inrule_config() -> tuple[dict, dict, dict]:
    icp = _load_yaml(BASE_DIR / "icp_profiles" / "inrule.yaml")
    rules_cfg = _load_yaml(BASE_DIR / "icp_profiles" / "inrule_glassbox_rules.yaml")
    signal_rules = _load_yaml(BASE_DIR / "icp_profiles" / "inrule_signal_rules.yaml")
    return icp, rules_cfg, signal_rules


# ---------------------------------------------------------------------------
# Name normalization (same as run_glassbox.py for cross-source dedup)
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    n = re.sub(r"\b(inc|incorporated|corp|corporation|llc|ltd|co|na|n\.a\.|national association|bank|the)\b\.?", "", name.lower())
    return re.sub(r"[^a-z0-9]", "", n).strip()


# ---------------------------------------------------------------------------
# Stage 1 — Signal Fetch
# ---------------------------------------------------------------------------

def fetch_edgar_signals(icp: dict, signal_rules: dict) -> list[dict]:
    """SEC EDGAR full-text search for InRule category terms + competitor names."""
    from src.signals.sec_filing_signal import SECFilingSignal

    terms = (
        list(icp.get("category_terms", []))
        + list(signal_rules.get("category_terms", []))
        + list(icp.get("competitor_products", []))
        + list(signal_rules.get("competitor_products", []))
    )
    # Deduplicate while preserving order
    seen_terms: set = set()
    unique_terms = []
    for t in terms:
        if t.lower() not in seen_terms:
            seen_terms.add(t.lower())
            unique_terms.append(t)

    print(f"[inrule_agent] EDGAR: searching {len(unique_terms)} terms...")
    hits = SECFilingSignal().fetch(queries=unique_terms, max_pages=1)

    # Filter to InRule's target SIC codes using the sic_codes field now
    # carried in each signal's extra dict (patched in sec_filing_signal.py).
    # Falls back to accepting all hits if no SIC list is configured.
    target_sics = set(
        list(icp.get("target_sic_codes", []))
        + list(signal_rules.get("target_sic_codes", []))
    )
    if target_sics:
        before = len(hits)
        hits = [
            h for h in hits
            if not h.get("sic_codes")  # no SIC data — keep (don't drop unknowns)
            or any(s in target_sics for s in h.get("sic_codes", []))
        ]
        dropped = before - len(hits)
        if dropped:
            print(f"[inrule_agent] EDGAR: SIC filter removed {dropped} out-of-ICP filings "
                  f"({before} → {len(hits)})")

    print(f"[inrule_agent] EDGAR: {len(hits)} filing signals from {len(unique_terms)} terms")
    return hits


def fetch_usaspending_signals(signal_rules: dict) -> list[dict]:
    """USASpending competitor contracts expiring within 12 months."""
    from src.signals.inrule_prospecting_signal import USASpendingCompetitorSignal

    keywords = signal_rules.get("competitor_contract_keywords", [])
    print(f"[inrule_agent] USASpending: searching {len(keywords)} competitor keywords...")
    hits = USASpendingCompetitorSignal().fetch(keywords=keywords)
    print(f"[inrule_agent] USASpending: {len(hits)} competitor contract signals")
    return hits


def fetch_occ_signals(lookback_days: int = 730) -> list[dict]:
    """OCC enforcement actions — compliance remediation triggers."""
    from src.signals.inrule_prospecting_signal import OCCEnforcementSignal

    print(f"[inrule_agent] OCC: fetching enforcement actions (lookback {lookback_days}d)...")
    hits = OCCEnforcementSignal().fetch(lookback_days=lookback_days)
    print(f"[inrule_agent] OCC: {len(hits)} enforcement action signals")
    return hits


def fetch_linkedin_signals(signal_rules: dict) -> list[dict]:
    """LinkedIn job postings for competitor tools — displacement signals."""
    from src.signals.inrule_prospecting_signal import LinkedInCompetitorJobSignal

    keywords = signal_rules.get("competitor_products", [])
    # Build job-specific search terms from competitor product names
    job_keywords = [f"{p} developer" for p in keywords[:8]]  # cap to avoid rate limits
    print(f"[inrule_agent] LinkedIn: searching {len(job_keywords)} competitor job keywords...")
    hits = LinkedInCompetitorJobSignal().fetch(keywords=job_keywords, max_pages=2)
    print(f"[inrule_agent] LinkedIn: {len(hits)} competitor job signals")
    return hits


# ---------------------------------------------------------------------------
# Stage 2 — Merge signals by company
# ---------------------------------------------------------------------------

def merge_signals_by_company(all_signals: list[dict]) -> dict[str, list[dict]]:
    """
    Group all signals by normalized company name.
    Returns {normalized_name: [signal_dicts]}.
    Also returns a reverse map {normalized_name: canonical_name} for display.
    """
    by_company: dict[str, list[dict]] = {}
    for sig in all_signals:
        company = sig.get("company_name", "").strip()
        if not company:
            continue
        key = _normalize_name(company)
        if not key:
            continue
        if key not in by_company:
            by_company[key] = []
        by_company[key].append(sig)

    print(f"[inrule_agent] merged {len(all_signals)} signals → {len(by_company)} unique companies")
    return by_company


def _canonical_name(signals: list[dict]) -> str:
    """Pick the most common company_name spelling from a list of signals."""
    from collections import Counter
    names = [s.get("company_name", "") for s in signals if s.get("company_name")]
    if not names:
        return ""
    return Counter(names).most_common(1)[0][0]


# ---------------------------------------------------------------------------
# Stage 3 — Evidence Building (InRule-specific)
# ---------------------------------------------------------------------------

def build_inrule_evidence(
    company_name: str,
    signals: list[dict],
    icp: dict,
    signal_rules: dict,
) -> dict:
    """
    Build an evidence dict for one company, keyed by rule condition.
    A missing key = no_evidence (not scored, not penalized).
    A present key with fired=False = checked, absent (scored as 0).

    Evidence conditions (matching inrule_glassbox_rules.yaml):
      category_language           — R1
      displacement                — R2
      industry_fit                — R3
      compliance_trigger          — R4
      competitor_contract_expiring — R5
      buying_window_timing        — R6
      decision_maker_found        — R7 (set by enrich_top, default no_evidence)
    """
    evidence: dict = {}

    cat_terms = (
        list(icp.get("category_terms", []))
        + list(signal_rules.get("category_terms", []))
    )
    comp_terms = (
        list(icp.get("competitor_products", []))
        + list(signal_rules.get("competitor_products", []))
    )
    target_industries = (
        list(icp.get("target_industries", []))
        + list(signal_rules.get("target_industries", []))
    )

    # Build a combined text blob for keyword matching
    signal_text = " ".join(
        (s.get("description") or "") + " " + (s.get("job_title") or "")
        for s in signals
    ).lower()

    # --- R1: category_language ---
    # Fired if any category term appears in SEC filing or signal text
    edgar_signals = [s for s in signals if s.get("source") == "sec_filing"]
    other_signals = [s for s in signals if s.get("source") != "sec_filing"]

    sec_cat_hit = next(
        (s for s in edgar_signals
         if any(t.lower() in (s.get("job_title", "") + s.get("description", "")).lower()
                for t in cat_terms)),
        None,
    )
    if sec_cat_hit:
        matched_term = next(
            (t for t in cat_terms
             if t.lower() in (sec_cat_hit.get("job_title", "") + sec_cat_hit.get("description", "")).lower()),
            "category term",
        )
        evidence["category_language"] = {
            "fired": True,
            "why": f'SEC filing uses category language ("{matched_term}") — first-party disclosure of the buying intent.',
            "source_url": sec_cat_hit.get("url", ""),
            "date": sec_cat_hit.get("posted_date", ""),
        }
    elif other_signals:
        term_hit = next((t for t in cat_terms if t.lower() in signal_text), None)
        if term_hit:
            src = next(
                (s for s in other_signals
                 if term_hit.lower() in (s.get("description", "") + s.get("job_title", "")).lower()),
                other_signals[0],
            )
            evidence["category_language"] = {
                "fired": True,
                "why": f'Uses category language ("{term_hit}") in job posting or news.',
                "source_url": src.get("url", ""),
                "date": src.get("posted_date", ""),
            }
        else:
            evidence["category_language"] = {"fired": False}
    elif edgar_signals:
        evidence["category_language"] = {"fired": False}
    # else: no signals checked at all → stays absent → no_evidence

    # --- R2: displacement ---
    # Fired if competitor product named in LinkedIn job, USASpending, or SEC filing
    linkedin_disp = [s for s in signals if s.get("source") == "linkedin_competitor_jobs"]
    usaspending_disp = [s for s in signals if s.get("source") == "usaspending_competitor"]

    comp_hit_linkedin = next(
        (s for s in linkedin_disp
         if any(t.lower() in (s.get("description", "") + s.get("job_title", "")).lower()
                for t in comp_terms)),
        None,
    )
    comp_hit_usaspending = next(
        (s for s in usaspending_disp), None
    )
    comp_hit_sec = next(
        (s for s in edgar_signals
         if any(t.lower() in (s.get("job_title", "") + s.get("description", "")).lower()
                for t in comp_terms)),
        None,
    )

    if comp_hit_linkedin:
        product = comp_hit_linkedin.get("competitor_product", "competitor product")
        evidence["displacement"] = {
            "fired": True,
            "why": f'Actively hiring for "{product}" — budget confirmed, category defined. Displacement opportunity.',
            "source_url": comp_hit_linkedin.get("url", ""),
            "date": comp_hit_linkedin.get("posted_date", ""),
        }
    elif comp_hit_usaspending:
        product = comp_hit_usaspending.get("competitor_product", "competitor product")
        months = comp_hit_usaspending.get("months_until_expiry")
        timing = f"contract expires in {months}mo" if months and months > 0 else "contract recently expired"
        evidence["displacement"] = {
            "fired": True,
            "why": f'Federal contract for "{product}" — {timing}. Active procurement window.',
            "source_url": comp_hit_usaspending.get("url", ""),
            "date": comp_hit_usaspending.get("posted_date", ""),
        }
    elif comp_hit_sec:
        matched_term = next(
            (t for t in comp_terms
             if t.lower() in (comp_hit_sec.get("job_title", "") + comp_hit_sec.get("description", "")).lower()),
            "competitor product",
        )
        evidence["displacement"] = {
            "fired": True,
            "why": f'SEC filing names competitor product "{matched_term}" — category budget exists.',
            "source_url": comp_hit_sec.get("url", ""),
            "date": comp_hit_sec.get("posted_date", ""),
        }
    elif signals:
        term_hit = next((t for t in comp_terms if t.lower() in signal_text), None)
        if term_hit:
            src = next(
                (s for s in signals
                 if term_hit.lower() in (s.get("description", "") + s.get("job_title", "")).lower()),
                signals[0],
            )
            evidence["displacement"] = {
                "fired": True,
                "why": f'Names competitor product "{term_hit}".',
                "source_url": src.get("url", ""),
                "date": src.get("posted_date", ""),
            }
        else:
            evidence["displacement"] = {"fired": False}

    # --- R3: industry_fit ---
    # Fired if company industry matches InRule's target verticals.
    # Priority order:
    #   1. OCC signal — automatic banking fit (authoritative source)
    #   2. EDGAR SIC code match — actual SEC-registered industry code (most reliable)
    #   3. Keyword match in signal text — fallback for non-EDGAR sources
    target_sics = set(
        list(icp.get("target_sic_codes", []))
        + list(signal_rules.get("target_sic_codes", []))
    )
    occ_signals = [s for s in signals if s.get("source") == "occ_enforcement"]
    edgar_signals_r3 = [s for s in signals if s.get("signal_type") == "sec_filing"]

    if occ_signals:
        # OCC only covers national banks — automatic industry fit
        evidence["industry_fit"] = {
            "fired": True,
            "why": "OCC-regulated national bank — core InRule ICP vertical (banking/financial services).",
            "source_url": occ_signals[0].get("url", ""),
            "date": occ_signals[0].get("posted_date", ""),
        }
    elif target_sics and edgar_signals_r3:
        # Check actual SIC codes carried in EDGAR signals (most reliable — SEC-registered)
        sic_match = next(
            (
                (s, sic)
                for s in edgar_signals_r3
                for sic in s.get("sic_codes", [])
                if sic in target_sics
            ),
            None,
        )
        if sic_match:
            matched_sig, matched_sic = sic_match
            evidence["industry_fit"] = {
                "fired": True,
                "why": (
                    f"SEC-registered SIC code {matched_sic} matches InRule target industry — "
                    f"authoritative industry classification from EDGAR filing."
                ),
                "source_url": matched_sig.get("url", ""),
                "date": matched_sig.get("posted_date", ""),
            }
        else:
            # EDGAR signals present but none matched target SICs — out-of-ICP
            evidence["industry_fit"] = {"fired": False}
    else:
        # No OCC, no EDGAR SIC data — fall back to keyword match in signal text
        ind_hit = next(
            (t for t in target_industries if t.lower() in signal_text),
            None,
        )
        if ind_hit:
            src = next(
                (s for s in signals
                 if ind_hit.lower() in (s.get("description", "") + s.get("job_title", "")).lower()),
                signals[0],
            )
            evidence["industry_fit"] = {
                "fired": True,
                "why": f'Industry keyword "{ind_hit}" found in signal — inferred InRule target vertical (keyword fallback, no SIC data).',
                "source_url": src.get("url", ""),
                "date": src.get("posted_date", ""),
            }
        elif signals:
            evidence["industry_fit"] = {"fired": False}

    # --- R4: compliance_trigger ---
    # Fired if OCC enforcement action found for this company
    if occ_signals:
        best = max(
            occ_signals,
            key=lambda s: s.get("is_high_value", False),
            default=occ_signals[0],
        )
        action_type = best.get("action_type", "Enforcement Action")
        evidence["compliance_trigger"] = {
            "fired": True,
            "why": (
                f'OCC {action_type} issued — mandatory, time-bound technology '
                'remediation requirement. Regulators require documented, auditable '
                'decision logic: exactly what InRule provides.'
            ),
            "source_url": best.get("url", ""),
            "date": best.get("posted_date", ""),
        }
    elif signals:
        # Check if any signal text mentions compliance/enforcement
        compliance_terms = signal_rules.get("compliance_trigger_types", [])
        comp_text_hit = next(
            (t for t in compliance_terms if t.lower() in signal_text),
            None,
        )
        if comp_text_hit:
            src = next(
                (s for s in signals
                 if comp_text_hit.lower() in (s.get("description", "") + s.get("job_title", "")).lower()),
                signals[0],
            )
            evidence["compliance_trigger"] = {
                "fired": True,
                "why": f'Compliance signal: "{comp_text_hit}" — regulatory pressure detected.',
                "source_url": src.get("url", ""),
                "date": src.get("posted_date", ""),
            }
        else:
            evidence["compliance_trigger"] = {"fired": False}

    # --- R5: competitor_contract_expiring ---
    # Fired if USASpending shows a competitor contract expiring within 12 months
    expiring = [
        s for s in usaspending_disp
        if s.get("months_until_expiry") is not None and s.get("months_until_expiry") <= 12
    ]
    if expiring:
        best = min(expiring, key=lambda s: s.get("months_until_expiry", 999))
        months = best.get("months_until_expiry", 0)
        product = best.get("competitor_product", "competitor product")
        timing = f"expires in {months} months" if months > 0 else "recently expired"
        evidence["competitor_contract_expiring"] = {
            "fired": True,
            "why": (
                f'Federal contract for "{product}" {timing}. '
                'Agency is entering a procurement window — InRule should be '
                'in the evaluation set before the RFP drops.'
            ),
            "source_url": best.get("url", ""),
            "date": best.get("contract_end_date", best.get("posted_date", "")),
        }
    elif usaspending_disp:
        evidence["competitor_contract_expiring"] = {"fired": False}

    # --- R6: buying_window_timing ---
    # Pure date-math over all signals — evaluable whenever ANY evidence exists
    if signals:
        window_days = 270
        cutoff = _TODAY - timedelta(days=window_days)
        recent_events = []
        for s in signals:
            date_str = s.get("posted_date", "")
            if not date_str:
                continue
            try:
                d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                if d >= cutoff:
                    recent_events.append({
                        "date": d,
                        "label": s.get("job_title") or s.get("description", "")[:60],
                        "url": s.get("url", ""),
                        "source": s.get("source", ""),
                    })
            except ValueError:
                continue

        n = len(recent_events)
        if n >= 2:
            most_recent = max(recent_events, key=lambda e: e["date"])
            days_ago = (_TODAY - most_recent["date"]).days
            evidence["buying_window_timing"] = {
                "fired": True,
                "why": (
                    f'{n} trigger events in the last {window_days} days '
                    f'(most recent {days_ago} days ago) — signals cluster in time, '
                    'indicating an active buying motion.'
                ),
                "source_url": most_recent["url"],
                "date": most_recent["date"].isoformat(),
                "events": [
                    {"date": e["date"].isoformat(), "label": e["label"][:80], "url": e["url"]}
                    for e in sorted(recent_events, key=lambda e: e["date"], reverse=True)[:5]
                ],
            }
        else:
            evidence["buying_window_timing"] = {"fired": False}

    # --- R7: decision_maker_found ---
    # Left absent (no_evidence) by default — set by enrich_top() after Apollo
    # enrichment runs. This is intentional: the score reflects what we know
    # before enrichment, so the delta after enrichment is visible.

    return evidence


# ---------------------------------------------------------------------------
# Stage 4 — Scoring
# ---------------------------------------------------------------------------

def score_all_companies(
    by_company: dict[str, list[dict]],
    icp: dict,
    rules: list[dict],
    signal_rules: dict,
) -> list[dict]:
    """Score every company and return a sorted list of results."""
    results = []
    for norm_key, signals in by_company.items():
        company_name = _canonical_name(signals)
        if not company_name:
            continue

        evidence = build_inrule_evidence(company_name, signals, icp, signal_rules)
        scored = score_company(rules, evidence)

        results.append({
            "company": company_name,
            "norm_key": norm_key,
            "signals": signals,
            "evidence": evidence,
            **scored,
        })

    # Sort: Tier 1 first, then by total score descending
    tier_order = {
        "TIER 1 — PRIORITY": 0,
        "TIER 2 — QUALIFIED": 1,
        "TIER 3 — MONITOR": 2,
        "TIER 4 — UNSCORED": 3,
        "TIER 4 — INSUFFICIENT EVIDENCE": 4,
    }
    results.sort(key=lambda r: (tier_order.get(r["tier"], 5), -r["total"]))

    tier_counts = {}
    for r in results:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1

    print(f"\n[inrule_agent] Scoring complete — {len(results)} companies:")
    for tier, count in sorted(tier_counts.items(), key=lambda x: tier_order.get(x[0], 5)):
        print(f"  {tier}: {count}")

    return results


# ---------------------------------------------------------------------------
# Stage 5 — Apollo Enrichment (optional)
# ---------------------------------------------------------------------------

def enrich_top_accounts(
    results: list[dict],
    n: int,
    icp: dict,
    rules: list[dict],
    signal_rules: dict,
) -> list[dict]:
    """
    Run Apollo people search for the top N scored accounts.
    Updates the decision_maker_found evidence condition and re-scores.
    """
    if not cfg.APOLLO_API_KEY:
        print("[inrule_agent] APOLLO_API_KEY not set — skipping enrichment")
        return results

    buyer_personas = signal_rules.get("buyer_personas", icp.get("buyer_personas", {}).get("all", []))
    top = [r for r in results if r["tier"] in ("TIER 1 — PRIORITY", "TIER 2 — QUALIFIED")][:n]

    print(f"\n[inrule_agent] Enriching top {len(top)} accounts via Apollo...")

    for r in top:
        company_name = r["company"]
        try:
            contacts = _apollo_people_search(company_name, buyer_personas)
            if contacts:
                best = contacts[0]
                r["evidence"]["decision_maker_found"] = {
                    "fired": True,
                    "why": (
                        f'Decision-maker found via Apollo: {best["name"]}, '
                        f'{best["title"]} at {company_name}. '
                        f'Email: {best.get("email", "not found")}.'
                    ),
                    "source_url": best.get("linkedin_url", ""),
                    "date": datetime.utcnow().strftime("%Y-%m-%d"),
                }
                r["contacts"] = contacts
                print(f"  [{company_name}] found {len(contacts)} contacts — best: {best['name']}, {best['title']}")
            else:
                r["evidence"]["decision_maker_found"] = {"fired": False}
                r["contacts"] = []
                print(f"  [{company_name}] no contacts found")

            # Re-score with updated evidence
            scored = score_company(rules, r["evidence"])
            r.update(scored)

            time.sleep(1.0)  # Apollo rate limit courtesy

        except Exception as e:
            logger.error(f"Apollo enrichment error for {company_name}: {e}")
            r["contacts"] = []

    # Re-sort after re-scoring
    tier_order = {
        "TIER 1 — PRIORITY": 0, "TIER 2 — QUALIFIED": 1,
        "TIER 3 — MONITOR": 2, "TIER 4 — UNSCORED": 3,
        "TIER 4 — INSUFFICIENT EVIDENCE": 4,
    }
    results.sort(key=lambda r: (tier_order.get(r["tier"], 5), -r["total"]))
    return results


def _apollo_people_search(company_name: str, personas: list[str]) -> list[dict]:
    """
    Thin wrapper around the shared apollo_enrichment._apollo_search.
    Delegates entirely to the shared client so auth, retry handling, and
    endpoint URL stay in one place and don't drift.
    Returns a list of contact dicts with name, title, email, linkedin_url.
    """
    from src.apollo_enrichment import _apollo_search, _apollo_call  # noqa: F401

    if not cfg.APOLLO_API_KEY:
        return []

    # _apollo_search returns (contacts_list, pass_used)
    # contacts_list items are already parsed dicts from apollo_enrichment
    raw_contacts, _ = _apollo_search(
        company_name=company_name,
        api_key=cfg.APOLLO_API_KEY,
        max_per=5,
        role_filters=personas[:10] if personas else None,
    )

    # Normalise to the shape the rest of this file expects
    results = []
    for c in raw_contacts:
        results.append({
            "name": f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(),
            "title": c.get("title", ""),
            "email": c.get("email", ""),
            "linkedin_url": c.get("linkedin_url", ""),
            "company": company_name,
        })
    return results


# ---------------------------------------------------------------------------
# Stage 6 — Export
# ---------------------------------------------------------------------------

def export_csv(
    results: list[dict],
    output_path: str,
    min_tier: int = 3,
) -> str:
    """
    Export scored prospects to CSV.
    Columns: Company, Tier, Score, Fired/Of, Evidence Summary,
             Top Signal, Top Signal URL, Contact Name, Contact Title,
             Contact Email, Contact LinkedIn, Hook Hint
    """
    tier_filter = {
        1: {"TIER 1 — PRIORITY"},
        2: {"TIER 1 — PRIORITY", "TIER 2 — QUALIFIED"},
        3: {"TIER 1 — PRIORITY", "TIER 2 — QUALIFIED", "TIER 3 — MONITOR"},
    }.get(min_tier, set())

    filtered = [
        r for r in results
        if not tier_filter or r["tier"] in tier_filter
    ]

    if not filtered:
        print(f"[inrule_agent] No results at min_tier={min_tier} to export")
        return output_path

    fieldnames = [
        "Company",
        "Tier",
        "Score",
        "Fired_Of",
        "Evidence_Summary",
        "Top_Signal_Label",
        "Top_Signal_URL",
        "Contact_Name",
        "Contact_Title",
        "Contact_Email",
        "Contact_LinkedIn",
        "Hook_Hint",
        "All_Sources",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in filtered:
            # Build evidence summary from fired rules
            fired_rules = [t for t in r.get("trace", []) if t["state"] == "fired"]
            evidence_parts = [t.get("why", t["condition"]) for t in fired_rules]
            evidence_summary = " | ".join(evidence_parts[:3])

            # Top signal — highest-weight fired rule
            top_signal = fired_rules[0] if fired_rules else {}
            top_label = top_signal.get("why", "")[:100] if top_signal else ""
            top_url = top_signal.get("source_url", "") if top_signal else ""

            # Contact info (first contact if enriched)
            contacts = r.get("contacts", [])
            contact = contacts[0] if contacts else {}

            # Hook hint — what angle to lead with based on top evidence
            hook_hint = _build_hook_hint(r)

            # All signal sources
            sources = list({s.get("source", "") for s in r.get("signals", []) if s.get("source")})

            writer.writerow({
                "Company": r["company"],
                "Tier": r["tier"],
                "Score": f"{r['total']}/{r['evaluable_weight']}",
                "Fired_Of": f"{r['fired']}/{r['of']}",
                "Evidence_Summary": evidence_summary[:300],
                "Top_Signal_Label": top_label,
                "Top_Signal_URL": top_url,
                "Contact_Name": contact.get("name", ""),
                "Contact_Title": contact.get("title", ""),
                "Contact_Email": contact.get("email", ""),
                "Contact_LinkedIn": contact.get("linkedin_url", ""),
                "Hook_Hint": hook_hint[:200],
                "All_Sources": ", ".join(sources),
            })

    print(f"\n[inrule_agent] Exported {len(filtered)} prospects → {output_path}")
    return output_path


def _build_hook_hint(result: dict) -> str:
    """
    Generate a one-line hook hint based on the strongest evidence.
    This is the 'why now' and 'why InRule' angle for the outreach.
    """
    trace = result.get("trace", [])
    fired = {t["condition"]: t for t in trace if t["state"] == "fired"}

    if "compliance_trigger" in fired:
        return (
            "Lead with compliance: OCC enforcement action creates a mandatory "
            "window for documented, auditable decision logic. InRule's irAuthor "
            "is purpose-built for this — rule changes are traceable, auditable, "
            "and deployable without a dev cycle."
        )
    if "competitor_contract_expiring" in fired:
        return (
            "Lead with procurement timing: their competitor contract is expiring. "
            "Position InRule before the RFP drops — 'we'd love to show you what "
            "a modern rules platform looks like before you renew.'"
        )
    if "displacement" in fired:
        ev = fired["displacement"]
        why = ev.get("why", "")
        if "FICO Blaze" in why or "Blaze Advisor" in why:
            return (
                "Lead with FICO Blaze displacement: 'Most teams we talk to on "
                "Blaze tell us the same three things...' — price, IT dependency, "
                "and the upgrade cycle. Ask which one is the biggest pain."
            )
        if "Corticon" in why:
            return (
                "Lead with Corticon displacement: they're already spending on "
                "rules automation. Position InRule's low-code authoring and "
                "cloud-native deployment as the upgrade path."
            )
        return (
            "Lead with displacement: they're already in the category. "
            "Ask what's working and what isn't with their current tool."
        )
    if "category_language" in fired:
        return (
            "Lead with category language from their own filing: they've already "
            "described the problem InRule solves. Mirror their language back — "
            "'You mentioned decision automation in your 10-K...'"
        )
    return "Research account further before outreach — signals are early-stage."


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="InRule GTM Prospecting Agent"
    )
    parser.add_argument("--no-sec", action="store_true",
                        help="Skip SEC EDGAR search")
    parser.add_argument("--no-occ", action="store_true",
                        help="Skip OCC enforcement action scrape")
    parser.add_argument("--no-usaspending", action="store_true",
                        help="Skip USASpending competitor contract search")
    parser.add_argument("--no-linkedin", action="store_true",
                        help="Skip LinkedIn competitor job search")
    parser.add_argument("--enrich-top", type=int, default=0,
                        help="Run Apollo enrichment for top N accounts (costs credits)")
    parser.add_argument("--lookback-days", type=int, default=730,
                        help="How far back to look for signals (default: 730 days)")
    parser.add_argument("--output", type=str, default="",
                        help="CSV output path (default: inrule_prospects_YYYYMMDD.csv)")
    parser.add_argument("--min-tier", type=int, default=3,
                        help="Only export accounts at this tier or better (1/2/3, default: 3)")
    args = parser.parse_args()

    output_path = args.output or f"inrule_prospects_{_RUN_TIMESTAMP}.csv"

    print(f"\n{'='*60}")
    print(f"  InRule GTM Prospecting Agent — {_TODAY}")
    print(f"{'='*60}\n")

    # Load config
    icp, rules_cfg, signal_rules = _load_inrule_config()
    rules = rules_cfg.get("rules", [])
    if not rules:
        print("[inrule_agent] ERROR: No rules found in inrule_glassbox_rules.yaml")
        sys.exit(1)

    print(f"[inrule_agent] Loaded {len(rules)} scoring rules from inrule_glassbox_rules.yaml")
    print(f"[inrule_agent] ICP: {len(icp.get('category_terms', []))} category terms, "
          f"{len(icp.get('competitor_products', []))} competitor products, "
          f"{len(icp.get('target_industries', []))} target industries\n")

    # Stage 1 — Fetch signals
    all_signals: list[dict] = []

    if not args.no_sec:
        print("[inrule_agent] --- Stage 1a: SEC EDGAR ---")
        all_signals.extend(fetch_edgar_signals(icp, signal_rules))

    if not args.no_usaspending:
        print("\n[inrule_agent] --- Stage 1b: USASpending ---")
        all_signals.extend(fetch_usaspending_signals(signal_rules))

    if not args.no_occ:
        print("\n[inrule_agent] --- Stage 1c: OCC Enforcement Actions ---")
        all_signals.extend(fetch_occ_signals(lookback_days=args.lookback_days))

    if not args.no_linkedin:
        print("\n[inrule_agent] --- Stage 1d: LinkedIn Competitor Jobs ---")
        all_signals.extend(fetch_linkedin_signals(signal_rules))

    if not all_signals:
        print("\n[inrule_agent] No signals fetched — check your flags and network connectivity")
        sys.exit(0)

    print(f"\n[inrule_agent] Total signals fetched: {len(all_signals)}")

    # Staffing / SI-firm filter — must run before merge, same as every other campaign
    from src.staffing_filter import filter_signals as _filter_staffing
    all_signals, staffing_removed = _filter_staffing(all_signals)
    if staffing_removed:
        print(f"[inrule_agent] Staffing filter: removed {staffing_removed} signals "
              f"from SI/staffing firms ({len(all_signals)} remain)")

    # Stage 2 — Merge by company
    print("\n[inrule_agent] --- Stage 2: Merging signals by company ---")
    by_company = merge_signals_by_company(all_signals)

    # Stage 3 + 4 — Evidence building + Scoring
    print("\n[inrule_agent] --- Stage 3+4: Building evidence + Scoring ---")
    results = score_all_companies(by_company, icp, rules, signal_rules)

    # Stage 5 — Enrichment (optional)
    if args.enrich_top > 0:
        print(f"\n[inrule_agent] --- Stage 5: Apollo Enrichment (top {args.enrich_top}) ---")
        results = enrich_top_accounts(results, args.enrich_top, icp, rules, signal_rules)

    # Stage 6 — Export
    print("\n[inrule_agent] --- Stage 6: Exporting CSV ---")
    export_csv(results, output_path, min_tier=args.min_tier)

    # Print top 10 summary
    print(f"\n{'='*60}")
    print("  TOP ACCOUNTS")
    print(f"{'='*60}")
    for r in results[:10]:
        contacts = r.get("contacts", [])
        contact_str = (
            f" | Contact: {contacts[0]['name']}, {contacts[0]['title']}"
            if contacts else ""
        )
        print(
            f"  {r['tier'][:6]}  {r['company'][:40]:<40}  "
            f"{r['total']:>5.1f}/{r['evaluable_weight']:.1f}  "
            f"({r['fired']}/{r['of']} rules fired)"
            f"{contact_str}"
        )

    print(f"\n[inrule_agent] Done. Output: {output_path}\n")


if __name__ == "__main__":
    main()
