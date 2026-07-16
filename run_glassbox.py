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
  4. Optionally searches for each candidate's own customers describing the
     exact pain the account's product solves — via G2/Capterra search-engine
     presence (fetch_g2_pain_corroboration()) AND real Reddit threads
     (fetch_reddit_pain_corroboration(), added after confirming G2/Capterra
     can't be scraped directly — both sit behind active anti-bot challenges;
     see g2_review_search.py) — the QuadSci equivalent of what SEC filings
     were for InRule: third-party disclosure of the precise buying trigger,
     not a proxy signal. Uses free ddgs web search, not g2_reviews_signal.py
     (Bing-News-only, never surfaces review pages). Skip both with --no-g2.
  5. Scores every candidate via glassbox_scorer.score_company() — each rule
     evaluated fired / not_fired / no_evidence, never zeroed out for a
     missing evidence source.
  6. Upserts account_prospects.
  7. With --enrich-top N: runs Apollo enrichment (apollo_enrichment.py,
     already generic) for the top N scored companies, then re-scores just
     those so R7 (decision_maker_found) reflects real contacts instead of
     defaulting to no_evidence.

Does NOT generate outreach hooks — that's a deliberate separate step via the
existing Campaign Builder / /api/campaign/generate-hooks, same
already-generic pipeline, once you've reviewed the scored list.

Usage:
    python run_glassbox.py --campaign-id 4
    python run_glassbox.py --campaign-id 4 --no-sec --no-g2
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


# Firmographic-vendor industry labels (Wikidata etc.) rarely phrase things the
# way an ICP file's target_industries does — see build_evidence()'s
# industry_fit fallback below.
_INDUSTRY_SYNONYMS = {
    "bank": ["banking", "financial services", "investment"],
    "banking": ["bank", "financial services", "investment banking"],
    "national bank": ["banking", "investment banking", "financial services"],
    "investment": ["banking", "investment banking", "asset management"],
    "financial services": ["banking", "investment", "asset management",
                            "private equity", "hedge fund", "real estate"],
    "economics of banking": ["banking", "investment banking"],
    "conglomerate": ["financial services", "investment banking"],
    "mergers and acquisitions": ["investment banking"],
    "asset management": ["hedge fund", "private equity", "asset management"],
    # SaaS-vertical labels (QuadSci-style ICPs). Only precise labels are
    # mapped — generic "software industry" / "information and communications
    # technology" deliberately match nothing, because they'd fire
    # industry_fit for every software company on earth and the rule would
    # stop meaning anything.
    "computer security": ["security saas", "security"],
    "cybersecurity": ["security saas", "security"],
    "network security": ["security saas", "security"],
    "marketing technology": ["martech", "marketing"],
    "advertising technology": ["martech", "marketing"],
    "data analytics": ["data / mdm", "data"],
    "business intelligence": ["data / mdm", "data"],
    "cloud infrastructure": ["infrastructure", "devtools"],
    "developer tools": ["infrastructure", "devtools"],
}


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


