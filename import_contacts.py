#!/usr/bin/env python3
"""
import_contacts.py
==================
Bulk-load the consolidated 280K Salesforce contact export into the tool's DB,
grouped by company, with each contact's validated email + LinkedIn.

Source: ALL_CONTACTS_CONSOLIDATED.xlsx (Salesforce Contact object dump).
Target: companies + company_contacts (source='contacts_master').

Why a dedicated script: the stock save_contacts() commits one transaction per
contact — fine for a handful from Apollo, hopeless for 276K rows. This streams
the sheet once, upserts every unique company, then batch-inserts contacts with
executemany. Idempotent: it clears only prior source='contacts_master' rows
before loading, so re-runs are clean and Apollo/Hunter contacts are untouched.

Usage:
    python import_contacts.py [/path/to/ALL_CONTACTS_CONSOLIDATED.xlsx] [--limit N]
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

BASE = Path(__file__).parent
ORACLE = BASE / "oracle_intent_engine"
if str(ORACLE) not in sys.path:
    sys.path.insert(0, str(ORACLE))

DEFAULT_PATH = "/Users/sid/Desktop/ALL_CONTACTS_CONSOLIDATED.xlsx"
SOURCE_TAG = "contacts_master"
BATCH = 5000

# Salesforce column → our field. Emails/LinkedIn have a preferred + fallback col.
_COLS = [
    "FirstName", "LastName", "Title", "Email", "Validated_Email", "ZB_Valid_Email",
    "Validated_Email_Status", "Existing_Company", "New_Company", "Domain",
    "LinkedIn_URL_Enriched", "LinkedIn_URL__c", "Management_Level__c",
    "Job_Function__c", "Phone", "MobilePhone", "MailingCity", "MailingState",
    "MailingCountry", "DoNotCall", "HasOptedOutOfEmail", "Overall_Opt_Out__c",
    "ZI_Person_has_Moved__c",
]


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _truthy(v) -> bool:
    return _s(v).lower() in ("1", "yes", "true")


def main() -> None:
    path = DEFAULT_PATH
    limit = None
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--limit":
            limit = int(argv[i + 1]); i += 2; continue
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
        elif not a.startswith("--"):
            path = a
        i += 1

    import openpyxl
    from src import database as db

    print(f"Source: {path}")
    db.init_db()

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    header = list(next(it))
    idx = {h: i for i, h in enumerate(header)}
    missing = [c for c in _COLS if c not in idx]
    if missing:
        print(f"WARNING: columns not found (will treat as blank): {missing}")

    def g(row, col):
        i = idx.get(col)
        return _s(row[i]) if i is not None and i < len(row) else ""

    # ── Pass: stream → normalize → buffer minimal contact tuples ──────────────
    print("Streaming + normalizing rows…")
    companies: dict[str, str] = {}     # name → domain (first non-empty wins)
    contacts: list[dict] = []
    seen_email_company: set[tuple] = set()
    skipped_no_email = skipped_dupe = 0

    for n, row in enumerate(it):
        if limit and n >= limit:
            break
        company = g(row, "Existing_Company") or g(row, "New_Company")
        if not company:
            continue
        email = (g(row, "Validated_Email") or g(row, "Email")).lower()
        if not email:
            skipped_no_email += 1
            continue
        key = (company.lower(), email)
        if key in seen_email_company:
            skipped_dupe += 1
            continue
        seen_email_company.add(key)

        domain = g(row, "Domain")
        if company not in companies or (not companies[company] and domain):
            companies[company] = domain

        contacts.append({
            "company": company,
            "first_name": g(row, "FirstName"),
            "last_name": g(row, "LastName"),
            "title": g(row, "Title"),
            "email": email,
            "linkedin": g(row, "LinkedIn_URL_Enriched") or g(row, "LinkedIn_URL__c"),
            "seniority": g(row, "Management_Level__c"),
            "job_function": g(row, "Job_Function__c"),
            "domain": domain,
            "phone": g(row, "Phone"),
            "mobile": g(row, "MobilePhone"),
            "city": g(row, "MailingCity"),
            "state": g(row, "MailingState"),
            "country": g(row, "MailingCountry"),
            "zb_valid": _truthy(g(row, "ZB_Valid_Email")),
            "dnc": _truthy(g(row, "DoNotCall")),
            "dne": _truthy(g(row, "HasOptedOutOfEmail")) or _truthy(g(row, "Overall_Opt_Out__c")),
            "moved": _truthy(g(row, "ZI_Person_has_Moved__c")),
        })
        if (n + 1) % 50000 == 0:
            print(f"  …{n + 1:,} rows scanned")

    print(f"Parsed {len(contacts):,} contacts across {len(companies):,} companies "
          f"(skipped {skipped_no_email:,} no-email, {skipped_dupe:,} dupes)")

    # ── Upsert companies, build name → id map ─────────────────────────────────
    print("Upserting companies…")
    with db.db_cursor() as cur:
        cur.executemany(
            "INSERT INTO companies (name, domain) VALUES (%s, %s) "
            "ON CONFLICT (name) DO UPDATE SET domain = COALESCE(NULLIF(EXCLUDED.domain,''), companies.domain)",
            [(name, dom) for name, dom in companies.items()],
        )
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT id, name FROM companies")
        name_to_id = {r["name"]: r["id"] for r in cur.fetchall()}

    # ── Clear prior corpus rows (idempotent re-run), then batch-insert ────────
    print(f"Clearing prior source='{SOURCE_TAG}' contacts…")
    with db.db_cursor() as cur:
        cur.execute("DELETE FROM company_contacts WHERE source = %s", (SOURCE_TAG,))

    print("Batch-inserting contacts…")
    cols = ("company_id, first_name, last_name, full_name, title, email, linkedin_url, "
            "seniority, source, email_validation_status, ready_for_outreach, unique_key, "
            "domain, phone, mobile_phone, city, state, country, do_not_call, do_not_email, "
            "person_has_moved, job_function, level")
    ph = ", ".join(["%s"] * 23)
    sql = f"INSERT INTO company_contacts ({cols}) VALUES ({ph})"

    inserted = 0
    batch: list[tuple] = []
    for c in contacts:
        cid = name_to_id.get(c["company"])
        if not cid:
            continue
        full = f"{c['first_name']} {c['last_name']}".strip()
        batch.append((
            cid, c["first_name"], c["last_name"], full, c["title"], c["email"], c["linkedin"],
            c["seniority"], SOURCE_TAG, "valid" if c["zb_valid"] else "",
            1 if c["zb_valid"] else 0, uuid.uuid4().hex,
            c["domain"], c["phone"], c["mobile"], c["city"], c["state"], c["country"],
            1 if c["dnc"] else 0, 1 if c["dne"] else 0, 1 if c["moved"] else 0,
            c["job_function"], c["seniority"],
        ))
        if len(batch) >= BATCH:
            with db.db_cursor() as cur:
                cur.executemany(sql, batch)
            inserted += len(batch)
            batch = []
            print(f"  …{inserted:,} inserted")
    if batch:
        with db.db_cursor() as cur:
            cur.executemany(sql, batch)
        inserted += len(batch)

    # ── Refresh per-company contact counts ────────────────────────────────────
    print("Updating company contact counts…")
    with db.db_cursor() as cur:
        cur.execute("""
            UPDATE companies SET contact_count = (
                SELECT COUNT(*) FROM company_contacts
                WHERE company_contacts.company_id = companies.id AND email != ''
            )
        """)

    print(f"\nDONE — {inserted:,} contacts stored across {len(name_to_id):,} companies.")
    _sample(db)


def _sample(db) -> None:
    print("\nSample — top companies by stored contacts:")
    with db.db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT c.name, COUNT(cc.id) AS n,
                   SUM(CASE WHEN cc.linkedin_url != '' THEN 1 ELSE 0 END) AS li,
                   SUM(cc.ready_for_outreach) AS valid
            FROM companies c JOIN company_contacts cc ON cc.company_id = c.id
            WHERE cc.source = %s
            GROUP BY c.id ORDER BY n DESC LIMIT 8
        """, (SOURCE_TAG,))
        for r in cur.fetchall():
            print(f"   {r['n']:6,} contacts  ({r['li'] or 0:,} LinkedIn, {r['valid'] or 0:,} valid)  {r['name']}")


if __name__ == "__main__":
    main()
