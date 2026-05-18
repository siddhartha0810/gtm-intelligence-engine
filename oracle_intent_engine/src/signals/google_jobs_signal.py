"""
Google Jobs signal via SerpAPI (if SERPAPI_KEY set) or
Indeed RSS as a free fallback (public feed, no key required).
"""

import re
import requests
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, random_delay, resolve_feed_url, is_valid_company_name
from src import config

logger = get_logger(__name__)


class GoogleJobsSignal(BaseSignal):
    source_name = "google_jobs"

    def fetch(self, query: str, location: str = "", max_pages: int = None) -> list[dict]:
        if config.SERPAPI_KEY:
            return self._fetch_serpapi(query, location)
        return self._fetch_rss_fallback(query, location)

    # ------------------------------------------------------------------ #
    #  SerpAPI (paid, high quality)
    # ------------------------------------------------------------------ #
    def _fetch_serpapi(self, query: str, location: str) -> list[dict]:
        try:
            params = {
                "engine": "google_jobs",
                "q": query,
                "location": location or "United States",
                "api_key": config.SERPAPI_KEY,
                "num": 30,
            }
            resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
            data = resp.json()

            results = []
            for job in data.get("jobs_results", []):
                company = clean_text(job.get("company_name", ""))
                title = clean_text(job.get("title", ""))
                description = truncate(clean_text(job.get("description", "")), 500)
                location_str = clean_text(job.get("location", ""))
                url = job.get("share_link") or job.get("job_id", "")

                if not company or not title:
                    continue

                results.append(self._make_signal(
                    company_name=company,
                    job_title=title,
                    description=description,
                    url=url,
                    location=location_str,
                    posted_date=job.get("detected_extensions", {}).get("posted_at", ""),
                ))

            logger.info(f"SerpAPI Google Jobs '{query}' → {len(results)} jobs")
            return results

        except Exception as e:
            logger.error(f"SerpAPI error: {e}")
            return []

    # ------------------------------------------------------------------ #
    #  Indeed RSS fallback (free public feed, no key required)
    # ------------------------------------------------------------------ #
    def _fetch_rss_fallback(self, query: str, location: str = "") -> list[dict]:
        try:
            encoded_q = requests.utils.quote(query)
            url = f"https://www.indeed.com/rss?q={encoded_q}&sort=date&fromage=30"
            if location:
                url += f"&l={requests.utils.quote(location)}"

            feed = feedparser.parse(url)
            results = []

            for entry in feed.entries[:25]:
                raw_title = clean_text(entry.get("title", ""))
                # Strip HTML from Indeed RSS descriptions
                raw_desc = entry.get("summary", "") or entry.get("description", "")
                description = truncate(clean_text(re.sub(r"<[^>]+>", " ", raw_desc)), 400)

                # Indeed RSS title format: "Job Title - Company Name"
                company = ""
                job_title = raw_title
                for sep in (" - ", " – ", " | "):
                    if sep in raw_title:
                        parts = raw_title.rsplit(sep, 1)
                        job_title = parts[0].strip()
                        candidate = parts[1].strip()
                        if is_valid_company_name(candidate):
                            company = candidate
                        break

                if not company:
                    # Try extracting from description: "Company: Accenture"
                    m = re.search(r"Company[:\s]+([A-Z][A-Za-z0-9\s&,\.]+)", description)
                    if m:
                        candidate = m.group(1).strip().rstrip(",.")
                        if is_valid_company_name(candidate):
                            company = candidate

                if not company or not job_title:
                    continue

                results.append(self._make_signal(
                    company_name=company,
                    job_title=job_title,
                    description=description,
                    url=entry.get("link", ""),
                    posted_date=entry.get("published", ""),
                    location=location,
                ))

            random_delay(config.SCAN_DELAY_MIN, config.SCAN_DELAY_MAX)
            logger.info(f"Indeed RSS (Google Jobs fallback) '{query}' → {len(results)} jobs")
            return results

        except Exception as e:
            logger.error(f"Google Jobs Indeed RSS fallback error: {e}")
            return []