def fetch_sec_officer_changes(candidates: list, window_days: int = 365,
                              sic_out: dict | None = None) -> dict:
    """SEC 8-K Item 5.02 = legally mandated disclosure of officer/director
    departures and appointments — the authoritative, citable source for the
    leadership_change rule on the PUBLIC slice of any ICP (news search finds
    these late or not at all; the company itself must file within 4 business
    days). Generalizes the method used ad hoc for the Endex account:
      1. resolve each candidate to a CIK via SEC's company_tickers.json
         (conservative name match — a wrong CIK cites another company's
         filing, worse than no citation)
      2. pull data.sec.gov/submissions/CIK##########.json
      3. surface 8-Ks whose items include 5.02 within window_days
    Free, keyless, ~0.3s/company (SEC fair-access pacing). Private companies
    simply don't resolve and are skipped — expected for most of QuadSci's ICP.

    sic_out: optional dict the caller owns; for every resolved company it
    gains {company_name: {"cik", "sic", "sic_desc"}} from the same
    submissions.json fetch — zero extra requests. This is what implements
    the "sec" half of the glassbox rules' declared `sec_or_firmographic`
    evidence source for industry_fit (build_evidence's sec_sic_by_name
    param), which was documented in the rules yaml but never wired up.

    Returns {company_name: [corroboration hits]} in the same shape as
    fetch_corroboration(), typed leadership_change."""
    import json as _json
    import time as _time
    import urllib.request
    from datetime import datetime as _dt, timedelta as _td
    from email.utils import format_datetime as _fmt822

    headers = {"User-Agent": "GTM Research siddharthakothi@gmail.com"}

    def _get_json(url: str) -> dict:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return _json.loads(resp.read())

    def _strip_legal(name: str) -> str:
        n = re.sub(r"[,.]", " ", name.lower())
        n = re.sub(r"\b(inc|incorporated|corp|corporation|holdings?|group|plc|llc|ltd|co|the|companies)\b", " ", n)
        return re.sub(r"\s+", " ", n).strip()

    try:
        tickers = _get_json("https://www.sec.gov/files/company_tickers.json")
    except Exception as e:
        print(f"[run_glassbox] SEC ticker map fetch failed: {e} — skipping officer-change pass")
        return {}
    # {stripped_title: cik} — first (lowest-index = largest) entry wins on dupes
    by_title: dict[str, int] = {}
    for entry in tickers.values():
        key = _strip_legal(entry["title"])
        if key and key not in by_title:
            by_title[key] = entry["cik_str"]

    cutoff = (_dt.now() - _td(days=window_days)).strftime("%Y-%m-%d")
    results: dict = {}
    resolved = 0
    for c in candidates:
        key = _strip_legal(c["name"])
        # Exact stripped-name match only. Substring matching resolves
        # "Census" to "Census Bureau Corp"-style strangers; a miss here is
        # just "private company", which is the honest default.
        cik = by_title.get(key)
        if not cik:
            continue
        resolved += 1
        try:
            subs = _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
            _time.sleep(0.3)  # SEC fair-access guideline
        except Exception as e:
            print(f"  [{c['name']}] submissions fetch failed: {e}")
            continue
        if sic_out is not None and subs.get("sicDescription"):
            sic_out[c["name"]] = {"cik": cik, "sic": subs.get("sic", ""),
                                  "sic_desc": subs.get("sicDescription", "")}
        recent = subs.get("filings", {}).get("recent", {})
        rows = zip(recent.get("form", []), recent.get("filingDate", []),
                   recent.get("accessionNumber", []), recent.get("primaryDocument", []),
                   recent.get("items", [""] * len(recent.get("form", []))))
        for form, fdate, acc, doc, items in rows:
            if form != "8-K" or "5.02" not in (items or "") or fdate < cutoff:
                continue
            acc_nodash = acc.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
            hit = {
                "type": "leadership_change",
                "term": "officer change (8-K Item 5.02)",
                "title": f"{subs.get('name', c['name'])} Form 8-K, Item 5.02 "
                         f"(Departure/Appointment of Officers), filed {fdate}",
                "url": url,
                "posted_date": _fmt822(_dt.strptime(fdate, "%Y-%m-%d")),
            }
            results.setdefault(c["name"], []).append(hit)
            print(f"  [{c['name']}] 8-K Item 5.02 filed {fdate}")
            break  # most recent qualifying filing is enough — R5 evaluates one hit
    print(f"[run_glassbox] SEC officer-change pass: {resolved}/{len(candidates)} "
          f"resolved to a CIK, {len(results)} with a recent Item 5.02")
    return results


