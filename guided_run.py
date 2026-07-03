#!/usr/bin/env python3
"""
guided_run.py
=============
A clean, real, $0 end-to-end run of the GTM engine against LIVE targets.

Uses the ATS signal — companies' own public job-board JSON (Greenhouse / Lever /
Ashby / SmartRecruiters). ~0% block rate, no keys, no cost, ToS-clean, and the
data is first-party truth: a company hiring a "Salesforce Administrator" is a
confirmed Salesforce operator.

The run walks the pipeline for real:
  DISCOVER  → pull open roles from live ATS boards
  QUALIFY   → title-level intent match + staffing filter, group by company
  RESEARCH  → build grounded context from the company's own posting text
  PERSONA   → infer the economic buyer for the system they operate
  DRAFT     → generate a grounded cold-email hook via the LLM gateway
  REPORT    → write guided_run_output.md with the full funnel + sample hooks

Enrichment (real decision-maker emails via Apollo) is the one paid step and is
intentionally left out — the run shows exactly where it plugs in.

Edit TARGET below, then:  python guided_run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).parent
ORACLE = BASE / "oracle_intent_engine"
if str(ORACLE) not in sys.path:
    sys.path.insert(0, str(ORACLE))

# ── TARGET — edit this block for your own ICP ─────────────────────────────────
TARGET = {
    "icp": "Mid-market & enterprise companies operating Salesforce, NetSuite, or "
           "Workday — targets for a managed-services / systems-consulting offer.",
    "intent_keywords": ["Salesforce", "NetSuite", "Workday", "SAP"],
    "product_pitch": (
        "We're a systems-integration partner that helps companies get more out of "
        "their Salesforce / NetSuite / Workday investment — cleanup, automation, "
        "and admin capacity without a full-time hire."
    ),
    # Live boards to scan (ats:token). Mix of platforms so coverage survives 404s.
    "boards": [
        {"ats": "greenhouse", "token": "stripe"},
        {"ats": "greenhouse", "token": "databricks"},
        {"ats": "greenhouse", "token": "gitlab"},
        {"ats": "greenhouse", "token": "figma"},
        {"ats": "greenhouse", "token": "anthropic"},
        {"ats": "ashby", "token": "openai"},
        {"ats": "ashby", "token": "Ramp"},
        {"ats": "ashby", "token": "Notion"},
        {"ats": "lever", "token": "mistral"},
        {"ats": "lever", "token": "spotify"},
    ],
    "max_hooks": 6,   # cap LLM calls — detection is free, drafting costs a little
}

# Economic buyer for each system (who owns the budget / feels the pain)
_BUYER_PERSONA = {
    "salesforce": "VP of Revenue Operations",
    "netsuite":   "VP of Finance",
    "workday":    "VP of People Operations",
    "sap":        "ERP Director",
}
_DEFAULT_PERSONA = "VP of Operations"


def _persona_for(matched_keyword: str) -> str:
    return _BUYER_PERSONA.get((matched_keyword or "").lower(), _DEFAULT_PERSONA)


def main() -> None:
    from src import config, guards, llm_gateway
    from src.signals.ats_signal import ATSSignal
    from src import staffing_filter
    from src.hook_generator import generate_hook

    # Make the runner's boards the active registry for this process
    config.ATS_BOARDS = TARGET["boards"]

    print("=" * 70)
    print("GUIDED RUN — real targets, $0, first-party ATS intent")
    print("=" * 70)
    print(f"ICP: {TARGET['icp']}")
    print(f"Intent keywords: {', '.join(TARGET['intent_keywords'])}")
    print(f"Boards: {len(TARGET['boards'])}")
    print(f"LLM providers available: {llm_gateway.active_providers() or '(none — hooks will be skipped)'}")
    print()

    # ── DISCOVER + QUALIFY (title-level intent) ───────────────────────────────
    print("[1/4] DISCOVER — pulling live open roles from ATS boards…")
    signals = ATSSignal().fetch(keywords=TARGET["intent_keywords"], max_pages=len(TARGET["boards"]))
    print(f"      {len(signals)} title-level intent signals detected")

    # ── STAFFING FILTER (house rule — never bypass) ───────────────────────────
    kept, removed = staffing_filter.filter_signals(signals)
    print(f"[2/4] QUALIFY — staffing filter removed {removed}; {len(kept)} real end-user signals")

    # Group by company — one lead per company, keep its strongest evidence
    leads: dict[str, dict] = {}
    for s in kept:
        co = s.get("company_name", "")
        if not co:
            continue
        leads.setdefault(co, {
            "company": co,
            "signals": [],
        })["signals"].append(s)
    print(f"      {len(leads)} unique in-market companies")
    print()

    # ── RESEARCH + PERSONA + DRAFT ────────────────────────────────────────────
    print(f"[3/4] DRAFT — generating grounded hooks for up to {TARGET['max_hooks']} companies…")
    drafted = []
    can_draft = llm_gateway.is_available()
    for co, lead in list(leads.items())[: TARGET["max_hooks"]] if can_draft else []:
        primary = lead["signals"][0]
        matched = primary.get("matched_keyword", "")
        evidence = primary.get("evidence") or primary.get("description", "")[:300]

        company_research = {
            "name": co,
            "one_liner": f"{co} is hiring for a {primary.get('job_title','role')} — operates {matched}.",
            "research": {"summary": (
                f"{co} is actively hiring a {primary.get('job_title','')}. "
                f"Observed signal from their own careers page: {evidence}"
            )},
        }
        contact = {
            "first_name": "there",
            "title": _persona_for(matched),
            "company": co,
            "email": "",   # ← enrichment (Apollo) fills this in a real send
            "linkedin_url": "",
        }
        hook = generate_hook(contact, company_research, product_context=TARGET["product_pitch"])
        drafted.append({"company": co, "matched": matched,
                        "signal": primary.get("job_title", ""),
                        "url": primary.get("url", ""), "evidence": evidence,
                        "persona": contact["title"], "hook": hook})
        status = "grounded" if hook.get("grounded") else ("ok" if hook.get("ok") else "failed")
        print(f"      • {co:14} [{status}] {hook.get('subject','')[:50]}")

    if not can_draft:
        print("      (no LLM provider — set GROQ/GEMINI/ANTHROPIC key to draft hooks)")
    print()

    # ── REPORT ────────────────────────────────────────────────────────────────
    print("[4/4] REPORT — writing guided_run_output.md")
    _write_report(leads, drafted)
    print()
    print("FUNNEL:")
    print(f"  boards scanned        {len(TARGET['boards'])}")
    print(f"  intent signals        {len(signals)}")
    print(f"  after staffing filter {len(kept)}")
    print(f"  in-market companies   {len(leads)}")
    print(f"  grounded hooks        {sum(1 for d in drafted if d['hook'].get('grounded'))}/{len(drafted)}")
    print("=" * 70)
    print("Artifact: guided_run_output.md — real companies, real evidence, real copy.")


def _write_report(leads: dict, drafted: list) -> None:
    lines = ["# Guided Run — Real GTM Output", ""]
    lines.append(f"**ICP:** {TARGET['icp']}")
    lines.append("")
    lines.append(f"**Funnel:** {len(TARGET['boards'])} boards → "
                 f"{len(leads)} in-market companies → "
                 f"{sum(1 for d in drafted if d['hook'].get('grounded'))} grounded hooks")
    lines.append("")
    lines.append("Every company below was detected from its OWN public job board — "
                 "first-party proof it operates the target system. Evidence quotes "
                 "are verbatim from the source.")
    lines.append("")

    lines.append("## In-market companies detected")
    lines.append("")
    lines.append("| Company | Operates | Hiring signal |")
    lines.append("|---|---|---|")
    for co, lead in leads.items():
        s = lead["signals"][0]
        lines.append(f"| {co} | {s.get('matched_keyword','')} | {s.get('job_title','')} |")
    lines.append("")

    if drafted:
        lines.append("## Sample grounded outreach")
        lines.append("")
        for d in drafted:
            h = d["hook"]
            lines.append(f"### {d['company']} — {d['persona']}")
            lines.append(f"- **Signal:** hiring *{d['signal']}* (operates {d['matched']})")
            lines.append(f"- **Evidence:** {d['evidence'][:200]}")
            lines.append(f"- **Source:** {d['url']}")
            if h.get("ok"):
                lines.append(f"- **Subject:** {h.get('subject','')}")
                lines.append(f"- **Body:** {h.get('body','')}")
                lines.append(f"- **Grounded on:** `{h.get('grounded_on','')}`  ·  Angle: {h.get('angle','')}")
            else:
                lines.append(f"- _hook failed: {h.get('error','')}_")
            lines.append("")

    (BASE / "guided_run_output.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
