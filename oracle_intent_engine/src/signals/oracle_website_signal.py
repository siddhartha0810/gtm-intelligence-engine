"""
Oracle website signal scraper — three tiers:

  1. Direct oracle.com scraping (with full browser session headers).
     oracle.com returns 403 to simple bots; we attempt with session cookies
     and proper headers. Works intermittently — fails gracefully.

  2. Google News RSS targeting oracle.com (confirmed working).
     Queries like "site:oracle.com/customers oracle cloud erp" surface
     oracle-published customer stories via Google. Titles reliably contain
     both company name and Oracle product, e.g.:
       "Exelon replaces its on-prem systems with Oracle Cloud ERP"

  3. Oracle press room via Google News RSS.
     Surfaces oracle.com/news/* announcements for "selects Oracle",
     "goes live with Oracle", "deploys Oracle".

Phase assignment:
  - Customer story pages   → "post_live"   (Oracle published = confirmed go-live)
  - "selects Oracle" news  → "evaluating" / "implementing"
  - "goes live" news       → "post_live"
  - "implements" news      → "implementing"
"""

import re
import time
import requests
import feedparser
from bs4 import BeautifulSoup
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, random_delay, random_headers, clean_text, truncate, resolve_feed_url, is_valid_company_name
from src import config
from src import llm_extractor

logger = get_logger(__name__)

# Oracle customer story URL patterns
ORACLE_CUSTOMER_PATHS = [
    "https://www.oracle.com/customers/",
    "https://www.oracle.com/customers/erp/",
    "https://www.oracle.com/customers/hcm/",
    "https://www.oracle.com/customers/scm/",
    "https://www.oracle.com/customers/epm/",
    "https://www.oracle.com/customers/cx/",
    "https://www.oracle.com/customers/netsuite/",
    "https://www.oracle.com/customers/oci/",
    "https://www.oracle.com/customers/database/",
]

# Google RSS queries that surface oracle.com customer stories and press releases
# Note: Google News RSS does NOT support the site: operator — use natural language queries
GOOGLE_RSS_CUSTOMER_QUERIES = [
    "oracle cloud erp implementation customer success story",
    "oracle fusion cloud erp customer go live",
    "oracle cloud hcm human capital management customer success",
    "oracle cloud scm supply chain customer implementation",
    "oracle cloud epm enterprise performance management customer",
    "netsuite erp customer implementation success story",
    "oracle oci cloud infrastructure customer migration",
    "oracle database cloud customer success story",
    "oracle integration cloud customer success implementation",
    "oracle cloud cx customer experience implementation story",
    # Industry-specific customer stories
    "manufacturing company oracle cloud erp go live",
    "retail oracle cloud erp customer success",
    "financial services oracle cloud erp implementation",
    "healthcare oracle cloud erp customer story",
    "oracle netsuite customer implementation 2024",
    "oracle cloud hcm payroll implementation customer",
    "oracle cloud scm procurement implementation",
    "oracle cloud epm planning budgeting customer",
]

GOOGLE_RSS_NEWS_QUERIES = [
    "selects oracle cloud erp finance implementation",
    "goes live oracle cloud erp enterprise",
    "implements oracle fusion cloud applications",
    "deploys oracle cloud hcm workforce management",
    "chooses oracle cloud erp digital transformation",
    "oracle cloud implementation go live announcement press release",
    "migrates oracle cloud erp modernization",
    # Additional press-release-style queries
    "announces oracle cloud erp deployment 2024",
    "completes oracle cloud migration enterprise",
    "awarded oracle cloud erp contract",
    "oracle fusion go live manufacturing 2024",
    "oracle cloud erp transformation announcement 2024",
    "selected oracle as erp vendor cloud",
    "oracle erp replacement legacy system announcement",
]

# Keyword patterns for phase from press-release-style titles
PRESS_PHASE_PATTERNS = [
    (r"goes?\s+live|go-live|launched?|completes?|completed?|successful", "post_live"),
    (r"selects?|chooses?|awards?|signs?|partners?\s+with|taps?", "evaluating"),
    (r"implements?|deploys?|migrates?|transforms?|modernizes?|adopts?", "implementing"),
    (r"expands?|upgrades?|extends?", "post_live"),
]


