"""
Lead Priority Scorer — produces a 0-100 score per company.

Score breakdown (total = 100):
  Phase weight     (0-40)  What stage of Oracle adoption?
  Signal tier      (0-20)  Are they actively posting Oracle jobs on job boards?
  Source diversity (0-15)  Do multiple independent sources agree?
  Signal volume    (0-10)  How many corroborating signals exist?
  Confidence       (0-15)  How strong is the aggregate signal quality?

Labels:
  HOT  70-100  → call this week
  WARM 45-69   → nurture / sequence
  COLD  0-44   → monitor only
"""

# Phase contribution — higher = deeper in buying cycle
_PHASE_SCORE = {
    "implementing": 40,
    "hiring":       30,
    "budgeting":    25,
    "evaluating":   20,
    "post_live":    15,
    "researching":  10,
}

# Signal tiers based on source type
_TIER1 = {"indeed", "linkedin", "google_jobs"}   # active hiring = strongest buying signal
_TIER2 = {"news"}                                 # public announcement
_TIER3 = {"oracle_website"}                       # confirmed customer (support opportunity)

# UI colours
_COLORS = {
    "HOT":  "#FF4757",
    "WARM": "#FFA502",
    "COLD": "#747D8C",
}


def calculate_priority_score(company: dict) -> int:
    """
    Accepts both in-memory aggregated dicts (from company_aggregator)
    and DB row dicts (from get_all_companies_with_signals).
    Both field-name conventions are handled.
    """
    score = 0

    # 1. Phase (0-40)
    phase = (
        company.get("phase")
        or (company.get("phases") or [""])[0]
        or "researching"
    )
    score += _PHASE_SCORE.get(phase, 10)

    # 2. Signal tier (0-20)
    sources = set(company.get("sources") or [])
    if sources & _TIER1:
        score += 20          # job-board posting = active hiring intent
    elif sources & _TIER2:
        score += 10          # news article = public announcement
    elif sources & _TIER3:
        score += 5           # oracle.com mention = confirmed customer

    # 3. Source diversity (0-15) — independent corroboration
    n = len(sources)
    if n >= 3:
        score += 15
    elif n == 2:
        score += 8

    # 4. Signal volume (0-10)
    vol = int(company.get("signal_count") or 0)
    if vol >= 10:
        score += 10
    elif vol >= 5:
        score += 7
    elif vol >= 3:
        score += 4
    elif vol >= 1:
        score += 1

    # 5. Confidence quality (0-15)
    conf = float(
        company.get("confidence")
        or company.get("max_confidence")
        or 0
    )
    score += round(conf * 15)

    return min(score, 100)


def get_priority_label(score: int) -> str:
    if score >= 70:
        return "HOT"
    if score >= 45:
        return "WARM"
    return "COLD"


def get_priority_color(score: int) -> str:
    return _COLORS[get_priority_label(score)]


def annotate(company: dict) -> dict:
    """Add priority_score, priority_label, priority_color to a company dict in-place."""
    score = calculate_priority_score(company)
    company["priority_score"] = score
    company["priority_label"] = get_priority_label(score)
    company["priority_color"] = get_priority_color(score)
    return company
