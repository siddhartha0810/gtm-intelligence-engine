"""
News signal scraper — three tiers:
  1. NewsAPI (if NEWSAPI_KEY set)
  2. Bing News Search API (if BING_NEWS_KEY set)
  3. Google News RSS fallback (always available)

Company name extraction:
  Primary  — Ollama LLM (batch, 10 articles/call) when available
  Fallback — Precise regex patterns requiring Oracle + company + action verb
"""

import re
import requests
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, resolve_feed_url, is_valid_company_name
from src import config
from src import llm_extractor

logger = get_logger(__name__)


class NewsSignal(BaseSignal):
    source_name = "news"

    def fetch(self, query: str, location: str = "", max_pages: int = None) -> list[dict]:
        # Step 1: collect raw articles from all available sources
        raw: list[dict] = []

        if config.NEWSAPI_KEY:
            raw.extend(self._collect_newsapi(query))
        if config.BING_NEWS_KEY:
            raw.extend(self._collect_bing(query))
        raw.extend(self._collect_bing_rss(query))
        raw.extend(self._collect_google_rss(query))

        if not raw:
            return []

        # Step 2: extract company names
        # LLM batch first; regex fallback for any article the LLM couldn't resolve
        if llm_extractor.is_available():
            names = llm_extractor.extract_companies_batch(raw)
            # Pad to raw length in case LLM returns fewer items than articles
            if len(names) < len(raw):
                names = names + [""] * (len(raw) - len(names))
        else:
            names = [""] * len(raw)

        results = []
        for article, company in zip(raw, names):
            if not company:
                company = self._extract_company_regex(
                    article["title"], article.get("description", "")
                )
            if not company:
                continue
            results.append(self._make_signal(
                company_name=company,
                job_title=article["title"],
                description=article.get("description", ""),
                url=article.get("url", ""),
                posted_date=article.get("posted_date", ""),
                extra={"signal_type": "news_article"},
            ))

        logger.info(f"News '{query}' → {len(results)} signals from {len(raw)} articles")
        return results

    # ------------------------------------------------------------------ #
    #  Article collectors — return raw dicts, no company extraction yet
    # ------------------------------------------------------------------ #

    def _collect_newsapi(self, query: str) -> list[dict]:
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query, "language": "en", "sortBy": "publishedAt",
                    "pageSize": 30, "apiKey": config.NEWSAPI_KEY,
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("status") != "ok":
                return []
            return [
                {
                    "title":       clean_text(a.get("title", "")),
                    "description": truncate(clean_text(a.get("description", "")), 500),
                    "url":         a.get("url", ""),
                    "posted_date": a.get("publishedAt", ""),
                }
                for a in data.get("articles", [])
                if a.get("title")
            ]
        except Exception as e:
            logger.error(f"NewsAPI error: {e}")
            return []

    def _collect_bing(self, query: str) -> list[dict]:
        try:
            resp = requests.get(
                "https://api.bing.microsoft.com/v7.0/news/search",
                headers={"Ocp-Apim-Subscription-Key": config.BING_NEWS_KEY},
                params={"q": query, "count": 30, "mkt": "en-US"},
                timeout=10,
            )
            data = resp.json()
            return [
                {
                    "title":       clean_text(a.get("name", "")),
                    "description": truncate(clean_text(a.get("description", "")), 500),
                    "url":         a.get("url", ""),
                    "posted_date": a.get("datePublished", ""),
                }
                for a in data.get("value", [])
                if a.get("name")
            ]
        except Exception as e:
            logger.error(f"Bing News error: {e}")
            return []

    def _collect_bing_rss(self, query: str) -> list[dict]:
        try:
            encoded = requests.utils.quote(query)
            url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
            feed = feedparser.parse(url)
            return [
                {
                    "title":       clean_text(e.get("title", "")),
                    "description": truncate(clean_text(e.get("summary", "")), 500),
                    "url":         e.get("link", ""),
                    "posted_date": e.get("published", ""),
                }
                for e in feed.entries[:25]
                if e.get("title")
            ]
        except Exception as e:
            logger.error(f"Bing RSS error: {e}")
            return []

    def _collect_google_rss(self, query: str) -> list[dict]:
        try:
            encoded = query.replace(" ", "+")
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            feed = feedparser.parse(url)
            return [
                {
                    "title":       clean_text(e.get("title", "")),
                    "description": truncate(clean_text(e.get("summary", "")), 500),
                    "url":         resolve_feed_url(e),
                    "posted_date": e.get("published", ""),
                }
                for e in feed.entries[:30]
                if e.get("title")
            ]
        except Exception as e:
            logger.error(f"Google RSS error: {e}")
            return []

    # ------------------------------------------------------------------ #
    #  Regex fallback — only precise structural patterns (no broad sweep)
    # ------------------------------------------------------------------ #

    _CO  = r"([A-Z][A-Za-z0-9&'\.\-]{1,29}(?:\s+[A-Z0-9&][A-Za-z0-9&'\.\-]{0,29}){0,4})"
    _COT = r"([A-Z][A-Za-z0-9&'\.\-]{1,29}(?:\s+[A-Z0-9&][A-Za-z0-9&'\.\-]{0,29}){0,4})"

    _EXTRACT_PATTERNS = [
        # [Company] + action verb + Oracle
        rf"{_CO}\s+(?:selects?|chooses?|adopts?|taps?|names?)\s+Oracle",
        rf"{_CO}\s+(?:implements?|deploys?|installs?|rolls?\s+out)\s+Oracle",
        rf"{_CO}\s+(?:migrates?\s+to|migrates?|transitions?\s+to|moves?\s+to|switches?\s+to)\s+Oracle",
        rf"{_CO}\s+(?:goes?\s+live|launched?|completed?)\s+(?:on|with|its)?\s*Oracle",
        rf"{_CO}\s+(?:signs?|inks?|awards?|announces?)\s+(?:a\s+)?(?:deal|contract|agreement|partnership)\s+with\s+Oracle",
        rf"{_CO}\s+(?:partners?\s+with|teams?\s+up\s+with|collaborates?\s+with)\s+Oracle",
        rf"{_CO}\s+(?:transforms?|modernizes?|upgrades?|digitizes?|reinvents?)\s+.{{0,40}}(?:with|using|on)\s+Oracle",
        rf"{_CO}\s+(?:achieves?|gains?|drives?|delivers?|unlocks?|harnesses?)\s+.{{0,40}}Oracle",
        rf"{_CO}\s+(?:expands?|extends?|deepens?)\s+.{{0,30}}Oracle",
        rf"{_CO}\s+(?:standardizes?|consolidates?|centralizes?)\s+.{{0,40}}Oracle",
        rf"{_CO}\s+(?:leverages?|embraces?|streamlines?|automates?)\s+.{{0,40}}Oracle",
        rf"{_CO}\s+announces?\s+(?:Oracle|go-live|ERP|HCM|SCM|EPM|cloud\s+migration)",
        rf"{_CO}\s+completes?\s+(?:Oracle|ERP|cloud|digital\s+transformation)",
        # Oracle [verb] [Company]
        r"Oracle\s+(?:wins?|lands?|secures?)\s+" + _COT,
        r"Oracle\s+(?:selected\s+by|chosen\s+by|deployed\s+at|implemented\s+at|goes?\s+live\s+at)\s+" + _COT,
        r"Oracle\s+Cloud\s+(?:at|for|powers?|enables?)\s+" + _COT,
        r"Oracle\s+(?:helps?|supports?|enables?)\s+" + _COT + r"\s+(?:to\s+)?(?:achieve|transform|modernize|deploy|migrate)",
        rf"{_CO}\s+and\s+Oracle\s+(?:partner|sign|announce|launch|collaborate|team)",
        rf"{_CO}'s\s+Oracle\s+(?:Cloud|ERP|HCM|SCM|EPM|implementation|deployment|migration|journey|transformation)",
        rf"{_CO}\s*[-–:]\s*Oracle\s+(?:Cloud|ERP|HCM|SCM|EPM|implementation|deployment)",
        # NetSuite
        rf"{_CO}\s+(?:selects?|adopts?|implements?|deploys?|goes?\s+live\s+with|migrates?\s+to)\s+NetSuite",
        r"NetSuite\s+(?:selected\s+by|deployed\s+at|chosen\s+by)\s+" + _COT,
    ]

    _TRIM_RE = re.compile(
        r"\s+(?:and|the|a|an|its|their|with|for|of|to|in|on|at|by|as|is|are|"
        r"has|have|will|that|which|who|new|said|also|now|after|"
        r"following|recently|today|this|these|those|some|many|more|all)$",
        re.IGNORECASE,
    )

    def _extract_company_regex(self, title: str, description: str) -> str:
        for text in (title, f"{title} {description}"):
            for pat in self._EXTRACT_PATTERNS:
                m = re.search(pat, text, re.IGNORECASE)
                if not m:
                    continue
                candidate = m.group(1).strip().rstrip(".,;:'\"")
                # re.IGNORECASE makes [A-Z] match lowercase too — reject if first char is lowercase
                if not candidate or not candidate[0].isupper():
                    continue
                candidate = re.sub(r"\s+[a-z].*$", "", candidate).strip()
                prev = None
                while prev != candidate:
                    prev = candidate
                    candidate = self._TRIM_RE.sub("", candidate).strip()
                if is_valid_company_name(candidate) and "oracle" not in candidate.lower():
                    return candidate
        return ""
