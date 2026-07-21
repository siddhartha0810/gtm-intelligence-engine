#!/usr/bin/env python3
"""
enrich_companies.py
===================
Free company enrichment — no paid API (no Clearbit/ZoomInfo/Apollo needed).

Every company already has a domain, so we enrich from the company's OWN website:
  * fetch the homepage
  * pull the proper name (og:site_name / <title>) and description (meta tags)
  * classify the industry from that text against a keyword taxonomy

This fills the industry gap for the long-tail companies (the curated reference
only covers the top ~40) and upgrades mangled long-tail names where the site
gives a cleaner one. Runs concurrently, rate-limited, and never raises on a
dead site — it just skips it.

The email side is already API-free too: the prediction engine (email_patterns,
37K domains) + the 222K validated corpus replace paid email reveals.

Usage:
    python enrich_companies.py --limit=200        # top-by-contacts, missing industry
    python enrich_companies.py --limit=200 --all  # include ones that already have industry
    python enrich_companies.py --workers=16
"""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = Path(__file__).parent
ORACLE = BASE / "intent_engine"
if str(ORACLE) not in sys.path:
    sys.path.insert(0, str(ORACLE))

_UA = "Mozilla/5.0 (compatible; gtm-company-enrichment/1.0)"
_TIMEOUT = 5

# Stealth fallback for sites that block a plain requests.get() (Cloudflare /
# bot-challenge pages return a 200 with near-empty content, not a clean
# error — which is why this is a fallback, not the first attempt: it's a
# real headless browser launch, much heavier than a bare HTTP GET, so it
# only runs for the minority of domains the fast path can't reach).
_SCRAPLING_AVAILABLE = False
try:
    from scrapling.fetchers import StealthyFetcher
    _SCRAPLING_AVAILABLE = True
except ImportError:
    pass

# Keyword → industry. Matched against name + domain + homepage description.
# Ordered so more-specific industries win (first match by iteration order).
_INDUSTRY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Banking",                 ["bank", "banking", "credit union", "mortgage lender"]),
    ("Insurance",               ["insurance", "insurer", "reinsurance", "underwriting", "actuarial"]),
    ("Financial Services",      ["asset management", "investment", "wealth", "capital markets",
                                 "brokerage", "financial services", "fintech", "payments", "hedge fund",
                                 "private equity", "venture capital", "trading"]),
    ("Pharmaceuticals",         ["pharmaceutical", "pharma", "biotech", "biopharma", "drug", "vaccine", "therapeutics"]),
    ("Healthcare",              ["healthcare", "health system", "hospital", "clinic", "medical center",
                                 "patient care", "medical device", "health plan"]),
    ("Aerospace & Defense",     ["aerospace", "defense", "defence", "aircraft", "missile", "satellite", "avionics"]),
    ("Automotive",              ["automotive", "vehicle", "car manufacturer", "auto parts", "mobility", "ev "]),
    ("Energy",                  ["energy", "oil", "gas", "petroleum", "renewable", "solar", "wind power",
                                 "utility", "power generation", "electric utility"]),
    ("Chemicals",               ["chemical", "chemicals", "coatings", "polymers", "materials science"]),
    ("Industrial Manufacturing",["manufacturing", "industrial", "machinery", "equipment", "automation",
                                 "engineering", "factory", "components"]),
    ("Technology",              ["software", "saas", "cloud", "platform", "technology", "developer",
                                 "data", "ai ", "artificial intelligence", "cybersecurity", "semiconductor",
                                 "computing", "digital", "api"]),
    ("Telecommunications",      ["telecom", "telecommunications", "wireless", "broadband", "network operator", "5g"]),
    ("Retail",                  ["retail", "retailer", "ecommerce", "e-commerce", "stores", "shopping"]),
    ("Consumer Goods",          ["consumer goods", "consumer products", "beverage", "food", "cpg",
                                 "beauty", "cosmetics", "apparel", "household"]),
    ("Media & Entertainment",   ["media", "entertainment", "broadcasting", "streaming", "publishing",
                                 "gaming", "studios", "film"]),
    ("Hospitality",             ["hotel", "hospitality", "resort", "restaurant", "travel", "lodging"]),
    ("Logistics",               ["logistics", "shipping", "freight", "supply chain", "courier", "delivery", "transportation"]),
    ("Real Estate",             ["real estate", "property", "reit", "commercial property"]),
    ("Education",               ["education", "university", "college", "school", "learning", "edtech", "academic"]),
    ("Professional Services",   ["consulting", "advisory", "accounting", "audit", "law firm", "legal services",
                                 "staffing", "recruitment"]),
    ("Government",              ["government", "public sector", "federal agency", "municipality", "ministry"]),
    ("Construction",            ["construction", "builder", "contractor", "infrastructure", "civil engineering"]),
]


