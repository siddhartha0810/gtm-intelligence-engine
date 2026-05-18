"""
company_prospector.py
=====================
Given a list of company names, searches Apollo's People Search API
for contacts with Oracle / JDE-relevant job titles.

Flow per company:
  1. Check PostgreSQL master_leads (free — skips Apollo if contacts already exist)
  2. Call Apollo mixed_people/search with Oracle/JDE title filters
  3. Return contacts ready for ZeroBounce validation + PG storage

Apollo endpoint: POST /api/v1/mixed_people/search
  (different from bulk_match — this DISCOVERS people by company + title)
"""

import re
import time
from typing import Dict, List, Tuple

# ── Oracle / JDE job-title keywords sent to Apollo ────────────────────────────
ORACLE_JDE_TITLES: List[str] = [
    "JD Edwards", "JDE", "JD Edwards EnterpriseOne", "JD Edwards World",
    "Oracle ERP", "Oracle Cloud", "Oracle Fusion", "Oracle E-Business Suite",
    "Oracle EBS", "Oracle HCM", "Oracle SCM", "Oracle EPM", "Oracle PBCS",
    "ERP Manager", "ERP Director", "ERP Consultant", "ERP Analyst",
    "Finance Director", "Finance Manager", "Financial Controller",
    "Chief Financial Officer", "CFO", "VP Finance",
    "IT Director", "Chief Information Officer", "CIO", "VP Information Technology",
    "Enterprise Applications Manager", "Business Systems Manager",
    "Supply Chain Director", "Supply Chain Manager",
    "HR Director", "Chief Human Resources Officer", "CHRO",
    "Operations Director", "VP Operations",
    "Digital Transformation Manager", "Digital Transformation Director",
    "ERP Project Manager", "ERP Implementation",
    "Oracle Developer", "Oracle Functional Consultant", "Oracle Technical Consultant",
]

APOLLO_SEARCH_URL  = "https://api.apollo.io/api/v1/mixed_people/search"
MAX_PER_PAGE       = 25        # Apollo hard limit per request
RATE_LIMIT_DELAY   = 1.2       # seconds between Apollo calls


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    """Normalise company name the same way the rest of the pipeline does."""
    name = name.lower()
    name = re.sub(
        r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|co|company|plc|private|pvt)\b",
        "", name,
    )
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _parse_person(p: dict, company_name: str) -> dict:
    """Extract usable fields from an Apollo people-search result."""
    if not p or not isinstance(p, dict):
        return {}

    email        = str(p.get("email") or "").strip().lower()
    email_status = str(p.get("email_status") or "").lower()
    if email_status in ("unavailable", "bounced", "invalid"):
        email = ""

    org = p.get("organization") or p.get("account") or {}
    domain = str(
        (org.get("primary_domain") or org.get("domain") or org.get("website_url") or "")
        if isinstance(org, dict) else ""
    ).lower().strip()
    domain = re.sub(r"^https?://", "", domain).lstrip("www.").split("/")[0]

    return {
        "first_name":   str(p.get("first_name") or "").strip(),
        "last_name":    str(p.get("last_name")  or "").strip(),
        "company":      company_name,
        "job_title":    str(p.get("title") or p.get("headline") or "").strip(),
        "email":        email,
        "email_source": "apollo_prospect" if email else "",
        "linkedin_url": str(p.get("linkedin_url") or p.get("linkedin") or "").strip(),
        "domain":       domain,
    }


# ── Apollo People Search ──────────────────────────────────────────────────────

def search_people_at_company(
    company_name: str,
    apollo_api_key: str,
    max_people: int = 25,
    title_keywords: List[str] = None,
) -> List[dict]:
    """
    Search Apollo for people at `company_name` matching Oracle/JDE titles.
    Returns a list of contact dicts.
    """
    from .utils import request_json

    if not apollo_api_key:
        return []

    titles = title_keywords if title_keywords is not None else ORACLE_JDE_TITLES

    try:
        data = request_json(
            "POST",
            APOLLO_SEARCH_URL,
            json={
                "q_organization_name": company_name,
                "person_titles":       titles,
                "per_page":            min(max_people, MAX_PER_PAGE),
                "page":                1,
            },
            headers={
                "Content-Type": "application/json",
                "X-Api-Key":    apollo_api_key,
            },
        )
    except Exception as exc:
        print(f"    [prospector] Apollo search error for '{company_name}': {exc}")
        return []

    if not isinstance(data, dict):
        return []

    people = data.get("people") or data.get("contacts") or []
    return [c for p in people if (c := _parse_person(p, company_name)) and c.get("first_name")]


