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
  to the frontend for display in the Intent tab.

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


# ── Fit / Intent split (from chadboyda/agent-gtm-skills) ──────────────────────
# Separating fit from intent surfaces two failure modes the single score hides:
#   High Fit + Low Intent  → nurture, wrong timing
#   Low Fit  + High Intent → monitor, wrong ICP

# Default ICP industry fit weights — overridden per campaign via `icp_industry_fit` field.
# When a campaign supplies its own keywords, fit scoring is based on signal quality only
# (intent_score carries the weight). These defaults are kept for backward compat.
_DEFAULT_INDUSTRY_FIT: dict[str, float] = {
    "manufacturing": 1.0, "distribution": 1.0, "wholesale": 1.0,
    "construction": 0.9, "engineering": 0.9, "oil and gas": 0.9,
    "energy": 0.9, "utilities": 0.9, "government": 0.85,
    "healthcare": 0.85, "life sciences": 0.85, "pharmaceuticals": 0.85,
    "financial services": 0.8, "banking": 0.8, "insurance": 0.8,
    "retail": 0.75, "food and beverage": 0.75, "logistics": 0.75,
    "software": 0.5, "media": 0.45, "advertising": 0.4,
}

_SIZE_FIT = {
    "1001-5000":   1.0,
    "501-1000":    0.95,
    "201-500":     0.85,
    "5001-10000":  0.80,
    "10001+":      0.75,
    "51-200":      0.60,
    "11-50":       0.35,
    "1-10":        0.15,
}


def _fit_score(company: dict) -> float:
    """
    0.0–1.0 firmographic fit.

    For universal campaigns (non-Oracle): if the company has no detectable
    industry or the campaign provides no ICP override, fit defaults to 0.60
    (neutral) and intent_score carries the full routing weight.

    Per-campaign ICP can override via company['icp_industry_fit'] (float 0-1).
    """
    # Campaign-level override — if the pipeline injected explicit fit, use it
    if "icp_industry_fit" in company and company["icp_industry_fit"] is not None:
        override = float(company["icp_industry_fit"])
        size_fit = _SIZE_FIT.get((company.get("size") or "").strip(), 0.5)
        return round(override * 0.60 + size_fit * 0.40, 2)

    industry_raw = (company.get("industry") or "").lower()
    size_raw     = (company.get("size") or "").strip()

    industry_fit = 0.50  # neutral default — unknown or non-matching industry
    for keyword, score in _DEFAULT_INDUSTRY_FIT.items():
        if keyword in industry_raw:
            industry_fit = score
            break

    size_fit = _SIZE_FIT.get(size_raw, 0.5)
    return round(industry_fit * 0.60 + size_fit * 0.40, 2)


def _intent_score(company: dict) -> float:
    """0.0–1.0 signal-based buying intent score."""
    phase = (
        company.get("phase")
        or (company.get("phases") or [""])[0]
        or "researching"
    )
    phase_weights = {
        "implementing": 1.0, "evaluating": 0.85, "budgeting": 0.75,
        "hiring": 0.70, "post_live": 0.55, "researching": 0.30,
    }
    phase_score = phase_weights.get(phase, 0.30)

    sources     = set(company.get("sources") or [])
    tier1_hit   = 1.0 if (sources & _TIER1) else 0.0
    tier2_hit   = 0.6 if (sources & _TIER2) else 0.0
    source_score = max(tier1_hit, tier2_hit)

    diversity   = min(len(sources) / 3.0, 1.0)
    confidence  = float(company.get("confidence") or company.get("max_confidence") or 0)
    vol         = min(int(company.get("signal_count") or 0) / 10.0, 1.0)

    # Weighted blend: phase is most predictive, then source tier
    return round(
        phase_score   * 0.40 +
        source_score  * 0.25 +
        confidence    * 0.20 +
        diversity     * 0.10 +
        vol           * 0.05,
        2,
    )


def route_company(fit: float, intent: float) -> str:
    """
    4-quadrant routing matrix (chadboyda pattern).
    ACTIVATE = 4-hour response target
    NURTURE  = add to sequence, revisit in 2 weeks
    MONITOR  = watch for ICP qualification signals
    DISQUALIFY = remove from active pipeline
    """
    if fit >= 0.65 and intent >= 0.65:
        return "ACTIVATE"
    if fit >= 0.65 and intent < 0.65:
        return "NURTURE"
    if fit < 0.65 and intent >= 0.65:
        return "MONITOR"
    return "DISQUALIFY"


_ROUTING_COLORS = {
    "ACTIVATE":    "#10b981",
    "NURTURE":     "#3b82f6",
    "MONITOR":     "#f59e0b",
    "DISQUALIFY":  "#94a3b8",
}


def annotate(company: dict) -> dict:
    """
    Add to company dict in-place:
      priority_score, priority_label, priority_color  (original 0-100 score)
      fit_score, intent_score                         (0.0-1.0 split scores)
      routing, routing_color                          (ACTIVATE/NURTURE/MONITOR/DISQUALIFY)
    """
    score = calculate_priority_score(company)
    company["priority_score"] = score
    company["priority_label"] = get_priority_label(score)
    company["priority_color"] = get_priority_color(score)

    fit    = _fit_score(company)
    intent = _intent_score(company)
    route  = route_company(fit, intent)

    company["fit_score"]      = fit
    company["intent_score"]   = intent
    company["routing"]        = route
    company["routing_color"]  = _ROUTING_COLORS[route]
    return company
