"""
apollo_enrichment.py
====================
Post-scan contact enrichment pipeline for the Oracle Intent Engine.
Called by enrichment_worker.py as a child subprocess after each scan.

PURPOSE:
  For every company detected during a scan, find the decision-makers
  (CIOs, ERP managers, IT directors) with validated email addresses so
  the sales team can reach them.  Prioritises free data sources before
  spending Apollo or ZeroBounce credits.

HOW IT FITS IN THE SYSTEM:
  scan_worker.py scrapes job boards → writes companies to DB
       ↓
  enrichment_worker.py spawns this module
       ↓
  apollo_enrichment.py:
    1. contacts_master lookup (Salesforce CRM export — free, no API cost)
    2. Apollo people search  (costs credits — only if contacts_master miss)
    3. ZeroBounce validation (costs 1 credit/email)
    4. Email pattern prediction for contacts still missing emails
    5. ZeroBounce validate predicted emails
    6. Writes validated contacts → company_contacts table

KEY CLASSES/FUNCTIONS:
  enrich_companies()        — main entry point, loops over all companies
  _apollo_search()          — two-pass Apollo search (targeted → broad)
  _zb_batch_validate()      — validates a list of emails via ZeroBounce
  _predict_and_fill_emails() — learns email naming patterns, predicts + validates
  _detect_email_pattern()   — maps (first, last, email) → pattern name
  _build_predicted_email()  — applies a pattern to produce a candidate email

DEPENDENCIES:
  - Apollo API  : X-Api-Key header (NOT Authorization: Bearer)
  - ZeroBounce  : batch API, 1 credit per email validated
  - oracle_intent_engine/src/database.py  : reads/writes company_contacts
  - contacts_master table : READ-ONLY Salesforce CRM export
  - email_patterns table  : domain → naming pattern (from COMPANY_FORMAT_ANALYSIS)

DOMAIN KNOWLEDGE:
  Apollo confidence scores (oracle_signals.confidence):
    0.90 — explicit Oracle product + company name in same job post
    0.80 — Oracle product name in job title
    0.75 — strong Oracle indicator in job description
    0.60 — generic Oracle context (could be staffing)
    0.50 — weak signal, Oracle mentioned in passing
    <0.40 — not stored at all
  ZeroBounce status:
    valid       — safe to contact
    invalid     — do not send (mailbox does not exist)
    catch-all   — server accepts all mail (may or may not be real)
    spamtrap    — will damage sender reputation, never send
    do_not_mail — role address or disposable domain
"""

import json
import re
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from src import database as db
from src import domain_enricher
from src import zoominfo_client
from src.utils import get_logger

logger = get_logger(__name__)

APOLLO_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
APOLLO_REVEAL_URL = "https://api.apollo.io/api/v1/people/match"
ZB_BATCH_URL      = "https://bulkapi.zerobounce.net/v2/validatebatch"
ZB_CREDITS_URL    = "https://api.zerobounce.net/v2/getcredits"

RATE_LIMIT_DELAY = 1.2   # seconds between Apollo calls

# ── Email prediction patterns ────────────────────────────────────────────────
# Self-contained — no pandas needed.  Mirrors lead_enrichment_engine/src/email_pattern_engine.py
# so both engines produce identical predictions.

_PREDICTION_PATTERNS = {
    "first.last": lambda f, l: f"{f}.{l}",
    "firstlast":  lambda f, l: f"{f}{l}",
    "flast":      lambda f, l: f"{f[0]}{l}",
    "first_last": lambda f, l: f"{f}_{l}",
    "f.last":     lambda f, l: f"{f[0]}.{l}",
    "first.l":    lambda f, l: f"{f}.{l[0]}",
    "last.first": lambda f, l: f"{l}.{f}",
    "first":      lambda f, l: f,
    "lastf":      lambda f, l: f"{l}{f[0]}",
    "last.f":     lambda f, l: f"{l}.{f[0]}",
    # Patterns from COMPANY_FORMAT_ANALYSIS reference data
    "firstl":     lambda f, l: f"{f}{l[0]}",   # john + s → johns (first + last initial)
    "last":       lambda f, l: l,               # smith only (last name)
}

# Industry-standard fallback when no domain-specific pattern is known.
# Ordered by prevalence across enterprise B2B (flast ~40%, first.last ~30%)
_DEFAULT_PREDICTION_ORDER = ["flast", "first.last", "first_last"]

# How many global-fallback candidates to generate per unknown-domain contact.
# Each is validated by ZeroBounce; the first valid hit wins.
_TOP_N_CANDIDATES = 3


def _pname(value: str) -> str:
    """Normalise a name part for pattern matching — lowercase, strip spaces/hyphens."""
    return str(value or "").lower().strip().replace(" ", "").replace("-", "")


