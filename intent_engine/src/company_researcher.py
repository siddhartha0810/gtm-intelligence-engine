"""
company_researcher.py
=====================
Scrapes a company's website and extracts a clean product/team description
to provide context for AI email hook generation.

Uses trafilatura for fast, clean text extraction (no Playwright needed).
Falls back gracefully if the site blocks or times out.

Usage:
    from intent_engine.src.company_researcher import research_company
    result = research_company("https://browserbase.com")
    # {"summary": "...", "raw_text": "...", "url": "...", "ok": True}
"""

import logging
import re
import time
from typing import Any

import requests
import trafilatura

logger = logging.getLogger(__name__)

_TIMEOUT = 12
_UA = "Mozilla/5.0 (compatible; research-bot/1.0)"

# Sections to try if the homepage is thin
_FALLBACK_PATHS = ["/about", "/product", "/platform", "/features"]


def _fetch_text(url: str) -> str:
    """Download a URL and extract clean main text via trafilatura."""
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": _UA})
        resp.raise_for_status()
        text = trafilatura.extract(
            resp.text,
            include_links=False,
            include_images=False,
            no_fallback=False,
        ) or ""
        return text.strip()
    except Exception as e:
        logger.debug(f"[Researcher] fetch failed for {url}: {e}")
        return ""


def _clean(text: str, max_chars: int = 2000) -> str:
    """Remove duplicate whitespace and cap length."""
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars].strip()


def _summarise(name: str, one_liner: str, raw: str) -> str:
    """
    Build a concise company summary from available data.
    If raw website text was fetched, use the first 800 chars of it.
    Always include the YC one-liner as a baseline.
    """
    parts: list[str] = []
    if one_liner:
        parts.append(one_liner)
    if raw:
        # Take the first meaningful chunk after deduplication
        snippet = _clean(raw, 800)
        if snippet and snippet.lower() not in one_liner.lower():
            parts.append(snippet)
    return " | ".join(parts) if parts else f"{name} — no description available"


def research_company(
    website: str,
    name: str = "",
    one_liner: str = "",
) -> dict[str, Any]:
    """
    Scrape a company website and return a structured research summary.

    Returns:
        {
            "name":     str,
            "url":      str,
            "summary":  str,   # Used as context for hook generation
            "raw_text": str,   # Full extracted text (capped at 2000 chars)
            "ok":       bool,
        }
    """
    if not website:
        return {"name": name, "url": "", "summary": one_liner, "raw_text": "", "ok": False}

    # Normalise URL
    url = website if website.startswith("http") else f"https://{website}"
    url = url.rstrip("/")

    # Primary — homepage
    raw = _fetch_text(url)

    # If homepage is thin, try one fallback path
    if len(raw) < 200:
        for path in _FALLBACK_PATHS:
            time.sleep(0.3)
            extra = _fetch_text(f"{url}{path}")
            if len(extra) > len(raw):
                raw = extra
                break

    raw_clean = _clean(raw, 2000)
    summary = _summarise(name, one_liner, raw_clean)

    return {
        "name":     name or url,
        "url":      url,
        "summary":  summary,
        "raw_text": raw_clean,
        "ok":       bool(raw_clean),
    }


def batch_research(
    companies: list[dict[str, Any]],
    delay: float = 0.5,
) -> list[dict[str, Any]]:
    """
    Research a list of companies. Each item must have 'website', optionally
    'name' and 'one_liner'. Returns the same list with 'research' key added.
    """
    enriched: list[dict[str, Any]] = []
    for co in companies:
        result = research_company(
            website=co.get("website", ""),
            name=co.get("name", ""),
            one_liner=co.get("one_liner", ""),
        )
        enriched.append({**co, "research": result})
        time.sleep(delay)
    return enriched
