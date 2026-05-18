"""
TotalJobs RSS signal — UK's largest job board, no API key needed.
Paginates via startIndex parameter (25 results per page).
"""

import re
import requests
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay
from src import config

logger = get_logger(__name__)

TOTALJOBS_RSS = "https://www.totaljobs.com/jobs/rss"


class TotalJobsSignal(BaseSignal):
    source_name = "totaljobs"

    def fetch(self, query: str, location: str = "", max_pages: int = None) -> list[dict]:
        # TotalJobs RSS endpoint returns HTML (bot-protected, Cloudflare).
        # Keeping this class for future use if a valid endpoint is found.
        logger.debug("TotalJobs skipped — RSS feed unavailable (bot protection)")
        return []

    def _fetch_disabled(self, query: str, location: str = "", max_pages: int = None) -> list[dict]:
        max_pages = max_pages or config.MAX_PAGES
        results = []
        seen = set()

        for page in range(max_pages):
            try:
                params = {
                    "Keywords":   query,
                    "distance":   30,
                    "startIndex": page * 25,
                }
                if location:
                    params["Location"] = location

                url  = requests.Request("GET", TOTALJOBS_RSS, params=params).prepare().url
                feed = feedparser.parse(url)

                if not feed.entries:
                    break

                page_count = 0
                for entry in feed.entries:
                    title   = clean_text(entry.get("title", ""))
                    raw_desc = entry.get("summary", "") or entry.get("description", "")
                    desc     = truncate(clean_text(re.sub(r"<[^>]+>", " ", raw_desc)), 400)
                    link     = entry.get("link", "")

                    key = title + link
                    if key in seen:
                        continue
                    seen.add(key)

                    company, job_title = self._parse_title(title)
                    if not company:
                        company = self._extract_from_desc(desc)
                    if not company or not job_title:
                        continue

                    results.append(self._make_signal(
                        company_name=company,
                        job_title=job_title,
                        description=desc,
                        url=link,
                        posted_date=entry.get("published", ""),
                        location=location,
                    ))
                    page_count += 1

                logger.info(f"TotalJobs '{query}' page {page+1} → {page_count} jobs")

                if len(feed.entries) < 25:
                    break

                random_delay(1, 2)

            except Exception as e:
                logger.error(f"TotalJobs error '{query}': {e}")
                break

        return results

    def _parse_title(self, title: str):
        """Split 'Job Title - Company Name' → (company, job_title)."""
        for sep in (" - ", " – ", " | "):
            if sep in title:
                parts    = title.split(sep, 1)
                job_part = parts[0].strip()
                co_raw   = parts[1].strip()
                # Strip trailing location noise (e.g. "Acme Corp - London")
                for inner in (" - ", " – ", ","):
                    if inner in co_raw:
                        co_raw = co_raw.split(inner)[0].strip()
                if is_valid_company_name(co_raw):
                    return co_raw, job_part
        return "", title

    def _extract_from_desc(self, desc: str) -> str:
        for pat in (r"Company[:\s]+([A-Z][A-Za-z0-9\s&\.]+)", r"Employer[:\s]+([A-Z][A-Za-z0-9\s&\.]+)"):
            m = re.search(pat, desc)
            if m:
                c = m.group(1).strip().rstrip(",.")
                if is_valid_company_name(c):
                    return c
        return ""