def _detect_email_pattern(first_name: str, last_name: str, email: str) -> str | None:
    """
    Return which naming pattern the given email follows, or None if no match.

    Example:
      _detect_email_pattern("John", "Smith", "jsmith@acme.com") → "flast"
      _detect_email_pattern("John", "Smith", "info@acme.com")   → None
    """
    if not email or "@" not in str(email):
        return None
    first = _pname(first_name)
    last  = _pname(last_name)
    if not first or not last:
        return None
    local = str(email).split("@")[0].lower().strip()
    for pattern, formatter in _PREDICTION_PATTERNS.items():
        try:
            if local == formatter(first, last):
                return pattern
        except Exception:
            continue
    return None


def _build_predicted_email(first_name: str, last_name: str, domain: str, pattern: str) -> str:
    """Construct a predicted email from name + domain + pattern."""
    first  = _pname(first_name)
    last   = _pname(last_name)
    domain = str(domain or "").lower().strip()
    if not first or not last or not domain or pattern not in _PREDICTION_PATTERNS:
        return ""
    try:
        return f"{_PREDICTION_PATTERNS[pattern](first, last)}@{domain}"
    except Exception:
        return ""


def _predict_and_fill_emails(
    contacts: list,
    zerobounce_key: str,
    company_domain: str,
    log: Callable,
    reference_patterns: dict = None,
) -> tuple[list, int]:
    """
    Stage 5+6: Email prediction for contacts that still have no email.

    Algorithm:
      1. Learn domain patterns from contacts with validated emails in this batch.
      1b. Merge with pre-loaded reference_patterns from the email_patterns DB table
          (sourced from COMPANY_FORMAT_ANALYSIS.xlsx — 40k companies, ~280k contacts).
          Live-validated patterns take priority; reference fills gaps.
      2. For each no-email contact with a known domain:
           - If domain pattern is known → try known patterns first
           - Otherwise → try _DEFAULT_PREDICTION_ORDER fallbacks
      3. Batch-validate all candidates with ZeroBounce.
      4. For each contact, apply the first candidate whose status = 'valid'.
      5. Mark email_source='predicted' and email_prediction_pattern=<pattern>.

    Returns (updated_contacts, count_of_new_predictions).
    """
    if not zerobounce_key:
        return contacts, 0

    # Step 1: learn domain → [pattern, ...] from contacts with valid emails in this batch
    domain_patterns: dict[str, list[str]] = {}  # domain → ordered list of patterns seen
    for c in contacts:
        if not c.get("email") or c.get("email_validation_status") != "valid":
            continue
        dom = (c.get("domain") or company_domain or "").lower().strip()
        if not dom:
            continue
        pat = _detect_email_pattern(c.get("first_name", ""), c.get("last_name", ""), c["email"])
        if pat:
            domain_patterns.setdefault(dom, [])
            if pat not in domain_patterns[dom]:
                domain_patterns[dom].append(pat)

    # Step 1b: fill gaps with reference patterns from email_patterns DB table
    # (pre-loaded from COMPANY_FORMAT_ANALYSIS.xlsx — highest sample_count first)
    if reference_patterns:
        for dom, ref_pats in reference_patterns.items():
            if dom not in domain_patterns:
                domain_patterns[dom] = list(ref_pats)
            else:
                # Append reference patterns not already known from live data
                for p in ref_pats:
                    if p not in domain_patterns[dom]:
                        domain_patterns[dom].append(p)

    # Step 2: build candidate list for contacts with no email
    # candidate_map: email_string → (contact_index, pattern_name)
    candidate_map: dict[str, tuple[int, str]] = {}
    # contact_candidates: contact_index → [email1, email2, ...]  (ordered preference)
    contact_candidates: dict[int, list[str]] = {}

    for idx, c in enumerate(contacts):
        if c.get("email"):
            continue  # already has an email
        first = c.get("first_name", "")
        last  = c.get("last_name", "")
        if not first or not last:
            continue  # can't predict without both name parts

        dom = (c.get("domain") or company_domain or "").lower().strip()
        if not dom:
            continue  # can't predict without a domain

        # Choose patterns to try for this domain
        patterns_to_try = (domain_patterns.get(dom) or []) + [
            p for p in _DEFAULT_PREDICTION_ORDER if p not in (domain_patterns.get(dom) or [])
        ]
        patterns_to_try = patterns_to_try[:_TOP_N_CANDIDATES]

        candidates_for_this = []
        for pat in patterns_to_try:
            email = _build_predicted_email(first, last, dom, pat)
            if email and email not in candidate_map:
                candidate_map[email] = (idx, pat)
                candidates_for_this.append(email)

        if candidates_for_this:
            contact_candidates[idx] = candidates_for_this

    if not candidate_map:
        return contacts, 0  # nothing to predict

    # Step 3: ZeroBounce validate all candidates in one batch
    all_candidates = list(candidate_map.keys())
    log(f"  ~ predicting emails: {len(contact_candidates)} contacts, "
        f"{len(all_candidates)} candidates → ZeroBounce")
    validation = _zb_validate_batch(all_candidates, zerobounce_key)

    # Step 4+5: apply the first valid prediction for each contact
    filled = 0
    contacts = [dict(c) for c in contacts]  # shallow-copy so we don't mutate in place

    for idx, candidate_emails in contact_candidates.items():
        for email in candidate_emails:
            zb = validation.get(email.lower(), {})
            status = zb.get("status", "unknown")
            if status == "valid":
                _, pat = candidate_map[email]
                contacts[idx]["email"]                    = email
                contacts[idx]["email_source"]             = "predicted"
                contacts[idx]["email_prediction_pattern"] = pat
                contacts[idx]["email_validation_status"]  = "valid"
                filled += 1
                break  # first valid hit wins; don't try other candidates

    return contacts, filled


