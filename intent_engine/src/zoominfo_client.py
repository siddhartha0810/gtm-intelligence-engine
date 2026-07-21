"""
zoominfo_client.py
==================
ZoomInfo contact-discovery provider for the enrichment pipeline.

PURPOSE:
  Alternative to Apollo for Stage 3 (contact enrichment).  The user picks the
  provider (apollo | zoominfo) in the Engine Control pre-flight modal; when
  zoominfo is selected, apollo_enrichment.py calls search_contacts() here
  instead of its own _apollo_search().

HOW THE ZOOMINFO API WORKS (https://api-docs.zoominfo.com):
  1. POST /authenticate {username, password}   → {"jwt": "..."}  (valid 60 min)
  2. POST /search/contact                       → contact ids + names (NO emails)
     Authorization: Bearer <jwt>
     body: {"companyName": "...", "rpp": 25, "page": 1}
  3. POST /enrich/contact                       → full records WITH email/phone
     body: {"matchPersonInput": [{"personId": id}, ...],
            "outputFields": ["firstName", "lastName", "email", ...]}

  Search results cost nothing; each ENRICHED contact consumes ZoomInfo credits,
  so we only enrich the contacts we intend to keep.

CONFIG (intent_engine/.env):
  ZOOMINFO_USERNAME=...
  ZOOMINFO_PASSWORD=...

OUTPUT SHAPE:
  search_contacts() returns the same contact-dict shape produced by
  apollo_enrichment._apollo_call() so the rest of the pipeline (ZeroBounce
  validation, email prediction, save_contacts) works unchanged.
"""

import json
import re
import time
import urllib.error
import urllib.request

from src import config
from src.utils import get_logger

logger = get_logger(__name__)

ZI_AUTH_URL    = "https://api.zoominfo.com/authenticate"
ZI_SEARCH_URL  = "https://api.zoominfo.com/search/contact"
ZI_ENRICH_URL  = "https://api.zoominfo.com/enrich/contact"

RATE_LIMIT_DELAY = 1.0          # ZoomInfo allows ~25 req/s but be conservative
_JWT_TTL_SECONDS = 55 * 60      # tokens last 60 min — refresh at 55

# Fields requested from /enrich/contact — only what the pipeline stores
_ENRICH_OUTPUT_FIELDS = [
    "id", "firstName", "lastName", "email", "phone", "mobilePhone",
    "jobTitle", "managementLevel", "contactAccuracyScore",
    "externalUrls", "companyName", "companyWebsite",
    "city", "state", "country", "street", "zipCode",
]

# Module-level JWT cache: (token, fetched_at_monotonic)
_jwt_cache: dict = {"token": "", "ts": 0.0}


def is_configured() -> bool:
    """True when ZoomInfo username + password are present in the environment."""
    return bool(config.ZOOMINFO_USERNAME and config.ZOOMINFO_PASSWORD)


