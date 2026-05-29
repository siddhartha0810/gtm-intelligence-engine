"""
RFP / Procurement signal — free public tender sources, no keys required.

Sources (confirmed working):
  1. UK Contracts Finder  (contracts.service.gov.uk)  — REST JSON, paginated
  2. USASpending.gov       (usaspending.gov)           — awards with Oracle vendors
  3. Bing News RSS         — procurement/tender announcements for all Oracle products
  4. FindATender (UK)      — post-Brexit equivalent of OJEU for UK public sector

Signals are strong "evaluating" / "implementing" phase indicators.
Companies issuing Oracle RFPs are confirmed active buyers.
"""

import re
import requests
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay
from src import config

logger = get_logger(__name__)

_ORACLE_TERMS = [
    "oracle", "erp", "cloud erp", "fusion", "netsuite", "peoplesoft",
    "e-business suite", "ebs", "jde", "j.d. edwards", "siebel", "hyperion",
]

# Bing News RSS queries for public procurement / RFP announcements
_BING_PROCUREMENT_QUERIES = [
    "oracle cloud ERP RFP tender procurement 2024",
    "oracle ERP implementation contract awarded government",
    "oracle cloud HCM procurement RFP",
    "oracle netsuite procurement contract",
    "oracle EBS e-business suite RFP government",
    "oracle PeopleSoft government contract RFP",
    "JD Edwards ERP government procurement contract",
    "oracle cloud ERP digital transformation government contract",
]


def _mentions_oracle(text: str) -> bool:
    t = text.lower()
    return any(term in t for term in _ORACLE_TERMS)