# Pass-1: exact Oracle/JDE/Finance/IT titles — very targeted
# Includes user-specified target roles plus standard Oracle/JDE roles
ORACLE_JDE_TITLES = [
    # User-specified exact roles
    "Oracle Apps DBA",
    "Oracle Business Analyst",
    "Finance Project Manager",
    "Oracle Cloud HCM Support Analyst",
    "Oracle Cloud Support Analyst",
    "Senior System Analyst",
    "Oracle Fusion Senior Support Agent",
    "Oracle Fusion Test Manager",
    "Oracle Change & Release Manager",
    "Head of Oracle Support",
    "Senior Transformation Leader",
    "Group Programme Director",
    "Senior Project Manager",
    "Project and Programme Delivery",
    "Head of Finance Systems",
    # Standard Oracle/JDE roles
    "JD Edwards", "JDE", "JDE EnterpriseOne",
    "Oracle ERP", "Oracle Cloud", "Oracle Fusion", "Oracle EBS",
    "Oracle HCM", "Oracle SCM", "Oracle EPM", "Oracle NetSuite",
    "ERP Manager", "ERP Director", "ERP Consultant", "ERP Project Manager",
    "Finance Director", "Financial Controller", "CFO", "VP Finance",
    "IT Director", "CIO", "CTO", "VP IT", "IT Manager",
    "Enterprise Applications Manager", "Business Systems Manager",
    "Supply Chain Director", "Operations Director",
    "Digital Transformation Manager", "Oracle Developer",
    "Chief Information Officer", "Chief Technology Officer",
    "Chief Financial Officer", "Head of IT", "Head of Finance",
    "IT Architect", "Enterprise Architect", "Solutions Architect",
    "Business Systems Analyst", "Financial Systems Manager",
    "Application Manager", "Applications Director",
    "Transformation Director", "Programme Director",
    "Project Manager", "Programme Manager",
]

# Keywords used to score pass-2 (broad) contacts — any match → keep
_RELEVANCE_KEYWORDS = [
    "oracle", "jd edwards", "jde", "erp", "enterprise resource",
    "fusion", "hcm", "cloud",
    "finance", "financial", "controller", "accounting", "accounts",
    "supply chain", "procurement", "operations",
    "information technology", "it director", "it manager", "systems",
    "cfo", "cio", "cto", "vp finance", "vp it",
    "digital transformation", "business systems", "enterprise applications",
    "architect", "architecture", "transformation", "programme",
    "financial system", "business system", "application", "project manager",
]

# Default role filters when user hasn't customised (matches ORACLE_JDE_TITLES above)
DEFAULT_ROLE_FILTERS = ORACLE_JDE_TITLES

# ── Live status (read by enrichment_worker's status thread) ─────────────────
_status: dict = {
    "status": "idle",
    "progress": "",
    "companies_processed": 0,
    "companies_total": 0,
    "contacts_found": 0,
    "contacts_validated": 0,
}


def current_status() -> dict:
    return dict(_status)


# ── Apollo helpers ───────────────────────────────────────────────────────────

# Legal suffixes to strip before sending to Apollo
_LEGAL_SUFFIXES = [
    ", llc", ", inc.", ", inc", ", ltd.", ", ltd", ", corp.", ", corp",
    ", l.l.c.", ", l.l.c", ", plc", ", llp", ", lp", ", gmbh", ", s.a.",
    " llc", " inc.", " inc", " ltd.", " ltd", " corp.", " corp",
    " limited", " l.l.c.", " l.l.c", " plc", " llp", " lp", " gmbh",
    " s.a.", " s.a", " ag", " nv", " bv", " co.", " co",
]


