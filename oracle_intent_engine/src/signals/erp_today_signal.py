"""
ERP Today (erptoday.com) signal scraper.

B2B publication covering enterprise ERP news — articles frequently name the
company going live with Oracle, the product, and the SI partner.
RSS feed is public and free.
"""

import re
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay

logger = get_logger(__name__)

RSS_URL     = "https://erptoday.com/feed/"
MAX_ENTRIES = 60

ORACLE_KEYWORDS = [
    "oracle", "netsuite", "oracle cloud", "oracle fusion", "oracle erp",
    "oracle hcm", "oracle scm", "oracle epm", "oracle oci", "oracle cx",
    "oracle financials", "oracle planning",
]

PRODUCT_PATTERNS = [
    (r"Oracle\s+Fusion\s+Cloud\s+ERP",            "Oracle Cloud ERP"),
    (r"Oracle\s+Cloud\s+ERP",                     "Oracle Cloud ERP"),
    (r"Oracle\s+Fusion\s+Cloud\s+HCM",            "Oracle HCM"),
    (r"Oracle\s+Cloud\s+HCM",                     "Oracle HCM"),
    (r"Oracle\s+HCM",                             "Oracle HCM"),
    (r"Oracle\s+Fusion\s+Cloud\s+SCM",            "Oracle SCM"),
    (r"Oracle\s+Cloud\s+SCM",                     "Oracle SCM"),
    (r"Oracle\s+Fusion\s+Cloud\s+EPM",            "Oracle EPM"),
    (r"Oracle\s+Cloud\s+EPM",                     "Oracle EPM"),
    (r"Oracle\s+Hyperion",                        "Oracle EPM"),
    (r"Oracle\s+Fusion\s+Cloud\s+CX",             "Oracle CX"),
    (r"Oracle\s+Cloud\s+CX",                      "Oracle CX"),
    (r"Oracle\s+NetSuite|NetSuite",               "NetSuite"),
    (r"Oracle\s+Cloud\s+Infrastructure|OCI\b",    "Oracle OCI"),
    (r"Oracle\s+Autonomous\s+Database",           "Oracle Database"),
    (r"Oracle\s+Analytics",                       "Oracle Analytics"),
    (r"Oracle\s+Cloud",                           "Oracle Cloud"),
    (r"Oracle",                                   "Oracle (General)"),
]

COMPANY_PATTERNS = [
    r"^([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:selects?|chooses?|adopts?|deploys?|implements?|goes?\s+live|migrates?|transforms?|upgrades?|partners?\s+with)\s+Oracle",
    r"^([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:selects?|chooses?|adopts?|deploys?|implements?|migrates?)\s+NetSuite",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+goes?\s+live\s+(?:with|on)\s+Oracle",
    r"Oracle\s+(?:selected\s+by|chosen\s+by|deployed\s+at|implemented\s+at|wins?\s+)\s*([A-Z][A-Za-z0-9\s&',\.\-]{2,50})",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+taps?\s+Oracle",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:signs?|awards?)\s+Oracle\s+deal",
]

PHASE_PATTERNS = [
    (r"goes?\s+live|go-live|launched?|completed?|successful", "post_live"),
    (r"selects?|chooses?|awards?|signs?\s+deal|taps?",        "evaluating"),
    (r"implements?|deploys?|migrates?|transforms?|upgrades?",  "implementing"),
]


class ErpTodaySignal(BaseSignal):
    source_name = "erp_today"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        results = []
        try:
            feed = feedparser.parse(RSS_URL)
            entries = feed.entries[:MAX_ENTRIES]
            logger.info(f"ERP Today RSS — {len(entries)} articles")

            for entry in entries:
                title   = clean_text(entry.get("title", ""))
                summary = truncate(clean_text(entry.get("summary", "")), 600)
                link    = entry.get("link", "")
                date    = entry.get("published", "")
                combined = f"{title} {summary}"

                if not any(kw in combined.lower() for kw in ORACLE_KEYWORDS):
                    continue

                company = self._extract_company(title, summary)
                if not company:
                    continue

                product = self._extract_product(combined)
                phase   = self._infer_phase(title)

                results.append(self._make_signal(
                    company_name=company,
                    job_title=title,
                    description=summary or title,
                    url=link,
                    posted_date=date,
                    extra={
                        "signal_type": "news_article",
                        "oracle_product_hint": product,
                        "phase_hint": phase,
                    },
                ))

        except Exception as e:
            logger.error(f"ERP Today RSS error: {e}")

        logger.info(f"ERP Today → {len(results)} Oracle signals")
        return results

    def _extract_company(self, title: str, summary: str) -> str:
        for pat in COMPANY_PATTERNS:
            for text in (title, summary):
                m = re.search(pat, text.strip())
                if m:
                    candidate = m.group(1).strip().rstrip(".,;:")
                    if is_valid_company_name(candidate) and "oracle" not in candidate.lower():
                        return candidate
        return ""

    def _extract_product(self, text: str) -> str:
        for pat, name in PRODUCT_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return name
        return "Oracle (General)"

    def _infer_phase(self, title: str) -> str:
        t = title.lower()
        for pat, phase in PHASE_PATTERNS:
            if re.search(pat, t):
                return phase
        return "implementing"