def fetch_layoff_corroboration(candidates: list, window_days: int = 365) -> dict:
    """Cost-pressure corroboration from layoffs.fyi's structured tracker
    (WARN filings + press, company/headcount/date/source-link rows). One
    bounded fetch for the whole candidate list — the inverse economics of
    fetch_corroboration()'s per-company news searches. Matched by normalized
    name; typed cost_pressure, which build_evidence() treats as a
    recent_trigger_event alternative and R6 counts as a dated event."""
    from email.utils import format_datetime as _fmt822

    from src.signals.layoff_signal import fetch_layoff_rows

    rows = fetch_layoff_rows(window_days=window_days)
    if not rows:
        return {}
    by_norm = {}
    for r in rows:
        by_norm.setdefault(_normalize_name(r["company"]), []).append(r)

    results: dict = {}
    for c in candidates:
        for r in by_norm.get(_normalize_name(c["name"]), [])[:1]:  # most recent is enough
            pct = r["percentage"]
            pct_txt = f" ({round(pct * 100)}%)" if isinstance(pct, (int, float)) else ""
            n = r["laid_off"]
            n_txt = f"{int(n)} employees" if isinstance(n, (int, float)) else "employees"
            results.setdefault(c["name"], []).append({
                "type": "cost_pressure",
                "term": "workforce reduction",
                "title": f"{r['company']} laid off {n_txt}{pct_txt} on {r['date']:%Y-%m-%d} "
                         f"(layoffs.fyi tracker, press-sourced)",
                "url": r["source_url"],
                "posted_date": _fmt822(r["date"]),
            })
            print(f"  [{c['name']}] layoff event {r['date']:%Y-%m-%d}")
    print(f"[run_glassbox] layoff corroboration: {len(results)}/{len(candidates)} candidates with a recent workforce reduction")
    return results


def fetch_competitor_churn_corroboration(candidates: list) -> dict:
    """Displacement corroboration from competitor customer-page churn
    (competitor_churn_watch.py): a candidate whose logo was REMOVED from a
    rival vendor's /customers wall between two structurally comparable
    Wayback snapshots very likely churned from that competitor — an
    in-flight displacement window. Typed competitor_displacement (same 0.55
    confidence class as news-based displacement evidence); cites the
    before/after archived pages. ~2-4 min for the full page list (8
    snapshot fetches per page, politely paced against archive.org)."""
    from datetime import datetime as _dt
    from email.utils import format_datetime as _fmt822

    from competitor_churn_watch import PAGES, watch_page

    by_norm = {_normalize_name(c["name"]): c["name"] for c in candidates}
    results: dict = {}
    print(f"[run_glassbox] competitor churn watch across {len(PAGES)} customer pages...")
    for page in PAGES:
        try:
            rep = watch_page(page)
        except Exception as e:
            print(f"  [{page}] churn watch failed: {e}")
            continue
        if not rep:
            continue
        vendor = page.split(".")[0].split("/")[-1].title()
        for removed in rep["removed"]:
            cand_name = by_norm.get(_normalize_name(removed))
            if not cand_name:
                continue
            results.setdefault(cand_name, []).append({
                "type": "competitor_displacement",
                "term": f"removed from {vendor} customers page",
                "title": f"{removed} removed from {vendor}'s public customers page between "
                         f"{rep['old_ts'][:8]} and {rep['new_ts'][:8]} (wall grew "
                         f"{rep['old_count']}→{rep['new_count']} — a specific takedown). "
                         f"Before: {rep['old_url']}",
                "url": rep["new_url"],
                "posted_date": _fmt822(_dt.strptime(rep["new_ts"][:8], "%Y%m%d")),
            })
            print(f"  [{cand_name}] removed from {vendor} customer wall")
    print(f"[run_glassbox] churn watch: {len(results)}/{len(candidates)} candidates matched a removal")
    return results


def fetch_corroboration(candidates: list, signal_rules: dict) -> dict:
    """Targeted, per-company search: does THIS specific company (already
    surfaced by a hiring/tech-stack signal) have a SECOND, different-typed
    signal — funding, leadership change, NRR/churn commentary, or competitor
    displacement? A hiring posting alone doesn't distinguish a real prospect
    from any company that happens to be hiring a RevOps manager for
    unrelated reasons; this is what actually tests for that.

    trigger_types included "nrr_commentary" (QuadSci's rule name) but not
    "ai_adoption_pressure" (Endex's differently-named equivalent rule — press
    coverage of AI automating analyst work / cutting analyst-class sizes /
    reducing junior-banker hours, arguably the single strongest signal type
    for the Endex ICP) — that type was silently never searched for any
    account using a different rule-type name than QuadSci's. Both are listed
    now so this function generalizes across accounts instead of only working
    for the one it was first written for.

    Returns {company_name: [{"type", "term", "title", "url", "posted_date"}]}."""
    from src.signals.news_signal import NewsSignal
    from src.phase_classifier import detect_campaign_product

    trigger_types = ["funding_event", "leadership_change", "nrr_commentary",
                      "ai_adoption_pressure", "competitor_displacement"]
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