def classify_industry(text: str) -> str:
    t = (text or "").lower()
    for industry, kws in _INDUSTRY_KEYWORDS:
        if any(k in t for k in kws):
            return industry
    return ""


_THIN_PAGE_BYTES = 2000  # a bot-challenge page returns 200 OK with ~near-empty HTML


def _parse_meta(html: str) -> tuple[str, str]:
    import trafilatura
    meta = trafilatura.extract_metadata(html)
    sitename = (getattr(meta, "sitename", "") or getattr(meta, "title", "") or "") if meta else ""
    desc = (getattr(meta, "description", "") or "") if meta else ""
    return sitename.strip(), desc.strip()


def _stealth_fetch(domain: str) -> str:
    """Real headless-browser fetch — only called when the fast path fails or
    comes back suspiciously thin (the Cloudflare/bot-challenge signature).
    Tuned tight: a genuinely dead/slow domain must fail fast (the default
    30s x however-many-internal-retries is impractical across a 39K-company
    run), while solve_cloudflare + disable_resources give the actual bot-
    walled sites their best shot in the time budget."""
    if not _SCRAPLING_AVAILABLE:
        return ""
    for scheme in ("https://", "http://"):
        try:
            page = StealthyFetcher.fetch(
                scheme + domain, headless=True,
                timeout=8000, disable_resources=True,
                solve_cloudflare=True, network_idle=False,
            )
            # A 403/404/5xx error page still has HTML (and a <title> like
            # "Access Denied" that would otherwise get stored as the company
            # name) — only accept genuine 2xx responses.
            status = getattr(page, "status", 0) or 0
            if status >= 400:
                continue
            html = getattr(page, "html_content", "") or getattr(page, "body", "") or ""
            if html:
                return html
        except Exception:
            continue
    return ""


def fetch_meta(domain: str) -> tuple[str, str]:
    """(sitename, description) from the homepage. ('','') on any failure.
    Fast plain-requests path first; stealth-browser fallback only for sites
    that block it (Cloudflare et al.) — most domains never need the fallback."""
    import requests
    best_html = ""
    for scheme in ("https://", "http://"):
        try:
            resp = requests.get(scheme + domain, headers={"User-Agent": _UA},
                                timeout=_TIMEOUT, allow_redirects=True)
            if resp.status_code < 400 and resp.text and len(resp.text) > _THIN_PAGE_BYTES:
                best_html = resp.text
                break
        except Exception:
            continue

    if not best_html:
        best_html = _stealth_fetch(domain)

    if not best_html:
        return "", ""
    try:
        return _parse_meta(best_html)
    except Exception:
        return "", ""


def _clean_sitename(sitename: str, current: str) -> str:
    """A homepage sitename is often the cleanest proper name ('Wells Fargo').
    Only use it if it looks like a real name and improves on the current one."""
    s = re.sub(r"\s*[|\-–—:].*$", "", sitename).strip()   # drop tagline after separator
    if not s or len(s) > 40:
        return ""
    if s.lower() == current.lower():
        return ""
    # improvement heuristic: multi-word, or current is a single mashed token
    if " " in s or (len(current.split()) == 1 and len(s) >= len(current)):
        return s
    return ""


