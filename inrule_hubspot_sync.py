"""
inrule_hubspot_sync.py
=======================
HubSpot sync layer for the InRule prospecting agent.

Takes the scored prospect list from run_inrule_agent.py and:
  1. Pushes each company to HubSpot with InRule-specific custom properties
     (intent_score, signal_tier, why_now_reason, inrule_signal_source)
  2. Pushes enriched contacts and associates them with their company
  3. Generates a grounded cold email hook for each Tier 1 + Tier 2 contact
     using the existing hook_generator.py (Claude Haiku, PAS framework)
  4. Writes the hook into the contact's HubSpot record as a note

This module is standalone — it reads a scored CSV from run_inrule_agent.py
and pushes to HubSpot. It does NOT require the PostgreSQL database.

Usage:
    python inrule_hubspot_sync.py --input inrule_prospects_20260724.csv
    python inrule_hubspot_sync.py --input inrule_prospects_20260724.csv --dry-run
    python inrule_hubspot_sync.py --input inrule_prospects_20260724.csv --hooks-only

Flags:
    --input FILE      Path to the CSV from run_inrule_agent.py (required)
    --dry-run         Print what would be pushed without actually calling HubSpot
    --hooks-only      Generate hooks and print them without pushing to HubSpot
    --min-tier N      Only process accounts at tier N or better (1/2/3, default: 2)
    --no-hooks        Skip hook generation (push contacts only)
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
ORACLE_DIR = BASE_DIR / "intent_engine"
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

from dotenv import load_dotenv
load_dotenv(ORACLE_DIR / ".env")

# ---------------------------------------------------------------------------
# InRule product context for hook generation
# ---------------------------------------------------------------------------

INRULE_PRODUCT_CONTEXT = """
InRule Technology — business rules management and decision automation platform.

Key capabilities:
- irAuthor: a low-code / no-code rules authoring environment where business
  analysts (not developers) write, test, and deploy decision logic
- irServer: runtime execution engine — rules run in-process, as a service,
  or in the cloud
- irVerify: automated rule testing and validation
- Cloud-native deployment: Azure, AWS, on-premise, or hybrid

