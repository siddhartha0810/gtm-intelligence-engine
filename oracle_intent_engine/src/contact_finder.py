"""
Contact finder — retrieves decision-maker contacts for detected companies.

Two strategies, both free by default:

1. LinkedIn via Bing Search (no API key required)
   Searches Bing for  "CompanyName" site:linkedin.com/in CFO OR CIO ...
   LinkedIn page titles follow the pattern "Name – Title at Company | LinkedIn"
   so we can parse full name + title from the search snippet without touching
   LinkedIn directly.

2. Hunter.io domain-search API (optional, free tier: 25 searches/month)
   Set HUNTER_API_KEY in .env to enable — adds verified email addresses on
   top of what LinkedIn search finds.

Target roles: CFO, CIO, CTO, VP Finance, VP IT, Director of Finance,
              Head of IT, ERP Manager, Controller, Treasurer.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from src.utils import get_logger, random_headers, random_delay
from src import config

logger = get_logger(__name__)

HUNTER_ENDPOINT = "https://api.hunter.io/v2/domain-search"

# Roles we care about — anyone who signs an Oracle deal
TARGET_ROLE_RE = re.compile(
    r"\b(cfo|cio|cto|cdo|coo|"
    r"vp[\s\-]+finance|vp[\s\-]+it|vp[\s\-]+technology|vp[\s\-]+erp|"
    r"vice\s+president.{0,25}(?:finance|it|technology|erp)|"
    r"chief\s+(?:financial|information|digital|technology|operating)|"
    r"director.{0,20}(?:finance|it|erp|technology|information|digital)|"
    r"head\s+of\s+(?:it|finance|technology|erp|digital)|"
    r"erp\s+(?:manager|director|lead)|"
    r"it\s+(?:manager|director)|"
    r"finance\s+(?:manager|director)|"
    r"controller|treasurer|it\s+director|finance\s+director)\b",
    re.IGNORECASE,
)

# LinkedIn page title: "First Last - Title at Company | LinkedIn"
# or "First Last | LinkedIn"
_LI_TITLE_RE = re.compile(
    r"^([A-Z][a-zA-Z\-'\.]{1,25}\s+[A-Z][a-zA-Z\-'\.]{1,30}(?:\s+[A-Z][a-zA-Z\-'\.]{1,20})?)"
    r"\s*[-–|]\s*(.+?)(?:\s*\|\s*LinkedIn|\s*at\s+.+?\s*\|\s*LinkedIn)?$",
    re.IGNORECASE,
)
_LI_TITLE_AT_RE = re.compile(
    r"^([A-Z][a-zA-Z\-'\.]{1,25}\s+[A-Z][a-zA-Z\-'\.]{1,30})"
    r"\s*[-–]\s*(.+?)\s+at\s+.+",
    re.IGNORECASE,
)


def find_contacts_linkedin(company_name: str, max_results: int = 8) -> list[dict]:
    """
    Searches Bing for public LinkedIn profiles of decision-makers at the company.
    Returns contacts parsed from search snippets — no LinkedIn scraping, no API key.
    """
    role_terms = (
        'CFO OR CIO OR CTO OR "VP Finance" OR "VP IT" OR "VP Technology" OR '
        '"Chief Financial" OR "Chief Information" OR "Chief Digital" OR '
        '"Director of Finance" OR "Director of IT" OR "Head of IT" OR '
        '"ERP Manager" OR "Finance Director" OR "IT Director" OR Controller'
    )
    query = f'"{company_name}" site:linkedin.com/in ({role_terms})'
    encoded = requests.utils.quote(query)
    url = f"https://www.bing.com/search?q={encoded}&count=20"

    contacts = []
    seen_names: set = set()

    try:
        resp = requests.get(
            url,
            headers={
                **random_headers(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"Bing people search returned {resp.status_code} for {company_name}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        # Bing web results: <li class="b_algo"> containing <h2><a> and <p>
        for result in soup.find_all("li", class_=lambda c: c and "b_algo" in c):
            if len(contacts) >= max_results:
                break

            a_tag = result.find("h2")
            if not a_tag:
                continue
            link_el = a_tag.find("a", href=True)
            if not link_el:
                continue

            href  = link_el.get("href", "")
            title = link_el.get_text(strip=True)

            # Only LinkedIn /in/ profile URLs
            if "linkedin.com/in/" not in href:
                continue

            name, role = _parse_li_title(title)
            if not name or name in seen_names:
                continue

            # Only keep decision-maker roles
            if not TARGET_ROLE_RE.search(role):
                continue

            # Snippet may give more detail
            snippet_el = result.find("p") or result.find("div", class_="b_caption")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            # Try to get a better title from snippet if role is vague
            if role and len(role) < 3:
                m = re.search(r"[-–]\s*([A-Za-z\s,]+?)\s+at\s+", snippet)
                if m:
                    role = m.group(1).strip()

            seen_names.add(name)
            parts = name.split()
            contacts.append({
                "first_name":   parts[0] if parts else "",
                "last_name":    " ".join(parts[1:]) if len(parts) > 1 else "",
                "full_name":    name,
                "title":        role,
                "email":        "",
                "linkedin_url": href.split("?")[0],
                "seniority":    _seniority_from_title(role),
                "confidence":   75,
                "is_target":    True,
                "source":       "linkedin_search",
            })

        random_delay(1, 2)

    except Exception as e:
        logger.error(f"LinkedIn Bing search error for {company_name}: {e}")

    logger.info(f"LinkedIn search '{company_name}' → {len(contacts)} decision-makers")
    return contacts


def find_contacts_hunter(domain: str, company_name: str = "") -> list[dict]:
    """Hunter.io domain search — adds verified email addresses."""
    if not bool(getattr(config, "HUNTER_API_KEY", "")):
        return []

    domain = _clean_domain(domain)
    if not domain:
        return []

    try:
        resp = requests.get(
            HUNTER_ENDPOINT,
            params={
                "domain":    domain,
                "api_key":   config.HUNTER_API_KEY,
                "type":      "personal",
                "seniority": "senior,executive",
                "limit":     10,
            },
            timeout=10,
        )
        if resp.status_code == 401:
            logger.warning("Hunter.io: invalid API key")
            return []
        if resp.status_code == 429:
            logger.warning("Hunter.io: monthly quota exceeded")
            return []
        if resp.status_code != 200:
            return []

        contacts = []
        for e in (resp.json().get("data") or {}).get("emails", []):
            title = e.get("position", "") or ""
            contacts.append({
                "first_name":   e.get("first_name", ""),
                "last_name":    e.get("last_name", ""),
                "full_name":    f"{e.get('first_name','')} {e.get('last_name','')}".strip(),
                "title":        title,
                "email":        e.get("value", ""),
                "linkedin_url": e.get("linkedin", ""),
                "seniority":    e.get("seniority", ""),
                "confidence":   e.get("confidence", 0),
                "is_target":    bool(TARGET_ROLE_RE.search(title)),
                "source":       "hunter.io",
            })

        contacts.sort(key=lambda c: (not c["is_target"], -c["confidence"]))
        logger.info(f"Hunter.io {domain} → {len(contacts)} contacts")
        return contacts

    except Exception as e:
        logger.error(f"Hunter.io error for {domain}: {e}")
        return []


def find_contacts(company_name: str, domain: str = "") -> list[dict]:
    """
    Merged contact lookup:
      1. LinkedIn via Bing search (always, no key required)
      2. Hunter.io (if HUNTER_API_KEY set) — merges emails onto LinkedIn results

    Returns deduplicated list, decision-makers first.
    """
    li_contacts  = find_contacts_linkedin(company_name)
    hun_contacts = find_contacts_hunter(domain or infer_domain(company_name), company_name)

    # Merge by normalised full name — add Hunter email to matching LinkedIn contact
    by_name = {c["full_name"].lower(): c for c in li_contacts}
    for hc in hun_contacts:
        key = hc["full_name"].lower()
        if key in by_name:
            # Enrich existing record with email
            if hc.get("email"):
                by_name[key]["email"] = hc["email"]
            if hc.get("linkedin_url") and not by_name[key].get("linkedin_url"):
                by_name[key]["linkedin_url"] = hc["linkedin_url"]
        else:
            by_name[key] = hc

    merged = list(by_name.values())
    merged.sort(key=lambda c: (not c["is_target"], -c["confidence"]))
    return merged


def is_available() -> bool:
    """Always True — LinkedIn search works without any API key."""
    return True


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_li_title(title: str) -> tuple[str, str]:
    """Extract (name, job_title) from a LinkedIn search result page title."""
    title = title.replace(" | LinkedIn", "").strip()

    # "Name - Title at Company"
    m = _LI_TITLE_AT_RE.match(title)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # "Name - Title"
    m = _LI_TITLE_RE.match(title)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # "Name | Title"
    if "|" in title:
        parts = title.split("|", 1)
        name = parts[0].strip()
        role = parts[1].strip() if len(parts) > 1 else ""
        if re.match(r"^[A-Z][a-z]+ [A-Z][a-z]", name):
            return name, role

    return "", ""


def _seniority_from_title(title: str) -> str:
    t = title.lower()
    if re.search(r"\bchief\b|^cfo|^cio|^cto|^cdo|^coo", t):
        return "executive"
    if re.search(r"\bvp\b|vice\s+president|director", t):
        return "senior"
    if re.search(r"\bmanager\b|head\s+of", t):
        return "manager"
    return "senior"


def _clean_domain(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip().lower()
    raw = re.sub(r"^https?://", "", raw)
    raw = re.sub(r"^www\.", "", raw)
    return raw.split("/")[0]


def infer_domain(company_name: str) -> str:
    name = company_name.lower().strip()
    for suffix in [" inc", " corp", " ltd", " llc", " group", " co", " plc", " ag"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", "", name)
    return f"{name}.com" if name else ""
