"""
seed_endex_campaign.py
========================
One-off seed script: creates the Endex ICP campaign so the signal-scanning
engine can be pointed at Endex's target market (IB/PE/HF hiring + finance
tech-stack tells + AI-adoption-pressure news) instead of Oracle terms — the
campaigns/query_builder/signal-scanning pipeline is fully generic, this just
gives it Endex-specific keywords. Mirrors seed_quadsci_campaign.py exactly.

Reads icp_profiles/endex.yaml and icp_profiles/endex_signal_rules.yaml as the
single source of truth for keywords/exclusions, so the seeded campaign never
drifts from what the Endex page displays.

SOURCE COVERAGE — same caveat as seed_quadsci_campaign.py: only job-board
sources (linkedin/indeed/adzuna/ats) and `news` accept arbitrary keywords via
query_builder.py. The rest of intent_engine/src/signals/ have Oracle
product terms hardcoded into their scraping/regex logic and would silently
search for Oracle mentions regardless of campaign keywords.

`news` needs `custom_news_queries` (not the default keyword×NEWS_TEMPLATES
crossing, which assumes keywords are product names) — built here from the
funding/leadership/ai_adoption_pressure/competitor_displacement signal rules,
which are already well-formed search phrases.

IMPORTANT — unified_app.py's launch_campaign_scan() branches on
`if custom_jq or custom_nq: job_queries = custom_jq; news_queries = custom_nq`
— if EITHER custom list is set, BOTH are used verbatim with no fallback to
auto-generated job queries. So custom_job_queries must ALSO be populated
explicitly whenever custom_news_queries is set (see seed_quadsci_campaign.py's
note on the live bug this caused there).

Idempotent: skips creation if a campaign with the same name already exists.
Does NOT trigger a scan — that's a deliberate, separate action (real
Indeed/LinkedIn/news API calls) via the Campaigns page or
POST /api/campaigns/{id}/scan.

Usage:
    python seed_endex_campaign.py
"""

import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
ORACLE_DIR = BASE_DIR / "intent_engine"

# config.py's own load_dotenv() only searches upward from CWD — when this
# script runs from the repo root (BASE_DIR, the common case), that walk never
# finds intent_engine/.env (a subdirectory, not an ancestor), so
# DB_* silently falls back to config.py's hardcoded defaults instead of the
# real oracle_intent DB (same bug documented in run_glassbox.py). Load it
# explicitly before src.config/src.database get imported.
load_dotenv(ORACLE_DIR / ".env")

if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

from src import database as db  # noqa: E402
from src.query_builder import build_job_queries  # noqa: E402

CAMPAIGN_NAME = "Endex ICP"


def _load_yaml(rel_path: str) -> dict:
    return yaml.safe_load((BASE_DIR / rel_path).read_text()) or {}


def build_campaign_kwargs() -> dict:
    icp = _load_yaml("icp_profiles/endex.yaml")
    rules = _load_yaml("icp_profiles/endex_signal_rules.yaml").get("signal_rules", [])

    hiring_terms: list[str] = []
    tech_stack_terms: list[str] = []
    news_queries: list[str] = []
    for rule in rules:
        rtype = rule.get("type")
        if rtype == "hiring":
            hiring_terms.extend(rule.get("detect", []))
        elif rtype == "tech_stack_tell":
            tech_stack_terms.extend(rule.get("detect", []))
        elif rtype in ("funding_event", "leadership_change", "ai_adoption_pressure", "competitor_displacement"):
            # Already well-formed search phrases — use directly as
            # custom_news_queries rather than crossing with NEWS_TEMPLATES
            # (which assumes keywords are product names).
            news_queries.extend(rule.get("detect", []))

    keywords = hiring_terms + tech_stack_terms  # kept for display/exclusion matching elsewhere

    exclude = [icp.get("meta", {}).get("company", "Endex")]
    exclude.extend(icp.get("competitor_products", []))

    # custom_news_queries is set, so custom_job_queries MUST also be set
    # explicitly. Hiring terms are already complete job titles — search as-is.
    # Tech-stack terms are product names, so those cross correctly with role
    # suffixes ("FactSet administrator" — finds firms hiring people to run
    # FactSet), same pattern build_job_queries() already uses for Oracle
    # product terms and for QuadSci's tech-stack terms.
    job_queries = list(hiring_terms) + build_job_queries(tech_stack_terms, tier=1)

    return dict(
        name=CAMPAIGN_NAME,
        description="IB/PE/HF hiring + finance tech-stack signals, plus funding/"
                     "leadership/AI-adoption-pressure/competitor-displacement news, "
                     "for the Endex ICP (Excel-native AI agent for finance).",
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
        print(f"[seed_endex_campaign] '{CAMPAIGN_NAME}' already exists (id={existing[0]['id']}) — skipping")
        return

    kwargs = build_campaign_kwargs()
    campaign = db.create_campaign(**kwargs)
    print(f"[seed_endex_campaign] created campaign id={campaign['id']} "
          f"with {len(kwargs['keywords'])} keywords, "
          f"{len(kwargs['exclude_companies'])} exclusions")


if __name__ == "__main__":
    db.init_db()
    seed()
