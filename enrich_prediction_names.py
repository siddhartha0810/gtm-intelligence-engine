#!/usr/bin/env python3
"""
enrich_prediction_names.py
===========================
Live, free enrichment of company_email_formats.company_name for domains
that are still naive-derived after fix_company_names.py's two mechanical
passes (no backfill source, no leaked-TLD to strip). Reuses
enrich_companies.py's fetch_meta()/_clean_sitename() — same free
og:site_name-from-the-domain's-own-homepage mechanism, no paid API.

Prioritizes by contacts_280k DESC — the domains that actually matter most
for Prediction Engine search results get enriched first.

Usage:
    python enrich_prediction_names.py --limit=500              # test batch
    python enrich_prediction_names.py --limit=500 --workers=16
    python enrich_prediction_names.py --limit=500 --no-stealth  # faster, lower hit rate
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = Path(__file__).parent
ORACLE = BASE / "intent_engine"
if str(ORACLE) not in sys.path:
    sys.path.insert(0, str(ORACLE))

import re

import enrich_companies as ec  # reuse fetch_meta / _clean_sitename / classify_industry

# enrich_companies._clean_sitename() accepts anything longer than the current
# name — including, it turns out, a raw domain/URL string when a site's
# metadata has no real og:site_name and trafilatura falls back to the URL
# itself (caught in a 20-domain trial: "oracle.com" -> "oracle.com",
# "chase.com" -> "jpmorganchase.com" — a domain string, just not even the
# right one). Reject anything that still looks like a domain.
_DOMAIN_LIKE = re.compile(r"\.[a-z]{2,6}$", re.IGNORECASE)


def _is_naive(domain: str, name: str) -> bool:
    return name.lower().replace(" ", "") == domain.split(".")[0].lower()


def _looks_like_domain(s: str) -> bool:
    return bool(_DOMAIN_LIKE.search(s.strip()))


def main() -> None:
    global ec
    limit, workers = 500, 12
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
        elif a.startswith("--workers="):
            workers = int(a.split("=", 1)[1])
        elif a == "--no-stealth":
            ec._SCRAPLING_AVAILABLE = False

    from src import database as db
    db.init_db()

    with db.db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT domain, company_name FROM company_email_formats
            WHERE format_rank = 1 AND contacts_280k > 0 AND is_predictable
            ORDER BY contacts_280k DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]

    candidates = [r for r in rows if _is_naive(r["domain"], r["company_name"])][:limit]
    print(f"{len(candidates):,} naive-named domains selected (of {len(rows):,} covered), "
          f"top by corpus evidence, {workers} workers, stealth={'on' if ec._SCRAPLING_AVAILABLE else 'off'}")

    def work(row: dict) -> tuple[str, str] | None:
        domain = row["domain"]
        sitename, _desc = ec.fetch_meta(domain)
        if not sitename:
            return None
        cleaned = ec._clean_sitename(sitename, row["company_name"])
        if not cleaned or _looks_like_domain(cleaned):
            return None
        return (domain, cleaned)

    done = hit = 0
    results: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(work, r): r for r in candidates}
        for fut in as_completed(futs):
            done += 1
            try:
                res = fut.result()
            except Exception:
                res = None
            if res:
                hit += 1
                results.append(res)
            if done % 50 == 0 or done == len(candidates):
                print(f"  …{done}/{len(candidates)} fetched, {hit} improved ({hit*100//max(done,1)}% hit rate)", flush=True)

    print(f"\nFetched {done}, got a real name for {hit} ({hit*100//max(done,1)}% hit rate).")
    print("Writing updates…")
    with db.db_cursor() as cur:
        for domain, new_name in results:
            cur.execute("UPDATE company_email_formats SET company_name = %s WHERE domain = %s", (new_name, domain))
    print(f"DONE — {len(results):,} domains updated.")

    print("\nSample:")
    for domain, new_name in results[:20]:
        print(f"  {domain:30} -> {new_name}")


if __name__ == "__main__":
    main()
