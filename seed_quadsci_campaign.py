"""
seed_quadsci_campaign.py
=========================
One-off seed script: creates the QuadSci ICP campaign so the signal-scanning
engine can be pointed at QuadSci's target market (RevOps/CS hiring +
tech-stack tells) instead of Oracle terms — the campaigns/query_builder
pipeline is fully generic, this just gives it QuadSci-specific keywords.

Reads icp_profiles/quadsci.yaml and icp_profiles/quadsci_signal_rules.yaml as
the single source of truth for keywords/exclusions, so the seeded campaign
never drifts from what the QuadSci page displays.

SOURCE COVERAGE — only a subset of oracle_intent_engine/src/signals/ is
generic/keyword-driven; the rest (sec_filing, g2_reviews, oracle_website,
oracle_community, oracle_event, erp_today, procurement, home_builders,
si_casestudy, partner_casestudy, company_pages, agentic_harvester) have
Oracle product terms hardcoded into their scraping/regex logic and will
silently search for Oracle mentions regardless of campaign keywords — adding
them to `sources` here would not surface QuadSci-relevant signals. Only
job-board sources (linkedin/indeed/adzuna/ats) and `news` accept arbitrary
keywords via query_builder.py. `news` needs `custom_news_queries` (not the
default keyword×NEWS_TEMPLATES crossing, which assumes keywords are product
names like "Oracle Cloud ERP" — QuadSci's hiring/tech-stack keywords don't
fit that template shape) — built here from the funding/leadership/NRR/
competitor-displacement signal rules, which are already well-formed search
phrases.

IMPORTANT — unified_app.py's launch_campaign_scan() branches on
`if custom_jq or custom_nq: job_queries = custom_jq; news_queries = custom_nq`
(unified_app.py:4267-4269) — if EITHER custom list is set, BOTH are used
verbatim, with no fallback to auto-generated job queries. Setting only
custom_news_queries here silently zeroed out job_queries entirely (confirmed
live: a real scan launched with 0 job queries, and scan_worker.py's
`job_queries or tech_profiles.get_active_search_queries()` fallback then
searched generic Oracle terms instead of stopping or erroring — a scan that
looked like it was working but was scanning for the wrong thing). So
custom_job_queries must ALSO be populated explicitly whenever
custom_news_queries is set — never leave one custom list set and the other
empty.

Idempotent: skips creation if a campaign with the same name already exists.
Does NOT trigger a scan — that's a deliberate, separate action (real
Indeed/LinkedIn/news API calls) via the Campaigns page or
POST /api/campaigns/{id}/scan.

Usage:
    python seed_quadsci_campaign.py
"""

import sys
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent
ORACLE_DIR = BASE_DIR / "oracle_intent_engine"
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

from src import database as db  # noqa: E402
from src.query_builder import build_job_queries  # noqa: E402

CAMPAIGN_NAME = "QuadSci ICP"


def _load_yaml(rel_path: str) -> dict:
    return yaml.safe_load((BASE_DIR / rel_path).read_text()) or {}


def build_campaign_kwargs() -> dict:
    icp = _load_yaml("icp_profiles/quadsci.yaml")
    rules = _load_yaml("icp_profiles/quadsci_signal_rules.yaml").get("signal_rules", [])

    hiring_terms: list[str] = []
    tech_stack_terms: list[str] = []
    news_queries: list[str] = []
    for rule in rules:
        rtype = rule.get("type")
        if rtype == "hiring":
            hiring_terms.extend(rule.get("detect", []))
        elif rtype == "tech_stack_tell":
            tech_stack_terms.extend(rule.get("detect", []))
        elif rtype in ("funding_event", "leadership_change", "nrr_commentary", "competitor_displacement"):
            # These detect-phrases are already well-formed search queries — use
            # them directly as custom_news_queries rather than crossing them
            # with query_builder's NEWS_TEMPLATES (which assumes keywords are
            # product names, e.g. "Oracle Cloud ERP goes live").
            news_queries.extend(rule.get("detect", []))

    keywords = hiring_terms + tech_stack_terms  # kept for display/exclusion matching elsewhere

    exclude = [icp.get("meta", {}).get("company", "QuadSci")]
    exclude.extend(icp.get("competitor_products", []))

    # Since custom_news_queries is set, custom_job_queries MUST also be set
    # explicitly (see the IMPORTANT note above). Hiring terms are already
    # complete job-titles — searching them as-is ("Head of RevOps") is
    # correct; crossing them with role suffixes would produce nonsense
    # ("Head of RevOps administrator"). Tech-stack terms are product names,
    # so THOSE cross correctly with role suffixes ("Gainsight administrator"
    # — finds companies hiring people to run Gainsight), same pattern
    # build_job_queries() already uses for Oracle product terms.
    job_queries = list(hiring_terms) + build_job_queries(tech_stack_terms, tier=1)

    return dict(
        name=CAMPAIGN_NAME,
        description="RevOps/CS hiring + tech-stack signals, plus funding/leadership/NRR/"
                     "competitor-displacement news, for the QuadSci ICP "
                     "(customer-intelligence AI for B2B SaaS).",
        keywords=keywords,
        location="United States",
        max_pages=3,
        sources=["linkedin", "indeed", "adzuna", "ats", "news"],
        custom_job_queries=job_queries,
        custom_news_queries=news_queries,
        query_tier=1,
        exclude_companies=exclude,
    )


def seed() -> None:
    existing = [c for c in db.list_campaigns() if c.get("name") == CAMPAIGN_NAME]
    if existing:
        print(f"[seed_quadsci_campaign] '{CAMPAIGN_NAME}' already exists (id={existing[0]['id']}) — skipping")
        return

    kwargs = build_campaign_kwargs()
    campaign = db.create_campaign(**kwargs)
    print(f"[seed_quadsci_campaign] created campaign id={campaign['id']} "
          f"with {len(kwargs['keywords'])} keywords, "
          f"{len(kwargs['exclude_companies'])} exclusions")


if __name__ == "__main__":
    db.init_db()
    seed()