_PAIN_MAX_AGE_DAYS = 540  # ~18 months; older third-party pain isn't current pain

_DATE_PATTERNS = [
    re.compile(r'<time[^>]+datetime="(\d{4}-\d{2}-\d{2})', re.I),
    re.compile(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', re.I),
    re.compile(r'property="article:published_time"[^>]+content="(\d{4}-\d{2}-\d{2})', re.I),
    re.compile(r'"dateCreated"\s*:\s*"(\d{4}-\d{2}-\d{2})', re.I),
]


def _page_publish_date(url: str) -> "date | None":
    """Best-effort publish date for a third-party page, from its own markup
    (<time datetime>, schema.org datePublished, og article:published_time).
    None when the page is unreachable or carries no machine-readable date."""
    from datetime import date as _date
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read(400_000).decode("utf-8", errors="ignore")
    except Exception:
        return None
    found = []
    for pat in _DATE_PATTERNS:
        for m in pat.findall(html):
            try:
                y, mo, d = m.split("-")
                found.append(_date(int(y), int(mo), int(d)))
            except Exception:
                continue
    return min(found) if found else None  # earliest = original post, not last reply


def _date_gate_pain_hits(company: str, hits: list) -> list:
    """Keep only pain-language hits whose page carries a machine-readable
    publish date within _PAIN_MAX_AGE_DAYS. Undated pages are DROPPED, not
    given a pass — an undated hit stored with posted_date='' bypasses every
    decay rule and scores like it happened yesterday (confirmed live: a
    Sep-2020 skydiopilots.com forum thread fired category_language at full
    weight in 2026). Kept hits gain their real date so decay applies."""
    from datetime import date as _date
    from email.utils import format_datetime as _fmt
    from datetime import datetime as _dt
    kept = []
    for h in hits:
        d = _page_publish_date(h["url"])
        if d is None:
            print(f"  [{company}] dropped pain hit (no publish date): {h['url'][:80]}")
            continue
        age = (_date.today() - d).days
        if age > _PAIN_MAX_AGE_DAYS:
            print(f"  [{company}] dropped pain hit ({age}d old, {d}): {h['url'][:80]}")
            continue
        h["posted_date"] = _fmt(_dt(d.year, d.month, d.day))
        kept.append(h)
    return kept


def fetch_g2_pain_corroboration(candidates: list, signal_rules: dict) -> dict:
    """The QuadSci-specific answer to what SEC filings were for InRule: not a
    proxy signal (hiring, funding) but a prospect's OWN CUSTOMERS describing
    the exact symptom QuadSci cures, in public G2/Capterra reviews. Third-party
    disclosure in the customer's own words — the sharpest evidence available
    for a private company with no SEC filings.

    Uses g2_review_search.py (free ddgs web search) — NOT g2_reviews_signal.py,
    which only hits Bing's News RSS feed and never surfaces review pages at all
    (confirmed empirically; news crawlers don't index evergreen review content).

    Returns {company_name: [{"type": "customer_pain_language", "term", "title",
    "url"}]} — same shape as fetch_corroboration() so build_evidence() can
    merge both into one list per company."""
    from src.g2_review_search import search_review_mentions
    from src.phase_classifier import detect_campaign_product

    pain_terms = _terms_for_signal_type(signal_rules, "customer_pain_language")
    if not pain_terms:
        return {}

    results: dict = {}
    print(f"[run_glassbox] searching G2/Capterra customer-pain language for {len(candidates)} companies...")
    for i, c in enumerate(candidates, 1):
        mentions = search_review_mentions(c["name"])
        name_key = _normalize_name(c["name"])
        hits = []
        for m in mentions:
            # Comparison/alternatives pages ("X vs Y", "Best X Alternatives")
            # legitimately rank in results for a company search while being
            # substantively ABOUT a different company — confirmed empirically:
            # searching "Tebra" surfaced a G2 page titled "athenaOne Reviews"
            # (a Tebra competitor). Require the searched company's name to
            # actually appear in the title or URL before trusting the match —
            # same class of fix as the exclude_companies name-mangling bug.
            if name_key not in _normalize_name(m["title"]) and name_key not in _normalize_name(m["url"]):
                continue
            matched_term, _ = detect_campaign_product(m["title"], m.get("body", ""), pain_terms)
            if matched_term:
                hits.append({
                    "type": "customer_pain_language", "term": matched_term,
                    "title": m["title"], "url": m["url"], "posted_date": "",
                })
        if hits:
            hits = _date_gate_pain_hits(c["name"], hits)
        if hits:
            results[c["name"]] = hits
            print(f"  [{c['name']}] {len(hits)} G2/Capterra pain-language hit(s): "
                  f"{[h['term'] for h in hits]}")
        if i % 10 == 0:
            print(f"  ...{i}/{len(candidates)} companies checked")
    print(f"[run_glassbox] G2/Capterra pain-language corroboration found for {len(results)}/{len(candidates)} companies")
    return results


def fetch_reddit_pain_corroboration(candidates: list, signal_rules: dict) -> dict:
    """Second pain-language source, added after confirming G2/Capterra can't
    be scraped directly (both sit behind active anti-bot challenges — see
    g2_review_search.py's module docstring). Real Reddit threads are
    unprompted, candid, and well-indexed by search engines, unlike G2's
    review pages whose SEO metadata is marketing copy, not review text.

    Same shape/contract as fetch_g2_pain_corroboration() — callers merge
    both into one corroboration list per company."""
    from src.g2_review_search import search_reddit_mentions
    from src.phase_classifier import detect_campaign_product

    pain_terms = _terms_for_signal_type(signal_rules, "customer_pain_language")
    if not pain_terms:
        return {}

    results: dict = {}
    print(f"[run_glassbox] searching Reddit customer-pain language for {len(candidates)} companies...")
    for i, c in enumerate(candidates, 1):
        mentions = search_reddit_mentions(c["name"])
        name_key = _normalize_name(c["name"])
        hits = []
        for m in mentions:
            # Same same-company sanity filter as the G2 search — a company
            # name search can surface threads substantively about a
            # different company (comparisons, "vs" posts, unrelated
            # subreddits that happen to mention the term in passing).
            if name_key not in _normalize_name(m["title"]) and name_key not in _normalize_name(m["url"]):
                continue
            matched_term, _ = detect_campaign_product(m["title"], m.get("body", ""), pain_terms)
            if matched_term:
                hits.append({
                    "type": "customer_pain_language", "term": matched_term,
                    "title": m["title"], "url": m["url"], "posted_date": "",
                })
        if hits:
            hits = _date_gate_pain_hits(c["name"], hits)
        if hits:
            results[c["name"]] = hits
            print(f"  [{c['name']}] {len(hits)} Reddit pain-language hit(s): "
                  f"{[h['term'] for h in hits]}")
        if i % 10 == 0:
            print(f"  ...{i}/{len(candidates)} companies checked")
    print(f"[run_glassbox] Reddit pain-language corroboration found for {len(results)}/{len(candidates)} companies")
    return results


def build_evidence(company: dict, icp: dict, signal_rules: dict,
                    sec_hits_by_name: dict, signals: list, contacts: list,
                    corroboration: list | None = None,
                    sec_sic_by_name: dict | None = None) -> dict:
    """One evidence dict per company, keyed by rule condition. A missing key
    means no_evidence — the caller (glassbox_scorer) treats that as excluded
    from scoring, not a failure.

    corroboration: hits from a targeted per-company news search (see
    fetch_corroboration()), each {"type", "term", "title", "url", "posted_date"}
    — distinct from `signals` (the campaign's own broad scan) because it's
    specifically "does THIS company have a SECOND, different-typed signal,"
    not just another hit on the same broad keyword search.

    sec_sic_by_name: {company_name: {"cik", "sic", "sic_desc"}} collected by
    fetch_sec_officer_changes(sic_out=...) — makes industry_fit's declared
    `sec_or_firmographic` evidence source real: EDGAR's own SIC classification
    is checked FIRST (authoritative + citable), falling back to the
    firmographic-vendor label, then tech-stack tells in signal text."""
    evidence: dict = {}
    corroboration = corroboration or []
    name_key = _normalize_name(company["name"])
    sec_hits = sec_hits_by_name.get(name_key, [])
    signal_texts = " ".join((s.get("evidence") or "") + " " + (s.get("job_title") or "") for s in signals).lower()

    def _corrob_hit(rule_type: str) -> dict | None:
        return next((h for h in corroboration if h["type"] == rule_type), None)

    # R1 category_language — priority order: SEC (rare but strongest, most of
    # this ICP is private so this rarely fires) > G2/Capterra customer pain
    # language (a prospect's OWN CUSTOMERS naming the exact symptom QuadSci
    # cures, in public — the sharpest broadly-available evidence for this ICP,
    # the direct analog to what SEC filings were for InRule's regulated ICP)
    # > signals text > nrr_commentary corroboration (weakest, most generic).
    cat_terms = icp.get("category_terms", [])
    sec_cat_hit = next((h for h in sec_hits if any(t.lower() in h.get("job_title", "").lower() for t in cat_terms)), None)
    pain_hit = _corrob_hit("customer_pain_language")
    nrr_hit = _corrob_hit("nrr_commentary")
    ai_pressure_hit = _corrob_hit("ai_adoption_pressure")
    if sec_cat_hit:
        evidence["category_language"] = {
            "fired": True, "why": f'Uses category language ("{sec_cat_hit.get("job_title", "")}") in SEC filings.',
            "source_url": sec_cat_hit.get("url", ""), "date": sec_cat_hit.get("posted_date", ""),
        }
    elif pain_hit:
        evidence["category_language"] = {
            "fired": True,
            "why": f'This company\'s own customers describe the exact pain QuadSci solves '
                   f'("{pain_hit["term"]}") in a public G2/Capterra review — {pain_hit["title"]}',
            "source_url": pain_hit["url"], "date": pain_hit["posted_date"],
        }
    elif signals and (term_hit := next((t for t in cat_terms if t.lower() in signal_texts), None)):
        src = next((s for s in signals if term_hit.lower() in (s.get("evidence") or "").lower()), signals[0])
        evidence["category_language"] = {
            "fired": True, "why": f'Uses category language ("{term_hit}").',
            "source_url": src.get("url", ""), "date": str(src.get("detected_at", "")),
        }
    elif ai_pressure_hit:
        evidence["category_language"] = {
            "fired": True,
            "why": f'Public commentary shows the exact AI-adoption pressure Endex sells into '
                   f'("{ai_pressure_hit["term"]}") — {ai_pressure_hit["title"]}',
            "source_url": ai_pressure_hit["url"], "date": ai_pressure_hit["posted_date"],
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

    # R3 industry_fit / technographic fit — three evaluable sources, checked
    # in declared sec_or_firmographic order:
    #   1. SEC SIC classification (sec_sic_by_name — public companies only;
    #      authoritative and citable, but note SIC is coarse for SaaS ICPs:
    #      nearly everything is 7372 "Prepackaged Software", which matches
    #      no vertical and correctly falls through to the next source)
    #   2. companies.industry field vs target_industries (firmographic)
    #   3. tech_stack_tell terms in signal text (e.g. "Gainsight Administrator"
    #      job posting) — quadsci_signal_rules.yaml's own description for this
    #      rule type is literally "confirms the technographic fit", so this is
    #      the correct evidence source for it, not R2/displacement.
    target_industries = icp.get("target_industries", [])
    sic_info = (sec_sic_by_name or {}).get(company["name"])
    sic_matched = False
    if sic_info:
        sic_desc = sic_info["sic_desc"].lower()
        match = next((t for t in target_industries if t.lower() in sic_desc or sic_desc in t.lower()), None)
        if not match:
            synonyms = [s for key, vals in _INDUSTRY_SYNONYMS.items() if key in sic_desc for s in vals]
            match = next((t for t in target_industries if any(s in t.lower() for s in synonyms)), None)
        if match:
            cik = sic_info["cik"]
            evidence["industry_fit"] = {
                "fired": True,
                "why": f'SEC industry classification (SIC {sic_info["sic"]}): '
                       f'{sic_info["sic_desc"]} — a core ICP vertical, confirmed via EDGAR.',
                "source_url": (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                                f"&CIK={cik:010d}&type=10-K&dateb=&owner=include&count=10"),
                "date": "",
            }
            sic_matched = True
        # A generic/non-matching SIC is NOT "checked, absent" by itself —
        # fall through so the firmographic/tech-stack sources still get
        # their look before the rule settles.
    # Sources FALL THROUGH until one fires — a checked-but-unmatched source
    # must not block a stronger one behind it (a generic Wikidata "software
    # industry" label was blocking AppFolio's hiring-for-Pendo technographic
    # evidence). "Checked, absent" is only settled at the end, if every
    # evaluable source came up empty.
    industry_checked = bool(sic_info)
    if sic_matched:
        pass
    elif company.get("industry"):
        # Bidirectional substring check — companies.industry is often a short
        # firmographic-vendor label ("bank"), while target_industries entries
        # are longer descriptive strings ("Investment Banking (bulge bracket
        # + boutique)"). A one-directional check (ICP string contained in the
        # short label) can never match; checking the short label against the
        # ICP string too lets "bank" correctly match "...Investment Banking...".
        industry_checked = True
        ind = company["industry"].lower()
        match = next(
            (t for t in target_industries if t.lower() in ind or ind in t.lower()),
            None,
        )
        if not match:
            # Firmographic vendors (Wikidata/Clearbit-style) return short
            # finance-vertical labels ("economics of banking", "conglomerate",
            # "mergers and acquisitions") that never literally substring-match
            # the ICP's descriptive category strings ("Investment Banking
            # (bulge bracket + boutique)") even bidirectionally. A small
            # synonym expansion catches these real matches instead of
            # under-counting every bank/PE firm whose vendor label happens to
            # phrase things differently than the ICP file does.
            synonyms = [s for key, vals in _INDUSTRY_SYNONYMS.items() if key in ind for s in vals]
            match = next((t for t in target_industries if any(s in t.lower() for s in synonyms)), None)
        if match:
            evidence["industry_fit"] = {"fired": True, "why": f'Industry match: {company["industry"]}.',
                                         "source_url": "", "date": ""}
    if "industry_fit" not in evidence and signals:
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
            industry_checked = True
    if "industry_fit" not in evidence and (industry_checked or signals):
        # at least one source was evaluable and none matched — checked, absent
        evidence["industry_fit"] = {"fired": False}
    # else: nothing evaluable at all -> stays absent -> no_evidence

    # R4 recent_trigger_event — SEC first, then signals, then corroboration.
    # funding_event and cost_pressure are BOTH trigger events: fresh capital
    # and a public layoff are opposite balance-sheet moments that create the
    # same "why now" (new scrutiny on retention economics). funding wins the
    # tie only because its terms are also checked in signal text first.
    trigger_terms = _terms_for_signal_type(signal_rules, "funding_event")
    fund_hit = _corrob_hit("funding_event") or _corrob_hit("cost_pressure")
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
    # "hiring signal + a second, different-typed signal close in time"). Keeps
    # each contributing event's own url/label so the trace can link straight
    # to what was actually counted — before this, the only way to check "is
    # this really 3 events" was to cross-reference the OTHER rule cards above
    # it, which only works for events that happen to ALSO be a scored rule
    # (a bare hiring signal contributing to the count had no trace row of
    # its own to point at).
    #
    # Corroboration hits are deduped by `type` before counting — multiple
    # news outlets covering the SAME underlying event (e.g. three sites
    # reporting one funding round on three different dates) must count as
    # ONE trigger event, not three. R2/R4/R5 already treat `type` as the
    # evaluation unit via _corrob_hit() picking a single representative
    # hit; R6 needs the same collapse or "N trigger events" gets inflated
    # by duplicate coverage of one real event (confirmed: Tebra's single
    # $250M raise, covered by 3 outlets, was counting as 3 of its 4
    # "trigger events").
    seen_corrob_types: set = set()
    deduped_corroboration = []
    for h in corroboration:
        if h["type"] in seen_corrob_types:
            continue
        seen_corrob_types.add(h["type"])
        deduped_corroboration.append(h)

    dated_events = [
        {"date": s["detected_at"], "url": s.get("url", ""),
         "label": s.get("evidence") or s.get("job_title") or "signal"}
        for s in signals if s.get("detected_at")
    ] + [
        {"date": h["posted_date"], "url": h.get("url", ""),
         "label": h.get("title") or h.get("term") or "corroboration"}
        for h in deduped_corroboration if h.get("posted_date")
    ]
    if dated_events:
        from datetime import datetime
        from email.utils import parsedate_to_datetime
        parsed = []
        for ev in dated_events:
            d = ev["date"]
            if hasattr(d, "year"):
                dt = d
            else:
                try:
                    dt = parsedate_to_datetime(str(d)).replace(tzinfo=None)
                except Exception:
                    continue
            parsed.append({"dt": dt, "url": ev["url"], "label": ev["label"]})
        if parsed:
            parsed.sort(key=lambda e: e["dt"], reverse=True)
            most_recent = parsed[0]["dt"]
            days_ago = (datetime.now() - most_recent).days
            evidence["buying_window_timing"] = {
                "fired": len(parsed) >= 2 and days_ago <= 270,
                "why": f"{len(parsed)} trigger events, most recent {days_ago} days ago.",
                "source_url": "", "date": str(most_recent),
                "events": [
                    {"label": str(e["label"])[:160], "url": e["url"], "date": str(e["dt"])}
                    for e in parsed
                ],
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


def score_campaign(campaign_id: int, use_sec: bool = True, use_g2: bool = True,
                   use_churn_watch: bool = True) -> list:
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
    sec_sic_by_name: dict = {}
    if use_sec:
        # Public-company officer changes from 8-K Item 5.02 filings — feeds
        # the same leadership_change rule as news corroboration, but from the
        # company's own legally mandated disclosure. The same submissions.json
        # fetch also yields each resolved company's SIC classification
        # (sic_out), which industry_fit checks first — the "sec" half of the
        # rules' declared sec_or_firmographic evidence source.
        for name, hits in fetch_sec_officer_changes(candidates, sic_out=sec_sic_by_name).items():
            corroboration_by_name.setdefault(name, []).extend(hits)
    # Workforce reductions (layoffs.fyi) — cost-pressure trigger events.
    # One bounded fetch; failure degrades to {} without blocking scoring.
    for name, hits in fetch_layoff_corroboration(candidates).items():
        corroboration_by_name.setdefault(name, []).extend(hits)
    if use_churn_watch:
        # Competitor customer-page churn (Wayback diffs) — displacement windows.
        for name, hits in fetch_competitor_churn_corroboration(candidates).items():
            corroboration_by_name.setdefault(name, []).extend(hits)
    if use_g2:
        g2_by_name = fetch_g2_pain_corroboration(candidates, signal_rules)
        for name, hits in g2_by_name.items():
            corroboration_by_name.setdefault(name, []).extend(hits)
        reddit_by_name = fetch_reddit_pain_corroboration(candidates, signal_rules)
        for name, hits in reddit_by_name.items():
            corroboration_by_name.setdefault(name, []).extend(hits)

    results = []
    for company in candidates:
        signals = [dict(s) for s in db.get_signals_for_company(company["id"])]
        contacts = [dict(c) for c in db.get_contacts_for_company(company["id"])]
        corroboration = corroboration_by_name.get(company["name"], [])
        evidence = build_evidence(company, icp, signal_rules, sec_hits_by_name, signals, contacts,
                                   corroboration, sec_sic_by_name=sec_sic_by_name)
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
    for name, hits in fetch_g2_pain_corroboration(real_companies, signal_rules).items():
        corroboration.setdefault(name, []).extend(hits)
    for name, hits in fetch_reddit_pain_corroboration(real_companies, signal_rules).items():
        corroboration.setdefault(name, []).extend(hits)
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
    parser.add_argument("--no-g2", action="store_true", help="skip G2/Capterra + Reddit customer-pain-language search")
    parser.add_argument("--no-churn-watch", action="store_true", help="skip competitor customer-page churn watch (Wayback diffs, ~3 min)")
    parser.add_argument("--enrich-top", type=int, default=0, help="run Apollo enrichment + re-score for top N prospects")
    args = parser.parse_args()

    db.init_db()
    score_campaign(args.campaign_id, use_sec=not args.no_sec, use_g2=not args.no_g2,
                   use_churn_watch=not args.no_churn_watch)

    if args.enrich_top:
        campaign = db.get_campaign(args.campaign_id)
        slug = campaign["name"].lower().split(" icp")[0].replace(" ", "").strip()
        enrich_top(args.campaign_id, args.enrich_top, slug)
