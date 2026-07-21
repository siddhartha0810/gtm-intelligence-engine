"""
SI Case Study signal scraper.

Searches Bing News RSS for Oracle implementation case studies published by
major Oracle System Integrators (Accenture, Deloitte, PwC, KPMG, EY, etc.).

Key difference from the staffing filter: we extract the CLIENT company from
these case studies, not the SI partner.  "Accenture helps Maersk implement
Oracle Cloud ERP" → signal for Maersk.

Also scrapes Oracle's own partner success story queries.
"""

import re
import requests
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay

logger = get_logger(__name__)

# Major Oracle SIs whose case studies we mine for client names
SI_PARTNERS = [
    "Accenture", "Deloitte", "PwC", "KPMG", "EY",
    "Infosys", "Wipro", "Capgemini", "TCS", "HCL",
    "Cognizant", "NTT Data", "DXC", "IBM", "Birlasoft",
]

# Bing RSS queries that surface SI-published Oracle case studies
_SI_QUERIES = [
    "oracle cloud erp implementation case study customer success 2024",
    "oracle fusion cloud implementation case study enterprise",
    "oracle cloud hcm deployment case study",
    "oracle cloud erp go live customer announcement",
    "oracle cloud digital transformation case study",
    "netsuite implementation case study 2024",
    "oracle cloud scm implementation success story",
    "oracle cloud finance transformation case study",
]

# Oracle partner / newsroom specific queries
_ORACLE_PARTNER_QUERIES = [
    "oracle partner implementation customer goes live",
    "oracle cloud implementation success story press release",
    "oracle customer award partner excellence",
]

PRODUCT_PATTERNS = [
    (r"Oracle\s+Fusion\s+Cloud\s+ERP",            "Oracle Cloud ERP"),
    (r"Oracle\s+Cloud\s+ERP",                     "Oracle Cloud ERP"),
    (r"Oracle\s+Fusion\s+Cloud\s+HCM",            "Oracle HCM"),
    (r"Oracle\s+Cloud\s+HCM|Oracle\s+HCM",        "Oracle HCM"),
    (r"Oracle\s+Fusion\s+Cloud\s+SCM|Oracle\s+Cloud\s+SCM", "Oracle SCM"),
    (r"Oracle\s+Cloud\s+EPM|Oracle\s+EPM|Oracle\s+Hyperion", "Oracle EPM"),
    (r"Oracle\s+Cloud\s+CX",                      "Oracle CX"),
    (r"Oracle\s+NetSuite|NetSuite",               "NetSuite"),
    (r"Oracle\s+Cloud\s+Infrastructure|OCI\b",    "Oracle OCI"),
    (r"Oracle\s+Analytics",                       "Oracle Analytics"),
    (r"Oracle\s+Cloud",                           "Oracle Cloud"),
    (r"Oracle",                                   "Oracle (General)"),
]

# Patterns to extract the CLIENT company name from a case-study headline
CLIENT_PATTERNS = [
    # "[SI] helps [CLIENT] implement Oracle..."
    r"(?:helps?|assisted?|partners?\s+with|supports?|enables?)\s+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:implement|deploy|migrate|transform|modernize|go\s+live)",
    # "[CLIENT] selects Oracle with [SI]"
    r"^([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:selects?|chooses?|adopts?|deploys?|implements?|goes?\s+live|migrates?)",
    # "How [SI] helped [CLIENT]..."
    r"(?:helped?|enabled?|assisted?)\s+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:to\s+)?(?:implement|deploy|migrate|transform|achieve|go\s+live)",
    # "[CLIENT] achieves X with Oracle and [SI]"
    r"([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:achieves?|gains?|drives?|builds?|streamlines?|unlocks?)\s+.{0,40}(?:Oracle|NetSuite)",
    # "Oracle goes live at [CLIENT]"
    r"Oracle\s+(?:goes?\s+live\s+at|deployed\s+at|implemented\s+at|selected\s+by|chosen\s+by)\s+([A-Z][A-Za-z0-9\s&',\.\-]{2,50})",
]

PHASE_PATTERNS = [
    (r"goes?\s+live|go-live|launched?|completed?|successful|post",  "post_live"),
    (r"selects?|chooses?|awards?|signs?|taps?",                     "evaluating"),
    (r"implements?|deploys?|migrates?|transforms?|modernizes?",     "implementing"),
]

_SI_NAME_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(si) for si in SI_PARTNERS) + r")\b",
    re.IGNORECASE,
)


class SICaseStudySignal(BaseSignal):
    source_name = "si_casestudy"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        results: list[dict] = []
        seen_titles: set = set()

        all_queries = _SI_QUERIES + _ORACLE_PARTNER_QUERIES

        for q in all_queries:
            try:
                encoded = requests.utils.quote(q)
                url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
                feed = feedparser.parse(url)

                for entry in feed.entries[:15]:
                    title   = clean_text(entry.get("title", ""))
                    summary = truncate(clean_text(entry.get("summary", "")), 600)
                    link    = entry.get("link", "")
                    date    = entry.get("published", "")

                    if title in seen_titles:
                        continue
                    seen_titles.add(title)

                    combined = f"{title} {summary}"
                    if "oracle" not in combined.lower() and "netsuite" not in combined.lower():
                        continue

                    company = self._extract_client(title, summary)
                    if not company:
                        continue

                    # Skip if extracted "client" is itself an SI
                    if _SI_NAME_RE.search(company):
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
                            "signal_type": "case_study",
                            "oracle_product_hint": product,
                            "phase_hint": phase,
                        },
                    ))

                random_delay(0.5, 1.5)

            except Exception as e:
                logger.error(f"SI case study Bing RSS error for '{q}': {e}")

        logger.info(f"SI Case Studies → {len(results)} client company signals")
        return results

    def _extract_client(self, title: str, summary: str) -> str:
        for pat in CLIENT_PATTERNS:
            for text in (title, summary):
                m = re.search(pat, text.strip(), re.IGNORECASE)
                if m:
                    candidate = m.group(1).strip().rstrip(".,;:")
                    if (is_valid_company_name(candidate)
                            and "oracle" not in candidate.lower()
                            and len(candidate) > 2):
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