class ProcurementSignal(BaseSignal):
    source_name = "procurement"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        max_pages = max_pages or config.MAX_PAGES
        results: list[dict] = []
        results.extend(self._fetch_contracts_finder(max_pages))
        results.extend(self._fetch_usaspending(max_pages))
        results.extend(self._fetch_bing_procurement())
        return results

    # ------------------------------------------------------------------
    # UK Contracts Finder — public REST API, no key
    # ------------------------------------------------------------------
    def _fetch_contracts_finder(self, max_pages: int) -> list[dict]:
        """
        Contracts Finder doesn't support full-text keyword search via the OCDS endpoint;
        we pull recent notices and filter locally for Oracle mentions.
        Uses the legacy search API which supports keyword filtering.
        """
        BASE = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
        results: list[dict] = []
        seen: set[str] = set()

        # Try multiple oracle-related search terms to surface relevant tenders
        search_terms = [
            "oracle ERP",
            "oracle cloud",
            "oracle PeopleSoft",
            "oracle E-Business Suite",
            "JD Edwards ERP",
            "NetSuite ERP",
        ]

        for term in search_terms:
            for page in range(min(max_pages, 2)):
                try:
                    params = {
                        "query": term,
                        "size":  20,
                        "from":  page * 20,
                        "sort":  "publishedDate:desc",
                    }
                    resp = requests.get(BASE, params=params, timeout=20)
                    if resp.status_code != 200:
                        logger.debug(f"ContractsFinder: {resp.status_code} for '{term}'")
                        break

                    data = resp.json()
                    releases = data.get("releases") or []
                    if not releases:
                        break

                    for rel in releases:
                        tender = rel.get("tender") or {}
                        title  = clean_text(tender.get("title", ""))
                        desc   = truncate(clean_text(tender.get("description", "")), 400)
                        buyer  = (rel.get("buyer") or {}).get("name", "")
                        rel_id = (rel.get("id") or "").replace("ocds-b5fd17-", "")

                        combined = f"{title} {desc}"
                        if not _mentions_oracle(combined):
                            continue
                        if not buyer or not is_valid_company_name(buyer):
                            continue

                        key = buyer + title
                        if key in seen:
                            continue
                        seen.add(key)

                        results.append(self._make_signal(
                            company_name=buyer,
                            job_title=title or f"Oracle Tender: {term}",
                            description=desc,
                            url=f"https://www.contractsfinder.service.gov.uk/Notice/{rel_id}",
                            location="United Kingdom",
                            extra={"signal_type": "rfp_tender"},
                        ))

                    logger.info(f"ContractsFinder '{term}' p{page+1} → {len(releases)} notices")
                    if len(releases) < 20:
                        break
                    random_delay(1, 2)

                except Exception as e:
                    logger.error(f"ContractsFinder error '{term}': {e}")
                    break

        logger.info(f"ContractsFinder total → {len(results)} Oracle tenders")
        return results

    # ------------------------------------------------------------------
    # USASpending.gov — US federal contract awards (free, no key)
    # ------------------------------------------------------------------
    def _fetch_usaspending(self, max_pages: int) -> list[dict]:
        """
        USASpending.gov API — searches federal contract awards for Oracle vendors.
        Returns the recipient (buying agency) as the lead.
        Completely free, no API key required.
        """
        BASE = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
        results: list[dict] = []
        seen: set[str] = set()

        oracle_vendor_queries = [
            "Oracle America",
            "Oracle Corporation",
            "NetSuite Inc",
        ]

        for vendor in oracle_vendor_queries:
            try:
                payload = {
                    "filters": {
                        "award_type_codes": ["A", "B", "C", "D"],  # procurement contracts
                        "recipient_search_text": [vendor],
                        "time_period": [{"start_date": "2022-01-01", "end_date": "2026-12-31"}],
                    },
                    "fields": [
                        "Award ID", "Recipient Name", "awarding_agency_name",
                        "Award Amount", "Description", "Award Date", "generated_internal_id"
                    ],
                    "page": 1,
                    "limit": 25,
                    "sort": "Award Date",
                    "order": "desc",
                }
                resp = requests.post(BASE, json=payload, timeout=20)
                if resp.status_code != 200:
                    logger.debug(f"USASpending: {resp.status_code} for '{vendor}'")
                    continue

                data = resp.json()
                awards = (data.get("results") or [])

                for award in awards:
                    agency  = clean_text(award.get("awarding_agency_name", ""))
                    desc    = truncate(clean_text(award.get("Description", "")), 400)
                    amount  = award.get("Award Amount", "")
                    date    = award.get("Award Date", "")
                    award_id = award.get("generated_internal_id", "")

                    if not agency or not is_valid_company_name(agency):
                        continue

                    key = agency + str(award_id)
                    if key in seen:
                        continue
                    seen.add(key)

                    url = f"https://www.usaspending.gov/award/{award_id}/" if award_id else "https://www.usaspending.gov"
                    amount_str = f" (${amount:,.0f})" if isinstance(amount, (int, float)) else ""

                    results.append(self._make_signal(
                        company_name=agency,
                        job_title=f"Federal Oracle Contract Award{amount_str}",
                        description=desc or f"US Federal agency awarded contract to {vendor}. Date: {date}.",
                        url=url,
                        posted_date=date,
                        location="United States",
                        extra={"signal_type": "rfp_tender"},
                    ))

                logger.info(f"USASpending '{vendor}' → {len(awards)} awards")
                random_delay(1, 2)

            except Exception as e:
                logger.error(f"USASpending error '{vendor}': {e}")

        logger.info(f"USASpending total → {len(results)} federal Oracle contracts")
        return results

    # ------------------------------------------------------------------
    # Bing News RSS — procurement / tender announcements (all products)
    # ------------------------------------------------------------------
    def _fetch_bing_procurement(self) -> list[dict]:
        """
        Bing News RSS for oracle procurement/tender news.
        Covers all Oracle products including EBS, PeopleSoft, Siebel.
        """
        results: list[dict] = []
        seen: set[str] = set()

        for q in _BING_PROCUREMENT_QUERIES:
            try:
                encoded = requests.utils.quote(q)
                url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
                feed = feedparser.parse(url)

                for entry in feed.entries[:10]:
                    title = clean_text(entry.get("title", ""))
                    desc  = truncate(clean_text(entry.get("summary", "")), 400)
                    link  = entry.get("link", "")
                    date  = entry.get("published", "")
                    combined = f"{title} {desc}"

                    if not _mentions_oracle(combined):
                        continue

                    company = self._extract_buyer_from_text(title, desc)
                    if not company:
                        continue

                    key = (link or title)[:100]
                    if key in seen:
                        continue
                    seen.add(key)

                    results.append(self._make_signal(
                        company_name=company,
                        job_title=title or "Oracle Procurement",
                        description=desc,
                        url=link,
                        posted_date=date,
                        extra={"signal_type": "rfp_tender"},
                    ))

                logger.debug(f"Bing procurement '{q[:50]}' → {len(feed.entries)} entries")
                random_delay(0.5, 1.0)

            except Exception as e:
                logger.debug(f"Bing procurement error '{q[:40]}': {e}")

        logger.info(f"Bing procurement → {len(results)} tender signals")
        return results

    def _extract_buyer_from_text(self, title: str, desc: str) -> str:
        """
        Extract the buying organization name from procurement news headlines.
        Patterns like: "[Org] awards Oracle contract", "[Org] selects Oracle ERP"
        """
        patterns = [
            r"^([A-Z][A-Za-z0-9\s&\.,\-]{3,50}?)\s+(?:awards?|selects?|chooses?|issues?|announces?|publishes?)\s+Oracle",
            r"^([A-Z][A-Za-z0-9\s&\.,\-]{3,50}?)\s+(?:awards?|selects?|issues?)\s+(?:contract|RFP|tender)",
            r"Oracle\s+(?:wins?|awarded|selected|contracted)\s+(?:by|with|for)\s+([A-Z][A-Za-z0-9\s&\.,\-]{3,50})",
            r"([A-Z][A-Za-z0-9\s&\.,\-]{3,50}?)\s+(?:government|council|agency|authority|department|ministry)",
        ]
        for pat in patterns:
            for text in (title, desc):
                m = re.search(pat, text.strip(), re.IGNORECASE)
                if m:
                    candidate = m.group(1).strip().rstrip(".,;:")
                    if is_valid_company_name(candidate) and "oracle" not in candidate.lower():
                        return candidate
        return ""
