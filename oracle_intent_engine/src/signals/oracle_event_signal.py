"""
Oracle Event Attendance signal — CloudWorld / OpenWorld / Oracle Live.

Uses Bing RSS to find companies announcing attendance, sponsorship, or
presentations at Oracle events. No API key required.
"""

import re
import urllib.parse
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay
from src import config

logger = get_logger(__name__)

BING_RSS = "https://www.bing.com/news/search?format=rss&q="

_EVENT_QUERIES = [
    "oracle cloudworld 2024 customer presenting",
    "oracle cloudworld 2024 sponsor implementation",
    "company presenting oracle cloudworld",
    "oracle openworld customer success story",
    "oracle live event customer",
    "oracle cloudworld session partner customer",
    "oracle cloud summit 2024 customer",
    "oracle modern finance cloudworld",
    "oracle HCM cloudworld customer story",
    "oracle industry cloudworld manufacturing",
    "oracle industry cloudworld retail",
    "oracle industry cloudworld financial services",
]

_COMPANY_PATTERNS = [
    r"([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+(?:presents?|sponsors?|showcases?|exhibits?|joins?)\s+(?:at\s+)?(?:oracle\s+)?(?:cloudworld|openworld)",
    r"([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+to\s+(?:present|speak|exhibit)\s+at\s+(?:oracle\s+)?cloudworld",
    r"([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+(?:shares?|discusses?)\s+(?:oracle\s+)?cloud\s+(?:journey|transformation|migration)",
    r"([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+(?:selected|named|recognized)\s+(?:as\s+)?oracle\s+(?:customer|partner)",
    r"join\s+([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+at\s+(?:oracle\s+)?cloudworld",
]

_SKIP = {"oracle", "cloudworld", "openworld", "event", "partner", "sponsor"}


def _extract_company(title: str, desc: str) -> str:
    for pat in _COMPANY_PATTERNS:
        for text in (title, desc):
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip().rstrip(".,")
                if candidate.lower() in _SKIP:
                    continue
                if is_valid_company_name(candidate) and len(candidate) > 3:
                    return candidate
    return ""


class OracleEventSignal(BaseSignal):
    source_name = "oracle_event"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        results = []
        seen = set()

        for q in _EVENT_QUERIES:
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
                        job_title="Oracle CloudWorld / Event Participation",
                        description=desc or title,
                        url=link,
                        posted_date=entry.get("published", ""),
                        signal_type="event_attendance",
                    ))
                    count += 1

                logger.info(f"OracleEvent '{q[:40]}' → {count} companies")
                random_delay(0.5, 1.0)

            except Exception as e:
                logger.error(f"OracleEvent error '{q[:40]}': {e}")

        return results
