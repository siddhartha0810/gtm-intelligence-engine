"""
Home Builders JDE signal scraper.

Targets home builders with 1,000+ annual closings — the size tier
most likely to run JD Edwards EnterpriseOne for job costing, procurement,
and project management. Uses Bing RSS (free, no key) to surface JDE signals
from known large builders and industry publications.
"""

import re
import urllib.parse
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay

logger = get_logger(__name__)

BING_RSS = "https://www.bing.com/news/search?format=rss&q="

# Home builders with 1,000+ annual closings (US + UK/International)
# Sources: Builder Magazine Top 100, NHBC, Homes England
LARGE_BUILDERS = [
    # US — top builders by closings
    "D.R. Horton", "Lennar", "PulteGroup", "NVR", "Meritage Homes",
    "Taylor Morrison", "Century Communities", "K. Hovnanian Homes",
    "Beazer Homes", "MDC Holdings", "LGI Homes", "Smith Douglas Homes",
    "Tri Pointe Homes", "Dream Finders Homes", "Stanley Martin Homes",
    "David Weekley Homes", "AV Homes", "Ashton Woods", "Mattamy Homes",
    "Toll Brothers", "William Lyon Homes", "Forestar Group",
    # UK — top builders by completions
    "Barratt Developments", "Persimmon", "Taylor Wimpey", "Bellway",
    "Vistry Group", "Redrow", "Crest Nicholson", "McCarthy Stone",
    "Countryside Properties", "Berkeley Group", "Miller Homes",
    "Keepmoat Homes", "Avant Homes", "Gleeson Homes",
]

# Search queries combining known builders + JDE signals
_BUILDER_QUERIES = [
    ("JDE Home Builders",       "JD Edwards home builder construction ERP implementation"),
    ("JDE Construction ERP",    "JD Edwards EnterpriseOne construction homebuilder"),
    ("Builder JDE Upgrade",     "JDE ERP upgrade homebuilder real estate construction"),
    ("Builder Magazine JDE",    "site:builderonline.com JD Edwards OR JDE ERP technology"),
    ("HousingWire JDE",         "site:housingwire.com JD Edwards OR JDE ERP"),
    ("ProBuilder JDE",          "site:probuilder.com JD Edwards OR JDE technology ERP"),
    ("JDE Job Cost Builder",    "JD Edwards job costing homebuilder construction consultant"),
    ("JDE Land Development",    "JD Edwards land development procurement construction"),
]

# Patterns to extract company name from article text
_COMPANY_PATTERNS = [
    r"^([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:selects?|implements?|deploys?|upgrades?|migrates?|goes?\s+live)\s+(?:JD\s*Edwards|JDE)",
    r"(?:JD\s*Edwards|JDE)\s+(?:selected\s+by|implemented\s+at|deployed\s+at|chosen\s+by)\s+([A-Z][A-Za-z0-9\s&',\.\-]{2,50})",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:selects?|adopts?|chooses?)\s+(?:JD\s*Edwards|JDE|EnterpriseOne)",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:goes?\s+live|went\s+live)\s+(?:with|on)\s+(?:JD\s*Edwards|JDE)",
]

_PHASE_PATTERNS = [
    (r"goes?\s+live|went\s+live|launched?|completed?|successful", "post_live"),
    (r"selects?|chooses?|awards?|signs?\s+deal",                  "evaluating"),
    (r"implements?|deploys?|migrates?|upgrades?|transforms?",     "implementing"),
]

_SKIP_WORDS = {
    "oracle", "sap", "microsoft", "infor", "epicor", "sage",
    "accenture", "deloitte", "pwc", "kpmg", "infosys", "wipro",
}

JDE_KEYWORDS = [
    "jd edwards", "jde", "enterpriseone", "e1", "jde e1",
    "jde cnc", "jde orchestrator", "jde oneworld",
]


def _matches_known_builder(text: str) -> str:
    """Return the known builder name if found in text, else empty string."""
    t = text.lower()
    for builder in LARGE_BUILDERS:
        if builder.lower() in t:
            return builder
    return ""


