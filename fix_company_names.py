#!/usr/bin/env python3
"""
fix_company_names.py
=====================
company_email_formats.company_name came from the source guide's naive
domain-parsing ("hsbc.com" -> "Hsbc", "hsbc.com.ar" -> "Hsbc Com" — the
generic second-level TLD leaked in because the parser split on every dot).
90% of covered domains (27,059 / 30,012) show this pattern.

Two free, mechanical fixes — no live scraping, no API calls:

  1. Backfill from the `companies` table, which enrich_companies.py has
     already been improving via free og:site_name scrapes for a while.
     27,732 of the 30,012 covered domains already have a row there — some
     already carry a real name ("flysterling.com" -> "Sterling Airways"),
     even if most are still the same naive parse. Free instant win either way.

  2. Strip a leaked generic-TLD fragment off the end of the name
     ("Abercrombiekent Co" -> "Abercrombiekent", 213 domains) — a distinct,
     narrower bug from splitting multi-part TLDs (.com.ar, .co.in, .com.au)
     on every dot instead of just the SLD.

Neither of these invents a name — they either reuse a name this project
already derived elsewhere, or remove characters that were never part of
any real name. Getting REAL company names (e.g. "Hsbc" -> "HSBC") needs
live per-domain enrichment — see enrich_companies.py, which already does
this for the `companies` table and could be pointed at the remaining
naive company_email_formats domains as a follow-up.

Usage:
    python fix_company_names.py            # writes to company_email_formats
    python fix_company_names.py --dry-run  # prints planned changes only
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).parent
ORACLE = BASE / "oracle_intent_engine"
if str(ORACLE) not in sys.path:
    sys.path.insert(0, str(ORACLE))

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
            SELECT cef.domain, cef.company_name AS naive_name, c.name AS enriched_name
            FROM company_email_formats cef
            JOIN companies c ON LOWER(c.domain) = cef.domain
            WHERE c.name IS NOT NULL AND c.name != '' AND c.name != cef.company_name
        """)
        backfill_rows = cur.fetchall()

        cur.execute("SELECT DISTINCT domain, company_name FROM company_email_formats")
        all_rows = cur.fetchall()

    backfill_map = {r["domain"]: r["enriched_name"] for r in backfill_rows}
    strip_map: dict[str, str] = {}
    for r in all_rows:
        domain = r["domain"]
        if domain in backfill_map:
            continue  # backfill takes priority for this domain
        cleaned = _strip_tld_fragment(r["company_name"], domain)
        if cleaned != r["company_name"]:
            strip_map[domain] = cleaned

    print(f"Backfill from companies table: {len(backfill_map):,} domains")
    print(f"TLD-fragment strip:            {len(strip_map):,} domains")

    if dry_run:
        print("\n--dry-run: showing a sample, writing nothing.")
        for domain, name in list(backfill_map.items())[:10]:
            print(f"  [backfill] {domain}: -> {name}")
        for domain, name in list(strip_map.items())[:10]:
            print(f"  [strip]    {domain}: -> {name}")
        return

    updates = {**backfill_map, **strip_map}
    with db.db_cursor() as cur:
        for domain, new_name in updates.items():
            cur.execute(
                "UPDATE company_email_formats SET company_name = %s WHERE domain = %s",
                (new_name, domain),
            )
    print(f"\nDONE — {len(updates):,} domains updated ({len(backfill_map):,} backfilled, {len(strip_map):,} TLD-stripped).")


if __name__ == "__main__":
    main()
