"""
Oracle Community / Migration Stories signal.

Sources (all free, no keys):
  - oracle.com/news RSS paginator (press releases, customer announcements)
  - Bing RSS for Oracle community migration stories and go-lives
  - Oracle Cloud Customer Connect forum mentions (via Bing)
"""

import re
import urllib.parse
import feedparser
import requests
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay
from src import config

logger = get_logger(__name__)

BING_RSS = "https://www.bing.com/news/search?format=rss&q="

_COMMUNITY_QUERIES = [
    "oracle cloud ERP migration story 2024",
    "oracle cloud go live success story",
    "oracle fusion cloud customer migration",
    "company migrated oracle cloud ERP",
    "oracle ERP upgrade cloud 2024",
    "oracle cloud HCM go live customer",
    "oracle netsuite migration 2024",
    "moved to oracle cloud ERP",
    'site:community.oracle.com "went live" OR "go live" ERP',
    'site:oracle.com/customers "oracle cloud" implemented',
]

_ORACLE_NEWS_RSS = "https://www.oracle.com/news/rss.html"

_COMPANY_PATTERNS = [
    r"([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+(?:goes?\s+live|went\s+live|completes?\s+migration|successfully\s+(?:deployed|implemented|migrated))",
    r"([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+(?:selects?|chooses?|adopts?)\s+oracle",
    r"oracle\s+(?:cloud|ERP|fusion)\s+(?:at|for|by)\s+([A-Z][A-Za-z0-9\s&\.]{3,40?})",
    r"([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+partners?\s+with\s+oracle",
    r"([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+(?:transforms?|modernizes?|upgrades?)\s+(?:with|to|using)\s+oracle",
]

_SKIP_WORDS = {"oracle", "announcement", "community", "migration", "cloud", "erp"}


def _extract_company(title: str, desc: str) -> str:
    for pat in _COMPANY_PATTERNS:
        for text in (title, desc):
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip().rstrip(".,")
                if candidate.lower() in _SKIP_WORDS:
                    continue
                if is_valid_company_name(candidate) and len(candidate) > 3:
                    return candidate
    return ""


class OracleCommunitySignal(BaseSignal):
    source_name = "oracle_community"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        max_pages = max_pages or config.MAX_PAGES
        results = []
        seen = set()

        # Bing RSS community queries
        for q in _COMMUNITY_QUERIES:
            loc_suffix = f" {location}" if location else ""
            rss_url = BING_RSS + urllib.parse.quote(q + loc_suffix)
            try:
                feed = feedparser.parse(rss_url)
                count = 0
                for entry in feed.entries[:15]:
                    title = clean_text(entry.get("title", ""))
                    raw   = entry.get("summary", "") or entry.get("description", "")
                    desc  = truncate(clean_text(re.sub(r"<[^>]+>", " ", raw)), 400)
                    link  = entry.get("link", "")

                    key = title + link
                    if key in seen:
                        continue
                    seen.add(key)

                    company = _extract_company(title, desc)
                    if not company:
                        continue

                    results.append(self._make_signal(
                        company_name=company,
                        job_title="Oracle Cloud Migration Story",
                        description=desc or title,
                        url=link,
                        posted_date=entry.get("published", ""),
                        signal_type="community_story",
                    ))
                    count += 1

                logger.info(f"OracleCommunity '{q[:40]}' → {count} stories")
                random_delay(0.5, 1.0)

            except Exception as e:
                logger.error(f"OracleCommunity query error: {e}")

        # Oracle.com news RSS (paginated via offset param)
        for page in range(max_pages):
            try:
                params = {"offset": page * 20}
                resp = requests.get(_ORACLE_NEWS_RSS, params=params, timeout=15)
                feed = feedparser.parse(resp.text if resp.status_code == 200 else "")
                if not feed.entries:
                    break

                count = 0
                for entry in feed.entries:
                    title = clean_text(entry.get("title", ""))
                    raw   = entry.get("summary", "") or ""
                    desc  = truncate(clean_text(re.sub(r"<[^>]+>", " ", raw)), 400)
                    link  = entry.get("link", "")

                    key = title + link
                    if key in seen:
                        continue
                    seen.add(key)

                    company = _extract_company(title, desc)
                    if not company:
                        continue

                    results.append(self._make_signal(
                        company_name=company,
                        job_title="Oracle News Announcement",
                        description=desc or title,
                        url=link,
                        posted_date=entry.get("published", ""),
                        signal_type="oracle_news",
                    ))
                    count += 1

                logger.info(f"OracleNews page {page+1} → {count} stories")
                if len(feed.entries) < 10:
                    break
                random_delay(1, 2)

            except Exception as e:
                logger.error(f"OracleNews RSS error: {e}")
                break

        return results
