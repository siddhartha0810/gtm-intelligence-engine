"""
Firmographics enrichment — company size via Wikidata (free, no key).

Wikidata has employee counts for most public and many private companies.
Falls back gracefully with no result when data is unavailable.
"""

import re
import requests
from src.utils import get_logger

logger = get_logger(__name__)

_WIKIDATA_SEARCH = "https://www.wikidata.org/w/api.php"
_WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
_HEADERS = {"User-Agent": "OracleIntentEngine/1.0 (research tool)"}

SIZE_BANDS = [
    (1,       50,    "1–50"),
    (51,      200,   "51–200"),
    (201,     1_000, "201–1K"),
    (1_001,   5_000, "1K–5K"),
    (5_001,   10_000,"5K–10K"),
    (10_001,  float("inf"), "10K+"),
]


def size_band(count: int) -> str:
    for lo, hi, label in SIZE_BANDS:
        if lo <= count <= hi:
            return label
    return "10K+"


def enrich(company_name: str) -> dict:
    """
    Returns dict with:
      employee_count: int | None
      size_band: str   e.g. "1K–5K"
      industry: str    from Wikidata if available
    """
    try:
        entity_id = _search_entity(company_name)
        if not entity_id:
            return {}
        return _fetch_properties(entity_id)
    except Exception as e:
        logger.debug(f"Firmographics error for '{company_name}': {e}")
        return {}


def _search_entity(name: str) -> str:
    resp = requests.get(
        _WIKIDATA_SEARCH,
        params={
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "type": "item",
            "format": "json",
            "limit": 3,
        },
        headers=_HEADERS,
        timeout=8,
    )
    results = resp.json().get("search", [])
    for r in results:
        desc = (r.get("description") or "").lower()
        # Prefer results that look like companies
        if any(w in desc for w in ("company", "corporation", "enterprise", "business", "organisation")):
            return r["id"]
    return results[0]["id"] if results else ""


def _fetch_properties(entity_id: str) -> dict:
    query = f"""
    SELECT ?employees ?industryLabel WHERE {{
      OPTIONAL {{ wd:{entity_id} wdt:P1128 ?employees. }}
      OPTIONAL {{ wd:{entity_id} wdt:P452 ?industry. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} LIMIT 1
    """
    resp = requests.get(
        _WIKIDATA_SPARQL,
        params={"query": query, "format": "json"},
        headers={**_HEADERS, "Accept": "application/sparql-results+json"},
        timeout=10,
    )
    rows = resp.json().get("results", {}).get("bindings", [])
    if not rows:
        return {}

    row = rows[0]
    result = {}

    if row.get("employees"):
        try:
            count = int(float(row["employees"]["value"]))
            result["employee_count"] = count
            result["size_band"] = size_band(count)
        except ValueError:
            pass

    if row.get("industryLabel"):
        result["industry"] = row["industryLabel"]["value"]

    return result
