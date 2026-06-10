"""
lead_scorer.py
==============
Produces a 0-100 priority score for each company detected during a scan.

PURPOSE:
  Lets the sales team triage companies by buying likelihood without manual review.
  A company with score HOT (70+) should be called this week.  COLD (<45) can
  be monitored for future signal volume before investing outreach effort.

HOW IT FITS IN THE SYSTEM:
  Called by scan_worker.py AFTER all signals are collected for a run.
  annotate() mutates the company dict in-place, adding:
    priority_score  (int 0-100)
    priority_label  ("HOT" / "WARM" / "COLD")
    priority_color  (hex colour for the React UI badge)

  unified_app.py reads these fields from the companies table and sends them
  to the frontend for display in the Oracle Intent tab.

SCORE BREAKDOWN (total = 100 points):
  Phase weight     (0-40): What stage of the Oracle adoption cycle?
    implementing=40, hiring=30, budgeting=25, evaluating=20,
    post_live=15, researching=10
  Signal tier      (0-20): Are they posting Oracle jobs on job boards?
    _TIER1 (indeed, linkedin, google_jobs) = 20 pts — active hiring intent
    _TIER2 (news) = 10 pts — public announcement
    _TIER3 (oracle_website) = 5 pts — confirmed Oracle customer
  Source diversity (0-15): Do independent sources agree?
    3+ sources = 15, 2 sources = 8, 1 source = 0
  Signal volume    (0-10): How many corroborating signals exist?
    10+ = 10, 5+ = 7, 3+ = 4, 1+ = 1
  Confidence       (0-15): Aggregate signal confidence quality.
    conf * 15 (confidence ranges from 0.0 to 1.0)

LABELS:
  HOT  70-100  → call this week
  WARM 45-69   → nurture / add to sequence
  COLD  0-44   → monitor only, revisit next scan
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