def enrich_one(row: dict, protect_names: set) -> dict | None:
    domain = (row.get("domain") or "").strip().lower()
    if not domain:
        return None
    sitename, desc = fetch_meta(domain)
    if not sitename and not desc:
        return None
    text = f"{row.get('name','')} {domain} {desc}"
    industry = classify_industry(text)
    new_name = "" if row["name"].lower() in protect_names else _clean_sitename(sitename, row["name"])
    if not industry and not new_name:
        return None
    return {"id": row["id"], "industry": industry, "name": new_name,
            "website": f"https://{domain}"}


def main() -> None:
    global _SCRAPLING_AVAILABLE
    limit, workers, include_all = 200, 12, False
    for a in sys.argv[1:]:
        if a.startswith("--limit="):   limit = int(a.split("=", 1)[1])
        elif a.startswith("--workers="): workers = int(a.split("=", 1)[1])
        elif a == "--all":             include_all = True
        elif a == "--no-stealth":
            # Bulk sweeps: the stealth-browser fallback trades throughput for
            # coverage — a dead domain costs several seconds proving it's dead
            # instead of failing fast like plain requests does. ~20x slower
            # in practice. Use plain-requests-only for a full-database pass;
            # drop this flag for smaller, quality-over-speed batches.
            _SCRAPLING_AVAILABLE = False

    from src import database as db, company_reference as ref
    protect_names = {n.lower() for (n, *_rest) in ref.COMPANY_REFERENCE.values()}

    where = "domain IS NOT NULL AND domain != ''" + ("" if include_all else " AND (industry IS NULL OR industry = '')")
    with db.db_cursor(commit=False) as cur:
        cur.execute(f"""
            SELECT id, name, domain FROM companies
            WHERE {where}
            ORDER BY contact_count DESC NULLS LAST
            LIMIT %s
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]

    print(f"Enriching {len(rows)} companies from their own websites ({workers} workers)…", flush=True)

    def apply_update(u: dict) -> tuple[bool, bool]:
        """Writes one company's update immediately. Returns (got_industry, got_name)."""
        sets, vals = ["website = %s"], [u["website"]]
        got_industry = got_name = False
        if u["industry"]:
            sets.append("industry = %s"); vals.append(u["industry"]); got_industry = True
        if u["name"]:
            sets.append("name = %s"); vals.append(u["name"]); got_name = True
        vals.append(u["id"])
        try:
            with db.db_cursor() as cur:
                cur.execute(f"UPDATE companies SET {', '.join(sets)} WHERE id = %s", vals)
        except Exception:
            return False, False  # e.g. name collision with an existing company
        return got_industry, got_name

    done = enriched = with_industry = with_name = 0
    # Each result is applied to the DB the moment it completes — progress is
    # real and durable, so killing/resuming this run never loses prior work.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(enrich_one, r, protect_names): r for r in rows}
        for fut in as_completed(futs):
            done += 1
            try:
                u = fut.result()
            except Exception:
                u = None
            if u:
                gi, gn = apply_update(u)
                enriched += 1
                with_industry += int(gi)
                with_name += int(gn)
            if done % 20 == 0 or done == len(rows):
                print(f"  …{done}/{len(rows)} fetched, {enriched} enriched "
                      f"({with_industry} industries, {with_name} names)", flush=True)

    print(f"\nDONE — {with_industry} industries classified, {with_name} names upgraded, "
          f"{enriched} companies updated (of {len(rows)} attempted).")
    _sample(db)


def _sample(db) -> None:
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) n FROM companies WHERE industry IS NOT NULL AND industry != ''")
        print(f"Companies with an industry now: {cur.fetchone()['n']:,}")
        cur.execute("""
            SELECT name, industry, location FROM companies
            WHERE industry IS NOT NULL AND industry != '' AND website IS NOT NULL AND website != ''
            ORDER BY contact_count DESC NULLS LAST LIMIT 10
        """)
        print("Freshly enriched (name · industry · location):")
        for r in cur.fetchall():
            print(f"   {(r['name'] or '')[:28]:28} | {(r['industry'] or '')[:24]:24} | {r['location'] or '—'}")


if __name__ == "__main__":
    main()
