"""
inrule_prospecting_signal.py
=============================
InRule-specific signal module. Pulls buying signals from three high-trust
sources that are uniquely valuable for InRule's regulated-industry ICP:

  1. USASpending.gov — federal contracts for competitor products (FICO Blaze,
     Corticon, IBM ODM, Drools) that are expiring within 12 months. These
     agencies are entering a procurement window and will issue a new RFP.
     Free, no API key required.

  2. OCC Enforcement Actions — Office of the Comptroller of the Currency
     publishes all enforcement actions (Consent Orders, Formal Agreements,
     Cease & Desist orders) against national banks. These create mandatory,
     time-bound technology remediation requirements. Free, no key required.

  3. LinkedIn Jobs (guest API) — job postings at companies actively hiring
     for competitor tools (FICO Blaze, Corticon, IBM ODM, Drools). If a
     company is hiring for a competitor, they have budget and a defined
     category. No authentication required.

All three inherit from BaseSignal and follow the standard signal dict shape.
The orchestrator (run_inrule_agent.py) calls each independently and merges
results into a unified evidence dict per company.

Signal dict shape (standard):
  {
    "company_name": str,
    "job_title":    str,   — repurposed as signal label
    "description":  str,   — evidence text
    "url":          str,   — source URL
    "source":       str,   — source_name attribute
    "location":     str,
    "posted_date":  str,
  }
"""

import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

_TODAY = datetime.utcnow().date()
_12_MONTHS_FROM_NOW = _TODAY + timedelta(days=365)