def _clean_company_name(name: str) -> str:
    """Return a clean company name suitable for Apollo search.

    Strips parenthetical abbreviations, legal suffixes, and stray punctuation
    that confuse Apollo's org-name matching.

    Examples:
      "Net2Source (N2S)"              -> "Net2Source"
      "Plastpro,Inc"                  -> "Plastpro"
      "G&W Electric Co."              -> "G&W Electric"
      "Chugach Government Solutions, LLC" -> "Chugach Government Solutions"
      "McDermott International, Ltd"  -> "McDermott International"
    """
    n = name.strip()
    # Remove parenthetical parts like "(N2S)" or "(formerly XYZ)"
    n = re.sub(r"\s*\(.*?\)", "", n).strip()
    # Strip legal suffixes (case-insensitive comparison)
    lower = n.lower()
    for suf in _LEGAL_SUFFIXES:
        if lower.endswith(suf):
            n = n[: len(n) - len(suf)].strip()
            lower = n.lower()
            break
    # Remove stray trailing punctuation
    n = n.rstrip(".,;:-").strip()
    return n or name  # fallback to original if cleaned name is empty


def _is_relevant_contact(title: str) -> bool:
    """Return True if the contact title contains any Oracle/finance/IT keyword."""
    t = title.lower()
    return any(kw in t for kw in _RELEVANCE_KEYWORDS)


