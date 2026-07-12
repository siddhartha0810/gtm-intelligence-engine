"""
generate_quadsci_hooks.py
==========================
One-off script: generates grounded cold-email hooks for the 12 verified
TIER 3 QuadSci prospects, using each company's REAL glassbox evidence (the
actual fired rule text + source URL) as the grounding material — not
invented specifics. Reuses the existing hook_generator.py pipeline
unchanged (grounding_check, personalization_bucket gate, PAS framework).

Demo/one-off script — not part of the reusable glassbox engine.
"""

import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
ORACLE_DIR = BASE_DIR / "oracle_intent_engine"
sys.path.insert(0, str(ORACLE_DIR))
load_dotenv(ORACLE_DIR / ".env")
load_dotenv(BASE_DIR / "lead_enrichment_engine" / ".env")

from src import database as db
from src.hook_generator import generate_hook

COMPANIES = ['Garner Health', 'LoopMe', 'Skydio', 'Ivo', 'Tebra', 'ElectronX', 'Whatnot', 'Hush',
             'Harvey', 'Thirty Madison', 'Aircall', 'BackOps AI']

PERSONA_PATTERNS = [
    r'\bchief revenue officer\b', r'\bcro\b', r'\bhead of revops\b', r'\bvp revops\b', r'\brevenue operations\b',
    r'\bchief customer officer\b', r'\bcco\b', r'\bhead of customer success\b', r'\bvp customer success\b',
    r'\bchief marketing officer\b', r'\bcmo\b',
    r'^ceo\b', r'\bceo\b(?!.{0,3}&.{0,3}co)', r'\bchief executive officer\b',
]

PRODUCT_CONTEXT = """
QuadSci — predictive revenue intelligence AI for B2B SaaS companies. Analyzes
product telemetry, CRM data, and customer engagement signals to forecast
churn and expansion 12 months ahead of renewal (94% accuracy claimed).
Founded 2023 by Dan Harmeson and Sean Murray (both ex-Elastic, ex-MuleSoft).
$10.1M raised, $8M Series A (Feb 2026, Crosslink Capital). Customers include
Clari, Reltio, Movable Ink, Boomi, Tenable. Named Machine Learning Company of
the Year, 2026 AI Breakthrough Awards. Pitch: eliminate surprise churn and
uncover growth by grounding customer intelligence in actual product usage,
not CRM notes or anecdote.
""".strip()

ICP_RESEARCH = """
Target: B2B SaaS companies, $20M-$500M ARR, Series C or later, subscription
or usage-based pricing, with a real product-usage telemetry layer. Buyers:
CRO, Head of RevOps/VP RevOps (primary); CCO/Head of Customer Success, CMO
(secondary). These companies typically already run product analytics or CS
tooling (Gainsight, Pendo, Mixpanel, Clari) and are under investor pressure
to prove efficient growth and protect net revenue retention — not just grow
top-line. A recent funding round, a new CRO/CCO hire, or active RevOps/CS
hiring signals exactly this moment: fresh scrutiny on retention and
expansion economics.
""".strip()


def pick_contact(contacts: list) -> dict | None:
    for pat in PERSONA_PATTERNS:
        hit = next((ct for ct in contacts if re.search(pat, (ct.get('title') or '').lower())
                    and 'to ceo' not in (ct.get('title') or '').lower()
                    and 'partner to' not in (ct.get('title') or '').lower()
                    and 'assistant' not in (ct.get('title') or '').lower()), None)
        if hit:
            return hit
    return contacts[0] if contacts else None


def build_research_summary(trace: list) -> str:
    """Real, verifiable evidence only — the exact why-text + source_url from
    fired glassbox rules. This is what grounding_check anchors against."""
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
            cur.execute("SELECT trace FROM account_prospects WHERE company_id=%s AND campaign_id=4",
                        (company["id"],))
            row = cur.fetchone()
        trace = row["trace"] if row else []
        summary = build_research_summary(trace)

        company_research = {
            "name": name,
            "research": {"summary": summary},
        }
        contact_dict = {
            "first_name": contact.get("first_name", ""),
            "last_name": contact.get("last_name", ""),
            "title": contact.get("title", ""),
            "company": name,
            "email": contact.get("email", ""),
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