class OracleWebsiteSignal(BaseSignal):
    source_name = "oracle_website"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        """
        `query` is ignored — this scraper uses its own fixed query list.
        Called once per pipeline run (not per search query like other scrapers).
        """
        results: list[dict] = []

        # Tier 1a: Direct oracle.com scraping (works intermittently, often 403)
        results.extend(self._scrape_oracle_direct())

        # Tier 2: Bing News RSS for customer stories (real URLs, no Google redirects)
        results.extend(self._fetch_bing_rss_customers())

        # Tier 3: Bing News RSS for press release / news signals
        results.extend(self._fetch_bing_rss_news())

        # Tier 4: Oracle Newsroom RSS (official press releases)
        results.extend(self._fetch_oracle_newsroom())

        logger.info(f"OracleWebsite total signals: {len(results)}")
        return results

    # ------------------------------------------------------------------ #
    #  Tier 1 — Direct oracle.com
    # ------------------------------------------------------------------ #
    def _scrape_oracle_direct(self) -> list[dict]:
        results: list[dict] = []
        session = requests.Session()

        # Prime session with a root request to pick up cookies / CDN tokens
        try:
            session.get(
                "https://www.oracle.com/",
                headers={
                    **random_headers(),
                    "Referer": "https://www.google.com/",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-CH-UA": '"Chromium";v="124", "Google Chrome";v="124"',
                    "Sec-CH-UA-Mobile": "?0",
                    "Sec-CH-UA-Platform": '"Windows"',
                },
                timeout=10,
                allow_redirects=True,
            )
            random_delay(2, 4)
        except Exception:
            pass

        for path in ORACLE_CUSTOMER_PATHS:
            try:
                resp = session.get(
                    path,
                    headers={
                        **random_headers(),
                        "Referer": "https://www.oracle.com/customers/",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "same-origin",
                    },
                    timeout=15,
                    allow_redirects=True,
                )

                if resp.status_code == 403:
                    logger.debug(f"oracle.com direct 403 for {path} — expected, skipping")
                    continue
                if resp.status_code != 200:
                    continue

                # Oracle CDN returns a 200 error page when WAF blocks bot traffic
                if "technical difficulty" in resp.text.lower() or "Incident Number" in resp.text:
                    logger.debug(f"oracle.com CDN error page for {path} — WAF blocked, skipping")
                    continue

                page_results = self._parse_oracle_customer_page(resp.text, path)
                results.extend(page_results)
                logger.info(f"oracle.com direct {path} → {len(page_results)} stories")
                random_delay(config.SCAN_DELAY_MIN + 1, config.SCAN_DELAY_MAX + 2)

            except Exception as e:
                logger.debug(f"oracle.com direct error for {path}: {e}")

        return results

    def _parse_oracle_customer_page(self, html: str, source_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        # Oracle uses various card structures — try multiple selectors
        cards = (
            soup.find_all("div", class_=lambda c: c and "card" in c.lower())
            or soup.find_all("li", class_=lambda c: c and "card" in c.lower())
            or soup.find_all("article")
        )

        for card in cards:
            try:
                title_el = card.find(["h2", "h3", "h4", "a"])
                title = clean_text(title_el.get_text()) if title_el else ""
                if not title or len(title) < 5:
                    continue

                company, product = self._parse_title(title)
                if not company:
                    continue

                # Individual /customers/{slug}/ pages are WAF-blocked — use the
                # listing page URL so the link in exports actually opens.
                url = source_url

                desc_el = card.find("p")
                description = truncate(clean_text(desc_el.get_text()), 400) if desc_el else title

                results.append(self._make_signal(
                    company_name=company,
                    job_title=title,
                    description=description,
                    url=url or source_url,
                    extra={
                        "signal_type": "customer_story",
                        "oracle_product_hint": product,
                        "phase_hint": "post_live",
                    },
                ))
            except Exception as e:
                logger.debug(f"Oracle card parse error: {e}")

        # Also try JSON-LD embedded data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string or "{}")
                if isinstance(data, list):
                    if not data:
                        continue
                    data = data[0]
                name = data.get("name") or data.get("headline", "")
                desc = data.get("description", "")
                if name:
                    company, product = self._parse_title(name)
                    if company:
                        # Use listing page URL — individual /customers/{slug}/ are WAF-blocked
                        results.append(self._make_signal(
                            company_name=company,
                            job_title=clean_text(name),
                            description=truncate(clean_text(desc), 400),
                            url=source_url,
                            extra={"signal_type": "customer_story", "phase_hint": "post_live"},
                        ))
            except Exception:
                pass

        return results

    # ------------------------------------------------------------------ #
    #  Tier 2 — Bing News RSS → oracle customer stories (real URLs)
    # ------------------------------------------------------------------ #
    def _fetch_bing_rss_customers(self) -> list[dict]:
        results: list[dict] = []

        for query in GOOGLE_RSS_CUSTOMER_QUERIES:
            try:
                encoded = requests.utils.quote(query)
                url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
                feed = feedparser.parse(url)

                for entry in feed.entries[:30]:
                    title = clean_text(entry.get("title", ""))
                    summary = truncate(clean_text(entry.get("summary", "")), 500)
                    link = entry.get("link", "")  # Bing gives real publisher URLs

                    company, product = self._parse_title(title)
                    if not company:
                        company = self._extract_company_from_news(title, summary)
                    if not company:
                        continue

                    results.append(self._make_signal(
                        company_name=company,
                        job_title=title,
                        description=summary or title,
                        url=link,
                        posted_date=entry.get("published", ""),
                        extra={
                            "signal_type": "customer_story",
                            "oracle_product_hint": product,
                            "phase_hint": "post_live",
                        },
                    ))

                logger.info(f"Bing customer RSS '{query}' → {len(feed.entries)} entries")
                random_delay(1, 2)

            except Exception as e:
                logger.error(f"Bing customer RSS error for '{query}': {e}")

        return results

    # ------------------------------------------------------------------ #
    #  Tier 3 — Bing News RSS → oracle press releases / news (real URLs)
    # ------------------------------------------------------------------ #
    def _fetch_bing_rss_news(self) -> list[dict]:
        results: list[dict] = []

        for query in GOOGLE_RSS_NEWS_QUERIES:
            try:
                encoded = requests.utils.quote(query)
                url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
                feed = feedparser.parse(url)

                for entry in feed.entries[:15]:
                    title = clean_text(entry.get("title", ""))
                    summary = truncate(clean_text(entry.get("summary", "")), 500)
                    link = entry.get("link", "")

                    company, product = self._parse_title(title)
                    if not company:
                        company = self._extract_company_from_news(title, summary)
                    if not company:
                        continue

                    phase = self._infer_phase_from_title(title)

                    results.append(self._make_signal(
                        company_name=company,
                        job_title=title,
                        description=summary or title,
                        url=link,
                        posted_date=entry.get("published", ""),
                        extra={
                            "signal_type": "press_release",
                            "oracle_product_hint": product,
                            "phase_hint": phase,
                        },
                    ))

                logger.info(f"Bing news RSS '{query}' → {len(feed.entries)} entries")
                random_delay(1, 2)

            except Exception as e:
                logger.error(f"Bing news RSS error for '{query}': {e}")

        return results

    # ------------------------------------------------------------------ #
    #  Tier 4 — Oracle Newsroom (official press release RSS)
    # ------------------------------------------------------------------ #
    def _fetch_oracle_newsroom(self) -> list[dict]:
        """
        Oracle's press room publishes customer announcements and go-live news.
        We try their Atom feed first; fall back to Bing RSS for oracle.com/news.
        """
        results: list[dict] = []

        # Oracle official newsroom feed (may require accept header)
        newsroom_urls = [
            "https://www.oracle.com/corporate/pressroom/rss-feeds/news.xml",
            "https://www.oracle.com/news/rss/",
        ]
        for feed_url in newsroom_urls:
            try:
                feed = feedparser.parse(feed_url)
                if not feed.entries:
                    continue
                for entry in feed.entries[:30]:
                    title   = clean_text(entry.get("title", ""))
                    summary = truncate(clean_text(entry.get("summary", "")), 500)
                    link    = entry.get("link", "")
                    combined = f"{title} {summary}"

                    if "oracle" not in combined.lower():
                        continue

                    company, product = self._parse_title(title)
                    if not company:
                        company = self._extract_company_from_news(title, summary)
                    if not company:
                        continue

                    phase = self._infer_phase_from_title(title)
                    results.append(self._make_signal(
                        company_name=company,
                        job_title=title,
                        description=summary or title,
                        url=link,
                        posted_date=entry.get("published", ""),
                        extra={
                            "signal_type": "press_release",
                            "oracle_product_hint": product,
                            "phase_hint": phase,
                        },
                    ))

                logger.info(f"Oracle Newsroom RSS {feed_url} → {len(results)} signals")
                break  # Use first feed that returns entries
            except Exception as e:
                logger.debug(f"Oracle Newsroom RSS {feed_url}: {e}")

        # Bing RSS fallback for oracle.com news
        if not results:
            try:
                encoded = requests.utils.quote("site:oracle.com/news selects implements goes live 2024")
                url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
                feed = feedparser.parse(url)
                for entry in feed.entries[:20]:
                    title   = clean_text(entry.get("title", ""))
                    summary = truncate(clean_text(entry.get("summary", "")), 500)
                    link    = entry.get("link", "")
                    company, product = self._parse_title(title)
                    if not company:
                        company = self._extract_company_from_news(title, summary)
                    if not company:
                        continue
                    phase = self._infer_phase_from_title(title)
                    results.append(self._make_signal(
                        company_name=company,
                        job_title=title,
                        description=summary or title,
                        url=link,
                        posted_date=entry.get("published", ""),
                        extra={
                            "signal_type": "press_release",
                            "oracle_product_hint": product,
                            "phase_hint": phase,
                        },
                    ))
                logger.info(f"Oracle Newsroom Bing fallback → {len(results)} signals")
            except Exception as e:
                logger.error(f"Oracle newsroom Bing fallback error: {e}")

        return results

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    def _parse_title(self, title: str) -> tuple[str, str]:
        """
        Extracts (company_name, oracle_product) from Oracle-published titles.
        Format examples:
          "Exelon replaces its on-prem systems with Oracle Cloud ERP"
          "Avis Budget Group gains automation with Oracle Cloud ERP"
          "Marriott builds global talent data using Oracle Cloud HCM"
        """
        if not title:
            return "", ""

        # Oracle product extraction
        product = ""
        product_patterns = [
            (r"Oracle\s+Fusion\s+Cloud\s+ERP", "Oracle Cloud ERP"),
            (r"Oracle\s+Cloud\s+ERP", "Oracle Cloud ERP"),
            (r"Oracle\s+Fusion\s+Cloud\s+HCM", "Oracle HCM"),
            (r"Oracle\s+Cloud\s+HCM", "Oracle HCM"),
            (r"Oracle\s+HCM", "Oracle HCM"),
            (r"Oracle\s+Fusion\s+Cloud\s+SCM", "Oracle SCM"),
            (r"Oracle\s+Cloud\s+SCM", "Oracle SCM"),
            (r"Oracle\s+Fusion\s+Cloud\s+EPM", "Oracle EPM"),
            (r"Oracle\s+Cloud\s+EPM", "Oracle EPM"),
            (r"Oracle\s+Hyperion", "Oracle EPM"),
            (r"Oracle\s+Fusion\s+Cloud\s+CX", "Oracle CX"),
            (r"Oracle\s+Cloud\s+CX", "Oracle CX"),
            (r"Oracle\s+Sales\s+Cloud", "Oracle CX"),
            (r"Oracle\s+NetSuite|NetSuite", "NetSuite"),
            (r"Oracle\s+Cloud\s+Infrastructure|Oracle\s+OCI|\bOCI\b", "Oracle OCI"),
            (r"Oracle\s+Autonomous\s+Database|Oracle\s+Database", "Oracle Database"),
            (r"Oracle\s+Integration\s+Cloud|\bOIC\b", "Oracle Integration"),
            (r"Oracle\s+APEX", "Oracle APEX"),
            (r"Oracle\s+Fusion\s+Cloud\s+Applications", "Oracle Cloud ERP"),
            (r"Oracle\s+Analytics", "Oracle Analytics"),
            (r"Oracle\s+Cloud", "Oracle Cloud"),
        ]
        for pat, prod_name in product_patterns:
            if re.search(pat, title, re.IGNORECASE):
                product = prod_name
                break

        # Company extraction — the subject before the verb
        # Patterns: "[Company] [verb] ... Oracle [product]"
        company_patterns = [
            r"^([A-Z][A-Za-z0-9\s&,\.\-]+?)\s+(?:taps?|selects?|adopts?|gains?|builds?|harnesses?|leverages?|relies?\s+on|replaces?|migrates?|moves?\s+to|transforms?|modernizes?|implements?|deploys?|goes?\s+live|leads?|launches?|unlocks?|streamlines?|boosts?|embraces?|serves?|expects?|achieves?|chooses?|upgrades?|extends?|digitizes?|empowers?|reinvents?)\b",
            r"^([A-Z][A-Za-z0-9\s&,\.\-]+?)\s+(?:with|using|on|via)\s+Oracle",
        ]

        company = ""
        for pat in company_patterns:
            m = re.match(pat, title.strip())
            if m:
                candidate = m.group(1).strip().rstrip(".,")
                if "Oracle" not in candidate and is_valid_company_name(candidate):
                    company = candidate
                    break

        return company, product

    def _extract_company_from_news(self, title: str, description: str) -> str:
        """LLM-based extraction for articles where _parse_title() found nothing."""
        return llm_extractor.extract_company(title, description)

    def _infer_phase_from_title(self, title: str) -> str:
        title_l = title.lower()
        for pattern, phase in PRESS_PHASE_PATTERNS:
            if re.search(pattern, title_l):
                return phase
        return "implementing"