def apollo_person_match(api_key: str, email: str = None, first_name: str = None,
                        last_name: str = None, company_name: str = None,
                        domain: str = None) -> dict:
    """
    Match one person on Apollo (POST /people/match) and return their record.

    Used by the list-import completion flow:
      - match by email          → fills missing LinkedIn URL
      - match by name + company → fills missing email AND LinkedIn URL

    Returns {} when no match. Costs 1 Apollo credit per successful match.
    """
    if not api_key:
        return {}
    payload: dict = {"reveal_personal_emails": True}
    if email:
        payload["email"] = email
    if first_name:
        payload["first_name"] = first_name
    if last_name:
        payload["last_name"] = last_name
    if company_name:
        payload["organization_name"] = company_name
    if domain:
        payload["domain"] = domain
    if len(payload) <= 1:
        return {}  # nothing to match on

    try:
        req = urllib.request.Request(
            APOLLO_REVEAL_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-Api-Key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning(f"Apollo person match failed ({email or company_name}): {e}")
        return {}

    person = data.get("person") or {}
    if not isinstance(person, dict):
        return {}
    return {
        "email":        str(person.get("email") or "").strip().lower(),
        "linkedin_url": str(person.get("linkedin_url") or "").strip(),
        "title":        str(person.get("title") or "").strip(),
        "first_name":   str(person.get("first_name") or "").strip(),
        "last_name":    str(person.get("last_name") or "").strip(),
    }


def _apollo_person_match(person_id: str, api_key: str, reveal_email: bool = False) -> dict:
    """
    Call Apollo /people/match for a person by their Apollo ID.
    Returns the full person dict (includes linkedin_url, email, etc.) or {}.
    Uses credits — call only when necessary.
    """
    if not person_id or not api_key:
        return {}
    try:
        payload = json.dumps({
            "id": person_id,
            "reveal_personal_emails": reveal_email,
        }).encode()
        req = urllib.request.Request(
            APOLLO_REVEAL_URL, data=payload,
            headers={"Content-Type": "application/json", "X-Api-Key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get("person") or {}
    except Exception:
        return {}


def _apollo_reveal(person_id: str, api_key: str) -> str:
    """Reveal a locked Apollo email by person ID. Returns email or ''."""
    person = _apollo_person_match(person_id, api_key, reveal_email=True)
    return str(person.get("email") or "").strip().lower()


def _apollo_call(org_name: str, api_key: str, max_per: int,
                 with_titles: bool, role_filters: list = None) -> list:
    """Single Apollo API call. Returns raw parsed contacts list."""
    payload_dict = {
        "q_organization_name": org_name,
        "per_page": min(max_per, 25),
        "page": 1,
    }
    if with_titles:
        payload_dict["person_titles"] = role_filters if role_filters else ORACLE_JDE_TITLES

    try:
        req = urllib.request.Request(
            APOLLO_SEARCH_URL,
            data=json.dumps(payload_dict).encode(),
            headers={"Content-Type": "application/json", "X-Api-Key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        logger.error(f"Apollo HTTP {e.code} [{org_name}]: {body}")
        return []
    except Exception as e:
        logger.error(f"Apollo API error [{org_name}]: {e}")
        return []

    if data.get("error"):
        logger.warning(f"Apollo error [{org_name}]: {data['error']}")
        return []

    people = data.get("people") or data.get("contacts") or []
    contacts = []
    for p in people:
        if not isinstance(p, dict):
            continue
        first = str(p.get("first_name") or "").strip()
        if not first:
            continue

        email        = str(p.get("email") or "").strip().lower()
        email_status = str(p.get("email_status") or "").lower()

        if not email and p.get("has_email"):
            email        = _apollo_reveal(str(p.get("id") or ""), api_key)
            email_status = "revealed" if email else ""
            time.sleep(0.3)

        if email_status in ("unavailable", "bounced", "invalid"):
            email = ""

        org  = p.get("organization") or p.get("account") or {}
        domain = ""
        if isinstance(org, dict):
            raw    = str(org.get("primary_domain") or org.get("domain") or org.get("website_url") or "")
            domain = re.sub(r"^https?://", "", raw).lstrip("www.").split("/")[0].lower().strip()

        last  = str(p.get("last_name") or "").strip()
        title = str(p.get("title") or p.get("headline") or "").strip()

        # Industry from org object
        industry = ""
        if isinstance(org, dict):
            industry = str(org.get("industry") or "").strip()

        # Location from person-level city/state/country
        location_parts = [str(p.get(k) or "").strip() for k in ("city", "state", "country") if p.get(k)]
        location = ", ".join(location_parts)

        # Resolve LinkedIn URL — direct field first, then from uid
        linkedin = str(p.get("linkedin_url") or "").strip()
        if not linkedin:
            uid = str(p.get("linkedin_uid") or "").strip()
            if uid and not uid.startswith("http"):
                linkedin = f"https://www.linkedin.com/in/{uid}"
            elif uid:
                linkedin = uid

        # If still no LinkedIn, use credits to call Person Match for full profile
        person_id = str(p.get("id") or "").strip()
        if not linkedin and person_id:
            full = _apollo_person_match(person_id, api_key, reveal_email=not email)
            linkedin = str(full.get("linkedin_url") or "").strip()
            if not email:
                email = str(full.get("email") or "").strip().lower()
                email_status = str(full.get("email_status") or "").lower()
                if email_status in ("unavailable", "bounced", "invalid"):
                    email = ""
            # Fill missing fields from full profile
            if not last:
                last = str(full.get("last_name") or "").strip()
            if not title:
                title = str(full.get("title") or full.get("headline") or "").strip()
            if not industry:
                full_org = full.get("organization") or {}
                if isinstance(full_org, dict):
                    industry = str(full_org.get("industry") or "").strip()
            if not location:
                loc_parts = [str(full.get(k) or "").strip() for k in ("city", "state", "country") if full.get(k)]
                location = ", ".join(loc_parts)
            if person_id:
                time.sleep(0.3)  # rate-limit match calls

        linkedin = linkedin or None

        # Skip contacts with no email AND no LinkedIn — zero outreach value
        if not email and not linkedin:
            continue

        contacts.append({
            "first_name":              first,
            "last_name":               last,
            "full_name":               f"{first} {last}".strip(),
            "title":                   title,
            "email":                   email or None,
            "linkedin_url":            linkedin,
            "domain":                  domain,
            "industry":                industry or None,
            "location":                location or None,
            "source":                  "apollo",
            "confidence":              0.8,
            "is_target":               1,
            "email_validation_status": email_status if email else None,
        })
    return contacts


def _apollo_search(company_name: str, api_key: str, max_per: int = 10,
                   role_filters: list = None) -> tuple:
    """
    Two-pass Apollo search.

    Pass 1 — clean name + role_filters title filter (targeted, fast).
    Pass 2 — if pass 1 returns nothing, retry without title filter and
              keep only contacts whose title contains a relevance keyword.
              If even after filtering nothing remains, keep all pass-2
              contacts (company has oracle signals, any contact is useful).

    Returns (contacts, pass_used) where pass_used is 1 or 2.
    """
    if not api_key:
        return [], 0

    clean = _clean_company_name(company_name)

    # Pass 1 — targeted with role filters
    contacts = _apollo_call(clean, api_key, max_per, with_titles=True, role_filters=role_filters)
    if contacts:
        return contacts, 1

    time.sleep(RATE_LIMIT_DELAY)  # rate-limit gap between the two passes

    # Pass 2 — broad search
    contacts = _apollo_call(clean, api_key, max_per, with_titles=False)
    if not contacts:
        return [], 2

    # Prefer contacts with relevant titles; fall back to all if none match
    relevant = [c for c in contacts if _is_relevant_contact(c.get("title", ""))]
    return (relevant if relevant else contacts), 2


# ── ZeroBounce helpers ───────────────────────────────────────────────────────

def _zb_credits(api_key: str) -> Optional[int]:
    if not api_key:
        return None
    try:
        url = f"{ZB_CREDITS_URL}?api_key={api_key}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        n = int(data.get("Credits", -1))
        return None if n == -1 else n
    except Exception:
        return None


def _zb_validate_batch(emails: list, api_key: str) -> dict:
    """
    Validate up to 200 emails via ZeroBounce batch API.
    Returns {email_lower: {"status": "...", "sub_status": "..."}}

    Statuses that are safe to send: valid
    Do-not-send: invalid, spamtrap, abuse, do_not_mail
    Uncertain: catch-all, unknown
    """
    if not api_key or not emails:
        return {e: {"status": "not_validated", "sub_status": "no_key"} for e in emails}

    CHUNK = 200
    result: dict = {}
    for i in range(0, len(emails), CHUNK):
        batch = emails[i:i + CHUNK]
        payload = json.dumps({
            "api_key":     api_key,
            "email_batch": [{"email_address": e} for e in batch],
        }).encode()
        try:
            req = urllib.request.Request(
                ZB_BATCH_URL, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            logger.warning(f"ZeroBounce batch error: {e}")
            result.update({e: {"status": "unknown", "sub_status": "api_error"} for e in batch})
            continue

        for item in (data.get("email_batch") or []):
            addr = (item.get("address") or item.get("email_address") or "").lower().strip()
            if addr:
                result[addr] = {
                    "status":     item.get("status",     "unknown"),
                    "sub_status": item.get("sub_status", ""),
                }
    return result


def master_rows_to_contacts(master_rows: list) -> list:
    """Convert contacts_master rows (Salesforce export) into the standard
    pipeline contact shape. All rows passed the ZB_Valid_Email = 'Yes' filter,
    so they arrive pre-validated — no ZeroBounce credits needed."""
    contacts = []
    for c in master_rows:
        first = c.get("first_name") or ""
        last  = c.get("last_name")  or ""
        contacts.append({
            "full_name":               f"{first} {last}".strip(),
            "first_name":              first,
            "last_name":               last,
            "title":                   c.get("job_title") or "",
            "email":                   c.get("email") or None,
            "linkedin_url":            c.get("linkedin_url") or None,
            "phone":                   c.get("phone") or "",
            "city":                    c.get("city") or "",
            "state":                   c.get("state") or "",
            "country":                 c.get("country") or "",
            "street":                  c.get("street") or "",
            "postal_code":             c.get("postal_code") or "",
            "domain":                  c.get("domain") or "",
            "source":                  "contacts_master",
            "confidence":              0.9,
            "is_target":               1,
            "email_validation_status": c.get("email_validation_status") or None,
        })
    return contacts


# ── Stage 7 — scoring ────────────────────────────────────────────────────────

def _score_contacts(contacts: list, target_product: str) -> list:
    """
    Stage 7: mark each contact ready_for_outreach and tag the Oracle product
    this person should be pitched (JD Edwards, Oracle Fusion, ...).

    Pass criteria (mirrors lead_enrichment_engine/src/scoring.py):
      valid email                              → ready
      catch-all email + LinkedIn URL present   → ready (LinkedIn is the backup channel)
      anything else                            → not ready
    """
    for c in contacts:
        c["target_product"] = target_product or ""
        status = str(c.get("email_validation_status") or "").lower().strip()
        # Only ZeroBounce-confirmed valid emails qualify — catch-all is not safe enough
        c["ready_for_outreach"] = bool(c.get("email") and status == "valid")
    return contacts


# ── Main pipeline ─────────────────────────────────────────────────────────────

def enrich_companies(
    apollo_key: str,
    zerobounce_key: str,
    limit: int = 50,
    max_per_company: int = 10,
    log: Callable = None,
    role_filters: list = None,
    batch_size: int = None,
    provider: str = "apollo",
    company_ids: list = None,
) -> dict:
    """
    Enrich companies that have intent signals but no contacts yet.

    Runs the same 7-stage flow as the standalone Lead Enrichment Engine:
      Stage 1 — clean company name        (_clean_company_name)
      Stage 2 — domain resolution         (domain_enricher, for companies missing one)
      Stage 3 — contact discovery         (contacts_master → Apollo OR ZoomInfo)
      Stage 4 — vendor email validation   (ZeroBounce)
      Stage 5 — email prediction          (pattern engine, for missing emails)
      Stage 6 — predicted email validation (ZeroBounce)
      Stage 7 — scoring                   (ready_for_outreach + target_product tag)

    Args:
        apollo_key:       Apollo API key for contact search.
        zerobounce_key:   ZeroBounce key for email validation.
        limit:            Max total companies to process this run.
        max_per_company:  Max contacts to fetch per company.
        log:              Callable for progress messages.
        role_filters:     List of job titles to search for (pass-1 filter).
                          Defaults to ORACLE_JDE_TITLES if not supplied.
        batch_size:       Process in sub-batches of this size with a pause between
                          (useful for rate limiting / credit control). None = no batching.
        provider:         "apollo" (default) or "zoominfo" — which paid API to use
                          when contacts_master has no match.
        company_ids:      Optional explicit list of company ids to enrich — used when
                          the user hand-picks companies from the scan results.

    Returns final status dict.
    """
    if log is None:
        log = lambda msg: logger.info(msg)

    provider = (provider or "apollo").lower().strip()

    # Resolve role filters — fall back to full ORACLE_JDE_TITLES list
    effective_roles = role_filters if role_filters else ORACLE_JDE_TITLES
    if role_filters:
        log(f"Role filters active: {len(effective_roles)} titles")

    _status.update({
        "status": "running",
        "progress": "Starting...",
        "companies_processed": 0,
        "companies_total": 0,
        "contacts_found": 0,
        "contacts_validated": 0,
    })

    if provider == "zoominfo":
        if not zoominfo_client.is_configured():
            log("ERROR: ZoomInfo selected but ZOOMINFO_USERNAME / ZOOMINFO_PASSWORD "
                "not set in oracle_intent_engine/.env")
            _status["status"] = "error"
            _status["progress"] = "ZoomInfo credentials not configured"
            return current_status()
        log("Contact provider: ZoomInfo")
    elif not apollo_key:
        log("ERROR: No Apollo API key configured — cannot enrich contacts.")
        _status["status"] = "error"
        _status["progress"] = "Apollo API key not configured"
        return current_status()
    else:
        log("Contact provider: Apollo")

    # Show ZeroBounce credit balance upfront
    if zerobounce_key:
        credits = _zb_credits(zerobounce_key)
        log(f"ZeroBounce credits available: {credits if credits is not None else 'unknown'}")
    else:
        log("No ZeroBounce key — emails will NOT be validated (stored as 'not_validated')")

    # Pre-load the email format reference table (sourced from COMPANY_FORMAT_ANALYSIS.xlsx).
    # This gives the prediction engine domain-specific patterns for ~40k companies before
    # any live enrichment runs — so even the very first Apollo contact can get a predicted
    # email if Apollo doesn't supply one.
    try:
        reference_patterns = db.load_domain_patterns()
        log(f"Email format reference loaded: {len(reference_patterns):,} domains")
    except Exception as e:
        reference_patterns = {}
        log(f"Warning: could not load email format reference ({e}) — using defaults only")

    # Fetch companies needing enrichment (optionally only the user-selected ones)
    companies = db.get_companies_needing_enrichment(limit, company_ids=company_ids)
    if company_ids:
        log(f"Enriching {len(companies)} hand-picked companies (of {len(company_ids)} selected)")
    _status["companies_total"] = len(companies)

    if not companies:
        log("All companies already enriched — nothing to do.")
        _status["status"] = "completed"
        _status["progress"] = "Already up to date"
        return current_status()

    log(f"Found {len(companies)} companies needing enrichment")
    total_contacts  = 0
    total_validated = 0

    for i, company in enumerate(companies):
        name           = company["name"]
        company_id     = company["id"]
        sig_count      = company.get("signal_count", "?")
        target_product = str(company.get("target_product") or "").strip()

        _status["progress"] = f"({i+1}/{len(companies)}) {name}"
        log(f"[{i+1}/{len(companies)}] {name}  ({sig_count} signals)"
            + (f"  → {target_product}" if target_product else ""))

        # Stage 2 — domain resolution for companies the scan couldn't resolve.
        # A domain is needed for Stage 5 email prediction to work.
        if not company.get("domain"):
            try:
                resolved = domain_enricher.lookup_domain(name)
                if resolved:
                    company["domain"] = resolved
                    db.set_company_domain(company_id, resolved)
                    log(f"  ~ domain resolved: {resolved}")
            except Exception as e:
                logger.warning(f"Domain resolution failed for {name}: {e}")

        # Stage 3a — check contacts_master first (Salesforce export — no API cost)
        master_rows = db.get_master_leads_by_company(name)
        if master_rows:
            to_save = master_rows_to_contacts(master_rows)
            to_save = _score_contacts(to_save, target_product)
            db.save_contacts(company_id, to_save)
            # All rows returned already passed the zb_valid_email = 'Yes' filter
            valid_ct = len(to_save)
            total_contacts  += valid_ct
            total_validated += valid_ct
            _status["contacts_found"]     = total_contacts
            _status["contacts_validated"] = total_validated
            _status["companies_processed"] += 1
            log(f"  + {valid_ct} contacts from contacts_master (ZB validated) — skipped Apollo")
            continue

        # Stage 3b — paid provider lookup (Apollo or ZoomInfo)
        if provider == "zoominfo":
            contacts = zoominfo_client.search_contacts(
                _clean_company_name(name), max_per=max_per_company,
                relevance_filter=_is_relevant_contact,
            )
            if not contacts:
                log(f"  — no contacts found on ZoomInfo")
                _status["companies_processed"] += 1
                time.sleep(RATE_LIMIT_DELAY)
                continue
            log(f"  + {len(contacts)} contacts from ZoomInfo")
        else:
            contacts, pass_used = _apollo_search(name, apollo_key, max_per_company,
                                                 role_filters=effective_roles)
            if not contacts:
                log(f"  — no contacts found on Apollo (pass 1 + pass 2 tried)")
                _status["companies_processed"] += 1
                time.sleep(RATE_LIMIT_DELAY)
                continue
            pass_label = "targeted" if pass_used == 1 else "broad fallback"
            log(f"  + {len(contacts)} contacts from Apollo ({pass_label})")

        # Stage 4: Validate Apollo emails in batch via ZeroBounce
        # Only VALID emails are kept — catch-all is cleared so the prediction engine
        # can attempt to find a confirmed-valid email for those contacts instead.
        emails_to_validate = [c["email"] for c in contacts if c.get("email")]
        if emails_to_validate and zerobounce_key:
            log(f"  ~ validating {len(emails_to_validate)} email(s)...")
            validation  = _zb_validate_batch(emails_to_validate, zerobounce_key)
            valid_count = 0
            cleared     = 0
            for c in contacts:
                raw = (c.get("email") or "").lower()
                if raw:
                    zb     = validation.get(raw, {})
                    status = zb.get("status", "not_validated")
                    if status == "valid":
                        c["email_validation_status"] = "valid"
                        valid_count += 1
                    elif status in ("catch-all", "catchall"):
                        # Clear catch-all email — let prediction engine attempt valid alternative
                        c["email"] = None
                        c["email_validation_status"] = None
                        cleared += 1
                    else:
                        # invalid / bounced / spamtrap / do_not_mail — discard
                        c["email"] = None
                        c["email_validation_status"] = status
            msg = f"  ~ {valid_count}/{len(emails_to_validate)} valid"
            if cleared:
                msg += f", {cleared} catch-all cleared (will attempt prediction)"
            log(msg)
            total_validated += valid_count
        elif emails_to_validate:
            for c in contacts:
                if c.get("email"):
                    c["email_validation_status"] = "not_validated"

        # Stage 5+6: Email prediction for contacts Apollo couldn't supply an email for.
        # Learns naming patterns from same-domain contacts with valid emails (e.g. the
        # domain uses "flast" format → predict jsmith@acme.com for remaining contacts),
        # then validates predictions with ZeroBounce before storing.
        no_email_count = sum(1 for c in contacts if not c.get("email"))
        if no_email_count and zerobounce_key:
            contacts, pred_count = _predict_and_fill_emails(
                contacts, zerobounce_key, company.get("domain", ""), log,
                reference_patterns=reference_patterns,
            )
            if pred_count:
                log(f"  ~ {pred_count} email(s) predicted and validated via pattern engine")
                total_validated += pred_count
        elif no_email_count:
            log(f"  ~ {no_email_count} contact(s) have no email — "
                "add ZeroBounce key to enable prediction")

        # Stage 7 — score readiness + tag the Oracle product to pitch, then save
        contacts = _score_contacts(contacts, target_product)
        db.save_contacts(company_id, contacts)
        total_contacts += len(contacts)
        _status["contacts_found"]     = total_contacts
        _status["contacts_validated"] = total_validated
        _status["companies_processed"] += 1

        time.sleep(RATE_LIMIT_DELAY)

        # Batch pause — give APIs (and credits) a breather between batches
        if batch_size and (i + 1) % batch_size == 0 and (i + 1) < len(companies):
            pause = 5  # seconds between batches
            log(f"── Batch {(i+1)//batch_size} complete "
                f"({i+1}/{len(companies)} companies). Pausing {pause}s before next batch...")
            time.sleep(pause)

    log(f"Enrichment complete: {total_contacts} contacts across {len(companies)} companies, "
        f"{total_validated} valid emails")
    _status["status"]   = "completed"
    _status["progress"] = f"Done — {total_contacts} contacts, {total_validated} valid emails"
    return current_status()
