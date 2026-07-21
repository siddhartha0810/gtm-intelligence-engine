"""
ERP / Oracle News signal — multi-source ERP news RSS aggregator.

Sources (all free, no keys):
  1. erptoday.com/feed/       — B2B ERP publication (tried first; may 404/empty)
  2. diginomica.com/tag/oracle/feed/ — Oracle-tagged analyst articles
  3. Bing News RSS             — broad coverage; fallback for dead feeds
     Covers: Oracle Cloud, EBS, PeopleSoft, Siebel, Hyperion, JDE go-lives

Company extraction:
  Regex patterns that work on "[Company] selects/goes live Oracle …" headlines.
  LLM fallback (Ollama/Claude) when regex finds nothing.
"""

import re
import requests
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay
from src import llm_extractor

logger = get_logger(__name__)

# Primary RSS feeds to try before Bing fallback
_PRIMARY_FEEDS = [
    ("erptoday",   "https://erptoday.com/feed/"),
    ("diginomica", "https://diginomica.com/tag/oracle/feed/"),
    ("erp_focus",  "https://erpfocus.com/feed/"),
]

# Bing News RSS queries for Oracle product news — covers legacy + cloud
_BING_QUERIES = [
    # Oracle Cloud (modern)
    "oracle cloud ERP implementation go live 2024",
    "oracle fusion cloud customer go live announcement",
    "oracle cloud HCM implementation go live",
    "oracle netsuite implementation go live announcement",
    "oracle cloud EPM planning implementation",
    "oracle cloud SCM supply chain go live",
    # Oracle EBS (legacy — massive installed base)
    "oracle E-Business Suite implementation go live",
    "oracle EBS R12 upgrade announcement",
    "oracle EBS migration cloud go live",
    "oracle EBS upgrade project",
    # PeopleSoft (HR/Finance — huge public sector base)
    "oracle PeopleSoft upgrade implementation",
    "PeopleSoft HCM go live announcement",
    "PeopleSoft financials implementation",
    "PeopleSoft to oracle cloud migration",
    # Siebel CRM (still in many large enterprises)
    "oracle Siebel CRM implementation upgrade",
    "Siebel to oracle CX migration",
    # Hyperion EPM (financial consolidation)
    "oracle Hyperion planning implementation",
    "oracle Hyperion financial management go live",
    # JDE (already covered by LinkedIn but news adds context)
    "JD Edwards go live implementation announcement",
    "JD Edwards upgrade announcement 2024",
]

ORACLE_KEYWORDS = {
    "oracle", "netsuite", "fusion", "ebs", "e-business suite", "peoplesoft",
    "siebel", "hyperion", "jd edwards", "jde", "oic", "oci",
}

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
    (r"Hyperion\s+(?:Planning|Financial)",        "Oracle EPM"),
    (r"Oracle\s+Fusion\s+Cloud\s+CX",             "Oracle CX"),
    (r"Oracle\s+Cloud\s+CX",                      "Oracle CX"),
    (r"Oracle\s+Siebel",                          "Oracle Siebel CRM"),
    (r"Siebel\s+CRM",                             "Oracle Siebel CRM"),
    (r"Oracle\s+NetSuite|NetSuite",               "NetSuite"),
    (r"Oracle\s+Cloud\s+Infrastructure|OCI\b",    "Oracle OCI"),
    (r"Oracle\s+Autonomous\s+Database",           "Oracle Database"),
    (r"Oracle\s+E-Business\s+Suite|Oracle\s+EBS", "Oracle EBS"),
    (r"PeopleSoft",                               "Oracle PeopleSoft"),
    (r"JD\s+Edwards|JDE\b",                       "JD Edwards"),
    (r"Oracle\s+Analytics",                       "Oracle Analytics"),
    (r"Oracle\s+Cloud",                           "Oracle Cloud"),
    (r"Oracle",                                   "Oracle (General)"),
]

COMPANY_PATTERNS = [
    r"^([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:selects?|chooses?|adopts?|deploys?|implements?|goes?\s+live|migrates?|transforms?|upgrades?|partners?\s+with)\s+Oracle",
    r"^([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:selects?|chooses?|adopts?|deploys?|implements?|migrates?)\s+(?:NetSuite|PeopleSoft|Siebel|Hyperion|JD\s+Edwards)",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+goes?\s+live\s+(?:with|on)\s+Oracle",
    r"Oracle\s+(?:selected\s+by|chosen\s+by|deployed\s+at|implemented\s+at|wins?\s+)\s*([A-Z][A-Za-z0-9\s&',\.\-]{2,50})",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+taps?\s+Oracle",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:signs?|awards?)\s+Oracle\s+deal",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:selects?|upgrades?)\s+(?:to\s+)?PeopleSoft",
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:migrates?|moves?)\s+(?:from\s+)?(?:Siebel|EBS|E-Business|PeopleSoft)",
]

PHASE_PATTERNS = [
    (r"goes?\s+live|go-live|launched?|completed?|successful|implemented",  "post_live"),
    (r"selects?|chooses?|awards?|signs?\s+deal|taps?",                     "evaluating"),
    (r"implements?|deploys?|migrates?|transforms?|upgrades?",              "implementing"),
]


def _mentions_oracle(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in ORACLE_KEYWORDS)


class ErpTodaySignal(BaseSignal):
    source_name = "erp_today"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        results: list[dict] = []
        seen: set[str] = set()

        # Tier 1: Primary RSS feeds
        for feed_name, feed_url in _PRIMARY_FEEDS:
            try:
                resp = requests.get(feed_url, timeout=10)
                if resp.status_code != 200 or len(resp.content) < 500:
                    logger.debug(f"{feed_name} RSS empty/unavailable ({resp.status_code})")
                    continue
                feed = feedparser.parse(resp.text)
                if not feed.entries:
                    logger.debug(f"{feed_name} RSS no entries")
                    continue
                count = 0
                for entry in feed.entries[:80]:
                    sig = self._process_entry(entry, seen)
                    if sig:
                        results.append(sig)
                        count += 1
                logger.info(f"{feed_name} RSS → {count} Oracle signals")
            except Exception as e:
                logger.debug(f"{feed_name} RSS error: {e}")

        # Tier 2: Bing News RSS — covers legacy Oracle products comprehensively
        for q in _BING_QUERIES:
            try:
                encoded = requests.utils.quote(q)
                url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
                feed = feedparser.parse(url)
                count = 0
                for entry in feed.entries[:15]:
                    sig = self._process_entry(entry, seen)
                    if sig:
                        results.append(sig)
                        count += 1
                if count:
                    logger.info(f"ERP Bing '{q[:50]}' → {count} signals")
                random_delay(0.5, 1.0)
            except Exception as e:
                logger.debug(f"ERP Bing error for '{q[:40]}': {e}")

        logger.info(f"ErpTodaySignal total: {len(results)} Oracle ERP signals")
        return results

    def _process_entry(self, entry: dict, seen: set) -> dict | None:
        title   = clean_text(entry.get("title", ""))
        raw     = entry.get("summary", "") or entry.get("description", "")
        summary = truncate(clean_text(raw), 600)
        link    = entry.get("link", "")
        date    = entry.get("published", "")
        combined = f"{title} {summary}"

        if not _mentions_oracle(combined):
            return None

        dedup_key = (link or title)[:120]
        if dedup_key in seen:
            return None
        seen.add(dedup_key)

        company = self._extract_company(title, summary)
        if not company:
            company = llm_extractor.extract_company(title, summary)
        if not company:
            return None

        product = self._extract_product(combined)
        phase   = self._infer_phase(title)

        return self._make_signal(
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
        )

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