Why buyers choose InRule over competitors:
1. Business users own the rules — no IT ticket required to change a decision
2. Full audit trail — every rule change is versioned, traceable, and citable
   (critical for regulated industries: OCC examiners, CMS auditors, state
   insurance regulators accept InRule's audit logs as compliance evidence)
3. Faster than FICO Blaze: no proprietary rule language to learn; standard
   .NET / Java integration
4. Cheaper than IBM ODM: no per-CPU licensing; predictable SaaS pricing
5. More business-friendly than Drools: visual authoring, not XML/DRL

Target buyers:
- IT Architects and Software Engineers who own the integration
- Business Analysts who will author the rules
- VP Technology / CTO / CIO who approve the budget
- Compliance Officers who need the audit trail
"""

INRULE_ICP_RESEARCH = """
InRule's ICP is concentrated in regulated industries where decision logic
must be documented, auditable, and changeable without a development cycle:

INSURANCE:
- Claims adjusters manually reviewing eligibility rules that change quarterly
- Underwriting teams whose pricing logic lives in spreadsheets or hardcoded
  Java — a compliance examiner's nightmare
- Policy administration systems that require IT involvement for every rule change
- Pain: "We had to file a regulatory change and it took 6 weeks to get IT to
  update the rules. We missed the deadline."

BANKING:
- Loan origination systems where credit policy changes require dev sprints
- BSA/AML compliance teams who need to document every decision and why it
  was made — OCC examiners ask for this
- Mortgage underwriting automation — CFPB requires documented, consistent
  decisioning logic
- Pain: "After our consent order, the OCC examiner wanted to see the exact
  rule that approved each loan. We couldn't produce it."

HEALTHCARE:
- Prior authorization rules that change with every payer contract update
- Eligibility determination for government programs (Medicaid, Medicare)
  where CMS requires documented, auditable logic
- Claims adjudication — the difference between a paid and denied claim is
  a rule; that rule needs to be traceable
- Pain: "We have 400 payer contracts, each with different rules. We can't
  keep up with the changes manually."

GOVERNMENT:
- Benefits eligibility determination (SNAP, Medicaid, housing assistance)
  where federal regulations require consistent, documented decisions
- Tax assessment rules that must be auditable for appeals
- Pain: "We got sued over an eligibility denial. We couldn't produce the
  exact rule that was applied. We settled."

COMPETITOR DISPLACEMENT CONTEXT:
- FICO Blaze: expensive, proprietary rule language (RETE), difficult to
  onboard business users, licensing tied to CPU count
- Corticon: strong in financial services but complex deployment model;
  Progress Software acquisition created uncertainty
- IBM ODM: enterprise-grade but requires IBM middleware stack; slow to
  deploy; expensive professional services
- Drools: open-source but requires Java developers to write DRL; no
  business-user authoring; no commercial support
"""


# ---------------------------------------------------------------------------
# Tier mapping
# ---------------------------------------------------------------------------

_TIER_TO_SIGNAL_TIER = {
    "TIER 1 — PRIORITY": "P0",
    "TIER 2 — QUALIFIED": "P1",
    "TIER 3 — MONITOR": "P2",
}

_TIER_TO_ROUTING = {
    "TIER 1 — PRIORITY": "ACTIVATE",
    "TIER 2 — QUALIFIED": "ACTIVATE",
    "TIER 3 — MONITOR": "NURTURE",
}

_TIER_FILTER = {
    1: {"TIER 1 — PRIORITY"},
    2: {"TIER 1 — PRIORITY", "TIER 2 — QUALIFIED"},
    3: {"TIER 1 — PRIORITY", "TIER 2 — QUALIFIED", "TIER 3 — MONITOR"},
}


# ---------------------------------------------------------------------------
# Hook generation (InRule-specific)
# ---------------------------------------------------------------------------

def _generate_inrule_hook(
    contact_name: str,
    contact_title: str,
    company_name: str,
    evidence_summary: str,
    top_signal_label: str,
    tier: str,
    dry_run: bool = False,
) -> dict:
    """
    Generate a grounded cold email hook for an InRule prospect.
    Uses the existing hook_generator.py (Claude Haiku, PAS framework).
    Falls back to a template-based hook if the LLM is unavailable.
    """
    if dry_run:
        return {
            "subject": f"[DRY RUN] Hook for {company_name}",
            "body": f"[DRY RUN] Hook for {contact_name} at {company_name} — {tier}",
            "angle": "Time",
            "word_count": 0,
        }

    try:
        from src.hook_generator import generate_hook

        first_name = contact_name.split()[0] if contact_name else "there"
        contact = {
            "first_name": first_name,
            "title": contact_title,
            "company": company_name,
        }
        company_research = {
            "name": company_name,
            "research": {
                "summary": (
                    f"Signal evidence: {evidence_summary[:300]}. "
                    f"Top signal: {top_signal_label[:200]}."
                )
            },
        }
        hook = generate_hook(contact, company_research, INRULE_PRODUCT_CONTEXT)
        return hook

    except Exception as e:
        # Fallback: template-based hook based on tier and top signal
        return _template_hook(contact_name, company_name, top_signal_label, tier)


def _template_hook(
    contact_name: str,
    company_name: str,
    top_signal: str,
    tier: str,
) -> dict:
    """
    Template-based hook fallback when LLM is unavailable.
    Selects angle based on the top signal type.
    """
    first = contact_name.split()[0] if contact_name else "there"

    if "OCC" in top_signal or "enforcement" in top_signal.lower() or "consent order" in top_signal.lower():
        subject = "decision logic after the consent order"
        body = (
            f"{first}, after a consent order the OCC examiner's first question is "
            "'show me the exact rule that approved this decision' — most banks "
            "can't produce it without a dev sprint."
        )
        angle = "Risk"
    elif "contract expir" in top_signal.lower() or "USASpending" in top_signal:
        subject = "before the RFP drops"
        body = (
            f"{first}, your current rules platform contract is coming up for renewal — "
            "most teams wait until the RFP to evaluate alternatives, by which time "
            "the incumbent has already locked in the renewal."
        )
        angle = "Time"
    elif "FICO Blaze" in top_signal or "Blaze Advisor" in top_signal:
        subject = "FICO Blaze — the three complaints"
        body = (
            f"{first}, every team we talk to on Blaze tells us the same three things: "
            "the rule language takes months to onboard, business users can't author "
            "without IT, and the CPU licensing math never works out."
        )
        angle = "Effort"
    elif "Corticon" in top_signal:
        subject = "Corticon — what's changed"
        body = (
            f"{first}, since the Progress acquisition most Corticon teams we talk to "
            "are quietly evaluating alternatives — the deployment model and roadmap "
            "uncertainty are the two things that come up most."
        )
        angle = "Risk"
    elif "IBM ODM" in top_signal or "IBM Operational Decision" in top_signal:
        subject = "IBM ODM — the middleware tax"
        body = (
            f"{first}, the teams that move off IBM ODM tell us the same thing: "
            "it wasn't the rules engine that was painful, it was everything around it — "
            "the middleware stack, the professional services, the upgrade cycles."
        )
        angle = "Cost"
    elif "Drools" in top_signal:
        subject = "Drools — when the developer leaves"
        body = (
            f"{first}, Drools works fine until the one developer who understands DRL "
            "leaves — then every rule change becomes a project."
        )
        angle = "Risk"
    else:
        subject = "decision automation — the compliance angle"
        body = (
            f"{first}, most teams in regulated industries tell us the same thing: "
            "the rules work fine until the auditor asks to see them, "
            "and then it's a three-week scramble."
        )
        angle = "Risk"

    return {
        "subject": subject,
        "body": body,
        "angle": angle,
        "word_count": len(body.split()),
    }


# ---------------------------------------------------------------------------
# HubSpot push (wraps existing hubspot_push.py)
# ---------------------------------------------------------------------------

async def push_prospect_to_hubspot(
    row: dict,
    dry_run: bool = False,
) -> dict:
    """
    Push one scored prospect (company + contact) to HubSpot.
    Returns {"company_result": ..., "contact_result": ..., "hook": ...}
    """
    from src.hubspot_push import push_company_to_hubspot, push_contact_to_hubspot

    tier = row.get("Tier", "")
    signal_tier = _TIER_TO_SIGNAL_TIER.get(tier, "P2")
    routing = _TIER_TO_ROUTING.get(tier, "NURTURE")

    # Build company record
    company_record = {
        "name": row.get("Company", ""),
        "signal_tier": signal_tier,
        "intent_score": _score_to_float(row.get("Score", "")),
        "why_now_reason": _build_why_now(row),
        "routing": routing,
        "campaign_name": "InRule GTM Prospecting Agent",
        # Custom InRule fields
        "detected_products": "InRule",
        "target_product": "InRule irAuthor",
        "vendor_relationship_type": "prospect",
    }

    # Build contact record
    contact_name = row.get("Contact_Name", "")
    contact_email = row.get("Contact_Email", "")
    contact_title = row.get("Contact_Title", "")
    contact_linkedin = row.get("Contact_LinkedIn", "")

    contact_record = {
        "first_name": contact_name.split()[0] if contact_name else "",
        "last_name": " ".join(contact_name.split()[1:]) if contact_name and len(contact_name.split()) > 1 else "",
        "email": contact_email,
        "title": contact_title,
        "linkedin_url": contact_linkedin,
        "company_name": row.get("Company", ""),
        "signal_tier": signal_tier,
        "product_alignment": "InRule irAuthor",
        "ready_for_outreach": "true" if contact_email else "false",
    }

    if dry_run:
        print(f"  [DRY RUN] Would push company: {company_record['name']} ({signal_tier})")
        if contact_email:
            print(f"  [DRY RUN] Would push contact: {contact_name} <{contact_email}>")
        return {
            "company_result": {"ok": True, "action": "dry_run"},
            "contact_result": {"ok": True, "action": "dry_run"},
        }

    company_result = await push_company_to_hubspot(company_record)
    contact_result = {"ok": False, "action": "skipped"}

    if contact_email:
        contact_result = await push_contact_to_hubspot(contact_record)

    return {
        "company_result": company_result,
        "contact_result": contact_result,
    }


def _score_to_float(score_str: str) -> float:
    """Convert '18.5/40.0' to 0.46 (normalized 0-1)."""
    try:
        parts = score_str.split("/")
        if len(parts) == 2:
            return round(float(parts[0]) / float(parts[1]), 3)
    except Exception:
        pass
    return 0.0


def _build_why_now(row: dict) -> str:
    """Build a one-sentence why-now reason from the CSV row."""
    tier = row.get("Tier", "")
    top_signal = row.get("Top_Signal_Label", "")
    sources = row.get("All_Sources", "")

    if "OCC" in sources or "occ_enforcement" in sources:
        return (
            f"OCC enforcement action — mandatory technology remediation window. "
            f"Signal: {top_signal[:100]}"
        )
    if "usaspending" in sources:
        return (
            f"Federal competitor contract expiring — active procurement window. "
            f"Signal: {top_signal[:100]}"
        )
    if "linkedin" in sources:
        return (
            f"Actively hiring for competitor tool — budget confirmed, category defined. "
            f"Signal: {top_signal[:100]}"
        )
    if "sec_filing" in sources:
        return (
            f"SEC filing uses decision automation language — first-party buying intent. "
            f"Signal: {top_signal[:100]}"
        )
    return f"{tier} prospect — {top_signal[:150]}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _run(args):
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[inrule_hubspot_sync] ERROR: Input file not found: {input_path}")
        sys.exit(1)

    min_tier_set = _TIER_FILTER.get(args.min_tier, _TIER_FILTER[2])

    with open(input_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    filtered = [r for r in rows if r.get("Tier", "") in min_tier_set]
    print(f"\n[inrule_hubspot_sync] {len(filtered)} prospects at min_tier={args.min_tier} "
          f"(from {len(rows)} total in CSV)\n")

    pushed_companies = 0
    pushed_contacts = 0
    hooks_generated = 0
    errors = []

    for i, row in enumerate(filtered):
        company = row.get("Company", "")
        tier = row.get("Tier", "")
        contact_name = row.get("Contact_Name", "")
        contact_title = row.get("Contact_Title", "")
        contact_email = row.get("Contact_Email", "")
        evidence_summary = row.get("Evidence_Summary", "")
        top_signal = row.get("Top_Signal_Label", "")

        print(f"[{i+1}/{len(filtered)}] {company} — {tier}")

        # Generate hook
        hook = None
        if not args.no_hooks and contact_name:
            hook = _generate_inrule_hook(
                contact_name=contact_name,
                contact_title=contact_title,
                company_name=company,
                evidence_summary=evidence_summary,
                top_signal_label=top_signal,
                tier=tier,
                dry_run=args.dry_run,
            )
            hooks_generated += 1
            print(f"  Hook ({hook.get('angle', '?')}): {hook.get('subject', '')}")
            print(f"  Body: {hook.get('body', '')[:120]}...")

        if args.hooks_only:
            continue

        # Push to HubSpot
        try:
            result = await push_prospect_to_hubspot(row, dry_run=args.dry_run)
            if result["company_result"].get("ok"):
                pushed_companies += 1
            else:
                errors.append(f"{company}: {result['company_result'].get('error', 'unknown')}")

            if result["contact_result"].get("ok") and contact_email:
                pushed_contacts += 1

        except Exception as e:
            errors.append(f"{company}: {e}")
            print(f"  ERROR: {e}")

        if not args.dry_run:
            time.sleep(0.5)  # HubSpot rate limit courtesy

    print(f"\n{'='*60}")
    print(f"  InRule HubSpot Sync — Complete")
    print(f"{'='*60}")
    print(f"  Prospects processed: {len(filtered)}")
    print(f"  Companies pushed:    {pushed_companies}")
    print(f"  Contacts pushed:     {pushed_contacts}")
    print(f"  Hooks generated:     {hooks_generated}")
    if errors:
        print(f"  Errors ({len(errors)}):")
        for e in errors[:5]:
            print(f"    - {e}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="InRule HubSpot Sync — push scored prospects to HubSpot"
    )
    parser.add_argument("--input", required=True,
                        help="Path to the CSV from run_inrule_agent.py")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be pushed without calling HubSpot")
    parser.add_argument("--hooks-only", action="store_true",
                        help="Generate and print hooks without pushing to HubSpot")
    parser.add_argument("--no-hooks", action="store_true",
                        help="Skip hook generation")
    parser.add_argument("--min-tier", type=int, default=2,
                        help="Only process accounts at this tier or better (1/2/3, default: 2)")
    args = parser.parse_args()

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
