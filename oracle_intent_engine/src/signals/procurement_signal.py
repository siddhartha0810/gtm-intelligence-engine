"""
RFP / Procurement signal — free public tender APIs, no keys required.

Sources:
  - UK Contracts Finder (contracts.service.gov.uk) — free JSON API, paginated
  - SAM.gov US (api.sam.gov) — free with DEMO_KEY, paginated
  - TED EU (ted.europa.eu) — free RSS feed

Looks for Oracle ERP/Cloud implementation tenders → strong "evaluating" phase signal.
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
    "e-business suite", "ebs", "jde", "j.d. edwards",
]

def _mentions_oracle(text: str) -> bool:
    t = text.lower()
    return any(term in t for term in _ORACLE_TERMS)


class ProcurementSignal(BaseSignal):
    source_name = "procurement"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        max_pages = max_pages or config.MAX_PAGES
        results = []
        results.extend(self._fetch_contracts_finder(max_pages))
        results.extend(self._fetch_sam_gov(max_pages))
        results.extend(self._fetch_ted_eu())
        return results

    # ------------------------------------------------------------------
    # UK Contracts Finder
    # ------------------------------------------------------------------
    def _fetch_contracts_finder(self, max_pages: int) -> list[dict]:
        BASE = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
        results = []
        page = 0
        per_page = 20

        while page < max_pages:
            try:
                params = {
                    "query":    "oracle ERP cloud implementation",
                    "size":     per_page,
                    "from":     page * per_page,
                    "sort":     "publishedDate:desc",
                }
                resp = requests.get(BASE, params=params, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"ContractsFinder: {resp.status_code}")
                    break

                data = resp.json()
                releases = data.get("releases", []) or []
                if not releases:
                    break

                for rel in releases:
                    tender = rel.get("tender", {}) or {}
                    title  = clean_text(tender.get("title", ""))
                    desc   = truncate(clean_text(tender.get("description", "")), 400)
                    buyer  = (rel.get("buyer") or {}).get("name", "")
                    url    = (rel.get("id") or "").replace("ocds-b5fd17-", "")

                    if not _mentions_oracle(title + " " + desc):
                        continue
                    if not buyer or not is_valid_company_name(buyer):
                        continue

                    results.append(self._make_signal(
                        company_name=buyer,
                        job_title=title or "Oracle ERP Tender",
                        description=desc,
                        url=f"https://www.contractsfinder.service.gov.uk/Notice/{url}",
                        signal_type="rfp_tender",
                    ))

                logger.info(f"ContractsFinder page {page+1} → {len(releases)} notices")
                if len(releases) < per_page:
                    break

                page += 1
                random_delay(1, 2)

            except Exception as e:
                logger.error(f"ContractsFinder error: {e}")
                break

        return results

    # ------------------------------------------------------------------
    # SAM.gov (US Federal)
    # ------------------------------------------------------------------
    def _fetch_sam_gov(self, max_pages: int) -> list[dict]:
        BASE = "https://api.sam.gov/opportunities/v2/search"
        results = []
        limit  = 25

        for page in range(max_pages):
            try:
                params = {
                    "api_key": "DEMO_KEY",
                    "q":       "oracle cloud ERP implementation",
                    "limit":   limit,
                    "offset":  page * limit,
                    "postedFrom": "01/01/2024",
                    "ptype":   "p,o,k",   # presolicitation, solicitation, combined
                    "active":  "Yes",
                }
                resp = requests.get(BASE, params=params, timeout=20)
                if resp.status_code == 429:
                    logger.warning("SAM.gov rate limit — stopping")
                    break
                if resp.status_code != 200:
                    logger.warning(f"SAM.gov: {resp.status_code}")
                    break

                data  = resp.json()
                items = data.get("opportunitiesData", []) or []
                if not items:
                    break

                for item in items:
                    title     = clean_text(item.get("title", ""))
                    desc      = truncate(clean_text(item.get("description", "")), 400)
                    org       = clean_text(item.get("organizationName", ""))
                    dept      = clean_text(item.get("departmentName", ""))
                    url       = item.get("uiLink", "") or f"https://sam.gov/opp/{item.get('noticeId','')}/view"
                    buyer     = org or dept

                    if not _mentions_oracle(title + " " + desc):
                        continue
                    if not buyer or not is_valid_company_name(buyer):
                        continue

                    results.append(self._make_signal(
                        company_name=buyer,
                        job_title=title or "Oracle ERP Procurement",
                        description=desc,
                        url=url,
                        signal_type="rfp_tender",
                        location="United States",
                    ))

                logger.info(f"SAM.gov page {page+1} → {len(items)} opportunities")
                if len(items) < limit:
                    break

                random_delay(1, 2)

            except Exception as e:
                logger.error(f"SAM.gov error: {e}")
                break

        return results

    # ------------------------------------------------------------------
    # TED EU (European public procurement)
    # ------------------------------------------------------------------
    def _fetch_ted_eu(self) -> list[dict]:
        # TED search RSS — no key, no pagination needed (returns recent)
        RSS = "https://ted.europa.eu/api/latest/notices/rss?q=oracle+cloud+erp&sortField=ND&pageSize=50"
        results = []
        try:
            feed = feedparser.parse(RSS)
            for entry in feed.entries:
                title   = clean_text(entry.get("title", ""))
                desc    = truncate(clean_text(re.sub(r"<[^>]+>", " ", entry.get("summary", ""))), 400)
                link    = entry.get("link", "")
                # buyer is often in title: "Oracle ERP — BuyerOrg — Country"
                buyer   = self._extract_buyer_ted(title, desc)

                if not _mentions_oracle(title + " " + desc):
                    continue
                if not buyer:
                    continue

                results.append(self._make_signal(
                    company_name=buyer,
                    job_title=title or "Oracle ERP EU Tender",
                    description=desc,
                    url=link,
                    signal_type="rfp_tender",
                    location="European Union",
                ))

            logger.info(f"TED EU → {len(results)} relevant tenders")
        except Exception as e:
            logger.error(f"TED EU error: {e}")

        return results

    def _extract_buyer_ted(self, title: str, desc: str) -> str:
        # TED titles often: "Title — OrgName — Country"
        for sep in (" — ", " – ", " | "):
            parts = title.split(sep)
            if len(parts) >= 2:
                for candidate in parts[1:]:
                    c = candidate.strip()
                    if is_valid_company_name(c) and len(c) > 3:
                        return c
        m = re.search(r"Contracting authority[:\s]+([A-Z][A-Za-z0-9\s&,\.]+)", desc)
        if m:
            c = m.group(1).strip().rstrip(",.")
            if is_valid_company_name(c):
                return c
        return ""
