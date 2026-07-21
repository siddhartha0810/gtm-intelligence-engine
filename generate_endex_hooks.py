"""
generate_endex_hooks.py
========================
One-off script: generates grounded cold-email hooks for the enriched Endex
TIER 3 prospects, using each company's REAL glassbox evidence (the actual
fired rule text + source URL) as the grounding material — not invented
specifics. Reuses the existing hook_generator.py pipeline unchanged
(grounding_check, personalization_bucket gate, PAS framework). Mirrors
generate_quadsci_hooks.py.

Demo/one-off script — not part of the reusable glassbox engine.
"""

import re
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
ORACLE_DIR = BASE_DIR / "intent_engine"
sys.path.insert(0, str(ORACLE_DIR))
load_dotenv(ORACLE_DIR / ".env")
load_dotenv(BASE_DIR / "lead_enrichment_engine" / ".env")

from src import database as db
from src.hook_generator import generate_hook

CAMPAIGN_ID = 5

# Clearsulting (consultancy, off-ICP) and Codex (no contacts) excluded per
# user direction — see account_prospects EXCLUDED tier + campaign
# exclude_companies update.
COMPANIES = [
    'Ares Management', 'Citi', 'BMO Capital Markets', 'UBS',
    'D.A. Davidson Companies', 'Oppenheimer & Co. Inc.', 'Santander US',
    'Houlihan Lokey', 'Raymond James', 'Jefferies',
    'Cohen & Company Capital Markets', 'Brown Advisory', 'Alpha Alternatives',
]

PERSONA_PATTERNS = [
    r'\bchief financial officer\b', r'\bcfo\b',
    r'\bhead of fp\s?&\s?a\b', r'\bvp financial planning\b',
    r'\bchief operating officer\b', r'\bcoo\b',
    r'\bmanaging director,?\s*investment banking\b', r'\bmanaging director\s*-\s*investment banking\b',
    r'\bvice president investment banking\b', r'\binvestment banking director\b',
]

PRODUCT_CONTEXT = """
Endex — Excel-native AI agent for finance. Builds DCF and three-statement
models directly inside Excel, with integrated citations for auditable
outputs, pulling from SEC filings, Capital IQ, and FactSet. Custom-built
LLMs engineered for finance, not a generic wrapper. Founded 2022 by Tarun
Amasa and Kevin Yang (NYC). $14.6M raised, $14M Series B (Aug 2025) led by
OpenAI Startup Fund, with Dorm Room Fund, Soma Capital, and Neo. Deployed at
leading investment banks, $100B+ AUM private equity firms, and global
multi-strategy hedge funds. SOC 2 / ISO 27001 / GDPR certified. Pitch:
collapse hours of manual model-building and data-pulling into minutes,
without leaving Excel, with every number traceable back to its source.
""".strip()

ICP_RESEARCH = """
Target: investment banks (bulge bracket + boutique), private equity firms
($1B-$100B+ AUM), multi-strategy hedge funds, Fortune 500 corporate finance/
FP&A teams, and publicly traded REITs — all Excel-centric modeling shops
with real capital-markets exposure. Buyers: CFO/Head of FP&A, Head of
Financial Modeling, VP/Director Investment Banking, Portfolio Manager
(primary); Head of Research, COO of fund, Head of Data/Technology
(secondary). These firms already run CapIQ/FactSet/Bloomberg/PitchBook and
are under real pressure right now: banks are cutting junior analyst classes
while still needing the same modeling output, and AI is reshaping how that
work gets done. Active IB/PE hiring, a fresh fund close, or a new CFO/Head
of Data are all signals the finance tech stack is being actively reviewed.
""".strip()


def pick_contact(contacts: list) -> dict | None:
    for pat in PERSONA_PATTERNS:
        hit = next((ct for ct in contacts if re.search(pat, (ct.get('title') or '').lower())), None)
        if hit:
            return hit
    return contacts[0] if contacts else None


def build_research_summary(trace: list) -> str:
    """Real, verifiable evidence only — the exact why-text from fired
    glassbox rules. This is what grounding_check anchors against."""
    lines = []
    for t in trace:
        if t.get("state") == "fired" and t.get("why"):
            lines.append(t["why"])
    return " ".join(lines)


def main():
    db.init_db()
    results = []
    for name in COMPANIES:
        company = db.get_company_by_name(name)
        if not company:
            print(f"[skip] {name}: not found")
            continue
        contacts = db.get_contacts_for_company(company["id"])
        contact = pick_contact(contacts)
        if not contact:
            print(f"[skip] {name}: no contacts")
            continue

        with db.db_cursor(commit=False) as cur:
            cur.execute("SELECT trace FROM account_prospects WHERE company_id=%s AND campaign_id=%s",
                        (company["id"], CAMPAIGN_ID))
            row = cur.fetchone()
        trace = row["trace"] if row else []
        summary = build_research_summary(trace)

        company_research = {"name": name, "research": {"summary": summary}}
        contact_dict = {
            "first_name": contact.get("first_name", ""),
            "last_name": contact.get("last_name", ""),
            "title": contact.get("title", ""),
            "company": name,
            "email": contact.get("email") or "",
            "linkedin_url": contact.get("linkedin_url", "") or "",
        }

        hook = generate_hook(
            contact=contact_dict,
            company_research=company_research,
            product_context=PRODUCT_CONTEXT,
            icp_research=ICP_RESEARCH,
        )
        hook_id = db.save_campaign_hook(
            hook, signal_summary=summary,
            product_context=PRODUCT_CONTEXT, icp_research=ICP_RESEARCH,
        )
        hook["hook_id"] = hook_id
        results.append(hook)

        status = "OK" if hook.get("ok") else ("HELD BACK" if hook.get("hold_back") else "FAILED")
        print(f"[{status}] {name} -> {contact_dict['first_name']} {contact_dict['last_name']} ({contact_dict['title']})")
        if hook.get("ok"):
            print(f"   Subject: {hook.get('subject')}")
            print(f"   Body: {hook.get('body')}")
            print(f"   Angle: {hook.get('angle')} | Bucket: {hook.get('personalization_label')} | Grounded on: {hook.get('grounded_on')}")
        elif hook.get("error"):
            print(f"   Reason: {hook.get('error')}")
        print()

    ok_hooks = [h for h in results if h.get("ok")]
    print(f"\n{len(ok_hooks)}/{len(results)} hooks generated successfully")
    return ok_hooks


if __name__ == "__main__":
    main()
