"""
G2 / Capterra reviews signal — confirms active Oracle product users.

Companies reviewing Oracle products on G2.com or Capterra.com have proven
active deployments — the strongest "post_live" signal available.

Approach (no API key required):
  1. Bing News RSS searching for G2 and Capterra review mentions of Oracle products
  2. Bing search for recent review pages that name the company + Oracle product
  3. Direct Bing RSS for oracle product reviews → company names in review headlines

Covers all Oracle products: Cloud ERP, HCM, SCM, EPM, NetSuite, EBS, PeopleSoft,
Siebel CRM, Hyperion, JD Edwards, OCI, Oracle Analytics.
"""

import re
import requests
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay
from src import llm_extractor

logger = get_logger(__name__)

# Bing RSS queries that surface G2/Capterra review pages naming the company
_REVIEW_QUERIES = [
    # G2 oracle product reviews
    'oracle cloud ERP review "g2" company implementation',
    'oracle fusion cloud review "g2" customer',
    'oracle HCM cloud review "g2" implementation',
    'oracle netsuite review "g2" customer company',
    'oracle EPM cloud review "g2" company',
    # Capterra oracle reviews
    'oracle ERP review capterra company implementation',
    'oracle cloud HCM review capterra customer',
    'oracle netsuite review capterra company',
    'oracle E-business suite review capterra',
    'oracle PeopleSoft review capterra company',
    # Press mentions of reviews / awards
    "oracle cloud ERP customer review award 2024",
    "oracle netsuite customer award implementation 2024",
    # Trustpilot / Software Advice
    "oracle cloud ERP review trustpilot company",
    "oracle ERP implementation review software advice",
]

# Pattern: "[Company] reviews Oracle [product]" or "Oracle [product] review by [Company]"
_COMPANY_PATTERNS = [
    r"^([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:reviews?|rated?|uses?|deployed?|implemented?)\s+Oracle",
    r"^([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:reviews?|rated?|uses?)\s+(?:NetSuite|PeopleSoft|Siebel|Hyperion)",
    r"Oracle\s+\w[\w\s]+\s+(?:review|rating)\s+(?:at|by|from)\s+([A-Z][A-Za-z0-9\s&',\.\-]{2,50})",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+gives?\s+Oracle\s+\w+\s+(?:review|rating)",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+wins?\s+Oracle\s+(?:Excellence|Partner|Customer)",
    r"Oracle\s+(?:Excellence|Innovation)\s+Award.*?([A-Z][A-Za-z0-9\s&',\.\-]{2,50})",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+named\s+Oracle\s+(?:customer|partner)\s+of\s+the\s+year",
]

_ORACLE_PRODUCT_PATTERNS = [
    (r"Oracle\s+Fusion\s+Cloud\s+ERP",          "Oracle Cloud ERP"),
    (r"Oracle\s+Cloud\s+ERP",                   "Oracle Cloud ERP"),
    (r"Oracle\s+Cloud\s+HCM",                   "Oracle HCM"),
    (r"Oracle\s+HCM",                           "Oracle HCM"),
    (r"Oracle\s+Cloud\s+EPM",                   "Oracle EPM"),
    (r"Oracle\s+Hyperion",                      "Oracle EPM"),
    (r"Oracle\s+NetSuite|NetSuite",             "NetSuite"),
    (r"Oracle\s+E-Business\s+Suite|Oracle\s+EBS", "Oracle EBS"),
    (r"PeopleSoft",                             "Oracle PeopleSoft"),
    (r"Oracle\s+Siebel",                        "Oracle Siebel CRM"),
    (r"JD\s+Edwards|JDE\b",                     "JD Edwards"),
    (r"Oracle\s+Analytics",                     "Oracle Analytics"),
    (r"Oracle\s+Cloud",                         "Oracle Cloud"),
    (r"Oracle",                                 "Oracle (General)"),
]

_ORACLE_KEYWORDS = {
    "oracle", "netsuite", "peoplesoft", "siebel", "hyperion",
    "jd edwards", "jde", "fusion", "ebs", "e-business suite",
}


def _mentions_oracle(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in _ORACLE_KEYWORDS)


class G2ReviewsSignal(BaseSignal):
    source_name = "g2_reviews"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        results: list[dict] = []
        seen: set[str] = set()

        for q in _REVIEW_QUERIES:
            try:
                encoded = requests.utils.quote(q)
                url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
                feed = feedparser.parse(url)

                count = 0
                for entry in feed.entries[:12]:
                    title   = clean_text(entry.get("title", ""))
                    summary = truncate(clean_text(entry.get("summary", "")), 400)
                    link    = entry.get("link", "")
                    date    = entry.get("published", "")
                    combined = f"{title} {summary}"

                    if not _mentions_oracle(combined):
                        continue

                    dedup_key = (link or title)[:100]
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)

                    company = self._extract_company(title, summary)
                    if not company:
                        company = llm_extractor.extract_company(title, summary)
                    if not company:
                        continue

                    product = self._extract_product(combined)

                    results.append(self._make_signal(
                        company_name=company,
                        job_title=title,
                        description=summary or title,
                        url=link,
                        posted_date=date,
                        extra={
                            "signal_type": "customer_review",
                            "oracle_product_hint": product,
                            "phase_hint": "post_live",   # reviewing = already live
                        },
                    ))
                    count += 1

                if count:
                    logger.info(f"G2Reviews Bing '{q[:50]}' → {count} signals")
                random_delay(0.5, 1.0)

            except Exception as e:
                logger.debug(f"G2Reviews error '{q[:40]}': {e}")

        logger.info(f"G2ReviewsSignal total: {len(results)} confirmed-user signals")
        return results

    def _extract_company(self, title: str, summary: str) -> str:
        for pat in _COMPANY_PATTERNS:
            for text in (title, summary):
                m = re.search(pat, text.strip(), re.IGNORECASE)
                if m:
                    candidate = m.group(1).strip().rstrip(".,;:")
                    if is_valid_company_name(candidate) and "oracle" not in candidate.lower():
                        return candidate
        return ""

    def _extract_product(self, text: str) -> str:
        for pat, name in _ORACLE_PRODUCT_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return name
        return "Oracle (General)"
