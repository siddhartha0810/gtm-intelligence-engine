"""
csv_contacts.py — PostgreSQL contacts lookup (replaces CSV file reader).

Queries the `contacts` table in 280k-contacts-db for contacts matching
a detected company name or domain.
Connection via PG_MASTER_CONNECTION_STRING env var (same DB as everything else).
"""

import os
import re
from src.utils import get_logger

logger = get_logger(__name__)

_STOP_WORDS = {
    "inc", "corp", "ltd", "llc", "plc", "gmbh", "ag", "sa", "nv", "bv",
    "co", "the", "group", "holdings", "holding", "global", "international",
    "solutions", "technologies", "technology", "systems", "system",
    "services", "service", "networks", "network", "communications",
    "enterprises", "enterprise", "partners", "consulting",
}


def _norm(s: str) -> str:
    s = re.sub(r"[^a-z0-9\s]", "", s.lower())
    return "".join(w for w in s.split() if w not in _STOP_WORDS)


def _conn():
    import psycopg2
    import psycopg2.extras
    dsn = os.environ.get("PG_MASTER_CONNECTION_STRING", "")
    conn = psycopg2.connect(dsn)
    return conn, psycopg2.extras.RealDictCursor


def is_available() -> bool:
    try:
        conn, _ = _conn()
        cur = conn.cursor()
        cur.execute('SELECT 1 FROM contacts LIMIT 1')
        conn.close()
        return True
    except Exception:
        return False


def find_contacts(company_name: str, domain: str = "") -> list[dict]:
    """
    Find contacts in the PostgreSQL contacts table for the given company.
    Tries exact company match first, then domain match, then fuzzy LIKE.
    Returns up to 100 contacts sorted by email availability.
    """
    results: list[dict] = []
    seen: set = set()

    def _row_to_contact(r: dict) -> dict:
        return {
            "first_name":   r.get("FirstName", ""),
            "last_name":    r.get("LastName", ""),
            "full_name":    f"{r.get('FirstName', '')} {r.get('LastName', '')}".strip(),
            "title":        r.get("Title", ""),
            "email":        r.get("Validated_Email", "") or r.get("Email", ""),
            "linkedin_url": r.get("LinkedIn_URL__c", "") or r.get("LinkedIn_URL_Enriched", ""),
            "domain":       r.get("Domain", ""),
            "seniority":    r.get("Management_Level__c", ""),
            "confidence":   1.0 if (r.get("Validated_Email") or r.get("Email")) else 0.5,
            "is_target":    False,
            "source":       "contacts_db",
        }

    def _add(rows):
        for r in rows:
            uid = r.get("Validated_Email") or r.get("Email") or r.get("LinkedIn_URL__c") or (
                f"{r.get('FirstName','')}_{r.get('LastName','')}"
            )
            if uid and uid not in seen:
                seen.add(uid)
                results.append(_row_to_contact(r))

    try:
        conn, CursorFactory = _conn()
        with conn:
            with conn.cursor(cursor_factory=CursorFactory) as cur:
                select = """
                    SELECT "FirstName","LastName","Title","Email","Validated_Email",
                           "Validated_Email_Status","LinkedIn_URL__c","LinkedIn_URL_Enriched",
                           "Domain","Existing_Company","Management_Level__c"
                    FROM contacts
                """

                # 1. Exact company name match
                cur.execute(
                    select + 'WHERE "Existing_Company" ILIKE %s LIMIT 100',
                    (company_name,),
                )
                _add(cur.fetchall())

                # 2. Domain match if not enough results
                if domain and len(results) < 10:
                    sld = domain.lower().lstrip("www.").split(".")[0]
                    cur.execute(
                        select + 'WHERE LOWER("Domain") LIKE %s LIMIT 100',
                        (f"%{sld}%",),
                    )
                    _add(cur.fetchall())

                # 3. Fuzzy LIKE on normalised name tokens if still sparse
                if len(results) < 5:
                    norm = _norm(company_name)
                    if len(norm) >= 5:
                        cur.execute(
                            select + 'WHERE LOWER("Existing_Company") LIKE %s LIMIT 100',
                            (f"%{norm[:8]}%",),
                        )
                        _add(cur.fetchall())

        conn.close()
    except Exception as e:
        logger.error(f"PG contacts lookup failed for '{company_name}': {e}")

    # Sort: contacts with validated email first
    results.sort(key=lambda c: (
        0 if c.get("email") else 1,
        0 if c.get("linkedin_url") else 1,
    ))
    return results[:100]
