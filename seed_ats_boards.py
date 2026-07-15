"""
seed_ats_boards.py
===================
One-off seed: populates the ats_boards registry (currently empty — which is
why every scan's ATS stage reported "0 first-party hiring signals": the
scraper had zero boards to scan, not a paid-API problem).

Discovers Greenhouse/Lever/Ashby/SmartRecruiters board tokens for a curated
list of QuadSci-ICP companies (B2B SaaS, telemetry-rich, roughly $20M-$500M
ARR / Series C+ — the archetypes from icp_profiles/quadsci.yaml, seeded with
lookalikes of QuadSci's own reference customers Clari/Reltio/Movable
Ink/Boomi/Tenable) via ats_discovery.py's keyless endpoint probing, then
registers them with db.upsert_ats_board so ats_signal.py picks them up on
the next scan.

All endpoints are free public JSON — no keys, ~0% block rate. Idempotent:
upsert_ats_board is ON CONFLICT DO UPDATE.

Usage:
    .venv/bin/python seed_ats_boards.py            # discover + register
    .venv/bin/python seed_ats_boards.py --dry-run  # discover only, no DB write
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
ORACLE_DIR = BASE_DIR / "oracle_intent_engine"
load_dotenv(ORACLE_DIR / ".env")
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

from src import database as db  # noqa: E402
from src.ats_discovery import discover_board  # noqa: E402

# QuadSci-ICP archetypes: telemetry-rich B2B SaaS across the yaml's five
# target verticals. Mid-size names deliberately favored over megacaps —
# the ICP tops out around $500M ARR, so Datadog-scale companies are edge
# cases kept only where their CS/RevOps hiring is still a useful signal pool.
ICP_COMPANIES = [
    # Infrastructure / DevTools SaaS
    "LaunchDarkly", "CircleCI", "Netlify", "Render", "Temporal Technologies",
    "Grafana Labs", "HashiCorp", "PagerDuty", "Honeycomb", "Chronosphere",
    "Postman", "Kong", "Docker", "Sentry", "Vercel",
    # Data / MDM / Integration platforms (Reltio/Boomi lookalikes)
    "Fivetran", "Airbyte", "dbt Labs", "Matillion", "Ataccama",
    "Tealium", "Rudderstack", "Hightouch", "Census", "Workato", "Tray.io",
    # Security SaaS (Tenable lookalikes)
    "Snyk", "Wiz", "Orca Security", "Arctic Wolf", "Expel",
    "Vanta", "Drata", "Abnormal Security", "Material Security",
    # MarTech (Movable Ink lookalikes)
    "Braze", "Iterable", "Klaviyo", "Amplitude", "Mixpanel",
    "Heap", "FullStory", "Pendo", "Contentsquare", "mParticle",
    # RevOps / GTM tooling (Clari lookalikes)
    "Gong", "Clari", "Salesloft", "Outreach", "Chili Piper",
    "Apollo.io", "ZoomInfo", "6sense", "Demandbase", "Highspot",
    "Seismic", "Mindtickle", "Docebo", "WorkRamp",
]


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    if not dry_run:
        db.init_db()

    found, missed = [], []
    for name in ICP_COMPANIES:
        board = discover_board(name)
        if board:
            found.append(board)
            print(f"  + {name:<25} {board['ats']}:{board['token']} "
                  f"({board['job_count']} jobs, verified={board['verified']})")
            if not dry_run:
                db.upsert_ats_board(**board)
        else:
            missed.append(name)
            print(f"  - {name:<25} no board found")

    print(f"\n{len(found)}/{len(ICP_COMPANIES)} boards discovered"
          + ("" if dry_run else " and registered"))
    if missed:
        print(f"No board (different ATS or non-guessable token): {', '.join(missed)}")


if __name__ == "__main__":
    main()
