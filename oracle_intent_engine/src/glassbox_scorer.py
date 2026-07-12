"""
glassbox_scorer.py
===================
Company-agnostic, evidence-source-agnostic rule scoring engine. Generalizes
the one-time InRule glassbox process (glassbox_rules.yaml + inrule_glassbox.json,
hand-run once, SEC-only, never committed as reusable code) into something any
account's run_glassbox.py can call repeatedly.

CORE PRINCIPLE — "build coverage where evidence exists, don't zero out the
rest": every rule condition is evaluated in one of three states, not two:
  fired      — evidence found, the condition is true
  not_fired  — the evidence source was checked, condition is false
  no_evidence — the evidence source doesn't cover this company (e.g. no SEC
                filings for a private company) — NOT the same as "false".

`no_evidence` rules are excluded from both the score and the "of N"
denominator, so a company is never penalized for an evidence gap rather than
a real lack of fit. See build_evidence() callers in run_glassbox.py for how
each condition's evidence dict gets built per company.

Usage:
    from src.glassbox_scorer import score_company

    trace = score_company(rules, evidence)
    # rules:    [{"id": "R1", "condition": "category_language", "weight": 10,
    #             "decay_days": 1460 (optional)}, ...]
    # evidence: {"category_language": {"fired": True, "why": "...",
    #                                   "source_url": "...", "date": "2026-01-01"},
    #            "displacement": {"fired": False},
    #            # "industry_fit" key absent entirely -> no_evidence
    #            }
"""

from __future__ import annotations

from datetime import datetime, date

# Tiers are a percentage of evaluable_weight (what could actually be
# checked), not raw total weight — so partial evidence coverage doesn't
# mechanically cap a company's tier just because fewer rules applied to it.
_TIER_THRESHOLDS = [
    (0.60, "TIER 1 — PRIORITY"),
    (0.40, "TIER 2 — QUALIFIED"),
    (0.20, "TIER 3 — MONITOR"),
]
_TIER_DEFAULT = "TIER 4 — UNSCORED"
_TIER_INSUFFICIENT = "TIER 4 — INSUFFICIENT EVIDENCE"

# Below this many evaluable rules, a company can't be trusted to TIER 1/2/3
# even with a high score — one lucky match on a thinly-covered company
# shouldn't outrank a company with broad, real evidence coverage.
_MIN_EVALUABLE_RULES = 2


def _parse_evidence_date(evidence_date: str) -> date | None:
    """Evidence dates arrive in whatever format their source uses — ISO from
    the DB (oracle_signals.detected_at), RFC 822 from RSS feeds (news
    corroboration hits, e.g. "Tue, 30 Jun 2020 07:00:00 GMT"). Silently
    failing to parse and falling back to "full weight" is the wrong default
    for a decay function — it means a genuinely 6-year-old funding
    announcement gets scored as if it happened today. Try both formats
    explicitly rather than swallowing the mismatch."""
    try:
        return datetime.fromisoformat(evidence_date.replace("Z", "+00:00")).date()
    except Exception:
        pass
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(evidence_date).date()
    except Exception:
        return None


def _decayed_weight(weight: float, decay_days: int | None, evidence_date: str | None) -> float:
    """Linear decay: a rule's weight fades to 0 over decay_days from its
    evidence date. No decay_days or no date on the evidence -> full weight.
    An unparseable date is NOT treated as "no date" — that would silently
    grant full weight to evidence whose age we simply failed to read."""
    if not decay_days or not evidence_date:
        return weight
    d = _parse_evidence_date(evidence_date)
    if d is None:
        return 0.0  # can't verify recency -> don't credit it as fresh
    days_since = (date.today() - d).days
    if days_since <= 0:
        return weight
    return max(0.0, weight * (1 - days_since / decay_days))


def score_company(rules: list[dict], evidence: dict) -> dict:
    """Evaluate one company's evidence against a rule config. Returns the
    same shape inrule_glassbox.json used per-company (name is NOT included
    here — callers attach company_id/name), so existing trace-rendering UI
    patterns carry over unchanged."""
    trace: list[dict] = []
    total = 0.0
    evaluable_weight = 0.0
    evaluable_count = 0

    for rule in rules:
        rid = rule["id"]
        condition = rule["condition"]
        weight = rule["weight"]
        decay_days = rule.get("decay_days")
        ev = evidence.get(condition)

        if ev is None:
            trace.append({
                "id": rid, "condition": condition, "state": "no_evidence",
                "points": 0,
            })
            continue

        evaluable_weight += weight
        evaluable_count += 1

        if ev.get("fired"):
            points = round(_decayed_weight(weight, decay_days, ev.get("date")), 2)
            total += points
            trace_item = {
                "id": rid, "condition": condition, "state": "fired",
                "points": points, "why": ev.get("why", ""),
                "source_url": ev.get("source_url", ""),
            }
            if ev.get("events"):
                trace_item["events"] = ev["events"]
            trace.append(trace_item)
        else:
            trace.append({
                "id": rid, "condition": condition, "state": "not_fired",
                "points": 0,
            })

    if evaluable_count < _MIN_EVALUABLE_RULES:
        tier = _TIER_INSUFFICIENT
    else:
        pct = (total / evaluable_weight) if evaluable_weight > 0 else 0.0
        tier = next((label for threshold, label in _TIER_THRESHOLDS if pct >= threshold), _TIER_DEFAULT)

    fired_count = sum(1 for t in trace if t["state"] == "fired")
    return {
        "total": round(total, 2),
        "of": evaluable_count,
        "fired": fired_count,
        "evaluable_weight": round(evaluable_weight, 2),
        "tier": tier,
        "trace": trace,
    }
