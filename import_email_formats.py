#!/usr/bin/env python3
"""
import_email_formats.py
=======================
Load the validated per-domain email formats into the prediction engine.

Source: COMPANY-EMAIL-FORMAT-REFERENCE-GUIDE.xlsx (sheet "DETAILED COMPANY
FORMAT GUIDE") — one row per domain×format, derived from the 280K validated
corpus, with the format code and how many validated emails matched it.

Target: email_patterns(domain, pattern, sample_count). email_pattern_engine
reads this via load_domain_patterns(): for a domain we've seen, it uses the
learned pattern instead of guessing from the global default. sample_count
orders multiple formats so the primary sorts first.

Only format codes the engine can actually build are loaded (see PATTERNS in
email_pattern_engine.py); "Other / unmatched" and custom multi-dot codes are
skipped rather than stored as unusable patterns.

Usage:
    python import_email_formats.py [/path/to/GUIDE.xlsx]
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).parent
ORACLE = BASE / "oracle_intent_engine"
if str(ORACLE) not in sys.path:
    sys.path.insert(0, str(ORACLE))

DEFAULT_PATH = "/Users/sid/Downloads/COMPANY-EMAIL-FORMAT-REFERENCE-GUIDE.xlsx"
SHEET = "DETAILED COMPANY FORMAT GUIDE"
BATCH = 5000

# Codes email_pattern_engine.PATTERNS can build. Guide codes outside this set
# (e.g. "Other / unmatched", "f...last / custom") are unusable — skip them.
_ENGINE_CODES = {
    "first.last", "firstlast", "flast", "first_last", "f.last", "first.l",
    "last.first", "first", "lastf", "last.f", "firstl", "last",
}


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else DEFAULT_PATH

    import openpyxl
    from src import database as db

    print(f"Source: {path}")
    db.init_db()

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if SHEET not in wb.sheetnames:
        print(f"ERROR: sheet '{SHEET}' not found. Sheets: {wb.sheetnames}")
        return
    ws = wb[SHEET]
    it = ws.iter_rows(values_only=True)
    header = list(next(it))
    idx = {h: i for i, h in enumerate(header)}

    def g(row, col):
        i = idx.get(col)
        return _s(row[i]) if i is not None and i < len(row) else ""

    print("Reading per-domain formats…")
    # Keep the strongest sample_count per (domain, pattern)
    seen: dict[tuple, int] = {}
    total = skipped_code = 0
    for row in it:
        total += 1
        domain = g(row, "Domain").lower()
        code = g(row, "Format Code")
        if not domain or code not in _ENGINE_CODES:
            if code and code not in _ENGINE_CODES:
                skipped_code += 1
            continue
        # sample_count: validated Format Count, with a small rank bias so the
        # primary format (rank 1) outsorts secondaries on ties.
        try:
            count = int(float(g(row, "Format Count") or 1))
        except ValueError:
            count = 1
        try:
            rank = int(float(g(row, "Format Rank") or 1))
        except ValueError:
            rank = 1
        weight = count * 100 + max(0, 100 - rank)
        key = (domain, code)
        if weight > seen.get(key, 0):
            seen[key] = weight

    print(f"Parsed {total:,} rows → {len(seen):,} usable domain/pattern pairs "
          f"(skipped {skipped_code:,} unmappable codes)")

    print("Upserting into email_patterns…")
    rows = [(dom, pat, cnt) for (dom, pat), cnt in seen.items()]
    inserted = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        with db.db_cursor() as cur:
            cur.executemany(
                "INSERT INTO email_patterns (domain, pattern, sample_count) VALUES (%s, %s, %s) "
                "ON CONFLICT (domain, pattern) DO UPDATE SET "
                "sample_count = MAX(email_patterns.sample_count, EXCLUDED.sample_count)",
                chunk,
            )
        inserted += len(chunk)
        if inserted % 20000 == 0:
            print(f"  …{inserted:,} upserted")

    print(f"\nDONE — {inserted:,} domain-format patterns loaded.")
    _sample(db)


def _sample(db) -> None:
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(DISTINCT domain) AS d, COUNT(*) AS p FROM email_patterns")
        r = cur.fetchone()
        print(f"email_patterns now covers {r['d']:,} domains ({r['p']:,} total patterns).")
        cur.execute("""
            SELECT domain, pattern, sample_count FROM email_patterns
            ORDER BY sample_count DESC LIMIT 8
        """)
        print("Top by evidence:")
        for r in cur.fetchall():
            print(f"   {r['domain'][:36]:36} → {r['pattern']:12} (weight {r['sample_count']:,})")


if __name__ == "__main__":
    main()
