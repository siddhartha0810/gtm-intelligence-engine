"""
seed_demo_data.py
==================
Populates a handful of synthetic companies/signals/contacts/campaign so a
fresh deployment (Docker demo, or a first local run) isn't an empty shell.

Idempotent: skips seeding if the companies table already has rows, unless
force=True is passed. Safe to call on every container boot.

Usage:
    python seed_demo_data.py            # seed only if companies table is empty
    python seed_demo_data.py --force    # seed regardless (adds duplicates)
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
ORACLE_DIR = BASE_DIR / "oracle_intent_engine"
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

from src import database as db  # noqa: E402

DEMO_COMPANIES = [
    {
        "name": "Meridian Manufacturing Co",
        "domain": "meridianmfg.com",
        "industry": "Manufacturing",
        "size": "1000-5000",
        "location": "Columbus, OH",
        "signals": [
            dict(oracle_product="JD Edwards", phase="hiring", source="indeed",
                 signal_type="job_posting", job_title="JDE CNC Administrator",
                 evidence="Meridian Manufacturing Co is hiring a JD Edwards EnterpriseOne CNC Administrator to support production ERP.",
                 url="https://indeed.com/demo/meridian-jde-cnc", confidence=0.9),
        ],
        "contacts": [
            dict(full_name="Dana Whitfield", first_name="Dana", last_name="Whitfield",
                 title="VP of IT", email="dana.whitfield@meridianmfg.com",
                 source="apollo", is_target=True, confidence=0.85, seniority="vp"),
        ],
    },
    {
        "name": "Coastal Home Builders",
        "domain": "coastalhomebuilders.com",
        "industry": "Construction",
        "size": "500-1000",
        "location": "Charleston, SC",
        "signals": [
            dict(oracle_product="JD Edwards", phase="upgrading", source="news",
                 signal_type="press_release", job_title="",
                 evidence="Coastal Home Builders announces JD Edwards EnterpriseOne cloud migration to modernize job costing.",
                 url="https://news.example.com/demo/coastal-jde-migration", confidence=0.75),
        ],
        "contacts": [
            dict(full_name="Marcus Ríos", first_name="Marcus", last_name="Ríos",
                 title="Director of Finance", email="marcus.rios@coastalhomebuilders.com",
                 source="apollo", is_target=True, confidence=0.8, seniority="director"),
        ],
    },
    {
        "name": "Bluepeak Logistics",
        "domain": "bluepeaklogistics.com",
        "industry": "Transportation & Logistics",
        "size": "1000-5000",
        "location": "Memphis, TN",
        "signals": [
            dict(oracle_product="Oracle Cloud ERP", phase="evaluating", source="procurement",
                 signal_type="rfp", job_title="",
                 evidence="Bluepeak Logistics issued an RFP for Oracle Fusion ERP Cloud implementation partners.",
                 url="https://procurement.example.com/demo/bluepeak-rfp", confidence=0.85),
        ],
        "contacts": [
            dict(full_name="Priya Natarajan", first_name="Priya", last_name="Natarajan",
                 title="CIO", email="priya.natarajan@bluepeaklogistics.com",
                 source="apollo", is_target=True, confidence=0.9, seniority="c_suite"),
        ],
    },
    {
        "name": "Summit Foods Group",
        "domain": "summitfoodsgroup.com",
        "industry": "Food & Beverage",
        "size": "5000-10000",
        "location": "Minneapolis, MN",
        "signals": [
            dict(oracle_product="Oracle SCM Cloud", phase="implementing", source="news",
                 signal_type="press_release", job_title="",
                 evidence="Summit Foods Group goes live on Oracle Supply Chain Cloud across three distribution centers.",
                 url="https://news.example.com/demo/summit-scm-golive", confidence=0.8),
        ],
        "contacts": [
            dict(full_name="Owen Baptiste", first_name="Owen", last_name="Baptiste",
                 title="VP Supply Chain", email="owen.baptiste@summitfoodsgroup.com",
                 source="apollo", is_target=True, confidence=0.82, seniority="vp"),
        ],
    },
    {
        "name": "Ironclad Energy Partners",
        "domain": "ironcladenergy.com",
        "industry": "Energy & Utilities",
        "size": "1000-5000",
        "location": "Houston, TX",
        "signals": [
            dict(oracle_product="JD Edwards", phase="supporting", source="indeed",
                 signal_type="job_posting", job_title="JDE EnterpriseOne Support Analyst",
                 evidence="Ironclad Energy Partners seeks a JD Edwards Support Analyst to manage existing production ERP environment.",
                 url="https://indeed.com/demo/ironclad-jde-support", confidence=0.7),
        ],
        "contacts": [
            dict(full_name="Talia Ferrante", first_name="Talia", last_name="Ferrante",
                 title="ERP Manager", email="talia.ferrante@ironcladenergy.com",
                 source="apollo", is_target=True, confidence=0.78, seniority="manager"),
        ],
    },
]

DEMO_CAMPAIGN = dict(
    name="Demo — Weave ICP (YC dev-tools)",
    description="Sample campaign seeded for demonstration purposes.",
    keywords=["developer tools", "AI infrastructure"],
    location="United States",
    max_pages=2,
    sources=["indeed", "news"],
    query_tier=1,
)


def _companies_table_has_rows() -> bool:
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM companies")
        row = cur.fetchone()
        return (row["n"] if row else 0) > 0


def seed_if_empty(force: bool = False) -> None:
    if not force and _companies_table_has_rows():
        print("[seed_demo_data] companies table already has data — skipping seed")
        return

    run_id = db.start_scan_run(queries="[demo seed]")
    total_signals = 0
    total_companies = 0

    for company in DEMO_COMPANIES:
        company_id = db.upsert_company(
            name=company["name"],
            domain=company["domain"],
            industry=company["industry"],
            size=company["size"],
            location=company["location"],
            website=f"https://{company['domain']}",
            first_scan_run_id=run_id,
        )
        total_companies += 1
        for sig in company["signals"]:
            db.insert_signal(company_id=company_id, scan_run_id=run_id, **sig)
            total_signals += 1
        db.save_contacts(company_id, company["contacts"])

    db.finish_scan_run(run_id, total_signals=total_signals, total_companies=total_companies)

    try:
        db.create_campaign(**DEMO_CAMPAIGN)
    except Exception as e:
        print(f"[seed_demo_data] campaign seed skipped: {e}")

    print(f"[seed_demo_data] seeded {total_companies} companies, {total_signals} signals, 1 campaign")


if __name__ == "__main__":
    db.init_db()
    seed_if_empty(force="--force" in sys.argv)
