"""
Scrapes Indeed public job search for Oracle-related postings.
Primary: HTML scraping. Fallback: Indeed public RSS feed.
Rate-limited with random delays.
"""

import re
import requests
import feedparser
from bs4 import BeautifulSoup
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, random_delay, random_headers, clean_text, truncate, is_valid_company_name
from src import config

logger = get_logger(__name__)

INDEED_BASE = "https://www.indeed.com/jobs"


class IndeedSignal(BaseSignal):
    source_name = "indeed"

    def fetch(self, query: str, location: str = "", max_pages: int = None) -> list[dict]:
        max_pages = max_pages or config.MAX_PAGES
        results = self._fetch_html(query, location, max_pages)
        if not results:
            logger.info(f"Indeed HTML returned 0 for '{query}' — trying RSS fallback")
            results = self._fetch_rss(query, location)
        return results

    def _fetch_html(self, query: str, location: str, max_pages: int) -> list[dict]:
        results = []
        for page in range(0, max_pages * 10, 10):
            try:
                params = {"q": query, "l": location, "start": page, "fromage": "30"}
                resp = requests.get(
                    INDEED_BASE,
                    params=params,
                    headers=random_headers(),
                    timeout=15,
                )
                if resp.status_code != 200:
                    logger.warning(f"Indeed returned {resp.status_code} for '{query}' page {page}")
                    break

                page_results = self._parse_page(resp.text)
                if not page_results:
                    break

                results.extend(page_results)
                logger.info(f"Indeed '{query}' page {page} → {len(page_results)} jobs")
                random_delay(config.SCAN_DELAY_MIN, config.SCAN_DELAY_MAX)

            except Exception as e:
                logger.error(f"Indeed HTML fetch error for '{query}': {e}")
                break
        return results

    def _fetch_rss(self, query: str, location: str = "") -> list[dict]:
        # Use the country-specific subdomain when a UK/GB location is set
        loc_lower = location.lower()
        if any(x in loc_lower for x in ("uk", "united kingdom", "england", "scotland", "wales", "london")):
            base = "https://www.indeed.co.uk/rss"
        else:
            base = "https://www.indeed.com/rss"

        urls_to_try = []
        encoded_q = requests.utils.quote(query)
        encoded_l = requests.utils.quote(location) if location else ""
        qs = f"q={encoded_q}&sort=date&fromage=30"
        if encoded_l:
            qs += f"&l={encoded_l}"
        urls_to_try.append(f"{base}?{qs}")
        # fallback: com always
        if "co.uk" in base:
            urls_to_try.append(f"https://www.indeed.com/rss?{qs}")

        for url in urls_to_try:
            try:
                feed = feedparser.parse(url)
                if not feed.entries:
                    continue

                results = []
                for entry in feed.entries[:25]:
                    raw_title = clean_text(entry.get("title", ""))
                    raw_desc = entry.get("summary", "") or entry.get("description", "")
                    description = truncate(clean_text(re.sub(r"<[^>]+>", " ", raw_desc)), 400)

                    company = ""
                    job_title = raw_title

                    # Indeed RSS title format: "Job Title - Company Name" (or " – " / " | ")
                    # Use split (not rsplit) to take the FIRST separator — avoids picking up
                    # location suffix (e.g. "Title - Company - London" → company="Company - London"
                    # trimmed below to just "Company").
                    for sep in (" - ", " – ", " | "):
                        if sep in raw_title:
                            parts = raw_title.split(sep, 1)
                            job_title = parts[0].strip()
                            # Company may have trailing location after another sep — strip it
                            company_raw = parts[1].strip()
                            for inner_sep in (" - ", " – ", " | ", ","):
                                if inner_sep in company_raw:
                                    company_raw = company_raw.split(inner_sep)[0].strip()
                                    break
                            if is_valid_company_name(company_raw):
                                company = company_raw
                            break

                    if not company:
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

                logger.info(f"Indeed RSS '{query}' → {len(results)} jobs (url={url[:60]})")
                if results:
                    return results
            except Exception as e:
                logger.error(f"Indeed RSS error for '{query}' ({url[:60]}): {e}")

        return []

    def _parse_page(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.find_all("div", attrs={"data-testid": "slider_item"})
        if not cards:
            cards = soup.find_all("div", class_=lambda c: c and "job_seen_beacon" in c)

        results = []
        for card in cards:
            try:
                signal = self._parse_card(card)
                if signal and signal["company_name"]:
                    results.append(signal)
            except Exception as e:
                logger.debug(f"Card parse error: {e}")
        return results

    def _parse_card(self, card) -> dict | None:
        title_el = (
            card.find("h2", class_=lambda c: c and "jobTitle" in c)
            or card.find("a", attrs={"data-jk": True})
        )
        job_title = clean_text(title_el.get_text()) if title_el else ""

        company_el = card.find("span", attrs={"data-testid": "company-name"})
        if not company_el:
            company_el = card.find("span", class_=lambda c: c and "companyName" in c)
        company_name = clean_text(company_el.get_text()) if company_el else ""

        location_el = card.find("div", attrs={"data-testid": "text-location"})
        if not location_el:
            location_el = card.find("div", class_=lambda c: c and "companyLocation" in c)
        location = clean_text(location_el.get_text()) if location_el else ""

        snippet_el = card.find("div", class_=lambda c: c and "job-snippet" in c)
        if not snippet_el:
            snippet_el = card.find("ul")
        description = truncate(clean_text(snippet_el.get_text()), 400) if snippet_el else ""

        link_el = card.find("a", href=True)
        url = ""
        if link_el:
            href = link_el["href"]
            url = f"https://www.indeed.com{href}" if href.startswith("/") else href

        date_el = card.find("span", class_=lambda c: c and "date" in (c or "").lower())
        posted_date = clean_text(date_el.get_text()) if date_el else ""

        if not job_title or not company_name:
            return None

        return self._make_signal(
            company_name=company_name,
            job_title=job_title,
            description=description,
            url=url,
            location=location,
            posted_date=posted_date,
        )
