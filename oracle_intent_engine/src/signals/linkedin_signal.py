"""
Scrapes LinkedIn public job search (unauthenticated).
LinkedIn's public job listings are accessible without login.
Rate-limited with generous delays — LinkedIn is stricter than Indeed.
Note: For production at scale, use LinkedIn's official API or a compliant
      data partner (e.g., Proxycurl, Coresignal).
"""

import requests
from bs4 import BeautifulSoup
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, random_delay, random_headers, clean_text, truncate
from src import config

logger = get_logger(__name__)

LI_BASE = "https://www.linkedin.com/jobs/search"


# LinkedIn industry codes for manufacturing-adjacent sectors
# Used to filter JDE job searches to actual manufacturing end-users
LINKEDIN_MANUFACTURING_INDUSTRIES = "96,4,80,22,10,74,57"
# 96=Manufacturing, 4=Automotive, 80=Mechanical/Industrial Eng, 22=Construction,
# 10=Civil Engineering, 74=Oil & Energy, 57=Food & Beverages


class LinkedInSignal(BaseSignal):
    source_name = "linkedin"

    def fetch(self, query: str, location: str = "", max_pages: int = None,
              industry_filter: str = "") -> list[dict]:
        max_pages = max_pages or config.MAX_PAGES
        results = []

        for page in range(0, max_pages * 25, 25):
            try:
                params = {
                    "keywords": query,
                    "location": location,
                    "start": page,
                    "f_TPR": "r2592000",  # last 30 days
                    "sortBy": "R",
                }
                if industry_filter:
                    params["f_I"] = industry_filter
                resp = requests.get(
                    LI_BASE,
                    params=params,
                    headers={**random_headers(), "X-Requested-With": "XMLHttpRequest"},
                    timeout=15,
                )
                if resp.status_code == 429:
                    logger.warning("LinkedIn rate limit hit — backing off")
                    random_delay(15, 30)
                    break
                if resp.status_code != 200:
                    logger.warning(f"LinkedIn returned {resp.status_code} for '{query}'")
                    break

                page_results = self._parse_page(resp.text)
                if not page_results:
                    break

                results.extend(page_results)
                logger.info(f"LinkedIn '{query}' offset {page} → {len(page_results)} jobs")
                random_delay(config.SCAN_DELAY_MIN + 1, config.SCAN_DELAY_MAX + 2)

            except Exception as e:
                logger.error(f"LinkedIn fetch error for '{query}': {e}")
                break

        return results

    def _parse_page(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.find_all("div", class_=lambda c: c and "base-card" in (c or ""))
        if not cards:
            cards = soup.find_all("li", class_=lambda c: c and "jobs-search" in (c or ""))

        results = []
        for card in cards:
            try:
                signal = self._parse_card(card)
                if signal and signal["company_name"]:
                    results.append(signal)
            except Exception as e:
                logger.debug(f"LinkedIn card parse error: {e}")
        return results

    def _parse_card(self, card) -> dict | None:
        title_el = card.find("h3", class_=lambda c: c and "base-search-card__title" in (c or ""))
        if not title_el:
            title_el = card.find("h3")
        job_title = clean_text(title_el.get_text()) if title_el else ""

        company_el = card.find("h4", class_=lambda c: c and "base-search-card__subtitle" in (c or ""))
        if not company_el:
            company_el = card.find("a", class_=lambda c: c and "hidden-nested-link" in (c or ""))
        company_name = clean_text(company_el.get_text()) if company_el else ""

        location_el = card.find("span", class_=lambda c: c and "job-search-card__location" in (c or ""))
        location = clean_text(location_el.get_text()) if location_el else ""

        date_el = card.find("time")
        posted_date = date_el.get("datetime", "") if date_el else ""

        link_el = card.find("a", href=True, class_=lambda c: c and "base-card__full-link" in (c or ""))
        if not link_el:
            link_el = card.find("a", href=True)
        url = link_el["href"].split("?")[0] if link_el else ""

        description = truncate(job_title, 300)

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
