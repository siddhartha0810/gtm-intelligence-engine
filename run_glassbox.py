"""
run_glassbox.py
================
Generalized glassbox scoring orchestrator — the repeatable process InRule's
Decision Intelligence tab never had (that was hand-run once; see
glassbox_scorer.py's module docstring for the full context).

For a given campaign (account), this:
  1. Loads icp_profiles/<slug>.yaml + icp_profiles/<slug>_glassbox_rules.yaml
     + icp_profiles/<slug>_signal_rules.yaml (term lists for the "signals"
     evidence source — reuses the same file the campaign's own keywords/news
     queries were built from, so nothing drifts).
  2. Gathers candidate companies already surfaced by this campaign's scan
     (oracle_signals joined on scan_run_id = campaign.last_run_id).
  3. Optionally runs a generalized SEC EDGAR search (sec_filing_signal.py's
     `queries` override) using the ICP's category_terms/competitor_products —
     skip with --no-sec for private-company-heavy ICPs where it won't help.
  4. Scores every candidate via glassbox_scorer.score_company() — each rule
     evaluated fired / not_fired / no_evidence, never zeroed out for a
     missing evidence source.
  5. Upserts account_prospects.
  6. With --enrich-top N: runs Apollo enrichment (apollo_enrichment.py,
     already generic) for the top N scored companies, then re-scores just
     those so R7 (decision_maker_found) reflects real contacts instead of
     defaulting to no_evidence.

Does NOT generate outreach hooks — that's a deliberate separate step via the
existing Campaign Builder / /api/campaign/generate-hooks, same
already-generic pipeline, once you've reviewed the scored list.

Usage:
    python run_glassbox.py --campaign-id 4
    python run_glassbox.py --campaign-id 4 --no-sec
    python run_glassbox.py --campaign-id 4 --enrich-top 10
"""

import argparse
import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
ORACLE_DIR = BASE_DIR / "oracle_intent_engine"
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

# config.py's own load_dotenv() only searches upward from CWD — when this
# script runs from the repo root (BASE_DIR), oracle_intent_engine/.env is a
# SUBdirectory, never found by that upward search. DB access silently "works"
# anyway because its defaults happen to match the local Postgres setup, which
# masked this for a while. APOLLO_API_KEY has no such fallback: on this
# machine it's only set in lead_enrichment_engine/.env, not
# oracle_intent_engine/.env — the running unified_app.py process only "has"
# it because it imports from both engines at startup and dotenv mutates the
# whole process's os.environ, not a per-module namespace. Load both here so
# a standalone run of this script matches what the real app sees.
load_dotenv(ORACLE_DIR / ".env")
load_dotenv(BASE_DIR / "lead_enrichment_engine" / ".env")

from src import database as db  # noqa: E402
from src import config as oracle_cfg  # noqa: E402
from src.glassbox_scorer import score_company  # noqa: E402


def _load_yaml(rel_path: str) -> dict:
    path = BASE_DIR / rel_path
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _slug_files(slug: str) -> tuple[dict, dict, dict]:
    icp = _load_yaml(f"icp_profiles/{slug}.yaml")
    rules_cfg = _load_yaml(f"icp_profiles/{slug}_glassbox_rules.yaml")
    signal_rules = _load_yaml(f"icp_profiles/{slug}_signal_rules.yaml")
    return icp, rules_cfg, signal_rules


def _normalize_name(name: str) -> str:
    n = re.sub(r"\b(inc|incorporated|corp|corporation|llc|ltd|co)\b\.?", "", name.lower())
    return re.sub(r"[^a-z0-9]", "", n).strip()


def _terms_for_signal_type(signal_rules: dict, rule_type: str) -> list[str]:
    for rule in signal_rules.get("signal_rules", []):
        if rule.get("type") == rule_type:
            return rule.get("detect", [])
    return []


