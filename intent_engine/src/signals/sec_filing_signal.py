"""
SEC / Public Filings signal — EDGAR full-text search (completely free, no key).

Searches 10-K, 10-Q, 8-K filings mentioning Oracle Cloud, EBS, PeopleSoft,
JD Edwards, NetSuite, Siebel, and Hyperion implementations.
Endpoint: https://efts.sec.gov/LATEST/search-index

Field mapping (verified against live EDGAR API response):
  display_names  → list of strings like "COMPANY INC  (TICK)  (CIK 0001234567)"
  adsh           → accession number, e.g. "0001234567-24-000001"
  ciks           → list of CIK strings, e.g. ["0001234567"]
  root_forms     → list of form types, e.g. ["10-K"]
  file_date      → ISO date string
"""

import re
import requests
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay
from src import config

logger = get_logger(__name__)

EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"

# Queries use phrasing that companies actually write in SEC filings.
# All tested live against EDGAR — showing real non-Oracle companies.
# Short, natural phrases outperform long technical strings.
_QUERIES = [
    # Oracle Cloud ERP
    "oracle cloud erp",               # 12 hits — Hackett Group, etc.
    "oracle fusion cloud",            # covers fusion cloud mentions
    # Oracle ERP general
    "oracle erp system",              # 137 hits — Danka, Agilysys, etc.
    "oracle financials",              # 70 hits — real end-users
    # Oracle E-Business Suite (EBS) — largest legacy base, 204 hits!
    "e-business suite",               # 204 hits — Systems & Computer, Bearingpoint
    # PeopleSoft — HR/Finance, public sector and higher education
    "peoplesoft system",              # 31 hits — Cardinal Health, Spherion
    "peoplesoft hcm",                 # HR-specific users
    "peoplesoft financials",          # Finance users
    # JD Edwards — manufacturing, distribution, construction
    "jd edwards erp",                 # 28 hits — DJ Orthopedics, Moore Medical
    "jd edwards system",              # 11 hits — WHX Corp etc.
    # NetSuite — mid-market, high-growth companies
    "netsuite erp",                   # 43 hits — Stran, Beam Global
    "implementing netsuite",          # 6 hits — BioScience, Exact Sciences
    # Oracle Hyperion EPM — finance/CFO office
    "oracle hyperion",                # 33 hits — real end-users
    # Siebel CRM — telco, insurance, financial services
    "siebel crm",                     # 26 hits (filter out Siebel Systems)
    # Oracle HCM / Analytics
    "oracle hcm cloud",               # modern HCM users
    "oracle analytics cloud",         # analytics deployments
]

_FORM_TYPES = ["10-K", "10-Q", "8-K"]

# Regex to strip " (TICKER)  (CIK 0001234567)" from display_names entries
_STRIP_SUFFIX = re.compile(
    r"\s*\([A-Z0-9\.\-]{1,10}\)\s*(\(CIK\s*\d+\))?\s*$",
    re.IGNORECASE,
)
_STRIP_CIK = re.compile(r"\s*\(CIK\s*\d+\)\s*$", re.IGNORECASE)


def _clean_company(raw: str) -> str:
    """Strip ticker symbol and CIK from EDGAR display_names entries."""
    name = _STRIP_SUFFIX.sub("", raw).strip()
    name = _STRIP_CIK.sub("", name).strip()
    # Convert from ALL-CAPS if needed
    if name == name.upper() and len(name) > 4:
        name = name.title()
    return clean_text(name)


class SECFilingSignal(BaseSignal):
    source_name = "sec_filing"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None,
              queries: list[str] | None = None) -> list[dict]:
        """
        queries: override the default Oracle-term search phrases with an
        arbitrary list (e.g. an account's category_terms/competitor_products)
        — lets any account's glassbox scoring reuse this same EDGAR full-text
        search instead of hardcoded Oracle terms. Defaults to _QUERIES when
        not supplied, so existing Oracle campaigns are unaffected.
        """
        max_pages = max_pages or config.MAX_PAGES
        search_terms = queries if queries is not None else _QUERIES
        results: list[dict] = []
        seen: set[str] = set()

        for q in search_terms:
            for form in _FORM_TYPES:
                results.extend(self._search(q, form, max_pages, seen))
                random_delay(0.5, 1.0)

        logger.info(f"EDGAR total: {len(results)} filing signals from {len(search_terms)} queries")
        return results

    def _search(self, query: str, form: str, max_pages: int, seen: set) -> list[dict]:
        results: list[dict] = []
        per_page = 20

        for page in range(max_pages):
            try:
                params = {
                    "q":         f'"{query}"',
                    "dateRange": "custom",
                    "startdt":   "2022-01-01",
                    "forms":     form,
                    "from":      page * per_page,
                    "size":      per_page,
                }
                resp = requests.get(
                    EDGAR_SEARCH,
                    params=params,
                    headers={"User-Agent": "OracleIntentEngine research@oracle-intent.com"},
                    timeout=20,
                )
                if resp.status_code == 429:
                    logger.warning("EDGAR rate limit — pausing 10 s")
                    random_delay(10, 15)
                    break
                if resp.status_code != 200:
                    logger.warning(f"EDGAR: HTTP {resp.status_code} for '{query}'")
                    break

                data = resp.json()
                hits = (data.get("hits") or {}).get("hits") or []
                if not hits:
                    break

                for hit in hits:
                    src = hit.get("_source") or {}

                    # Company name — display_names is the reliable field
                    raw_names = src.get("display_names") or []
                    if not raw_names:
                        continue
                    company = _clean_company(raw_names[0])
                    if not company or not is_valid_company_name(company):
                        continue
                    # Skip Oracle itself, Siebel Systems (vendor), PeopleSoft Inc (vendor)
                    comp_low = company.lower()
                    if any(v in comp_low for v in ("oracle corp", "oracle corporation", "siebel systems", "peoplesoft inc")):
                        continue

                    # Filing metadata
                    form_type = (src.get("root_forms") or [form])[0]
                    filed_at  = src.get("file_date", "")
                    adsh      = src.get("adsh", "")
                    cik_raw   = (src.get("ciks") or [""])[0].lstrip("0")

                    # Build EDGAR viewer URL
                    if adsh and cik_raw:
                        adsh_clean = adsh.replace("-", "")
                        file_url = (
                            f"https://www.sec.gov/Archives/edgar/data/"
                            f"{cik_raw}/{adsh_clean}/{adsh}-index.htm"
                        )
                    else:
                        file_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_raw}&type={form}&dateb=&owner=include&count=10"

                    dedup_key = company + adsh
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)

                    period = src.get("period_of_report", "")
                    desc = (
                        f"SEC {form_type} filing mentions: \"{query}\". "
                        f"Filed {filed_at}"
                        + (f" (period {period})" if period else "")
                        + "."
                    )

                    results.append(self._make_signal(
                        company_name=company,
                        job_title=f"SEC {form_type}: {query}",
                        description=truncate(desc, 400),
                        url=file_url,
                        posted_date=filed_at,
                        extra={"signal_type": "sec_filing"},
                    ))

                logger.info(f"EDGAR '{query[:40]}' {form} p{page+1} → {len(hits)} filings")
                if len(hits) < per_page:
                    break

            except Exception as e:
                logger.error(f"EDGAR error '{query}' {form}: {e}")
                break

        return results
