"""
g2_review_search.py
====================
Free, no-API-key search for a company's G2/Capterra review presence, using
ddgs (DuckDuckGo's general web search). This is deliberately NOT built on
g2_reviews_signal.py's approach — that module only hits Bing's NEWS RSS feed
(bing.com/news/search&format=rss), and news crawlers essentially never index
evergreen review pages, which is why it silently returned nothing. ddgs
searches DuckDuckGo's general web index, which does surface G2/Capterra
listings — confirmed empirically against real companies before building this.

WHY THIS SOURCE: SEC filings worked for InRule because they're where InRule's
buying trigger (new SOX/audit obligations) gets disclosed by a party other
than the prospect. The equivalent for QuadSci — a churn/retention-intelligence
product — isn't a regulatory filing, it's a prospect's OWN CUSTOMERS
describing the exact symptom QuadSci cures (reactive support, no usage
visibility, surprise renewals) in a public review, in their own words. That's
third-party disclosure of the precise pain point, not a proxy signal like a
job posting.

Searches "{company}" (site:g2.com OR site:capterra.com) and returns raw
result snippets — callers classify the snippet text themselves against a
pain-language term list (see run_glassbox.py's fetch_g2_pain_corroboration()),
same "search broad, classify locally" pattern news_signal.py's
search_company_mentions() already uses, for the same reason: cramming
multiple OR'd terms into the search query itself pulls in unrelated noise
(confirmed empirically — see this module's git history / session notes).

COVERAGE CAVEAT: only surfaces companies with an established G2/Capterra
listing that DuckDuckGo has indexed. Newer/smaller companies often return
nothing at all (confirmed: an ~8-employee company returned zero real hits,
just fuzzy-name matches on unrelated products). That's a real gap, not a
bug — the 3-state glassbox scorer already treats "no evidence" as excluded
from scoring, not a penalty, so this degrades gracefully.
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
