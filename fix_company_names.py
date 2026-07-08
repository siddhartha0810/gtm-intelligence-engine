#!/usr/bin/env python3
"""
fix_company_names.py
=====================
company_email_formats.company_name has three distinct, stackable data-quality
bugs, all present in the source guide from the start (none introduced by any
script in this repo):

  1. Naive domain-parsing: "hsbc.com" -> "Hsbc" (90% of covered domains,
     27,059 / 30,012).
  2. Leaked multi-part-TLD fragment: "hsbc.com.ar" -> "Hsbc Com" (splitting
     on every dot instead of just the SLD leaks the generic middle label).
  3. company_name literally equal to the full raw domain string:
     "iqvia.com" as the NAME, not just the domain (3,633 domains) — worse
     than #1, since it's not even title-cased.

Two free, mechanical fixes applied here, no live scraping, no invented names:

  A. Backfill from the `companies` table, which enrich_companies.py has
     already been improving via free og:site_name scrapes. Only applied when
     BOTH sides check out: the existing company_email_formats name is
     currently bad (one of the three patterns above, or a prior live-scrape
     artifact that also looks like a domain), AND the companies.name being
     pulled in doesn't itself look like a raw domain. Without this guard, an
     earlier version of this script clobbered good live-scraped values
     ("Cardinal Health Inc") with worse companies-table ones
     ("cardinalhealth.com", itself bug #3 in that table) just because they
     differed — verified and fixed before running for real.

  B. Fix bugs #2 and #3 directly wherever backfill didn't already fix them.

Getting genuinely new names beyond what's already sitting in the companies
table needs live per-domain enrichment — see enrich_prediction_names.py
(reuses enrich_companies.py's free og:site_name mechanism, with an added
filter for domain-shaped junk that mechanism can return).

Usage:
    python fix_company_names.py            # writes to company_email_formats
    python fix_company_names.py --dry-run  # prints planned changes only
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BASE = Path(__file__).parent
ORACLE = BASE / "oracle_intent_engine"
if str(ORACLE) not in sys.path:
    sys.path.insert(0, str(ORACLE))

_DOMAIN_LIKE = re.compile(r"\.[a-z]{2,6}$", re.IGNORECASE)


def _looks_like_domain(name: str) -> bool:
    return bool(_DOMAIN_LIKE.search(name.strip()))


def _is_bad(name: str, domain: str) -> bool:
    """True if `name` is one of the three known-bad patterns for `domain`."""
    n = name.strip().lower()
    d = domain.strip().lower()
    root = d.split(".")[0]
    if n == d:                                  # bug #3: exact domain string
        return True
    if n.replace(" ", "") == root:               # bug #1: naive title-case of root
        return True
    if _looks_like_domain(name):                 # any other domain-shaped junk
        return True
    return False


def _strip_tld_fragment(name: str, domain: str) -> str:
    """
    Strip a trailing word off `name` ONLY if it's provably a leaked domain
    label — i.e. the domain has a multi-part suffix (hsbc.com.ar) and the
    name's last word matches that suffix's middle label (com) exactly.

    Must be tied to the actual domain structure, not a generic word list —
    a plain word-list check misfires on real brand names that happen to end
    in a country-code-shaped word from a hyphenated domain, e.g.
    "cds-net.com" -> "Cds Net" is NOT "Cds" + a leaked ".net" (the domain's
    only TLD is .com; "net" is part of the actual domain label "cds-net").
    """
    labels = domain.split(".")
    if len(labels) < 3:
        return name  # no compound suffix like .com.ar / .co.in to leak from
    suffix_middle = labels[-2].lower()  # e.g. "com" in hsbc.com.ar
    parts = name.split()
    if len(parts) >= 2 and parts[-1].lower() == suffix_middle:
        return " ".join(parts[:-1])
    return name


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    from src import database as db

    db.init_db()

    with db.db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT cef.domain, cef.company_name AS current_name, c.name AS candidate_name
            FROM company_email_formats cef
            JOIN companies c ON LOWER(c.domain) = cef.domain
            WHERE c.name IS NOT NULL AND c.name != ''
        """)
        join_rows = cur.fetchall()

        cur.execute("SELECT DISTINCT domain, company_name FROM company_email_formats")
        all_rows = cur.fetchall()

    backfill_map: dict[str, str] = {}
    for r in join_rows:
        domain, current, candidate = r["domain"], r["current_name"], r["candidate_name"]
        if candidate == current:
            continue
        if not _is_bad(current, domain):
            continue  # current name is already fine — don't touch it
        if _is_bad(candidate, domain):
            continue  # companies.name is itself junk — nothing to gain
        backfill_map[domain] = candidate

    exact_map: dict[str, str] = {}
    strip_map: dict[str, str] = {}
    for r in all_rows:
        domain, name = r["domain"], r["company_name"]
        if domain in backfill_map:
            continue  # backfill takes priority for this domain
        if name.strip().lower() == domain.strip().lower():
            exact_map[domain] = domain.split(".")[0].title()
            continue
        cleaned = _strip_tld_fragment(name, domain)
        if cleaned != name:
            strip_map[domain] = cleaned

    print(f"Backfill from companies table:  {len(backfill_map):,} domains")
    print(f"Exact-domain-string fix:        {len(exact_map):,} domains")
    print(f"TLD-fragment strip:             {len(strip_map):,} domains")

    if dry_run:
        print("\n--dry-run: showing a sample, writing nothing.")
        for domain, name in list(backfill_map.items())[:10]:
            print(f"  [backfill] {domain}: -> {name}")
        for domain, name in list(exact_map.items())[:10]:
            print(f"  [exact]    {domain}: -> {name}")
        for domain, name in list(strip_map.items())[:10]:
            print(f"  [strip]    {domain}: -> {name}")
        return

    updates = {**backfill_map, **exact_map, **strip_map}
    with db.db_cursor() as cur:
        for domain, new_name in updates.items():
            cur.execute(
                "UPDATE company_email_formats SET company_name = %s WHERE domain = %s",
                (new_name, domain),
            )
    print(f"\nDONE — {len(updates):,} domains updated "
          f"({len(backfill_map):,} backfilled, {len(exact_map):,} exact-domain-fixed, {len(strip_map):,} TLD-stripped).")


if __name__ == "__main__":
    main()
