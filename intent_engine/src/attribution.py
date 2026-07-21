"""
attribution.py
==============
Pure rollup math for the learning loop — turns raw (outcome, signal) rows from
the DB into per-dimension conversion rates. No DB, no LLM, fully testable.

Given every outreach outcome tied to the signals that surfaced its company,
this answers: which signal_type / product / phase / source actually converts?
"contacted" is neutral; "replied" and "meeting" are positive (meeting weighs
highest); "bounced"/"bad"/"unsubscribed" are negative.

The Analyst view and the Recalibrator agent both consume rollup_attribution().
"""

from __future__ import annotations

POSITIVE = {"replied", "meeting"}
NEGATIVE = {"bounced", "bad", "unsubscribed"}
_DIMENSIONS = {
    "by_signal_type":  "signal_type",
    "by_product":      "detected_product",
    "by_phase":        "phase",
    "by_source":       "source",
}


def _rollup_one(rows: list[dict], field: str) -> list[dict]:
    """Group by one dimension, dedup per (outcome_id, value) so a company with
    two 'ats' signals doesn't double-count one outcome. Rates per distinct
    outcome that touched that dimension value."""
    seen: set[tuple] = set()
    buckets: dict[str, dict] = {}
    for r in rows:
        value = (r.get(field) or "").strip()
        if not value:
            continue
        oid = r.get("outcome_id")
        dedup_key = (oid, value)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        b = buckets.setdefault(value, {"total": 0, "positive": 0, "meetings": 0, "negative": 0})
        b["total"] += 1
        oc = r.get("outcome")
        if oc in POSITIVE:
            b["positive"] += 1
        if oc == "meeting":
            b["meetings"] += 1
        if oc in NEGATIVE:
            b["negative"] += 1

    out = []
    for value, b in buckets.items():
        total = b["total"]
        out.append({
            "value":         value,
            "total":         total,
            "positive":      b["positive"],
            "meetings":      b["meetings"],
            "negative":      b["negative"],
            "positive_rate": round(b["positive"] / total, 3) if total else 0.0,
            "meeting_rate":  round(b["meetings"] / total, 3) if total else 0.0,
        })
    # Rank best-converting first; ties broken by volume
    out.sort(key=lambda x: (x["meeting_rate"], x["positive_rate"], x["total"]), reverse=True)
    return out


def _rollup_bucket(rows: list[dict]) -> list[dict]:
    """Like _rollup_one but keys on personalization_bucket (an int, not a
    string) — dedup and math are identical, just labeled by bucket number."""
    out = _rollup_one(
        [{"_bucket": str(r.get("personalization_bucket") or ""), "outcome_id": r.get("outcome_id"),
          "outcome": r.get("outcome"), "personalization_label": r.get("personalization_label")} for r in rows],
        "_bucket",
    )
    label_by_bucket = {str(r.get("personalization_bucket") or ""): r.get("personalization_label", "")
                        for r in rows}
    for b in out:
        b["label"] = label_by_bucket.get(b["value"], "")
    return out


def rollup_attribution(rows: list[dict], totals: dict | None = None,
                        hook_rows: list[dict] | None = None) -> dict:
    """
    rows: from db.get_outcome_signal_rows() — one per (outcome, signal) pair.
    totals: from db.get_outcome_totals() — counts by outcome type.
    hook_rows: from db.get_outcome_hook_rows() — one per outcome that traces
    back to a campaign_hooks row (Signal -> Angle -> Hook -> Email pipeline).
    Optional and separate from `rows` because not every outcome has a hook_id
    yet, and hook attribution (angle, personalization bucket) doesn't come
    from the signal join.
    Returns per-dimension conversion tables plus headline numbers.
    """
    result = {dim: _rollup_one(rows, field) for dim, field in _DIMENSIONS.items()}

    hook_rows = hook_rows or []
    result["by_angle"] = _rollup_one(hook_rows, "angle")
    result["by_personalization_bucket"] = _rollup_bucket(hook_rows)

    totals = totals or {}
    contacted = sum(totals.values())
    positives = sum(v for k, v in totals.items() if k in POSITIVE)
    result["totals"] = totals
    result["headline"] = {
        "total_outcomes":   contacted,
        "replies":          totals.get("replied", 0),
        "meetings":         totals.get("meeting", 0),
        "reply_rate":       round(positives / contacted, 3) if contacted else 0.0,
        "meeting_rate":     round(totals.get("meeting", 0) / contacted, 3) if contacted else 0.0,
    }
    return result
