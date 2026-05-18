"""
SEC / Public Filings signal — EDGAR full-text search (completely free, no key).

Searches 10-K, 10-Q, 8-K filings mentioning Oracle Cloud migrations.
Endpoint: https://efts.sec.gov/LATEST/search-index
Returns the filing company as a lead.
"""

import re
import requests
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay
from src import config

logger = get_logger(__name__)

EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"

_QUERIES = [
    "oracle cloud ERP implementation",
    "oracle fusion cloud migration",
    "oracle netsuite implementation",
    "implementing oracle ERP",
    "oracle cloud HCM implementation",
    "oracle cloud EPM implementation",
]

_FORM_TYPES = ["10-K", "10-Q", "8-K"]


class SECFilingSignal(BaseSignal):
    source_name = "sec_filing"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        max_pages = max_pages or config.MAX_PAGES
        results = []
        seen = set()

        for q in _QUERIES:
            for form in _FORM_TYPES:
                results.extend(self._search(q, form, max_pages, seen))
                random_delay(0.5, 1.0)

        return results

    def _search(self, query: str, form: str, max_pages: int, seen: set) -> list[dict]:
        results = []
        per_page = 20

        for page in range(max_pages):
            try:
                params = {
                    "q":          f'"{query}"',
                    "dateRange":  "custom",
                    "startdt":    "2022-01-01",
                    "forms":      form,
                    "from":       page * per_page,
                    "size":       per_page,
                }
                resp = requests.get(
                    EDGAR_SEARCH,
                    params=params,
                    headers={"User-Agent": "OracleIntentEngine research@oracle-intent.com"},
                    timeout=20,
                )
                if resp.status_code == 429:
                    logger.warning("EDGAR rate limit — pausing")
                    random_delay(5, 10)
                    break
                if resp.status_code != 200:
                    logger.warning(f"EDGAR: {resp.status_code} for '{query}'")
                    break

                data = resp.json()
                hits = data.get("hits", {}).get("hits", []) or []
                if not hits:
                    break

                for hit in hits:
                    src = hit.get("_source", {})
                    company  = clean_text(src.get("entity_name", "") or src.get("display_names", [""])[0])
                    form_type = src.get("form_type", form)
                    filed_at  = src.get("file_date", "")
                    file_url  = f"https://www.sec.gov/Archives/edgar/data/{src.get('entity_id','')}/{src.get('file_num','')}"
                    # Prefer the EDGAR filing viewer URL
                    accession = src.get("accession_no", "").replace("-", "")
                    entity_id = src.get("entity_id", "")
                    if accession and entity_id:
                        file_url = f"https://www.sec.gov/Archives/edgar/data/{entity_id}/{accession}"

                    excerpt   = truncate(clean_text(src.get("period_of_report", "") + " " + query), 400)

                    key = company + accession
                    if key in seen:
                        continue
                    seen.add(key)

                    if not company or not is_valid_company_name(company):
                        continue

                    results.append(self._make_signal(
                        company_name=company,
                        job_title=f"{form_type}: {query}",
                        description=f"SEC {form_type} filing mentions: {query}. Filed {filed_at}. {excerpt}",
                        url=file_url,
                        posted_date=filed_at,
                        signal_type="sec_filing",
                    ))

                logger.info(f"EDGAR '{query}' {form} page {page+1} → {len(hits)} filings")
                if len(hits) < per_page:
                    break

            except Exception as e:
                logger.error(f"EDGAR error '{query}' {form}: {e}")
                break

        return results