# ── PostgreSQL pre-check ──────────────────────────────────────────────────────

def _pg_lookup(company_names: List[str], conn_str: str) -> Dict[str, List[dict]]:
    """
    Check master_leads for existing validated contacts for these companies.
    Returns { company_normalized -> [contact_dict, ...] }.
    Silently returns {} on any error.
    """
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        return {}

    norms = [_normalize(n) for n in company_names if n and n.strip()]
    if not norms:
        return {}

    try:
        conn = psycopg2.connect(conn_str)
    except Exception as exc:
        print(f"    [prospector] PG connect failed: {exc}")
        return {}

    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM master_leads
                    WHERE  company_normalized = ANY(%s)
                      AND  email != ''
                      AND  (email_validation_status = 'valid' OR email_validation_status = '')
                    ORDER  BY company_normalized, ready_for_outreach DESC
                    """,
                    (norms,),
                )
                rows = cur.fetchall()
    except Exception:
        return {}
    finally:
        conn.close()

    result: Dict[str, List[dict]] = {}
    for r in rows:
        result.setdefault(r["company_normalized"], []).append(dict(r))
    return result


# ── Main prospecting function ─────────────────────────────────────────────────

def prospect_companies(
    company_names: List[str],
    apollo_api_key: str,
    pg_conn_str: str = "",
    max_people_per_company: int = 25,
    title_keywords: List[str] = None,
) -> Tuple[List[dict], dict]:
    """
    For each company in `company_names`:
      1. Check PostgreSQL master_leads — if contacts exist, use them (free).
      2. Otherwise call Apollo People Search with Oracle/JDE title filters.

    Returns:
      (all_contacts, stats)

    stats keys:
      total_companies   — how many companies were processed
      pg_hits           — companies whose contacts came from DB (cost $0)
      apollo_searched   — companies queried via Apollo
      total_contacts    — total contact rows returned
    """
    companies = [c.strip() for c in company_names if c and c.strip()]
    stats = {
        "total_companies": len(companies),
        "pg_hits":         0,
        "apollo_searched": 0,
        "total_contacts":  0,
    }

    # ── Step 1: bulk PG lookup ────────────────────────────────────────────────
    pg_results: Dict[str, List[dict]] = {}
    if pg_conn_str:
        print(f"    [prospector] Checking DB for {len(companies)} companies...")
        pg_results = _pg_lookup(companies, pg_conn_str)
        print(f"    [prospector] DB hit: {len(pg_results)} companies have existing contacts")

    # ── Step 2: per-company Apollo or DB pick ─────────────────────────────────
    all_contacts: List[dict] = []

    for company in companies:
        norm = _normalize(company)

        if norm in pg_results:
            contacts = pg_results[norm]
            print(f"    [prospector] ✓ {company} → {len(contacts)} contacts from DB (free)")
            all_contacts.extend(contacts)
            stats["pg_hits"] += 1

        else:
            print(f"    [prospector] ⟳ {company} → searching Apollo...")
            contacts = search_people_at_company(
                company_name=company,
                apollo_api_key=apollo_api_key,
                max_people=max_people_per_company,
                title_keywords=title_keywords,
            )
            found = len(contacts)
            print(f"    [prospector] {'✓' if found else '—'} {company} → {found} contacts via Apollo")
            all_contacts.extend(contacts)
            stats["apollo_searched"] += 1
            time.sleep(RATE_LIMIT_DELAY)   # stay inside Apollo rate limits

    stats["total_contacts"] = len(all_contacts)
    return all_contacts, stats
