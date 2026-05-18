"""
Adzuna job board API — free tier (250 calls/day).
Register at https://developer.adzuna.com/ to get APP_ID + APP_KEY.
Falls back to no results gracefully when keys are not set.

Adzuna covers: UK, US, Australia, Canada, Germany, France, and more.
Country is inferred from the location string (defaults to 'us').
"""

import requests
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name
from src import config

logger = get_logger(__name__)

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"

# Location keyword → Adzuna country code
_COUNTRY_MAP = {
    "uk": "gb", "united kingdom": "gb", "england": "gb",
    "scotland": "gb", "wales": "gb", "london": "gb",
    "australia": "au", "sydney": "au", "melbourne": "au",
    "canada": "ca", "toronto": "ca",
    "germany": "de", "berlin": "de",
    "france": "fr", "paris": "fr",
    "us": "us", "usa": "us", "united states": "us",
    "new york": "us", "san francisco": "us",
}


def _country_code(location: str) -> str:
    loc = location.lower()
    for keyword, code in _COUNTRY_MAP.items():
        if keyword in loc:
            return code
    return "us"


class AdzunaSignal(BaseSignal):
    source_name = "adzuna"

    def fetch(self, query: str, location: str = "", max_pages: int = None) -> list[dict]:
        if not config.ADZUNA_APP_ID or not config.ADZUNA_APP_KEY:
            logger.debug("Adzuna keys not set — skipping")
            return []

        country = _country_code(location)
        max_pages = max_pages or config.MAX_PAGES
        results = []

        for page in range(1, max_pages + 1):
            try:
                params = {
                    "app_id":           config.ADZUNA_APP_ID,
                    "app_key":          config.ADZUNA_APP_KEY,
                    "results_per_page": 50,
                    "what":             query,
                    "content-type":     "application/json",
                    "sort_by":          "date",
                }
                if location:
                    params["where"] = location

                url  = f"{ADZUNA_BASE}/{country}/search/{page}"
                resp = requests.get(url, params=params, timeout=15)

                if resp.status_code == 401:
                    logger.warning("Adzuna: invalid API credentials")
                    break
                if resp.status_code != 200:
                    logger.warning(f"Adzuna: {resp.status_code} for '{query}'")
                    break

                data  = resp.json()
                items = data.get("results", [])
                if not items:
                    break

                for job in items:
                    company_name = (job.get("company") or {}).get("display_name", "").strip()
                    job_title    = clean_text(job.get("title", ""))
                    description  = truncate(clean_text(job.get("description", "")), 400)
                    job_url      = job.get("redirect_url", "")
                    job_location = (job.get("location") or {}).get("display_name", location)

                    if not company_name or not job_title:
                        continue
                    if not is_valid_company_name(company_name):
                        continue

                    results.append(self._make_signal(
                        company_name=company_name,
                        job_title=job_title,
                        description=description,
                        url=job_url,
                        location=job_location,
                    ))

                logger.info(f"Adzuna '{query}' page {page} → {len(items)} jobs")

                # Stop early if we got fewer results than a full page
                if len(items) < 50:
                    break

            except Exception as e:
                logger.error(f"Adzuna error for '{query}': {e}")
                break

        return results
