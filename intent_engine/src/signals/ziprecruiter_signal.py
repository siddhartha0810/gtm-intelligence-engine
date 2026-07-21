"""
ZipRecruiter job signal scraper — public RSS feed, no API key required.

ZipRecruiter aggregates job postings independently from Indeed/LinkedIn and
exposes a free public RSS: https://www.ziprecruiter.com/candidate/search?...&format=rss

Title format: "Job Title" with company in the <author> or description field.
"""

import re
import requests
import feedparser
from bs4 import BeautifulSoup
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, random_delay, is_valid_company_name
from src import config

logger = get_logger(__name__)

ZR_BASE = "https://www.ziprecruiter.com/candidate/search"


class ZipRecruiterSignal(BaseSignal):
    source_name = "ziprecruiter"

    def fetch(self, query: str, location: str = "", max_pages: int = None) -> list[dict]:
        results = self._fetch_rss(query, location)
        if not results:
            results = self._fetch_html(query, location)
        return results

    def _fetch_rss(self, query: str, location: str = "") -> list[dict]:
        try:
            params = {
                "search":   query,
                "location": location or "United States",
                "format":   "rss",
                "days":     30,
            }
            url = ZR_BASE + "?" + "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
            feed = feedparser.parse(url)

            if not feed.entries:
                logger.debug(f"ZipRecruiter RSS '{query}' returned 0 entries")
                return []

            results = []
            for entry in feed.entries[:30]:
                raw_title = clean_text(entry.get("title", ""))
                summary_raw = entry.get("summary", "") or entry.get("description", "")
                description = truncate(clean_text(re.sub(r"<[^>]+>", " ", summary_raw)), 400)
                link = entry.get("link", "")
                date = entry.get("published", "")

                # ZipRecruiter RSS: title is just job title, company in <author> or description
                company = clean_text(entry.get("author", "")) or ""
                job_title = raw_title

                # Try "Job Title at Company" pattern in title
                if not company:
                    m = re.search(r"\bat\s+([A-Z][A-Za-z0-9\s&,\.]{2,50}?)(?:\s*[-–|]|\s*$)", raw_title)
                    if m:
                        candidate = m.group(1).strip()
                        if is_valid_company_name(candidate):
                            company = candidate
                            job_title = raw_title[:raw_title.lower().rfind(" at ")].strip()

                # Try description: "Company: XYZ" or "Employer: XYZ"
                if not company:
                    m = re.search(r"(?:Company|Employer)[:\s]+([A-Z][A-Za-z0-9\s&,\.]{2,50}?)(?:\s*[\n,]|$)", description)
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
                    url=link,
                    posted_date=date,
                    location=location,
                ))

            logger.info(f"ZipRecruiter RSS '{query}' → {len(results)} jobs")
            random_delay(config.SCAN_DELAY_MIN, config.SCAN_DELAY_MAX)
            return results

        except Exception as e:
            logger.error(f"ZipRecruiter RSS error for '{query}': {e}")
            return []

    def _fetch_html(self, query: str, location: str = "") -> list[dict]:
        """Fallback HTML scrape if RSS returns nothing."""
        try:
            params = {
                "search":   query,
                "location": location or "United States",
                "days":     30,
            }
            resp = requests.get(
                ZR_BASE,
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            results = []

            # ZipRecruiter job cards
            for card in soup.find_all("article", class_=lambda c: c and "job_result" in (c or "")):
                try:
                    title_el = card.find("h2") or card.find("a", class_=lambda c: c and "job_title" in (c or ""))
                    company_el = card.find("a", class_=lambda c: c and "company_name" in (c or "")) \
                                 or card.find("span", class_=lambda c: c and "company" in (c or ""))
                    location_el = card.find("span", class_=lambda c: c and "location" in (c or ""))
                    link_el = card.find("a", href=True)

                    job_title = clean_text(title_el.get_text()) if title_el else ""
                    company = clean_text(company_el.get_text()) if company_el else ""
                    loc = clean_text(location_el.get_text()) if location_el else location
                    url = link_el["href"] if link_el else ""
                    if url and url.startswith("/"):
                        url = f"https://www.ziprecruiter.com{url}"

                    if not job_title or not company:
                        continue

                    results.append(self._make_signal(
                        company_name=company,
                        job_title=job_title,
                        description=job_title,
                        url=url,
                        location=loc,
                    ))
                except Exception:
                    continue

            logger.info(f"ZipRecruiter HTML '{query}' → {len(results)} jobs")
            return results

        except Exception as e:
            logger.error(f"ZipRecruiter HTML error for '{query}': {e}")
            return []
