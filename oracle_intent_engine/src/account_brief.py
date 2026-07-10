"""
account_brief.py
=================
Builds a read-only, on-demand summary for one company: phase trajectory,
current priority score + delta since the last scan, top evidence signals,
contact coverage, and staleness — plus an optional one-line LLM narrative.

Inspired by the account-brief pattern in Profound's "Prophet" tool: instead
of browsing raw signal/contact tables, surface what changed and why it
matters. No new tables or persisted state — built entirely from
oracle_signals (which accumulate across scan runs) and company_contacts,
read fresh on every call.
"""

import logging
from datetime import datetime

from src import database as db
from src import lead_scorer

logger = logging.getLogger(__name__)


def _company_summary(company: dict, signals: list) -> dict:
    """Build the dict shape lead_scorer.calculate_priority_score() expects."""
    sources = sorted({s["source"] for s in signals if s.get("source")})
    confidences = [s["confidence"] for s in signals if s.get("confidence") is not None]
    return {
        "phase": signals[0]["phase"] if signals else None,
        "sources": sources,
        "signal_count": len(signals),
        "confidence": max(confidences) if confidences else 0,
        "industry": company.get("industry"),
        "size": company.get("size"),
    }


def _phase_trajectory(signals: list) -> list:
    """Chronological, deduplicated phase progression from signal history."""
    ordered = sorted(
        (s for s in signals if s.get("phase") and s.get("detected_at")),
        key=lambda s: s["detected_at"],
    )
    trajectory = []
    for s in ordered:
        if not trajectory or trajectory[-1]["phase"] != s["phase"]:
            trajectory.append({"phase": s["phase"], "first_seen": s["detected_at"]})
    return trajectory


def _narrative(company: dict, trajectory: list, score: int, delta: int, top_signal: dict | None) -> str | None:
    """One-line LLM summary. Degrades to None (never raises) if the gateway
    is unavailable or returns something unparseable — the rest of the brief
    is still useful without it."""
    from src import llm_gateway

    if not llm_gateway.is_available():
        return None

    phase_path = " -> ".join(t["phase"] for t in trajectory) or "no phase data yet"
    prompt = (
        f"Company: {company.get('name')}\n"
        f"Phase trajectory: {phase_path}\n"
        f"Current priority score: {score}/100 (change since last scan: {delta:+d})\n"
        f"Top signal: {(top_signal or {}).get('evidence') or 'none on file'}\n\n"
        "Write one plain-English sentence (max 25 words) summarizing what "
        "changed for this account and why it matters to a sales rep. "
        "No preamble, no markdown."
    )
    try:
        parsed = llm_gateway.complete_json(
            prompt,
            system=(
                "You write terse, factual one-sentence account summaries for B2B "
                'sales reps. Return JSON: {"narrative": "..."}.'
            ),
            task="copy",
            max_tokens=150,
        )
        if not parsed:
            return None
        return (parsed.get("narrative") or "").strip() or None
    except Exception:
        logger.exception("[AccountBrief] narrative generation failed for company_id=%s", company.get("id"))
        return None


def build_brief(company_id: int) -> dict | None:
    company = db.get_company_by_id(company_id)
    if not company:
        return None
    company = dict(company)

    signals = [dict(s) for s in db.get_signals_for_company(company_id)]
    contacts = [dict(c) for c in db.get_contacts_for_company(company_id)]

    trajectory = _phase_trajectory(signals)

    current_score = lead_scorer.calculate_priority_score(_company_summary(company, signals))

    # Score before the most recent scan run — the delta isolates what the
    # latest scan actually changed, without needing a persisted score history.
    run_ids = [s["scan_run_id"] for s in signals if s.get("scan_run_id") is not None]
    latest_run_id = max(run_ids) if run_ids else None
    prior_signals = (
        [s for s in signals if s.get("scan_run_id") != latest_run_id]
        if latest_run_id is not None else []
    )
    prior_score = (
        lead_scorer.calculate_priority_score(_company_summary(company, prior_signals))
        if prior_signals else current_score
    )
    score_delta = current_score - prior_score

    key_signals = sorted(
        (s for s in signals if s.get("confidence") is not None),
        key=lambda s: s["confidence"],
        reverse=True,
    )[:3]

    staleness_days = None
    detected_ats = [s["detected_at"] for s in signals if s.get("detected_at")]
    if detected_ats:
        staleness_days = (datetime.now() - max(detected_ats)).days

    narrative = _narrative(
        company, trajectory, current_score, score_delta,
        key_signals[0] if key_signals else None,
    )

    return {
        "company": {"id": company["id"], "name": company["name"], "domain": company.get("domain")},
        "narrative": narrative,
        "phase_trajectory": trajectory,
        "current_phase": trajectory[-1]["phase"] if trajectory else None,
        "priority_score": current_score,
        "priority_label": lead_scorer.get_priority_label(current_score),
        "score_delta": score_delta,
        "key_signals": [
            {
                "source": s.get("source"),
                "evidence": s.get("evidence"),
                "url": s.get("url"),
                "confidence": s.get("confidence"),
                "detected_at": s.get("detected_at"),
            }
            for s in key_signals
        ],
        "contact_coverage": {
            "total": len(contacts),
            "targets": len([c for c in contacts if c.get("is_target")]),
        },
        "staleness_days": staleness_days,
        "signal_count": len(signals),
    }
