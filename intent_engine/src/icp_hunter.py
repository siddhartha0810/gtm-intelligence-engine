"""
icp_hunter.py
=============
Fetches YC-backed companies matching a configurable ICP from the public
yc-oss/api. Returns companies filtered by tag, batch recency, and team size.

No API key required — yc-oss/api is a free public GitHub Pages endpoint.

DEFAULT_ICP_TAGS below is just a starting point (AI/dev-tool/infra
startups) — pass your own tags via search_icp(keywords=[...]) to target a
different ICP entirely; they replace the defaults rather than adding to them.

Usage:
    from intent_engine.src.icp_hunter import fetch_icp_companies
    companies = fetch_icp_companies()
    # [{"name": "Browserbase", "website": "https://browserbase.com", ...}, ...]
"""

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BASE = "https://yc-oss.github.io/api"
_TIMEOUT = 15

# Default tags — a reasonable starting ICP (AI / dev-tool / infra startups).
# Only include slugs that exist on yc-oss.github.io/api/tags/<slug>.json
# Override entirely via search_icp(keywords=[...]) for a different ICP.
DEFAULT_ICP_TAGS = {
    "developer-tools",
    "ai",
    "infrastructure",
    "devops",
    "analytics",
    "api",
    "ml",
    "artificial-intelligence",
    "saas",
}

# yc-oss API uses full batch names: "Winter 2025", "Summer 2024", etc.
RECENT_BATCHES = {
    "Winter 2026", "Spring 2026", "Summer 2026", "Fall 2026",
    "Winter 2025", "Spring 2025", "Summer 2025", "Fall 2025",
    "Winter 2024", "Summer 2024", "Fall 2024",
    "Winter 2023", "Summer 2023",
    "Winter 2022", "Summer 2022",
}

# Default team-size range (total headcount, not just engineers) — override
# via search_icp(min_team=..., max_team=...).
MIN_TEAM = 8
MAX_TEAM = 400


def _fetch_tag(tag: str) -> list[dict[str, Any]]:
    url = f"{_BASE}/tags/{tag}.json"
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"[ICP Hunter] Failed to fetch tag {tag}: {e}")
        return []


def _passes_filters(company: dict[str, Any]) -> bool:
    batch = company.get("batch", "") or ""
    if batch not in RECENT_BATCHES:
        return False

    team_size = company.get("team_size") or 0
    if team_size < MIN_TEAM or team_size > MAX_TEAM:
        return False

    # Must have a website
    if not company.get("website"):
        return False

    return True


def fetch_icp_companies(
    tags: set[str] | list[str] | None = None,
    min_team: int = MIN_TEAM,
    max_team: int = MAX_TEAM,
    batches: set[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Fetch YC companies matching an ICP defined by `tags` — replaces
    DEFAULT_ICP_TAGS entirely when given, so a custom ICP doesn't get
    diluted with unrelated AI/dev-tool companies.

    Returns a list of dicts with keys:
        name, website, one_liner, team_size, batch, tags, industry
    """
    tags_to_fetch = list(tags) if tags else list(DEFAULT_ICP_TAGS)

    effective_batches = batches if batches else RECENT_BATCHES

    seen_ids: set[int] = set()
    results: list[dict[str, Any]] = []

    for tag in tags_to_fetch:
        companies = _fetch_tag(tag)
        for co in companies:
            cid = co.get("id")
            if cid in seen_ids:
                continue

            batch = co.get("batch", "") or ""
            if batch not in effective_batches:
                continue

            ts = co.get("team_size") or 0
            if ts < min_team or ts > max_team:
                continue

            if not co.get("website"):
                continue

            seen_ids.add(cid)
            results.append({
                "id":          cid,
                "name":        co.get("name", ""),
                "website":     co.get("website", ""),
                "one_liner":   co.get("one_liner", ""),
                "team_size":   ts,
                "batch":       batch,
                "tags":        co.get("tags", []),
                "industry":    co.get("industry", ""),
                "subindustry": co.get("subindustry", ""),
                "slug":        co.get("slug", ""),
            })

        time.sleep(0.1)  # be polite to the CDN

        if len(results) >= limit:
            break

    # Sort: smallest teams first (earliest-stage companies surface first)
    results.sort(key=lambda c: c["team_size"])
    logger.info(f"[ICP Hunter] Found {len(results)} companies across {len(tags_to_fetch)} tags")
    return results[:limit]


def search_icp(
    keywords: list[str] | None = None,
    min_team: int = MIN_TEAM,
    max_team: int = MAX_TEAM,
    batches: list[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Flexible ICP search — called by the Campaign Builder API endpoint.
    keywords maps directly to tags, replacing DEFAULT_ICP_TAGS; if none
    given, falls back to the defaults.
    """
    batch_set = set(batches) if batches else RECENT_BATCHES
    return fetch_icp_companies(
        tags=set(keywords) if keywords else None,
        min_team=min_team,
        max_team=max_team,
        batches=batch_set,
        limit=limit,
    )
