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

BASE_DIR = Path(__file__).parent
ORACLE_DIR = BASE_DIR / "oracle_intent_engine"
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

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


def get_candidate_companies(campaign: dict) -> list:
    last_run_id = campaign.get("last_run_id")
    if not last_run_id:
        return []
    with db.db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT DISTINCT c.id, c.name, c.domain, c.industry
            FROM oracle_signals s JOIN companies c ON c.id = s.company_id
            WHERE s.scan_run_id = %s
        """, (last_run_id,))
        return [dict(r) for r in cur.fetchall()]


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


def build_evidence(company: dict, icp: dict, signal_rules: dict,
                    sec_hits_by_name: dict, signals: list, contacts: list) -> dict:
    """One evidence dict per company, keyed by rule condition. A missing key
    means no_evidence — the caller (glassbox_scorer) treats that as excluded
    from scoring, not a failure."""
    evidence: dict = {}
    name_key = _normalize_name(company["name"])
    sec_hits = sec_hits_by_name.get(name_key, [])
    signal_texts = " ".join((s.get("evidence") or "") + " " + (s.get("job_title") or "") for s in signals).lower()

    # R1 category_language — SEC first, else signals text
    cat_terms = icp.get("category_terms", [])
    sec_cat_hit = next((h for h in sec_hits if any(t.lower() in h.get("job_title", "").lower() for t in cat_terms)), None)
    if sec_cat_hit:
        evidence["category_language"] = {
            "fired": True, "why": f'Uses category language ("{sec_cat_hit.get("job_title", "")}") in SEC filings.',
            "source_url": sec_cat_hit.get("url", ""), "date": sec_cat_hit.get("posted_date", ""),
        }
    elif signals:
        term_hit = next((t for t in cat_terms if t.lower() in signal_texts), None)
        if term_hit:
            src = next((s for s in signals if term_hit.lower() in (s.get("evidence") or "").lower()), signals[0])
            evidence["category_language"] = {
                "fired": True, "why": f'Uses category language ("{term_hit}").',
                "source_url": src.get("url", ""), "date": str(src.get("detected_at", "")),
            }
        else:
            evidence["category_language"] = {"fired": False}
    # else: no signals and no SEC hit at all -> stays absent -> no_evidence

    # R2 displacement — signals only (competitor product named in a job/news signal)
    comp_terms = _terms_for_signal_type(signal_rules, "competitor_displacement") or icp.get("competitor_products", [])
    if signals:
        term_hit = next((t for t in comp_terms if t.lower() in signal_texts), None)
        if term_hit:
            src = next((s for s in signals if term_hit.lower() in (s.get("evidence") or "").lower()), signals[0])
            evidence["displacement"] = {
                "fired": True, "why": f'Names a competitor product/behavior ("{term_hit}").',
                "source_url": src.get("url", ""), "date": str(src.get("detected_at", "")),
            }
        else:
            evidence["displacement"] = {"fired": False}

    # R3 industry_fit — SEC SIC not implemented here (no per-company CIK lookup
    # yet); firmographic fallback against companies.industry is always evaluable
    # when that field is populated.
    target_industries = icp.get("target_industries", [])
    if company.get("industry"):
        match = next((t for t in target_industries if t.lower() in company["industry"].lower()), None)
        evidence["industry_fit"] = (
            {"fired": True, "why": f'Industry match: {company["industry"]}.', "source_url": "", "date": ""}
            if match else {"fired": False}
        )
    # else: no industry on file -> no_evidence

    # R4 recent_trigger_event — SEC first, else signals (funding_event terms)
    trigger_terms = _terms_for_signal_type(signal_rules, "funding_event")
    if signals:
        term_hit = next((t for t in trigger_terms if t.lower() in signal_texts), None)
        if term_hit:
            src = next((s for s in signals if term_hit.lower() in (s.get("evidence") or "").lower()), signals[0])
            evidence["recent_trigger_event"] = {
                "fired": True, "why": f'Recent trigger event ("{term_hit}").',
                "source_url": src.get("url", ""), "date": str(src.get("detected_at", "")),
            }
        else:
            evidence["recent_trigger_event"] = {"fired": False}

    # R5 leadership_change — signals (leadership_change terms)
    lead_terms = _terms_for_signal_type(signal_rules, "leadership_change")
    if signals:
        term_hit = next((t for t in lead_terms if t.lower() in signal_texts), None)
        if term_hit:
            src = next((s for s in signals if term_hit.lower() in (s.get("evidence") or "").lower()), signals[0])
            evidence["leadership_change"] = {
                "fired": True, "why": f'Leadership change signal ("{term_hit}").',
                "source_url": src.get("url", ""), "date": str(src.get("detected_at", "")),
            }
        else:
            evidence["leadership_change"] = {"fired": False}

    # R6 buying_window_timing — pure date-math, evaluable whenever any signal exists
    if signals:
        dates = sorted((s["detected_at"] for s in signals if s.get("detected_at")), reverse=True)
        if dates:
            from datetime import datetime
            most_recent = dates[0]
            days_ago = (datetime.now() - most_recent).days if hasattr(most_recent, "year") else 0
            evidence["buying_window_timing"] = {
                "fired": len(dates) >= 2 and days_ago <= 270,
                "why": f"{len(dates)} trigger events, most recent {days_ago} days ago.",
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

    candidates = get_candidate_companies(campaign)
    print(f"[run_glassbox] {len(candidates)} candidate companies from campaign '{campaign['name']}'")
    if not candidates:
        print("[run_glassbox] no companies yet — run a scan for this campaign first")
        return []

    sec_hits_by_name = fetch_sec_hits(icp) if use_sec else {}

    results = []
    for company in candidates:
        signals = [dict(s) for s in db.get_signals_for_company(company["id"])]
        contacts = [dict(c) for c in db.get_contacts_for_company(company["id"])]
        evidence = build_evidence(company, icp, signal_rules, sec_hits_by_name, signals, contacts)
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
    icp, rules_cfg, signal_rules = _slug_files(icp_slug)
    rules = rules_cfg.get("rules", [])
    campaign = db.get_campaign(campaign_id)
    for p in prospects:
        company = {"id": p["company_id"], "name": p["company_name"], "domain": p.get("domain"),
                   "industry": None}
        signals = [dict(s) for s in db.get_signals_for_company(company["id"])]
        contacts = [dict(c) for c in db.get_contacts_for_company(company["id"])]
        sec_hits_by_name = {}  # skip re-running SEC search on re-score
        evidence = build_evidence(company, icp, signal_rules, sec_hits_by_name, signals, contacts)
        scored = score_company(rules, evidence)
        db.upsert_account_prospect(
            campaign_id=campaign_id, company_id=company["id"],
            total_score=scored["total"], evaluable_weight=scored["evaluable_weight"],
            tier=scored["tier"], trace=scored["trace"],
        )
    print(f"[run_glassbox] re-scored {len(prospects)} companies after enrichment")


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