def _months_until(date_str: str) -> int | None:
    """Return months until a date string (YYYY-MM-DD). None if unparseable."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        delta = (d - _TODAY).days
        return round(delta / 30)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 1. USASpending — competitor contract expiry signals
# ---------------------------------------------------------------------------

_USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# Competitor product keywords to search for in contract descriptions.
# These are the exact strings that appear in USASpending contract descriptions.
_COMPETITOR_KEYWORDS = [
    "FICO Blaze",
    "Blaze Advisor",
    "Corticon",
    "IBM ODM",
    "IBM Operational Decision Manager",
    "Drools",
    "business rules engine",
    "decision management platform",
    "eligibility rules engine",
    "claims adjudication system",
    "underwriting rules engine",
]


class USASpendingCompetitorSignal(BaseSignal):
    """
    Finds federal contracts for competitor decision-automation products that
    are expiring within 12 months — the procurement window signal.

    The 'company_name' field is the awarding agency (the buyer), not the
    vendor. These agencies are the InRule prospect.
    """

    source_name = "usaspending_competitor"

    def fetch(self, query: str = "", location: str = "", max_pages: int = 3,
              keywords: list[str] | None = None) -> list[dict]:
        """
        keywords: override the default competitor keyword list with a custom
        list (e.g. from icp_profiles/inrule_signal_rules.yaml's
        competitor_contract_keywords). Defaults to _COMPETITOR_KEYWORDS.
        """
        search_keywords = keywords if keywords is not None else _COMPETITOR_KEYWORDS
        results: list[dict] = []
        seen: set[str] = set()

        for kw in search_keywords:
            try:
                payload = {
                    "filters": {
                        "keywords": [kw],
                        "award_type_codes": ["A", "B", "C", "D"],
                        "time_period": [
                            {
                                "start_date": "2020-01-01",
                                "end_date": _12_MONTHS_FROM_NOW.strftime("%Y-%m-%d"),
                            }
                        ],
                    },
                    "fields": [
                        "Award ID",
                        "Recipient Name",
                        "Description",
                        "Award Amount",
                        "Start Date",
                        "End Date",
                        "Awarding Agency",
                        "generated_internal_id",
                    ],
                    "page": 1,
                    "limit": 25,
                    "sort": "End Date",
                    "order": "asc",
                }
                resp = requests.post(
                    _USASPENDING_URL, json=payload, timeout=20
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"USASpending: HTTP {resp.status_code} for '{kw}'"
                    )
                    continue

                data = resp.json()
                awards = data.get("results") or []

                for award in awards:
                    agency = clean_text(award.get("Awarding Agency", ""))
                    desc = truncate(
                        clean_text(award.get("Description", "")), 400
                    )
                    amount = award.get("Award Amount", 0)
                    end_date = award.get("End Date", "")
                    award_id = award.get("generated_internal_id", "")
                    start_date = award.get("Start Date", "")

                    if not agency or not is_valid_company_name(agency):
                        continue

                    # Only flag contracts expiring within 12 months
                    months_left = _months_until(end_date)
                    if months_left is not None and months_left > 12:
                        continue
                    if months_left is not None and months_left < 0:
                        # Already expired — still a signal (renewal window)
                        window_label = f"expired {abs(months_left)}mo ago"
                    elif months_left is not None:
                        window_label = f"expires in {months_left}mo"
                    else:
                        window_label = "expiry unknown"

                    key = agency + (award_id or desc[:40])
                    if key in seen:
                        continue
                    seen.add(key)

                    url = (
                        f"https://www.usaspending.gov/award/{award_id}/"
                        if award_id
                        else "https://www.usaspending.gov"
                    )
                    amount_str = (
                        f"${amount:,.0f}" if isinstance(amount, (int, float)) else "unknown"
                    )

                    signal_label = (
                        f"Competitor Contract Expiring ({window_label}): {kw}"
                    )
                    evidence_text = (
                        f"Federal contract for '{kw}' awarded to {agency}. "
                        f"Contract value: {amount_str}. "
                        f"Period: {start_date} → {end_date} ({window_label}). "
                        f"Description: {desc}"
                    )

                    results.append(
                        self._make_signal(
                            company_name=agency,
                            job_title=signal_label,
                            description=truncate(evidence_text, 500),
                            url=url,
                            posted_date=end_date,
                            location="United States",
                            extra={
                                "signal_type": "competitor_contract_expiring",
                                "competitor_product": kw,
                                "contract_end_date": end_date,
                                "months_until_expiry": months_left,
                                "contract_value": amount,
                                "award_id": award_id,
                            },
                        )
                    )

                logger.info(
                    f"USASpending '{kw}' → {len(awards)} contracts, "
                    f"{sum(1 for r in results if r.get('competitor_product') == kw)} in window"
                )
                random_delay(1.0, 2.0)

            except Exception as e:
                logger.error(f"USASpending error '{kw}': {e}")

        logger.info(
            f"USASpending total → {len(results)} competitor contract signals"
        )
        return results


# ---------------------------------------------------------------------------
# 2. OCC Enforcement Actions — compliance trigger signals
# ---------------------------------------------------------------------------

_OCC_BASE = "https://www.occ.gov"
_OCC_ENFORCEMENT_URL = (
    "https://www.occ.gov/topics/laws-and-regulations/enforcement-actions/"
    "index-enforcement-actions.html"
)

# Action types that create mandatory technology remediation requirements
_HIGH_VALUE_ACTION_TYPES = {
    "Consent Order",
    "Formal Agreement",
    "Cease and Desist",
    "Memorandum of Understanding",
    "Safety and Soundness",
    "BSA/AML",
    "Fair Lending",
    "Model Risk",
    "Operational Risk",
}

# Regex patterns to extract bank name and action type from OCC press release text
# OCC format: "<ActionType> against <BankName>, <City>, <State>, for <reason>"
_OCC_ACTION_PATTERN = re.compile(
    r'(Cease and Desist Order|Formal Agreement|Consent Order|'
    r'Memorandum of Understanding|Civil Money Penalty|Order of Prohibition)'
    r'\s+(?:against|with)\s+([^,]+(?:Bank|Credit Union|Association|Trust|Savings)[^,]*)',
    re.IGNORECASE,
)


class OCCEnforcementSignal(BaseSignal):
    """
    Scrapes OCC enforcement actions (Consent Orders, Formal Agreements, etc.)
    against national banks. These create mandatory, time-bound technology
    remediation requirements — the highest-confidence buying signal for
    InRule's banking ICP.

    The OCC publishes enforcement actions at:
    https://www.occ.gov/topics/laws-and-regulations/enforcement-actions/
    """

    source_name = "occ_enforcement"

    def fetch(self, query: str = "", location: str = "", max_pages: int = 3,
              lookback_days: int = 730) -> list[dict]:
        """
        Two-level scrape:
          Level 1: OCC index page → list of monthly press release links
          Level 2: Each press release → extract individual bank names + action types

        OCC publishes monthly roundup press releases, not per-bank pages.
        Each release contains paragraphs like:
          "Cease and Desist Order against United Texas Bank, Dallas, Texas, for..."
        We regex-extract bank name + action type from the release text.
        """
        results: list[dict] = []
        seen: set[str] = set()
        cutoff_date = _TODAY - timedelta(days=lookback_days)

        try:
            # Level 1: fetch the index page
            resp = requests.get(_OCC_ENFORCEMENT_URL, headers=_HEADERS, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"OCC index: HTTP {resp.status_code}")
                return results

            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table", {"id": "example_simple"})
            if not table:
                logger.warning("OCC: could not find enforcement table")
                return results

            # Collect press release links within the lookback window
            release_links: list[tuple[str, str, str]] = []  # (date_str, url, release_date_iso)
            for row in table.find_all("tr")[1:]:
                cols = row.find_all("td")
                if len(cols) < 3:
                    continue
                date_str = clean_text(cols[0].get_text())
                link_tag = cols[2].find("a")
                if not link_tag:
                    continue
                href = link_tag.get("href", "")
                release_url = href if href.startswith("http") else _OCC_BASE + href

                # Parse date
                release_date = None
                for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y"):
                    try:
                        release_date = datetime.strptime(date_str, fmt).date()
                        break
                    except ValueError:
                        continue

                if release_date is None:
                    continue
                if release_date < cutoff_date:
                    break  # table is sorted newest-first; stop when past window

                release_links.append((date_str, release_url, release_date.isoformat()))

            logger.info(f"OCC: {len(release_links)} monthly releases in lookback window")

            # Level 2: fetch each press release and extract individual bank actions
            for date_str, release_url, release_date_iso in release_links[:12]:  # cap at 12 months
                try:
                    r2 = requests.get(release_url, headers=_HEADERS, timeout=20)
                    if r2.status_code != 200:
                        continue
                    text = BeautifulSoup(r2.text, "html.parser").get_text(" ", strip=True)

                    # Find all action matches in the release text
                    for match in _OCC_ACTION_PATTERN.finditer(text):
                        action_type = match.group(1).strip()
                        bank_raw = match.group(2).strip().rstrip(".,;:")
                        bank_name = clean_text(bank_raw)

                        if not bank_name or not is_valid_company_name(bank_name):
                            continue

                        # Skip IAP (individual) actions — we want bank-level actions
                        if any(w in bank_name.lower() for w in ["jpmorgan chase", "chase bank"]):
                            # These are almost always IAP actions at large banks — skip
                            pass  # still include them, they're valid signals

                        key = bank_name + release_date_iso
                        if key in seen:
                            continue
                        seen.add(key)

                        is_high_value = any(
                            t.lower() in action_type.lower()
                            for t in _HIGH_VALUE_ACTION_TYPES
                        )

                        evidence_text = (
                            f"OCC {action_type} issued against {bank_name} "
                            f"(announced {date_str}). "
                            "Enforcement orders require banks to document, audit, "
                            "and remediate decision-making processes — a mandatory "
                            "buying trigger for decision automation and business "
                            "rules platforms like InRule."
                        )

                        results.append(
                            self._make_signal(
                                company_name=bank_name,
                                job_title=f"OCC {action_type}: Compliance Remediation Trigger",
                                description=truncate(evidence_text, 500),
                                url=release_url,
                                posted_date=release_date_iso,
                                location="United States",
                                extra={
                                    "signal_type": "compliance_trigger",
                                    "action_type": action_type,
                                    "action_date": release_date_iso,
                                    "is_high_value": is_high_value,
                                    "regulator": "OCC",
                                },
                            )
                        )

                    random_delay(0.5, 1.0)  # polite pacing

                except Exception as e:
                    logger.error(f"OCC release parse error ({release_url}): {e}")

            logger.info(f"OCC enforcement → {len(results)} bank actions in lookback window")

        except Exception as e:
            logger.error(f"OCC enforcement scrape error: {e}")

        return results


# ---------------------------------------------------------------------------
# 3. LinkedIn Jobs — competitor displacement signals
# ---------------------------------------------------------------------------

_LINKEDIN_JOBS_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)

# Competitor product search terms for LinkedIn job postings.
# If a company is hiring for these tools, they have budget and a defined
# category — InRule's pitch is a replacement.
_COMPETITOR_JOB_KEYWORDS = [
    "FICO Blaze Advisor",
    "Corticon business rules",
    "IBM ODM developer",
    "IBM Operational Decision Manager",
    "Drools rule engine",
    "Pega decisioning",
    "business rules engine developer",
    "decision management platform",
    "BRMS developer",
    "business rules management system",
]


class LinkedInCompetitorJobSignal(BaseSignal):
    """
    Finds companies actively hiring for competitor decision-automation tools
    via LinkedIn's public guest job search API. No authentication required.

    A company hiring a "FICO Blaze Advisor Developer" has:
    1. Budget allocated for this category
    2. An existing implementation they need to maintain/extend
    3. A known pain point (the competitor's limitations)

    This is a displacement signal, not a greenfield opportunity.
    """

    source_name = "linkedin_competitor_jobs"

    def fetch(self, query: str = "", location: str = "United States",
              max_pages: int = 3,
              keywords: list[str] | None = None) -> list[dict]:
        """
        keywords: override the default competitor job keyword list.
        Defaults to _COMPETITOR_JOB_KEYWORDS.
        """
        search_keywords = keywords if keywords is not None else _COMPETITOR_JOB_KEYWORDS
        results: list[dict] = []
        seen: set[str] = set()

        for kw in search_keywords:
            for page in range(max_pages):
                try:
                    params = {
                        "keywords": kw,
                        "location": location,
                        "start": page * 25,
                        "f_TPR": "r2592000",  # posted in last 30 days
                    }
                    resp = requests.get(
                        _LINKEDIN_JOBS_URL,
                        params=params,
                        headers=_HEADERS,
                        timeout=20,
                    )
                    if resp.status_code == 429:
                        logger.warning("LinkedIn: rate limited — pausing 30s")
                        time.sleep(30)
                        break
                    if resp.status_code != 200:
                        logger.debug(
                            f"LinkedIn: HTTP {resp.status_code} for '{kw}'"
                        )
                        break

                    soup = BeautifulSoup(resp.text, "html.parser")
                    job_cards = soup.find_all("li")

                    if not job_cards:
                        break

                    page_results = 0
                    for card in job_cards:
                        title_tag = card.find(
                            "h3", class_=re.compile(r"base-search-card__title")
                        )
                        company_tag = card.find(
                            "h4", class_=re.compile(r"base-search-card__subtitle")
                        )
                        location_tag = card.find(
                            "span", class_=re.compile(r"job-search-card__location")
                        )
                        date_tag = card.find("time")
                        link_tag = card.find("a", class_=re.compile(r"base-card__full-link"))

                        if not title_tag or not company_tag:
                            continue

                        job_title = clean_text(title_tag.get_text())
                        company = clean_text(company_tag.get_text())
                        job_location = clean_text(
                            location_tag.get_text() if location_tag else ""
                        )
                        posted_date = (
                            date_tag.get("datetime", "") if date_tag else ""
                        )
                        job_url = link_tag.get("href", "") if link_tag else ""

                        if not company or not is_valid_company_name(company):
                            continue

                        key = company + job_title + kw
                        if key in seen:
                            continue
                        seen.add(key)

                        # Extract the competitor product name from the keyword
                        competitor = kw.split(" ")[0] + " " + kw.split(" ")[1] if len(kw.split()) > 1 else kw

                        evidence_text = (
                            f"{company} is hiring a '{job_title}' — actively "
                            f"seeking expertise in '{kw}'. This confirms they "
                            f"have an active {competitor} implementation and "
                            "budget allocated to this category. "
                            f"Location: {job_location}. Posted: {posted_date}."
                        )

                        results.append(
                            self._make_signal(
                                company_name=company,
                                job_title=f"Hiring: {job_title} ({competitor})",
                                description=truncate(evidence_text, 500),
                                url=job_url,
                                posted_date=posted_date,
                                location=job_location,
                                extra={
                                    "signal_type": "competitor_job_posting",
                                    "competitor_product": competitor,
                                    "job_title_raw": job_title,
                                    "search_keyword": kw,
                                },
                            )
                        )
                        page_results += 1

                    logger.info(
                        f"LinkedIn '{kw}' p{page + 1} → {page_results} jobs"
                    )

                    if page_results < 5:
                        break

                    random_delay(2.0, 4.0)

                except Exception as e:
                    logger.error(f"LinkedIn error '{kw}': {e}")
                    break

        logger.info(
            f"LinkedIn competitor jobs total → {len(results)} displacement signals"
        )
        return results


# ---------------------------------------------------------------------------
# 4. SEC EDGAR Full-Text Search — first-party buying intent signals
# ---------------------------------------------------------------------------

_EDGAR_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"

# SIC codes for InRule's core ICP verticals
# Insurance: 6311-6399 | Banking: 6020-6099 | Healthcare: 8011-8099
# Government/Finance: 6141-6199 | Mortgage: 6159, 6552
_INRULE_SIC_CODES = [
    "6311", "6321", "6331", "6351", "6361", "6371", "6399",  # Insurance
    "6020", "6021", "6022", "6035", "6036",                   # Banking
    "6141", "6153", "6159", "6162", "6163",                   # Finance/Mortgage
    "8011", "8049", "8051", "8062", "8099",                   # Healthcare
]

# Keywords that indicate decision automation buying intent in SEC filings
# Note: EDGAR EFTS accepts plain terms; phrase search uses the q= param directly
_EDGAR_INRULE_QUERIES = [
    "business rules engine",
    "decision automation",
    "claims automation",
    "underwriting automation",
    "eligibility determination rules",
    "FICO Blaze",
    "Corticon",
    "IBM ODM",
    "policy administration automation",
    "prior authorization automation",
]


class EDGARFilingSignal(BaseSignal):
    """
    SEC EDGAR EFTS (full-text search) signal for InRule.

    Searches 10-K, 10-Q, 8-K, and S-1 filings for companies that mention:
      - Business rules engines by name (FICO Blaze, Corticon, IBM ODM)
      - Decision automation language (claims automation, underwriting automation)
      - Eligibility determination + rules

    These are first-party buying signals — the company itself is disclosing
    that this technology is material to their operations. Filtered to InRule's
    target SIC codes (insurance, banking, healthcare, finance).

    API: https://efts.sec.gov/LATEST/search-index (free, no auth required)
    Rate limit: ~10 req/sec; we pace at 1 req/2s to be safe.
    """

    source_name = "sec_edgar"

    def fetch(self, query: str = "", location: str = "", max_pages: int = 2) -> list[dict]:
        """
        max_pages: number of pages per query (10 results/page = 20 filings/query max).
        With 11 queries × 2 pages = up to 220 filing signals per run.
        """
        results: list[dict] = []
        seen: set[str] = set()

        queries = [query] if query else _EDGAR_INRULE_QUERIES

        for q in queries:
            for page in range(max_pages):
                try:
                    params = {
                        "q": q,
                        "dateRange": "custom",
                        "startdt": (datetime.now().replace(year=datetime.now().year - 2)).strftime("%Y-%m-%d"),
                        "enddt": _TODAY.isoformat(),
                        "forms": "10-K,10-Q,8-K,S-1",
                        "hits.hits.total.value": "true",
                        "hits.hits._source": "file_date,entity_name,form_type,period_of_report,display_names,sics",
                        "from": page * 10,
                        "size": 10,
                    }

                    resp = requests.get(
                        _EDGAR_EFTS_URL,
                        params=params,
                        headers={
                            "User-Agent": "InRule GTM Research gtm@inrule.com",
                            "Accept": "application/json",
                        },
                        timeout=30,
                    )

                    if resp.status_code != 200:
                        logger.warning(f"EDGAR '{q}': HTTP {resp.status_code}")
                        break

                    data = resp.json()
                    hits = data.get("hits", {}).get("hits", [])

                    if not hits:
                        break

                    page_results = 0
                    for hit in hits:
                        src = hit.get("_source", {})
                        # EDGAR EFTS actual field names (confirmed from API)
                        display_names_list = src.get("display_names", [])
                        entity_name = ""
                        if display_names_list:
                            # Format: "COMPANY NAME  (TICKER)  (CIK 0001234567)"
                            raw = display_names_list[0]
                            entity_name = raw.split("(")[0].strip().title()
                        file_date = src.get("file_date", "")
                        form_type = src.get("form", "") or src.get("file_type", "")
                        sics = src.get("sics", [])
                        display_names = display_names_list
                        filing_id = hit.get("_id", "")
                        adsh = src.get("adsh", "")  # accession number

                        if not entity_name:
                            continue

                        # Filter to InRule's target SIC codes
                        if sics and not any(s in _INRULE_SIC_CODES for s in sics):
                            continue

                        # Dedup by entity + query
                        key = entity_name + q
                        if key in seen:
                            continue
                        seen.add(key)

                        # Build filing URL using accession number
                        if adsh:
                            adsh_path = adsh.replace("-", "")
                            filing_url = f"https://www.sec.gov/Archives/edgar/data/{adsh_path[:10]}/{adsh_path}/{adsh}-index.htm"
                        else:
                            filing_url = f"https://efts.sec.gov/LATEST/search-index?q={q}&forms={form_type}"

                        # Determine which competitor/technology was mentioned
                        q_clean = q.replace('"', '').strip()
                        competitor_mention = q_clean if any(
                            c in q_clean for c in ["FICO", "Corticon", "IBM ODM", "Drools"]
                        ) else ""

                        evidence_text = (
                            f"{entity_name} filed a {form_type} on {file_date} "
                            f"that mentions '{q_clean}'. "
                            + (
                                f"This is a competitor displacement signal — "
                                f"they are disclosing active use of {competitor_mention}."
                                if competitor_mention
                                else
                                f"This is a first-party buying intent signal — "
                                f"the company is disclosing that {q_clean} is "
                                f"material to their operations."
                            )
                        )

                        sic_str = ", ".join(sics) if sics else "unknown"

                        results.append(
                            self._make_signal(
                                company_name=entity_name,
                                job_title=(
                                    f"SEC {form_type}: '{q_clean}' mentioned"
                                    + (f" — {competitor_mention} displacement" if competitor_mention else "")
                                ),
                                description=truncate(evidence_text, 500),
                                url=filing_url,
                                posted_date=file_date,
                                location="United States",
                                extra={
                                    "signal_type": "sec_filing",
                                    "form_type": form_type,
                                    "filing_date": file_date,
                                    "sic_codes": sics,
                                    "edgar_query": q_clean,
                                    "competitor_mention": competitor_mention,
                                    "display_names": display_names,
                                },
                            )
                        )
                        page_results += 1

                    logger.info(f"EDGAR '{q}' p{page + 1} → {page_results} filings")

                    if page_results < 10:
                        break  # no more pages

                    random_delay(1.5, 2.5)

                except Exception as e:
                    logger.error(f"EDGAR error '{q}': {e}")
                    break

        logger.info(f"EDGAR total → {len(results)} filing signals")
        return results


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    "USASpendingCompetitorSignal",
    "OCCEnforcementSignal",
    "LinkedInCompetitorJobSignal",
    "EDGARFilingSignal",
]
