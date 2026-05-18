"""
Domain lookup for company names — two free tiers, no API keys required.

Tier 1: Wikidata (P856 — official website property)
         Reliable for publicly known companies. ~2 requests per lookup.

Tier 2: DuckDuckGo Instant Answer API
         Covers companies Wikidata doesn't have. Single request, fast.

Results are cached in-process so repeated lookups (firmographics already
queried the same company) cost nothing.
"""

import re
import time
import requests
from urllib.parse import urlparse
from src.utils import get_logger

logger = get_logger(__name__)

_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_DDG_API      = "https://api.duckduckgo.com/"
_HEADERS      = {"User-Agent": "OracleIntentEngine/1.0 (research)"}

_cache: dict[str, str] = {}

_SKIP_DOMAINS = {
    "wikipedia.org", "wikidata.org",
    "twitter.com", "x.com",
    "linkedin.com", "facebook.com",
    "instagram.com", "youtube.com",
    "bloomberg.com", "reuters.com",
    "forbes.com", "wsj.com",
    "duckduckgo.com", "google.com",
}


def lookup_domain(company_name: str) -> str:
    """
    Return the primary domain for a company (e.g. "acmecorp.com").
    Returns "" if nothing reliable is found.
    """
    if not company_name:
        return ""
    key = company_name.strip().lower()
    if key in _cache:
        return _cache[key]

    domain = _from_wikidata(company_name) or _from_duckduckgo(company_name)
    _cache[key] = domain
    if domain:
        logger.debug(f"Domain enriched: '{company_name}' → {domain}")
    return domain


# ------------------------------------------------------------------ #
#  Tier 1 — Wikidata
# ------------------------------------------------------------------ #

def _from_wikidata(name: str) -> str:
    """
    Two-call approach using the Wikidata action API (no SPARQL — avoids rate limits).
    Call 1: search for entity ID.
    Call 2: fetch P856 (official website) claim directly.
    """
    try:
        # Step 1: find entity ID
        resp = requests.get(
            _WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "type": "item",
                "format": "json",
                "limit": 5,
            },
            headers=_HEADERS,
            timeout=6,
        )
        results = resp.json().get("search", [])
        if not results:
            return ""

        _company_words = {
            "company", "corporation", "organisation", "organization",
            "enterprise", "business", "bank", "hospital", "university",
            "group", "holding", "ltd", "inc", "publisher",
        }
        entity_id = None
        for r in results:
            desc = (r.get("description") or "").lower()
            if any(w in desc for w in _company_words):
                entity_id = r["id"]
                break
        if not entity_id:
            entity_id = results[0]["id"]

        # Step 2: fetch P856 (official website) via entity API (retry once on empty)
        for attempt in range(2):
            if attempt:
                time.sleep(0.5)
            resp2 = requests.get(
                _WIKIDATA_API,
                params={
                    "action": "wbgetentities",
                    "ids": entity_id,
                    "props": "claims",
                    "format": "json",
                },
                headers=_HEADERS,
                timeout=8,
            )
            if not resp2.text.strip():
                continue
            claims = (
                resp2.json()
                .get("entities", {})
                .get(entity_id, {})
                .get("claims", {})
            )
            p856 = claims.get("P856", [])
            if p856:
                url = p856[0]["mainsnak"]["datavalue"]["value"]
                return _clean_domain(url)
            break

    except Exception as e:
        logger.debug(f"Wikidata domain lookup failed for '{name}': {e}")
    return ""


# ------------------------------------------------------------------ #
#  Tier 2 — DuckDuckGo Instant Answer
# ------------------------------------------------------------------ #

def _from_duckduckgo(name: str) -> str:
    try:
        resp = requests.get(
            _DDG_API,
            params={"q": name, "format": "json", "no_html": "1", "skip_disambig": "1"},
            headers=_HEADERS,
            timeout=6,
        )
        data = resp.json()

        for key in ("OfficialSite", "AbstractURL"):
            url = data.get(key, "")
            if url:
                domain = _clean_domain(url)
                if domain:
                    return domain

        for item in data.get("Infobox", {}).get("content", []):
            if item.get("label", "").lower() in ("website", "official website"):
                domain = _clean_domain(item.get("value", ""))
                if domain:
                    return domain
    except Exception as e:
        logger.debug(f"DuckDuckGo domain lookup failed for '{name}': {e}")
    return ""


# ------------------------------------------------------------------ #
#  Shared helper
# ------------------------------------------------------------------ #

def _clean_domain(url: str) -> str:
    """Extract bare SLD+TLD domain from a URL, filtering known junk domains."""
    if not url:
        return ""
    try:
        if "://" not in url:
            url = f"https://{url}"
        parsed = urlparse(url)
        domain = parsed.netloc.lower().lstrip("www.")
        # Strip port if present
        domain = domain.split(":")[0]
        if domain and not any(skip in domain for skip in _SKIP_DOMAINS):
            return domain
    except Exception:
        pass
    return ""
