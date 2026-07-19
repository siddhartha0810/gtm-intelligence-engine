"""
generate_quadsci_variants.py
============================
Runs the copy_lab framework bake-off for the QuadSci board's actionable
prospects: for each account's buyer, generate PAS / OIQ / Challenger variants,
score every one (deterministic gates + LLM judge), keep the winner, and
persist the whole set so the Emails tab can show the losers too.

The evidence handed to each variant is the account's own fired-rule text from
the scoring trace — the same data that scored it writes its email, and every
claim in the copy is therefore traceable to a citation.

Usage:
    .venv/bin/python generate_quadsci_variants.py            # TIER 2/3 board
    .venv/bin/python generate_quadsci_variants.py Cloudflare # one account
"""

import re
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent
ORACLE = BASE / "oracle_intent_engine"
sys.path.insert(0, str(ORACLE))
load_dotenv(ORACLE / ".env")
load_dotenv(BASE / "lead_enrichment_engine" / ".env")

from src import database as db          # noqa: E402
from src import copy_lab                # noqa: E402
import generate_quadsci_hooks as g      # noqa: E402  (reuse pick_contact + product/icp context)

CAMPAIGN_ID = 4

# Plain-language product context — deliberately NOT the marketing phrasing, so
# the model says it simply (the reading-level gate punishes jargon).
PRODUCT = ("QuadSci reads how a company's own customers actually use its "
           "product, and warns 9-18 months early which customers will grow, "
           "shrink, or leave — 90%+ accurate. It reads real product usage, "
           "not CRM notes or guesswork.")


def evidence_for(prospect: dict) -> str:
    fired = [t for t in (prospect.get("trace") or []) if t.get("state") == "fired"]
    return " ".join((t.get("why") or "").strip() for t in fired if t.get("why"))


def main() -> None:
    db.init_db()
    only = sys.argv[1] if len(sys.argv) > 1 else None

    prospects = [p for p in db.get_account_prospects(CAMPAIGN_ID)
                 if "DISQUALIFIED" not in (p.get("tier") or "")
                 and ("TIER 2" in p["tier"] or "TIER 3" in p["tier"])]
    if only:
        prospects = [p for p in prospects if p["company_name"].lower() == only.lower()]

    print(f"Running framework bake-off for {len(prospects)} prospects...\n")
    for p in prospects:
        name = p["company_name"]
        ev = evidence_for(p)
        if not ev:
            print(f"[skip] {name}: no fired-rule evidence")
            continue
        contacts = [dict(c) for c in db.get_contacts_for_company(p["company_id"])]
        contact = g.pick_contact(contacts)
        if not contact:
            print(f"[skip] {name}: no buyer on file")
            continue

        c = {"first_name": contact.get("first_name", ""), "last_name": contact.get("last_name", ""),
             "title": contact.get("title", ""), "company": name}
        variants = copy_lab.generate_variants(c, ev, PRODUCT)
        db.save_copy_variants(name, f"{c['first_name']} {c['last_name']}".strip(),
                              c["title"], variants)
        win = variants[0]
        print(f"=== {name} → {c['first_name']} {c['last_name']} ({c['title'][:34]})")
        for v in variants:
            flag = "  ★ WINNER" if v is win else ""
            print(f"   [{v['framework']:<10}] total={v['total_score']:>3}  "
                  f"mech={v['mechanical_score']}/60  judge={v['judge'].get('judge_score',0)}/40  "
                  f"FK={v['fk_grade']} w={v['word_count']}{flag}")
        print(f"   WINNER copy: {win['subject']} — {win['body']}\n")

    print("Done. Variants persisted to copy_variants; the Emails tab shows the bake-off.")


if __name__ == "__main__":
    main()
