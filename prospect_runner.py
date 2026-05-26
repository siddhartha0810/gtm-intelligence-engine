"""
prospect_runner.py
==================
Subprocess script — run by unified_app.py for Apollo-based prospecting.
Streams progress via print() so the parent can SSE it to the browser.

Called as:
  python prospect_runner.py
       --companies-file /path/to/companies.txt
       --max-per-company 25
       --job-id <job_id>

Reads credentials from environment variables set by unified_app.py:
  APOLLO_API_KEY
  PG_MASTER_CONNECTION_STRING   — lead enrichment master (280k-contacts-db)
  ORACLE_PG_DSN                 — oracle intent DB (oracle_intent)
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "").strip()
PG_CONN_STR    = os.environ.get("PG_MASTER_CONNECTION_STRING", "").strip()
ORACLE_PG_DSN  = os.environ.get("ORACLE_PG_DSN", "").strip()

# MAX_PER and JOB_ID are resolved inside main() once args are parsed

APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_people/api_search"
APOLLO_REVEAL_URL = "https://api.apollo.io/v1/people/match"
RATE_LIMIT_DELAY  = 1.2

ORACLE_JDE_TITLES = [
    "JD Edwards", "JDE", "JDE EnterpriseOne",
    "Oracle ERP", "Oracle Cloud", "Oracle Fusion", "Oracle EBS",
    "Oracle HCM", "Oracle SCM", "Oracle EPM",
    "ERP Manager", "ERP Director", "ERP Consultant",
    "Finance Director", "Finance Manager", "Financial Controller",
    "CFO", "VP Finance", "IT Director", "CIO",
    "Enterprise Applications Manager", "Business Systems Manager",
    "Supply Chain Director", "HR Director", "CHRO",
    "Operations Director", "Digital Transformation Manager",
    "ERP Project Manager", "Oracle Developer",
]

# ── Helpers ─────────────────────────────────────────────────────────────────

def _log(msg: str):
    print(msg, flush=True)


def _normalize(name: str) -> str:
    name = name.lower()
    name = re.sub(r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|co|company|plc|private|pvt)\b", "", name)
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _apollo_reveal_email(person_id: str) -> str:
    """Reveal a locked Apollo email by person id. Returns email or ''."""
    if not person_id:
        return ""
    try:
        import urllib.request
        payload = json.dumps({
            "id": person_id,
            "reveal_personal_emails": True,
        }).encode()
        req = urllib.request.Request(
            APOLLO_REVEAL_URL,
            data=payload,
            headers={"Content-Type": "application/json", "X-Api-Key": APOLLO_API_KEY},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return str(data.get("person", {}).get("email") or "").strip().lower()
    except Exception:
        return ""


def _apollo_search(company: str, max_per: int = 25) -> list:
    try:
        import urllib.request
        payload = json.dumps({
            "q_organization_name": company,
            "person_titles":       ORACLE_JDE_TITLES,
            "per_page":            min(max_per, 25),
            "page":                1,
        }).encode()
        req = urllib.request.Request(
            APOLLO_SEARCH_URL,
            data=payload,
            headers={"Content-Type": "application/json", "X-Api-Key": APOLLO_API_KEY},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        _log(f"ERROR: Apollo search failed for '{company}': {e}")
        return []

    people = data.get("people") or data.get("contacts") or []
    contacts = []
    for p in people:
        if not isinstance(p, dict):
            continue

        first = str(p.get("first_name") or "").strip()
        if not first:
            continue

        email = str(p.get("email") or "").strip().lower()
        email_status = str(p.get("email_status") or "").lower()

        # Search returns has_email=True but email=None — reveal by person id
        if not email and p.get("has_email"):
            email = _apollo_reveal_email(str(p.get("id") or ""))
            email_status = "revealed" if email else ""
            time.sleep(0.3)

        if email_status in ("unavailable", "bounced", "invalid"):
            email = ""

        org    = p.get("organization") or p.get("account") or {}
        domain = str(
            org.get("primary_domain") or org.get("domain") or org.get("website_url") or ""
            if isinstance(org, dict) else ""
        ).lower().strip()
        domain = re.sub(r"^https?://", "", domain).lstrip("www.").split("/")[0]

        contacts.append({
            "first_name":              first,
            "last_name":               str(p.get("last_name") or "").strip(),
            "company":                 company,
            "job_title":               str(p.get("title") or p.get("headline") or "").strip(),
            "email":                   email,
            "email_validation_status": email_status if email else "",
            "email_source":            "apollo_prospect" if email else "",
            "linkedin_url":            str(p.get("linkedin_url") or "").strip(),
            "domain":                  domain,
            "source":                  "apollo",
        })
    return contacts


def _oracle_pg_lookup(company: str) -> list:
    """Check oracle_intent PostgreSQL for saved contacts for this company."""
    if not ORACLE_PG_DSN:
        return []
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(ORACLE_PG_DSN)
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT id, domain FROM companies WHERE name = %s", (company,))
                row = cur.fetchone()
                if not row:
                    return []
                company_id = row["id"]
                domain     = row["domain"] or ""
                cur.execute("""
                    SELECT * FROM company_contacts
                    WHERE company_id = %s
                    ORDER BY is_target DESC, confidence DESC
                """, (company_id,))
                contacts = []
                for c in cur.fetchall():
                    contacts.append({
                        "first_name":              c["first_name"],
                        "last_name":               c["last_name"],
                        "company":                 company,
                        "job_title":               c["title"],
                        "email":                   c["email"],
                        "email_validation_status": "",
                        "email_source":            "",
                        "linkedin_url":            c["linkedin_url"],
                        "domain":                  domain,
                        "source":                  c["source"] or "oracle_db",
                    })
        conn.close()
        return contacts
    except Exception as e:
        _log(f"ERROR: Oracle PG lookup failed: {e}")
        return []


def _pg_lookup(company_names: list) -> dict:
    """Bulk contacts table lookup by company name. Returns {company_name: [contacts]}."""
    if not PG_CONN_STR:
        return {}
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        return {}
    if not company_names:
        return {}
    try:
        conn = psycopg2.connect(PG_CONN_STR)
        result: dict = {}
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for name in company_names:
                    cur.execute(
                        """
                        SELECT "FirstName", "LastName", "Title", "Validated_Email",
                               "Validated_Email_Status", "LinkedIn_URL__c",
                               "LinkedIn_URL_Enriched", "Domain", "Existing_Company"
                        FROM contacts
                        WHERE  LOWER("Existing_Company") LIKE %s
                          AND  "Validated_Email" IS NOT NULL
                          AND  "Validated_Email" != ''
                        ORDER  BY "Validated_Email_Status" ASC
                        LIMIT  50
                        """,
                        (f"%{name.lower()}%",),
                    )
                    rows = cur.fetchall()
                    if rows:
                        result[name] = [{
                            "first_name":              r.get("FirstName", ""),
                            "last_name":               r.get("LastName", ""),
                            "company":                 name,
                            "job_title":               r.get("Title", ""),
                            "email":                   r.get("Validated_Email", ""),
                            "email_validation_status": r.get("Validated_Email_Status", ""),
                            "email_source":            "",
                            "linkedin_url":            r.get("LinkedIn_URL__c") or r.get("LinkedIn_URL_Enriched") or "",
                            "domain":                  r.get("Domain", ""),
                            "source":                  "contacts_db",
                        } for r in rows]
        conn.close()
        return result
    except Exception as e:
        _log(f"ERROR: PG lookup failed: {e}")
        return {}


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Apollo-based prospect runner")
    parser.add_argument("--companies-file",  required=True)
    parser.add_argument("--max-per-company", type=int, default=25)
    parser.add_argument("--job-id",          default="")
    args = parser.parse_args()

    max_per = args.max_per_company
    job_id  = args.job_id

    companies_file = Path(args.companies_file)
    if not companies_file.exists():
        _log(f"ERROR: companies file not found: {companies_file}")
        sys.exit(1)

    companies = [
        line.strip()
        for line in companies_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not companies:
        _log("ERROR: No companies in list")
        sys.exit(1)

    _log(f"Starting prospector for {len(companies)} companies...")

    all_contacts: list = []
    stats = {
        "total_companies": len(companies),
        "pg_hits":         0,
        "apollo_searched": 0,
        "total_contacts":  0,
    }

    # ── Bulk PG pre-check ─────────────────────────────────────────────────
    if PG_CONN_STR:
        _log(f"Checking DB for {len(companies)} companies...")
        pg_results = _pg_lookup(companies)
        _log(f"DB hit: {len(pg_results)} companies have existing contacts")
    else:
        pg_results = {}

    # ── Per-company resolution ────────────────────────────────────────────
    for company in companies:
        if company in pg_results:
            contacts = pg_results[company]
            _log(f"[DB] {company} -> {len(contacts)} contacts (free)")
            all_contacts.extend(contacts)
            stats["pg_hits"] += 1
            continue

        # Oracle Intent PG fallback
        oracle_contacts = _oracle_pg_lookup(company)
        if oracle_contacts:
            _log(f"[DB] {company} -> {len(oracle_contacts)} contacts (free)")
            all_contacts.extend(oracle_contacts)
            stats["pg_hits"] += 1
            continue

        # Apollo people search
        _log(f"[Apollo] {company} -> searching...")
        contacts = _apollo_search(company, max_per=max_per)
        found = len(contacts)
        status_tag = "found" if found else "none"
        _log(f"[Apollo] {company} -> {found} contacts ({status_tag})")
        all_contacts.extend(contacts)
        stats["apollo_searched"] += 1
        time.sleep(RATE_LIMIT_DELAY)

    stats["total_contacts"] = len(all_contacts)

    # ── Write results to file the server can pick up ──────────────────────
    out_path = companies_file.parent / f"_prospect_results_{job_id}.json"
    out_path.write_text(
        json.dumps({"contacts": all_contacts, "stats": stats}),
        encoding="utf-8",
    )

    _log(f"Saved {len(all_contacts)} contacts across {len(companies)} companies")
    _log(f"__PROSPECT_DONE__:{len(all_contacts)}")

    # Clean up temp companies file
    try:
        companies_file.unlink()
    except Exception:
        pass


if __name__ == "__main__":
    main()