def get_candidate_companies(campaign: dict, icp: dict) -> list:
    """Scoped by keyword provenance (oracle_signals.oracle_product — the
    exact matched campaign keyword, set by phase_classifier.detect_campaign_product()),
    not by campaign.last_run_id. scan_runs/oracle_signals have no campaign_id
    column at all, so filtering by last_run_id alone means a second scan
    silently REPLACES the candidate pool instead of widening it — every
    company found by an earlier scan would drop out the moment a newer scan
    updates last_run_id. Keyword-scoped candidates accumulate across any
    number of scans automatically, with no schema change needed.

    Also reapplies the same non-destructive filtering the live scan pipeline
    applies at persist time (pipeline.py:677-689), for pre-existing rows from
    before a scraper-bug fix (e.g. numbered-digest name mangling) that
    shouldn't silently re-enter scoring. Never deletes from `companies` —
    filters the query only, per this project's DB rules."""
    from rapidfuzz import fuzz as _fuzz

    keywords = campaign.get("keywords") or []
    sources = campaign.get("sources") or []
    if not keywords:
        return []
    exclude_companies = campaign.get("exclude_companies") or []
    exclude_companies = list(exclude_companies) + [icp.get("meta", {}).get("company", "")]
    with db.db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT DISTINCT c.id, c.name, c.domain, c.industry
            FROM oracle_signals s JOIN companies c ON c.id = s.company_id
            WHERE s.oracle_product = ANY(%s) AND s.source = ANY(%s)
        """, (keywords, sources))
        rows = [dict(r) for r in cur.fetchall()]

    candidates = []
    for r in rows:
        if re.match(r"^\d+\.\s", r["name"]):
            continue  # numbered-digest artifact, e.g. "1. Pendo" — pre-dates the news_signal.py fix
        if any(_fuzz.token_sort_ratio(r["name"], excl) >= 85 for excl in exclude_companies if excl):
            continue
        candidates.append(r)
    return candidates


def fetch_sec_hits(icp: dict) -> dict:
    """One EDGAR search covering category_terms + competitor_products,
    returning {normalized_company_name: [hit dicts]}. Uses
    sec_filing_signal.py's generalized `queries` override (this session's
    change) instead of the hardcoded Oracle term list."""
    from src.signals.sec_filing_signal import SECFilingSignal

    terms = list(icp.get("category_terms", [])) + list(icp.get("competitor_products", []))
    if not terms:
        return {}
    print(f"[run_glassbox] searching SEC EDGAR for {len(terms)} terms...")
    hits = SECFilingSignal().fetch(queries=terms, max_pages=1)
    by_name: dict = {}
    for h in hits:
        key = _normalize_name(h.get("company_name", ""))
        if key:
            by_name.setdefault(key, []).append(h)
    print(f"[run_glassbox] EDGAR returned {len(hits)} filings across {len(by_name)} companies")
    return by_name


def fetch_corroboration(candidates: list, signal_rules: dict) -> dict:
    """Targeted, per-company search: does THIS specific company (already
    surfaced by a hiring/tech-stack signal) have a SECOND, different-typed
    signal — funding, leadership change, NRR/churn commentary, or competitor
    displacement? A hiring posting alone doesn't distinguish a real prospect
    from any company that happens to be hiring a RevOps manager for
    unrelated reasons; this is what actually tests for that.

    Returns {company_name: [{"type", "term", "title", "url", "posted_date"}]}."""
    from src.signals.news_signal import NewsSignal
    from src.phase_classifier import detect_campaign_product

    trigger_types = ["funding_event", "leadership_change", "nrr_commentary", "competitor_displacement"]
    term_to_type = {
        t.lower(): rtype for rtype in trigger_types for t in _terms_for_signal_type(signal_rules, rtype)
    }
    all_terms = list(term_to_type.keys())
    if not all_terms:
        return {}

    ns = NewsSignal()
    results: dict = {}
    print(f"[run_glassbox] searching targeted corroboration for {len(candidates)} companies...")
    for i, c in enumerate(candidates, 1):
        try:
            articles = ns.search_company_mentions(c["name"])
        except Exception as e:
            print(f"  [{c['name']}] search failed: {e}")
            continue
        hits = []
        for a in articles:
            matched_term, _ = detect_campaign_product(a["title"], a.get("description", ""), all_terms)
            if matched_term:
                hits.append({
                    "type": term_to_type[matched_term.lower()], "term": matched_term,
                    "title": a["title"], "url": a["url"], "posted_date": a["posted_date"],
                })
        if hits:
            results[c["name"]] = hits
            print(f"  [{c['name']}] {len(hits)} corroborating hit(s): {[h['type'] for h in hits]}")
        if i % 10 == 0:
            print(f"  ...{i}/{len(candidates)} companies checked")
    print(f"[run_glassbox] corroboration found for {len(results)}/{len(candidates)} companies")
    return results


def build_evidence(company: dict, icp: dict, signal_rules: dict,
                    sec_hits_by_name: dict, signals: list, contacts: list,
                    corroboration: list | None = None) -> dict:
    """One evidence dict per company, keyed by rule condition. A missing key
    means no_evidence — the caller (glassbox_scorer) treats that as excluded
    from scoring, not a failure.

    corroboration: hits from a targeted per-company news search (see
    fetch_corroboration()), each {"type", "term", "title", "url", "posted_date"}
    — distinct from `signals` (the campaign's own broad scan) because it's
    specifically "does THIS company have a SECOND, different-typed signal,"
    not just another hit on the same broad keyword search."""
    evidence: dict = {}
    corroboration = corroboration or []
    name_key = _normalize_name(company["name"])
    sec_hits = sec_hits_by_name.get(name_key, [])
    signal_texts = " ".join((s.get("evidence") or "") + " " + (s.get("job_title") or "") for s in signals).lower()

    def _corrob_hit(rule_type: str) -> dict | None:
        return next((h for h in corroboration if h["type"] == rule_type), None)

    # R1 category_language — SEC first, then signals text, then corroboration
    # (an nrr_commentary hit — e.g. "NRR softness" — IS category language for
    # this ICP, arguably more directly than the marketing terms in category_terms).
    cat_terms = icp.get("category_terms", [])
    sec_cat_hit = next((h for h in sec_hits if any(t.lower() in h.get("job_title", "").lower() for t in cat_terms)), None)
    nrr_hit = _corrob_hit("nrr_commentary")
    if sec_cat_hit:
        evidence["category_language"] = {
            "fired": True, "why": f'Uses category language ("{sec_cat_hit.get("job_title", "")}") in SEC filings.',
            "source_url": sec_cat_hit.get("url", ""), "date": sec_cat_hit.get("posted_date", ""),
        }
    elif signals and (term_hit := next((t for t in cat_terms if t.lower() in signal_texts), None)):
        src = next((s for s in signals if term_hit.lower() in (s.get("evidence") or "").lower()), signals[0])
        evidence["category_language"] = {
            "fired": True, "why": f'Uses category language ("{term_hit}").',
            "source_url": src.get("url", ""), "date": str(src.get("detected_at", "")),
        }
    elif nrr_hit:
        evidence["category_language"] = {
            "fired": True, "why": f'Public commentary uses category language ("{nrr_hit["term"]}") — {nrr_hit["title"]}',
            "source_url": nrr_hit["url"], "date": nrr_hit["posted_date"],
        }
    elif signals or corroboration:
        evidence["category_language"] = {"fired": False}
    # else: nothing checked at all -> stays absent -> no_evidence

    # R2 displacement — signals text, else targeted corroboration search
    comp_terms = _terms_for_signal_type(signal_rules, "competitor_displacement") or icp.get("competitor_products", [])
    disp_hit = _corrob_hit("competitor_displacement")
    if signals and (term_hit := next((t for t in comp_terms if t.lower() in signal_texts), None)):
        src = next((s for s in signals if term_hit.lower() in (s.get("evidence") or "").lower()), signals[0])
        evidence["displacement"] = {
            "fired": True, "why": f'Names a competitor product/behavior ("{term_hit}").',
            "source_url": src.get("url", ""), "date": str(src.get("detected_at", "")),
        }
    elif disp_hit:
        evidence["displacement"] = {
            "fired": True, "why": f'Public evidence of displacement ("{disp_hit["term"]}") — {disp_hit["title"]}',
            "source_url": disp_hit["url"], "date": disp_hit["posted_date"],
        }
    elif signals or corroboration:
        evidence["displacement"] = {"fired": False}

    # R3 industry_fit / technographic fit — SEC SIC not implemented here (no
    # per-company CIK lookup yet). Two evaluable fallbacks, checked in order:
    #   1. companies.industry field vs target_industries (firmographic)
    #   2. tech_stack_tell terms in signal text (e.g. "Gainsight Administrator"
    #      job posting) — quadsci_signal_rules.yaml's own description for this
    #      rule type is literally "confirms the technographic fit", so this is
    #      the correct evidence source for it, not R2/displacement.
    target_industries = icp.get("target_industries", [])
    if company.get("industry"):
        match = next((t for t in target_industries if t.lower() in company["industry"].lower()), None)
        evidence["industry_fit"] = (
            {"fired": True, "why": f'Industry match: {company["industry"]}.', "source_url": "", "date": ""}
            if match else {"fired": False}
        )
    elif signals:
        tech_terms = _terms_for_signal_type(signal_rules, "tech_stack_tell")
        term_hit = next((t for t in tech_terms if t.lower() in signal_texts), None)
        if term_hit:
            src = next((s for s in signals if term_hit.lower() in (s.get("evidence") or "").lower()
                        or term_hit.lower() in (s.get("job_title") or "").lower()), signals[0])
            evidence["industry_fit"] = {
                "fired": True, "why": f'Technographic fit — already uses/hires for "{term_hit}".',
                "source_url": src.get("url", ""), "date": str(src.get("detected_at", "")),
            }
        else:
            evidence["industry_fit"] = {"fired": False}
    # else: no industry field and no signals at all -> stays absent -> no_evidence

    # R4 recent_trigger_event — SEC first, then signals, then corroboration (funding_event terms)
    trigger_terms = _terms_for_signal_type(signal_rules, "funding_event")
    fund_hit = _corrob_hit("funding_event")
    if signals and (term_hit := next((t for t in trigger_terms if t.lower() in signal_texts), None)):
        src = next((s for s in signals if term_hit.lower() in (s.get("evidence") or "").lower()), signals[0])
        evidence["recent_trigger_event"] = {
            "fired": True, "why": f'Recent trigger event ("{term_hit}").',
            "source_url": src.get("url", ""), "date": str(src.get("detected_at", "")),
        }
    elif fund_hit:
        evidence["recent_trigger_event"] = {
            "fired": True, "why": f'Recent trigger event ("{fund_hit["term"]}") — {fund_hit["title"]}',
            "source_url": fund_hit["url"], "date": fund_hit["posted_date"],
        }
    elif signals or corroboration:
        evidence["recent_trigger_event"] = {"fired": False}

    # R5 leadership_change — signals, else corroboration (leadership_change terms)
    lead_terms = _terms_for_signal_type(signal_rules, "leadership_change")
    lead_hit = _corrob_hit("leadership_change")
    if signals and (term_hit := next((t for t in lead_terms if t.lower() in signal_texts), None)):
        src = next((s for s in signals if term_hit.lower() in (s.get("evidence") or "").lower()), signals[0])
        evidence["leadership_change"] = {
            "fired": True, "why": f'Leadership change signal ("{term_hit}").',
            "source_url": src.get("url", ""), "date": str(src.get("detected_at", "")),
        }
    elif lead_hit:
        evidence["leadership_change"] = {
            "fired": True, "why": f'Leadership change signal ("{lead_hit["term"]}") — {lead_hit["title"]}',
            "source_url": lead_hit["url"], "date": lead_hit["posted_date"],
        }
    elif signals or corroboration:
        evidence["leadership_change"] = {"fired": False}

    # R6 buying_window_timing — pure date-math over signals + corroboration hits,
    # evaluable whenever ANY evidence exists (this is what actually detects
    # "hiring signal + a second, different-typed signal close in time")
    all_dates = [s["detected_at"] for s in signals if s.get("detected_at")]
    all_dates += [h["posted_date"] for h in corroboration if h.get("posted_date")]
    if all_dates:
        from datetime import datetime
        parsed = []
        for d in all_dates:
            if hasattr(d, "year"):
                parsed.append(d)
            else:
                try:
                    from email.utils import parsedate_to_datetime
                    parsed.append(parsedate_to_datetime(str(d)).replace(tzinfo=None))
                except Exception:
                    continue
        if parsed:
            parsed.sort(reverse=True)
            most_recent = parsed[0]
            days_ago = (datetime.now() - most_recent).days
            evidence["buying_window_timing"] = {
                "fired": len(parsed) >= 2 and days_ago <= 270,
                "why": f"{len(parsed)} trigger events, most recent {days_ago} days ago.",
                "source_url": "", "date": str(most_recent),
            }

    # R7 decision_maker_found — existing company_contacts only (no_evidence
    # until enrichment has actually been attempted for this company — see
    # --enrich-top, which re-scores after running Apollo).
    if contacts:
        top = contacts[0]
        evidence["decision_maker_found"] = {
            "fired": True, "why": f'Decision-maker on file: {top.get("full_name", "")} ({top.get("title", "")}).',
            "source_url": top.get("linkedin_url", "") or "", "date": "",
        }

    return evidence


def score_campaign(campaign_id: int, use_sec: bool = True) -> list:
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        raise SystemExit(f"No campaign with id={campaign_id}")

    # Infer slug from campaign name convention "<Company> ICP" — matches how
    # seed_quadsci_campaign.py names campaigns.
    slug = campaign["name"].lower().split(" icp")[0].replace(" ", "").strip() or "unknown"
    icp, rules_cfg, signal_rules = _slug_files(slug)
    rules = rules_cfg.get("rules", [])
    if not rules:
        raise SystemExit(f"No rules found at icp_profiles/{slug}_glassbox_rules.yaml")

    candidates = get_candidate_companies(campaign, icp)
    print(f"[run_glassbox] {len(candidates)} candidate companies from campaign '{campaign['name']}'")
    if not candidates:
        print("[run_glassbox] no companies yet — run a scan for this campaign first")
        return []

    sec_hits_by_name = fetch_sec_hits(icp) if use_sec else {}
    corroboration_by_name = fetch_corroboration(candidates, signal_rules)

    results = []
    for company in candidates:
        signals = [dict(s) for s in db.get_signals_for_company(company["id"])]
        contacts = [dict(c) for c in db.get_contacts_for_company(company["id"])]
        corroboration = corroboration_by_name.get(company["name"], [])
        evidence = build_evidence(company, icp, signal_rules, sec_hits_by_name, signals, contacts, corroboration)
        scored = score_company(rules, evidence)
        db.upsert_account_prospect(
            campaign_id=campaign_id, company_id=company["id"],
            total_score=scored["total"], evaluable_weight=scored["evaluable_weight"],
            tier=scored["tier"], trace=scored["trace"],
        )
        results.append({"company": company["name"], **scored})
        print(f"  {company['name']}: {scored['total']}/{scored['evaluable_weight']} "
              f"({scored['fired']}/{scored['of']} fired) — {scored['tier']}")

    return results


def enrich_top(campaign_id: int, n: int, icp_slug: str) -> None:
    from src.apollo_enrichment import enrich_companies

    prospects = db.get_account_prospects(campaign_id, limit=n)
    company_ids = [p["company_id"] for p in prospects]
    if not company_ids:
        print("[run_glassbox] no scored prospects to enrich")
        return
    if not oracle_cfg.APOLLO_API_KEY:
        print("[run_glassbox] APOLLO_API_KEY not set — skipping enrichment")
        return

    print(f"[run_glassbox] enriching top {len(company_ids)} companies via Apollo...")
    enrich_companies(
        apollo_key=oracle_cfg.APOLLO_API_KEY,
        zerobounce_key=oracle_cfg.ZEROBOUNCE_API_KEY,
        company_ids=company_ids,
        limit=len(company_ids),
    )

    # Re-score just the enriched companies so R7 reflects real contacts.
    # Re-fetches corroboration for just these N companies (cheap — that's the
    # whole point of --enrich-top being scoped) rather than reusing what
    # score_campaign() found, since this function can also run standalone.
    # Earlier version omitted this entirely, silently discarding every
    # funding/leadership/displacement hit found for these companies and
    # dropping them out of TIER 3 on "re-score" — the opposite of the intent.
    icp, rules_cfg, signal_rules = _slug_files(icp_slug)
    rules = rules_cfg.get("rules", [])
    real_companies = [db.get_company_by_id(p["company_id"]) for p in prospects]
    real_companies = [dict(c) for c in real_companies if c]
    corroboration = fetch_corroboration(real_companies, signal_rules)
    for company in real_companies:
        signals = [dict(s) for s in db.get_signals_for_company(company["id"])]
        contacts = [dict(c) for c in db.get_contacts_for_company(company["id"])]
        sec_hits_by_name = {}  # skip re-running SEC search on re-score
        evidence = build_evidence(company, icp, signal_rules, sec_hits_by_name, signals, contacts,
                                   corroboration=corroboration.get(company["name"], []))
        scored = score_company(rules, evidence)
        db.upsert_account_prospect(
            campaign_id=campaign_id, company_id=company["id"],
            total_score=scored["total"], evaluable_weight=scored["evaluable_weight"],
            tier=scored["tier"], trace=scored["trace"],
        )
    print(f"[run_glassbox] re-scored {len(real_companies)} companies after enrichment")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", type=int, required=True)
    parser.add_argument("--no-sec", action="store_true", help="skip SEC EDGAR search (private-company-heavy ICPs)")
    parser.add_argument("--enrich-top", type=int, default=0, help="run Apollo enrichment + re-score for top N prospects")
    args = parser.parse_args()

    db.init_db()
    score_campaign(args.campaign_id, use_sec=not args.no_sec)

    if args.enrich_top:
        campaign = db.get_campaign(args.campaign_id)
        slug = campaign["name"].lower().split(" icp")[0].replace(" ", "").strip()
        enrich_top(args.campaign_id, args.enrich_top, slug)