def _extract_company(title: str, desc: str) -> str:
    for pat in _COMPANY_PATTERNS:
        for text in (title, desc):
            m = re.search(pat, text.strip())
            if m:
                candidate = m.group(1).strip().rstrip(".,;:")
                if candidate.lower().split()[0] in _SKIP_WORDS:
                    continue
                if is_valid_company_name(candidate):
                    return candidate

    # Fall back: check if a known large builder is mentioned
    combined = f"{title} {desc}"
    builder = _matches_known_builder(combined)
    if builder:
        return builder

    return ""


def _infer_phase(title: str) -> str:
    t = title.lower()
    for pat, phase in _PHASE_PATTERNS:
        if re.search(pat, t):
            return phase
    return "implementing"


class HomeBuildersSignal(BaseSignal):
    source_name = "home_builders"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        results = []
        seen = set()

        # --- Bing RSS searches for JDE signals in home building industry ---
        for label, search_query in _BUILDER_QUERIES:
            loc_suffix = f" {location}" if location else ""
            rss_url = BING_RSS + urllib.parse.quote(search_query + loc_suffix)

            try:
                feed = feedparser.parse(rss_url)
                count = 0

                for entry in feed.entries[:25]:
                    title   = clean_text(entry.get("title", ""))
                    raw_sum = entry.get("summary", "") or entry.get("description", "")
                    desc    = truncate(clean_text(re.sub(r"<[^>]+>", " ", raw_sum)), 500)
                    link    = entry.get("link", "")
                    combined = f"{title} {desc}".lower()

                    key = title + link
                    if key in seen:
                        continue
                    seen.add(key)

                    if not any(kw in combined for kw in JDE_KEYWORDS):
                        continue

                    company = _extract_company(title, desc)
                    if not company:
                        continue

                    phase = _infer_phase(title)

                    results.append(self._make_signal(
                        company_name=company,
                        job_title=f"JD Edwards Signal — {label}",
                        description=desc or title,
                        url=link,
                        posted_date=entry.get("published", ""),
                        extra={
                            "signal_type": "industry_news",
                            "oracle_product_hint": "JD Edwards",
                            "phase_hint": phase,
                            "industry": "Construction / Home Building",
                        },
                    ))
                    count += 1

                logger.info(f"HomeBuildersSignal '{label}' → {count} JDE signals")
                random_delay(0.5, 1.2)

            except Exception as e:
                logger.error(f"HomeBuildersSignal '{label}': {e}")

        # --- Direct searches for each known large builder ---
        for builder in LARGE_BUILDERS:
            rss_url = BING_RSS + urllib.parse.quote(f'"{builder}" JD Edwards OR JDE ERP')
            try:
                feed = feedparser.parse(rss_url)
                for entry in feed.entries[:5]:
                    title   = clean_text(entry.get("title", ""))
                    raw_sum = entry.get("summary", "") or ""
                    desc    = truncate(clean_text(re.sub(r"<[^>]+>", " ", raw_sum)), 400)
                    link    = entry.get("link", "")
                    combined = f"{title} {desc}".lower()

                    key = title + link
                    if key in seen:
                        continue
                    seen.add(key)

                    if not any(kw in combined for kw in JDE_KEYWORDS):
                        continue

                    results.append(self._make_signal(
                        company_name=builder,
                        job_title=f"JD Edwards Signal — {builder}",
                        description=desc or title,
                        url=link,
                        posted_date=entry.get("published", ""),
                        extra={
                            "signal_type": "industry_news",
                            "oracle_product_hint": "JD Edwards",
                            "phase_hint": _infer_phase(title),
                            "industry": "Construction / Home Building",
                            "min_closings": 1000,
                        },
                    ))

                random_delay(0.3, 0.8)

            except Exception as e:
                logger.error(f"HomeBuildersSignal direct '{builder}': {e}")

        logger.info(f"HomeBuildersSignal total → {len(results)} JDE signals from home builders")
        return results
