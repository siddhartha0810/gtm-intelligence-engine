"""
g2_review_search.py
====================
Free, no-API-key search for a prospect's own customers describing their pain
in public — two sources, both via ddgs (search-engine snippets, not direct
site scraping):

1. search_review_mentions() — G2/Capterra presence via DuckDuckGo's general
   web index. This is deliberately NOT built on g2_reviews_signal.py's
   approach — that module only hits Bing's NEWS RSS feed, and news crawlers
   essentially never index evergreen review pages, which is why it silently
   returned nothing.

2. search_reddit_mentions() — real Reddit threads via ddgs's Bing backend.
   Added after confirming G2/Capterra can't be scraped directly: both sites
   sit behind active anti-bot systems (G2 = DataDome CAPTCHA, Capterra =
   Cloudflare Turnstile challenge, confirmed empirically — plain requests
   gets a 403 challenge page, not review content, and defeating that would
   mean building detection-evasion against a commercial site's explicit
   anti-scraping measures, which this project isn't going to do). Search
   engines that have crawled the review page's SEO metadata are the only
   legitimate way to see pain language without scraping the page itself —
   and G2/Capterra's own metadata rarely contains real complaint text (it's
   marketing copy), whereas Reddit threads are real unprompted complaints
   and are well-indexed by search engines. Empirically, ddgs's DEFAULT
   backend rotation returns useless stub snippets for reddit.com results
   ("The site owner hides the web page description" / "Link to reddit.com"
   as the title) — explicitly requesting backend="bing" is what actually
   returns real thread titles and body text; confirmed against a company
   with zero G2 hits before adding this.

WHY THIS SOURCE (both): SEC filings worked for InRule because they're where
InRule's buying trigger (new SOX/audit obligations) gets disclosed by a party
other than the prospect. The equivalent for QuadSci — a churn/retention-
intelligence product — isn't a regulatory filing, it's a prospect's OWN
CUSTOMERS describing the exact symptom QuadSci cures (reactive support, no
usage visibility, surprise renewals) in their own words, in public. That's
third-party disclosure of the precise pain point, not a proxy signal like a
job posting.

Both return raw result snippets — callers classify the snippet text
themselves against a pain-language term list (see run_glassbox.py's
fetch_g2_pain_corroboration() / fetch_reddit_pain_corroboration()), same
"search broad, classify locally" pattern news_signal.py's
search_company_mentions() already uses, for the same reason: cramming
multiple OR'd terms into the search query itself pulls in unrelated noise
(confirmed empirically — see this module's git history / session notes).

COVERAGE CAVEAT: only surfaces companies with an established G2/Capterra
listing or Reddit discussion that a search engine has indexed. Newer/smaller
companies often return nothing at all. That's a real gap, not a bug — the
3-state glassbox scorer already treats "no evidence" as excluded from
scoring, not a penalty, so this degrades gracefully.
"""

from ddgs import DDGS

from src.utils import get_logger, random_delay

logger = get_logger(__name__)


def search_review_mentions(company_name: str, max_results: int = 6) -> list[dict]:
    """Raw DDG results for this company's G2/Capterra presence.
    Returns [{"title", "url", "body"}, ...] — no classification here.

    Query anchors on a single quoted phrase ("customer support"), not a
    site:-only scope — empirically, the site:-scoped-only query mostly
    returns generic marketing blurbs from the review page's own meta
    description, while anchoring on a real review-topic phrase surfaces
    actual sentiment (both positive AND negative — e.g. a competitor
    comparison site summarizing "Slow Customer Support... clear trend of
    users migrating away" from real Aircall G2 reviews). Classification of
    positive vs. negative happens locally against the pain-language term
    list, same as everywhere else in this codebase — cramming multiple OR'd
    terms into the query itself is the mistake that produced noise
    elsewhere (see phase_classifier.py's word-boundary fix this session)."""
    query = f'"{company_name}" g2 review "customer support"'
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "body": r.get("body", "")}
            for r in results
        ]
    except Exception as e:
        logger.warning(f"[g2_review_search] '{company_name}' search failed: {e}")
        return []
    finally:
        random_delay(1.0, 2.5)  # ddgs throttles after rapid requests


def search_reddit_mentions(company_name: str, max_results: int = 6) -> list[dict]:
    """Real Reddit thread titles/snippets for this company's support/product
    reputation. Returns [{"title", "url", "body"}, ...] — no classification
    here, same contract as search_review_mentions().

    backend="bing" is required, not optional — ddgs's default backend
    rotation returns unusable stub snippets for reddit.com results (see
    module docstring); explicitly requesting Bing is what surfaces real
    thread content. Falls back to the default rotation only if the Bing
    backend itself errors (e.g. temporarily unavailable), so this degrades
    to "probably empty" rather than hard-failing."""
    query = f'site:reddit.com "{company_name}" customer support'
    try:
        with DDGS() as ddgs:
            try:
                results = list(ddgs.text(query, max_results=max_results, backend="bing"))
            except Exception as e:
                logger.warning(f"[g2_review_search] reddit bing backend failed for '{company_name}': {e}, falling back")
                results = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "body": r.get("body", "")}
            for r in results
        ]
    except Exception as e:
        logger.warning(f"[g2_review_search] reddit search '{company_name}' failed: {e}")
        return []
    finally:
        random_delay(1.0, 2.5)  # ddgs throttles after rapid requests
