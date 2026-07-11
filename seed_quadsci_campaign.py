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

Idempotent: skips creation if a campaign with the same name already exists.
Does NOT trigger a scan — that's a deliberate, separate action (real
Indeed/LinkedIn API calls) via the Campaigns page or POST /api/campaigns/{id}/scan.

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

CAMPAIGN_NAME = "QuadSci ICP"


def _load_yaml(rel_path: str) -> dict:
    return yaml.safe_load((BASE_DIR / rel_path).read_text()) or {}


def build_campaign_kwargs() -> dict:
    icp = _load_yaml("icp_profiles/quadsci.yaml")
    rules = _load_yaml("icp_profiles/quadsci_signal_rules.yaml").get("signal_rules", [])

    keywords: list[str] = []
    for rule in rules:
        if rule.get("type") in ("hiring", "tech_stack_tell"):
            keywords.extend(rule.get("detect", []))

    exclude = [icp.get("meta", {}).get("company", "QuadSci")]
    exclude.extend(icp.get("competitor_products", []))

    return dict(
        name=CAMPAIGN_NAME,
        description="RevOps/CS hiring + tech-stack signals for the QuadSci ICP "
                     "(customer-intelligence AI for B2B SaaS).",
        keywords=keywords,
        location="United States",
        max_pages=3,
        sources=["linkedin", "indeed", "adzuna", "ats"],
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