def _post_json(url: str, payload: dict, jwt: str = "") -> dict:
    """POST JSON and parse the response. Raises on HTTP/network errors."""
    headers = {"Content-Type": "application/json"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _get_jwt() -> str:
    """Return a cached JWT, re-authenticating when the token is near expiry."""
    if _jwt_cache["token"] and (time.monotonic() - _jwt_cache["ts"]) < _JWT_TTL_SECONDS:
        return _jwt_cache["token"]
    if not is_configured():
        return ""
    try:
        data = _post_json(ZI_AUTH_URL, {
            "username": config.ZOOMINFO_USERNAME,
            "password": config.ZOOMINFO_PASSWORD,
        })
        token = str(data.get("jwt") or "")
        if token:
            _jwt_cache["token"] = token
            _jwt_cache["ts"]    = time.monotonic()
        else:
            logger.error("ZoomInfo authenticate returned no jwt field")
        return token
    except urllib.error.HTTPError as e:
        logger.error(f"ZoomInfo auth HTTP {e.code} — check ZOOMINFO_USERNAME/PASSWORD")
        return ""
    except Exception as e:
        logger.error(f"ZoomInfo auth error: {e}")
        return ""


def _extract_linkedin(person: dict) -> str:
    """ZoomInfo returns social links in externalUrls: [{type, url}, ...]."""
    for item in (person.get("externalUrls") or []):
        if isinstance(item, dict) and "linkedin" in str(item.get("type", "")).lower():
            return str(item.get("url") or "").strip()
    return ""


def _clean_domain(raw: str) -> str:
    return re.sub(r"^https?://", "", str(raw or "")).lstrip("www.").split("/")[0].lower().strip()


def _search_ids(company_name: str, jwt: str, max_per: int) -> list[dict]:
    """Step 2: search contacts at a company. Returns raw person stubs (no emails)."""
    try:
        data = _post_json(ZI_SEARCH_URL, {
            "companyName": company_name,
            "rpp":         min(max_per, 25),
            "page":        1,
        }, jwt=jwt)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        logger.error(f"ZoomInfo search HTTP {e.code} [{company_name}]: {body}")
        return []
    except Exception as e:
        logger.error(f"ZoomInfo search error [{company_name}]: {e}")
        return []
    return [p for p in (data.get("data") or []) if isinstance(p, dict) and p.get("id")]


def _enrich_ids(person_ids: list, jwt: str) -> list[dict]:
    """Step 3: enrich person ids to full records with email. Costs credits."""
    if not person_ids:
        return []
    try:
        data = _post_json(ZI_ENRICH_URL, {
            "matchPersonInput": [{"personId": pid} for pid in person_ids],
            "outputFields":     _ENRICH_OUTPUT_FIELDS,
        }, jwt=jwt)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        logger.error(f"ZoomInfo enrich HTTP {e.code}: {body}")
        return []
    except Exception as e:
        logger.error(f"ZoomInfo enrich error: {e}")
        return []

    # Response shape: {"success": true, "data": {"result": [{"data": [person]}...]}}
    results = []
    payload = data.get("data") or {}
    for item in (payload.get("result") or []):
        for person in (item.get("data") or []):
            if isinstance(person, dict):
                results.append(person)
    return results


def search_contacts(company_name: str, max_per: int = 10,
                    relevance_filter=None) -> list[dict]:
    """
    Find + enrich contacts at a company via ZoomInfo.

    relevance_filter: optional callable(title) -> bool applied to search stubs
                      BEFORE enrichment, so credits are only spent on contacts
                      with Oracle/finance/IT-relevant titles.

    Returns contacts in the standard pipeline shape (same keys as Apollo).
    """
    jwt = _get_jwt()
    if not jwt:
        return []

    stubs = _search_ids(company_name, jwt, max_per=25)
    if not stubs:
        return []

    # Prefer relevant titles; fall back to all stubs if no titles match
    if relevance_filter:
        relevant = [s for s in stubs if relevance_filter(str(s.get("jobTitle") or ""))]
        if relevant:
            stubs = relevant
    stubs = stubs[:max_per]

    time.sleep(RATE_LIMIT_DELAY)
    enriched = _enrich_ids([s["id"] for s in stubs], jwt)

    # Index enriched records by id so stubs without an enrich hit are kept too
    enriched_by_id = {str(p.get("id")): p for p in enriched}

    contacts = []
    for stub in stubs:
        person = enriched_by_id.get(str(stub.get("id")), stub)
        first  = str(person.get("firstName") or stub.get("firstName") or "").strip()
        if not first:
            continue
        last   = str(person.get("lastName") or stub.get("lastName") or "").strip()
        email  = str(person.get("email") or "").strip().lower()
        title  = str(person.get("jobTitle") or stub.get("jobTitle") or "").strip()
        contacts.append({
            "first_name":              first,
            "last_name":               last,
            "full_name":               f"{first} {last}".strip(),
            "title":                   title,
            "email":                   email or None,
            "linkedin_url":            _extract_linkedin(person) or None,
            "phone":                   str(person.get("phone") or person.get("mobilePhone") or "").strip(),
            "city":                    str(person.get("city") or "").strip(),
            "state":                   str(person.get("state") or "").strip(),
            "country":                 str(person.get("country") or "").strip(),
            "street":                  str(person.get("street") or "").strip(),
            "postal_code":             str(person.get("zipCode") or "").strip(),
            "domain":                  _clean_domain(person.get("companyWebsite")),
            "source":                  "zoominfo",
            "confidence":              0.8,
            "is_target":               1,
            "email_validation_status": None,
        })
    return contacts
