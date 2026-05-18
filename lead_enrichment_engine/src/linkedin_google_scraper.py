"""
linkedin_google_scraper.py
==========================
Discovers LinkedIn profiles using Google dork queries and parses
name, title, company, location, and LinkedIn URL from search snippets.

Query logic:
    site:linkedin.com/in "at {company}" AND ("{kw1}" OR "{kw2}" ...)

SETUP — choose one backend:

  A) Google Custom Search API (recommended, 100 free queries/day)
     1. Enable "Custom Search API" at console.cloud.google.com
     2. Create a search engine at programmablesearchengine.google.com
        → set "Search the entire web" ON
     3. Add to .env:
          GOOGLE_CSE_API_KEY=your_api_key
          GOOGLE_CSE_ID=your_cx_id

  B) SerpAPI (paid, very reliable, 100 free/month)
     1. Sign up at serpapi.com
     2. Add to .env:
          SERPAPI_KEY=your_api_key

  C) Playwright (free, headless browser — no API key needed)
     1. pip install playwright
     2. playwright install chromium
     → Use --backend playwright

Usage (CLI):
    python -m src.linkedin_google_scraper ^
        --company "OLA Energy" ^
        --keywords "JD Edwards" JDE Oracle ^
        --pages 3 ^
        --out output/ola_energy_leads.csv ^
        --backend google_cse

Usage (import):
    from src.linkedin_google_scraper import scrape_linkedin_profiles
    results = scrape_linkedin_profiles(
        company="OLA Energy",
        keywords=["JD Edwards", "JDE", "Oracle"],
        pages=3,
        backend="google_cse",
    )
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import re
import time
from dataclasses import dataclass, fields, asdict
from typing import List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Data model ─────────────────────────────────────────────────────────────

@dataclass
class LinkedInProfile:
    name: str = ""
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    linkedin_url: str = ""
    snippet: str = ""


# ── Query builder ──────────────────────────────────────────────────────────

def build_google_query(company: str, keywords: List[str]) -> str:
    """Builds: site:linkedin.com/in "at {company}" AND ("kw1" OR "kw2" ...)"""
    company_clause = f'"at {company}"'
    if keywords:
        kw_parts = " OR ".join(f'"{kw}"' for kw in keywords)
        return f'site:linkedin.com/in {company_clause} AND ({kw_parts})'
    return f'site:linkedin.com/in {company_clause}'


# ── Snippet parsers ────────────────────────────────────────────────────────

# Title patterns (after stripping trailing "| LinkedIn"):
#   "John Doe - Senior ERP Consultant at OLA Energy"
#   "John Doe - JDE Developer"
#   "John Doe"
# Spaces required around separator so "Al-Nasser" isn't split as a separator.
_TITLE_FULL = re.compile(r'^(.+?)\s+[-–]\s+(.+?)\s+at\s+(.+)$', re.IGNORECASE)
_TITLE_ROLE = re.compile(r'^(.+?)\s+[-–]\s+(.+)$', re.IGNORECASE)
_SNIPPET_AT = re.compile(r'(.+?)\s+at\s+(.+?)[\.\,]', re.IGNORECASE)


def _parse_title(raw_title: str) -> tuple[str, str, str]:
    """Returns (name, job_title, company) from a Google result title."""
    # Strip trailing separators and "LinkedIn"
    raw = re.sub(r'\s*[|—\-–]\s*LinkedIn\s*$', '', raw_title, flags=re.IGNORECASE).strip()
    raw = re.sub(r'\s*[|—]\s*$', '', raw).strip()
    m = _TITLE_FULL.match(raw)
    if m:
        return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    m = _TITLE_ROLE.match(raw)
    if m:
        return m.group(1).strip(), m.group(2).strip(), ""
    return raw.strip(), "", ""


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    return (parts[0], " ".join(parts[1:])) if len(parts) >= 2 else (full_name, "")


def _parse_location(snippet: str) -> str:
    """Pull a 'City, Country' style location from snippet text."""
    # Split on bullets, pipes, or periods
    for part in re.split(r'[·•\|\.]', snippet):
        part = part.strip()
        if ',' in part and 3 < len(part) < 60 and re.match(r'^[A-Z]', part):
            if not re.search(r'\b(at|the|and|or|for|of|in)\b', part, re.IGNORECASE):
                return part
    return ""


def _clean_url(url: str) -> str:
    """Extract bare linkedin.com/in/... from any wrapper URL."""
    m = re.search(r'linkedin\.com/in/[^&\s"\']+', url)
    return f"https://www.{m.group(0)}" if m else url


def _assemble_profile(raw: dict) -> LinkedInProfile:
    name, job_title, company = _parse_title(raw.get("title", ""))
    first, last = _split_name(name)
    snippet = raw.get("snippet", "")
    if not company:
        m = _SNIPPET_AT.search(snippet)
        if m:
            company = m.group(2).strip().rstrip(".,")
    return LinkedInProfile(
        name=name, first_name=first, last_name=last,
        title=job_title, company=company,
        location=_parse_location(snippet),
        linkedin_url=_clean_url(raw.get("url", "")),
        snippet=snippet[:300],
    )


# ── Backend A: Google Custom Search API ───────────────────────────────────

def _scrape_google_cse(query: str, pages: int) -> List[dict]:
    api_key = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
    cx      = os.getenv("GOOGLE_CSE_ID",      "").strip()
    if not api_key or not cx:
        raise ValueError(
            "Set GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID in .env\n"
            "  → Enable 'Custom Search API' at console.cloud.google.com\n"
            "  → Create engine at programmablesearchengine.google.com"
        )
    results = []
    for page in range(pages):
        start = page * 10 + 1  # CSE uses 1-based index
        params = {"key": api_key, "cx": cx, "q": query, "num": 10, "start": start}
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params, timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                print(f"  No more results at page {page + 1}.")
                break
            for item in items:
                results.append({
                    "title":   item.get("title", ""),
                    "url":     item.get("link",  ""),
                    "snippet": item.get("snippet", ""),
                })
            print(f"  Page {page + 1}: {len(items)} results")
            if page < pages - 1:
                time.sleep(1)
        except requests.HTTPError as e:
            print(f"  [error] Google CSE: {e}")
            break
    return results


# ── Backend B: SerpAPI ─────────────────────────────────────────────────────

def _scrape_serpapi(query: str, pages: int) -> List[dict]:
    api_key = os.getenv("SERPAPI_KEY", "").strip()
    if not api_key:
        raise ValueError("Set SERPAPI_KEY in .env  →  sign up at serpapi.com")
    results = []
    for page in range(pages):
        params = {
            "engine": "google", "q": query,
            "num": 10, "start": page * 10,
            "hl": "en", "api_key": api_key,
        }
        try:
            resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
            resp.raise_for_status()
            for r in resp.json().get("organic_results", []):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("link",  ""),
                    "snippet": r.get("snippet", ""),
                })
            print(f"  Page {page + 1}: done")
        except Exception as e:
            print(f"  [warn] SerpAPI page {page + 1}: {e}")
            break
    return results


# ── Backend C: Playwright (headless browser) ───────────────────────────────

def _scrape_playwright(query: str, pages: int) -> List[dict]:
    """
    Uses a real Chromium browser to execute Google's JavaScript.
    Requires: pip install playwright && playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError(
            "Playwright not installed.\n"
            "  Run: pip install playwright && playwright install chromium"
        )

    from bs4 import BeautifulSoup

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        # Mask all common headless detection signals
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            window.chrome = {runtime: {}};
        """)
        page = ctx.new_page()
        for p in range(pages):
            start = p * 10
            url = (
                f"https://www.google.com/search"
                f"?q={requests.utils.quote(query)}&num=10&start={start}&hl=en"
            )
            print(f"  Playwright: loading page {p + 1}...")
            page.goto(url, wait_until="networkidle", timeout=30000)
            time.sleep(random.uniform(2, 4))  # let results fully render

            html = page.content()

            # Detect CAPTCHA / bot challenge
            if "captcha" in html.lower() or "unusual traffic" in html.lower():
                print("  [!] Google served a CAPTCHA — try again later or use a different IP.")
                break

            soup = BeautifulSoup(html, "lxml")
            batch = []
            for g in soup.select("div.g, div.tF2Cxc"):
                h3 = g.find("h3")
                a  = g.find("a", href=True)
                if not h3 or not a:
                    continue
                href = a["href"]
                if "linkedin.com" not in href:
                    continue
                snip_el = (
                    g.select_one("div.VwiC3b")
                    or g.select_one("span.aCOpRe")
                    or g.select_one("div.IsZvec")
                )
                batch.append({
                    "title":   h3.get_text(strip=True),
                    "url":     href,
                    "snippet": snip_el.get_text(" ", strip=True) if snip_el else "",
                })

            print(f"  Page {p + 1}: {len(batch)} results")
            results.extend(batch)
            if not batch:
                break
            if p < pages - 1:
                time.sleep(random.uniform(3, 6))

        ctx.close()
        browser.close()
    return results


# ── Public API ─────────────────────────────────────────────────────────────

_BACKENDS = {
    "google_cse": _scrape_google_cse,
    "serpapi":    _scrape_serpapi,
    "playwright": _scrape_playwright,
}


def scrape_linkedin_profiles(
    company: str,
    keywords: Optional[List[str]] = None,
    pages: int = 2,
    backend: str = "google_cse",
) -> List[LinkedInProfile]:
    """
    Returns a list of LinkedInProfile objects found via Google dork search.

    Args:
        company:  Target company name, e.g. "OLA Energy"
        keywords: Skill/tech filters, e.g. ["JD Edwards", "JDE", "Oracle"]
        pages:    Number of result pages (10 results each)
        backend:  "google_cse" | "serpapi" | "playwright"
    """
    if backend not in _BACKENDS:
        raise ValueError(f"Unknown backend '{backend}'. Choose: {list(_BACKENDS)}")

    keywords = keywords or []
    query = build_google_query(company, keywords)
    print(f"\nQuery : {query}")
    print(f"Pages : {pages}  |  Backend: {backend}\n")

    raw = _BACKENDS[backend](query, pages)

    profiles = [_assemble_profile(r) for r in raw]
    seen, unique = set(), []
    for p in profiles:
        key = p.linkedin_url or p.name
        if key not in seen:
            seen.add(key)
            unique.append(p)

    print(f"\nFound {len(unique)} unique profiles.")
    return unique


# ── CSV writer ─────────────────────────────────────────────────────────────

def save_to_csv(profiles: List[LinkedInProfile], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    field_names = [f.name for f in fields(LinkedInProfile)]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=field_names)
        writer.writeheader()
        writer.writerows(asdict(p) for p in profiles)
    print(f"Saved {len(profiles)} profiles → {path}")


# ── CLI ────────────────────────────────────────────────────────────────────

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape LinkedIn profiles via Google dork queries."
    )
    parser.add_argument("--company",  required=True, help='Target company, e.g. "OLA Energy"')
    parser.add_argument("--keywords", nargs="*", default=[],
                        help='Skill filters, e.g. "JD Edwards" JDE Oracle')
    parser.add_argument("--pages",    type=int, default=2,
                        help="Result pages to fetch (default: 2 = ~20 results)")
    parser.add_argument("--out",      default="output/linkedin_profiles.csv")
    parser.add_argument("--backend",  choices=list(_BACKENDS), default="google_cse",
                        help="Search backend (default: google_cse)")
    args = parser.parse_args()

    profiles = scrape_linkedin_profiles(
        company=args.company,
        keywords=args.keywords,
        pages=args.pages,
        backend=args.backend,
    )

    if profiles:
        save_to_csv(profiles, args.out)
        print("\nSample results:")
        for p in profiles[:5]:
            print(f"  {p.name:<28} | {p.title:<32} | {p.company:<20} | {p.location}")
    else:
        print("No profiles found.")


if __name__ == "__main__":
    _cli()
