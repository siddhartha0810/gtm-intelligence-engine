"""
Company Pages signal — press releases and announcements from company newsrooms.

Uses Bing RSS to surface companies that have issued press releases about
Oracle Cloud ERP/HCM/EPM implementations, upgrades, or go-lives.
No API key required.
"""

import re
import urllib.parse
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay
from src import config

logger = get_logger(__name__)

BING_RSS = "https://www.bing.com/news/search?format=rss&q="

_PR_QUERIES = [
    '"oracle cloud" "go live" press release 2024',
    '"oracle fusion" implementation announcement 2024',
    '"oracle ERP" "go live" announcement company',
    '"oracle cloud HCM" implementation announcement',
    '"oracle cloud EPM" go live 2024',
    '"oracle netsuite" implementation announcement 2024',
    'company "selected oracle cloud" ERP 2024',
    'company "implemented oracle" ERP cloud 2024',
    '"oracle cloud" "digital transformation" announcement 2024',
    '"oracle cloud" supply chain implementation announcement',
    '"oracle JDE" upgrade cloud announcement',
    '"oracle EBS" migration cloud announcement 2024',
]

_COMPANY_PATTERNS = [
    r"^([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+(?:Announces?|Completes?|Selects?|Deploys?|Implements?|Goes?\s+Live)",
    r"([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+(?:announces?|completes?|selects?|deploys?|goes?\s+live\s+(?:on|with))\s+oracle",
    r"([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+(?:successfully|now|recently)\s+(?:deployed|implemented|migrated|upgraded)",
    r"([A-Z][A-Za-z0-9\s&\.]{3,40}?)\s+(?:transforms?|modernizes?)\s+(?:finance|HR|operations|supply chain)\s+with\s+oracle",
    r"oracle\s+(?:cloud|fusion|ERP|HCM|EPM|netsuite)\s+(?:helps?|powers?|enables?)\s+([A-Z][A-Za-z0-9\s&\.]{3,40?})",
]

_SKIP = {"oracle", "press", "release", "announcement", "company", "news"}


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


class CompanyPagesSignal(BaseSignal):
    source_name = "company_pages"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        results = []
        seen = set()

        for q in _PR_QUERIES:
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
                        job_title="Oracle Cloud Announcement (Press Release)",
                        description=desc or title,
                        url=link,
                        posted_date=entry.get("published", ""),
                        signal_type="press_release",
                    ))
                    count += 1

                logger.info(f"CompanyPages '{q[:40]}' → {count} companies")
                random_delay(0.5, 1.0)

            except Exception as e:
                logger.error(f"CompanyPages error '{q[:40]}': {e}")

        return results
