"""
agentic_harvester_signal.py
============================
Agentic signal harvester — extracts Oracle intent signals from arbitrary
watch-list URLs without a hand-written per-site parser.

Every other signal in this directory is a bespoke scraper tuned to one
source's HTML/API shape (see signals.md's "new signal checklist" — a new
Python file per source). This one instead:

  1. Fetches each URL in config.AGENTIC_HARVESTER_URLS — stealth-capable via
     the optional `scrapling` package for Cloudflare-protected pages nothing
     else here can reach, falling back to plain requests when scrapling
     isn't installed (mirrors the graceful-optional-dependency pattern
     already used for maigret in maigret_enricher.py).
  2. Extracts clean text via trafilatura (same library company_researcher.py
     already uses — no new extraction dependency).
  3. Skips pages with no Oracle-relevant keywords.
  4. Reuses the existing Ollama-based llm_extractor (already used by
     news_signal.py) to pull a company name out of the page text — no
     second LLM-extraction library.

Adding a new site to watch is a config change (append a URL to
AGENTIC_HARVESTER_URLS), not a new Python file — that's the point.

Install for stealth fetching (optional):
    pip install "scrapling[fetchers]" && scrapling install
"""

from __future__ import annotations

import requests
import trafilatura

from src.signals.base_signal import BaseSignal
from src.utils import clean_text, truncate, random_delay, get_logger
from src import config, llm_extractor

logger = get_logger(__name__)

_SCRAPLING_AVAILABLE = False
try:
    from scrapling.fetchers import StealthyFetcher
    _SCRAPLING_AVAILABLE = True
except ImportError:
    logger.info(
        "[AgenticHarvester] scrapling not installed — falling back to plain "
        "requests (won't get past Cloudflare-protected pages). "
        'Run: pip install "scrapling[fetchers]" && scrapling install'
    )

_TIMEOUT = 15
_UA = "Mozilla/5.0 (compatible; oracle-intent-harvester/1.0)"

_ORACLE_TERMS = [
    "oracle", "erp", "cloud erp", "fusion", "netsuite", "peoplesoft",
    "e-business suite", "ebs", "jde", "j.d. edwards", "jd edwards",
    "siebel", "hyperion",
]


def _mentions_oracle(text: str) -> bool:
    t = text.lower()
    return any(term in t for term in _ORACLE_TERMS)


def _fetch_html(url: str) -> str:
    """Stealth-fetch via scrapling if available (needed for Cloudflare-
    protected pages); otherwise a plain requests GET. Never raises."""
    if _SCRAPLING_AVAILABLE:
        try:
            page = StealthyFetcher.fetch(url, headless=True)
            html = getattr(page, "html_content", "") or getattr(page, "body", "") or ""
            if html:
                return html
        except Exception as e:
            logger.debug(f"[AgenticHarvester] scrapling fetch failed for {url}: {e}")
            # fall through to plain requests

    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": _UA})
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.debug(f"[AgenticHarvester] requests fetch failed for {url}: {e}")
        return ""


def _extract_title(html: str, fallback: str) -> str:
    try:
        meta = trafilatura.extract_metadata(html)
        if meta and meta.title:
            return meta.title
    except Exception:
        pass
    return fallback


class AgenticHarvesterSignal(BaseSignal):
    source_name = "agentic_harvester"

    def fetch(self, query: str = "", location: str = "", max_pages: int = 3) -> list[dict]:
        urls = getattr(config, "AGENTIC_HARVESTER_URLS", [])
        if not urls:
            return []

        articles_for_llm: list[dict] = []
        page_meta: list[dict] = []

        for url in urls[:max_pages]:
            try:
                html = _fetch_html(url)
                if not html:
                    continue

                text = trafilatura.extract(html, include_links=False, include_images=False) or ""
                text = clean_text(text)
                if not text or not _mentions_oracle(text):
                    continue

                title = _extract_title(html, fallback=url)
                articles_for_llm.append({"title": title, "description": text[:500]})
                page_meta.append({"url": url, "title": title, "text": text})
                random_delay(config.SCAN_DELAY_MIN, config.SCAN_DELAY_MAX)
            except Exception as e:
                logger.debug(f"[AgenticHarvester] error processing {url}: {e}")
                continue

        if not articles_for_llm:
            return []

        # Same Ollama-based extractor news_signal.py already uses — gracefully
        # returns "" for every entry if Ollama isn't running.
        company_names = llm_extractor.extract_companies_batch(articles_for_llm)

        signals: list[dict] = []
        for meta, company in zip(page_meta, company_names):
            if not company:
                continue
            signals.append(self._make_signal(
                company_name=company,
                job_title=meta["title"],
                description=truncate(meta["text"], 2000),
                url=meta["url"],
                location=location,
                extra={"signal_type": "agentic_harvest"},
            ))

        return signals
