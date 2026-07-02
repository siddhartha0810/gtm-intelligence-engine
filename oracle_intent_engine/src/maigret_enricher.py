"""
maigret_enricher.py
====================
LinkedIn URL gap-filler using maigret OSINT (soxoj/maigret).

Maigret checks a username across 3,000+ sites with no API keys required.
We use it to fill missing linkedin_url values in master_leads by deriving
username candidates from first_name + last_name + company patterns.

Install: pip install maigret

Usage:
    from src.maigret_enricher import fill_missing_linkedin_urls, find_social_profiles
    asyncio.run(fill_missing_linkedin_urls(limit=50))

The fill job is designed to run as a nightly background task. It only touches
rows where linkedin_url IS NULL and first_name + last_name are both present.
It never overwrites existing data.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_MAIGRET_AVAILABLE = False
try:
    import maigret  # noqa: F401
    _MAIGRET_AVAILABLE = True
except ImportError:
    logger.info(
        "[Maigret] maigret not installed — LinkedIn enrichment disabled. "
        "Run: pip install maigret"
    )


def _derive_usernames(first: str, last: str, company: str = "") -> list[str]:
    """
    Generate likely username patterns for a person.
    Ordered by probability — most common LinkedIn patterns first.
    """
    f = re.sub(r"[^a-z]", "", first.lower())
    l = re.sub(r"[^a-z]", "", last.lower())
    if not f or not l:
        return []

    candidates = [
        f"{f}{l}",          # johndoe
        f"{f}.{l}",         # john.doe
        f"{f[0]}{l}",       # jdoe
        f"{f}-{l}",         # john-doe
        f"{f}_{l}",         # john_doe
        f"{f[0]}.{l}",      # j.doe
    ]
    # Deduplicate while preserving order
    seen: set[str] = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]  # type: ignore[func-returns-value]


async def find_social_profiles(
    first: str,
    last: str,
    company: str = "",
    timeout: int = 8,
    top_sites_only: bool = True,
) -> dict[str, str]:
    """
    Run maigret for a contact and return any social profiles found.

    Args:
        first:          First name
        last:           Last name
        company:        Company name (used only for username generation heuristics)
        timeout:        Per-site HTTP timeout in seconds
        top_sites_only: If True, only check the top 500 sites (faster, still catches LinkedIn)

    Returns:
        {site_name: profile_url} — e.g. {"LinkedIn": "https://linkedin.com/in/johndoe"}
    """
    if not _MAIGRET_AVAILABLE:
        return {}

    from maigret.maigret import maigret as _maigret_search
    from maigret.sites import MaigretDatabase
    from maigret.result import QueryStatus

    usernames = _derive_usernames(first, last, company)
    if not usernames:
        return {}

    try:
        db = MaigretDatabase()
        db.load_from_path(None)  # loads bundled site database
        site_dict = db.sites_dict(top_sites_only)
    except Exception as e:
        logger.warning("[Maigret] Failed to load site database: %s", e)
        return {}

    found: dict[str, str] = {}

    for username in usernames[:3]:  # try top 3 username patterns
        try:
            results = await _maigret_search(
                username=username,
                site_dict=site_dict,
                query_notify=None,
                timeout=timeout,
                is_parsing_enabled=False,
                id_type="username",
                debug=False,
                logger=logger,
                forced=False,
                max_connections=5,
                no_progressbar=True,
                retries=1,
                check_domains=False,
            )
            for site_name, result in results.items():
                if result.status.status == QueryStatus.CLAIMED and site_name not in found:
                    found[site_name] = result.url
        except Exception as e:
            logger.debug("[Maigret] Username %s failed: %s", username, e)
            continue

        # If we found LinkedIn, that's enough — stop trying other usernames
        if any("linkedin" in k.lower() for k in found):
            break

    return found


def extract_linkedin_url(profiles: dict[str, str]) -> Optional[str]:
    """Pull the LinkedIn URL out of a maigret results dict."""
    for key, url in profiles.items():
        if "linkedin" in key.lower() or "linkedin" in url.lower():
            return url
    return None


async def fill_missing_linkedin_urls(limit: int = 50) -> dict:
    """
    Batch job: find contacts in master_leads with no linkedin_url and try to fill
    them via maigret. Designed to run nightly — never overwrites existing data.

    Returns: {found: int, checked: int, failed: int}
    """
    if not _MAIGRET_AVAILABLE:
        return {"found": 0, "checked": 0, "failed": 0, "error": "maigret not installed"}

    try:
        import oracle_intent_engine.src.database as db
    except Exception as e:
        return {"found": 0, "checked": 0, "failed": 0, "error": str(e)}

    try:
        with db.db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT id, first_name, last_name, company
                FROM master_leads
                WHERE linkedin_url IS NULL
                  AND first_name IS NOT NULL AND first_name != ''
                  AND last_name  IS NOT NULL AND last_name  != ''
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            rows = cur.fetchall()
    except Exception as e:
        logger.error("[Maigret] Failed to fetch leads: %s", e)
        return {"found": 0, "checked": 0, "failed": 0, "error": str(e)}

    found_count = failed_count = 0

    for row in rows:
        try:
            profiles = await find_social_profiles(
                first=row["first_name"],
                last=row["last_name"],
                company=row.get("company", ""),
                top_sites_only=True,
            )
            linkedin = extract_linkedin_url(profiles)
            if linkedin:
                with db.db_cursor() as cur:
                    cur.execute(
                        "UPDATE master_leads SET linkedin_url = ? WHERE id = ? AND linkedin_url IS NULL",
                        (linkedin, row["id"]),
                    )
                found_count += 1
                logger.info("[Maigret] Found LinkedIn for %s %s: %s",
                            row["first_name"], row["last_name"], linkedin)

            # Be polite — 1s between contacts
            await asyncio.sleep(1.0)

        except Exception as e:
            logger.warning("[Maigret] Failed for %s %s: %s",
                           row.get("first_name", ""), row.get("last_name", ""), e)
            failed_count += 1

    logger.info("[Maigret] Batch complete: %d found, %d checked, %d failed",
                found_count, len(rows), failed_count)

    try:
        from src.metrics import maigret_enrichments_total
        maigret_enrichments_total.inc(found_count)
    except Exception:
        pass

    return {
        "found":   found_count,
        "checked": len(rows),
        "failed":  failed_count,
    }
