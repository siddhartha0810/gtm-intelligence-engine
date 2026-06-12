"""
phase_classifier.py
====================
Classifies a raw signal (job posting, news article) into:
  oracle_product — which Oracle product family is involved
  phase          — where the company is in its Oracle journey
  confidence     — 0.0 to 1.0 (how certain we are about the classification)

PURPOSE:
  Transforms unstructured text (job title + description) into structured
  metadata that drives the priority scoring, filtering, and export.
  Also exports PHASE_LABELS and PHASE_COLORS used by unified_app.py for the
  React frontend badges and filter dropdowns.

HOW IT FITS IN THE SYSTEM:
  Called by scan_worker.py for every raw signal returned by a scraper:
    1. scraper.fetch()   → raw dict with job_title + description
    2. classify()        → adds oracle_products[], phases[], confidence
    3. database.upsert_signal() → stored in oracle_signals table

KEY FUNCTIONS:
  detect_oracle_product(text)  — returns (product_name, confidence) or (None, 0)
  detect_phase(text)           — returns (phase_name, confidence) or (None, 0)
  classify(title, description) — combines both; returns full classification dict

CONFIDENCE SCORING:
  Product confidence: min(keyword_match_count / 3.0, 1.0)
    — 3+ keyword matches = full confidence (1.0)
    — 1 match = 0.33 (single keyword, low confidence)
  Phase confidence: weighted keyword counts
    — Title keywords score 1.5x vs description keywords (title is more reliable)
    — Normalized by expected match count for the phase
  Combined: (product_conf + phase_conf) / 2

  Per signals.md rules:
    Never set confidence > 0.75 if you cannot confirm Oracle product by string match.
    0.90 = explicit Oracle product + company in same post (set externally, not here)
    0.80 = Oracle product in job title
    0.75 = strong Oracle indicator in description
    0.60 = generic Oracle context
    0.50 = weak signal
    <0.40 = not stored (filtered before DB insert)

PHASE DEFINITIONS:
  researching   — early awareness stage (Oracle mentioned in passing)
  evaluating    — actively comparing vendors (RFP, selection keywords)
  budgeting     — budget approval cycle (capex, approvals, business case)
  hiring        — actively hiring Oracle staff = strongest implementation signal
  implementing  — go-live underway (highest confidence, highest lead score)
  post_live     — live on Oracle (support/admin roles = expansion opportunity)
"""

import logging

from src.utils import clean_text

logger = logging.getLogger(__name__)

# Fallback used when the DB is unavailable at startup.
# Mirrors the 8-product taxonomy so signals are never silently lost.
_FALLBACK_PRODUCTS: dict[str, list[str]] = {
    "JD Edwards EnterpriseOne": [
        "jd edwards enterpriseone", "jd edwards", "jde", "jde enterpriseone",
        "jde e1", "jde oneworld", "jd edwards oneworld", "jdedwards",
        "jde cnc", "jde cnc administrator", "jde basis administrator",
        "enterpriseone", "e1 developer", "e1 consultant",
    ],
    "JD Edwards World": [
        "jd edwards world", "jde world", "world software", "as/400 jde",
        "jde world to enterpriseone",
    ],
    "Oracle Cloud ERP": [
        "oracle cloud erp", "oracle fusion erp", "oracle erp cloud",
        "fusion financials", "oracle financials cloud", "oracle fusion financials",
        "oracle general ledger cloud", "oracle procurement cloud",
    ],
    "Oracle E-Business Suite": [
        "oracle e-business suite", "oracle ebs", "oracle apps", "oracle applications",
        "oracle r12", "oracle 11i", "apps dba", "oracle ebusiness",
    ],
    "Oracle PeopleSoft": [
        "peoplesoft", "oracle peoplesoft", "psft", "peopletools", "people tools",
        "hcm peoplesoft", "fscm", "campus solutions",
    ],
    "Oracle NetSuite": [
        "netsuite", "oracle netsuite", "netsuite erp", "netsuite implementation",
        "netsuite administrator", "netsuite developer", "netsuite consultant",
        "suitescript", "netsuite oneworld",
    ],
    "Oracle HCM Cloud": [
        "oracle hcm cloud", "oracle hcm", "oracle human capital management",
        "fusion hcm", "oracle global hr", "oracle payroll cloud",
        "oracle talent management", "oracle recruiting cloud",
        "oracle learning cloud", "oracle orc",
    ],
    "Oracle SCM Cloud": [
        "oracle scm cloud", "oracle scm", "oracle supply chain cloud",
        "oracle inventory cloud", "oracle order management cloud",
        "oracle manufacturing cloud", "oracle otm", "oracle warehouse management",
    ],
}

_FALLBACK_WEIGHTS: dict[str, float] = {
    "JD Edwards EnterpriseOne": 1.0,
    "JD Edwards World":         1.0,
    "Oracle Cloud ERP":         1.0,
    "Oracle E-Business Suite":  0.9,
    "Oracle PeopleSoft":        0.9,
    "Oracle NetSuite":          0.8,
    "Oracle HCM Cloud":         0.9,
    "Oracle SCM Cloud":         0.85,
}

_products_cache: dict[str, list[str]] | None = None
_weights_cache:  dict[str, float] | None = None


def _load_products() -> tuple[dict[str, list[str]], dict[str, float]]:
    try:
        from src import tech_profiles
        rows = tech_profiles.get_active_products()
        if not rows:
            raise ValueError("taxonomy table is empty")
        products: dict[str, list[str]] = {}
        weights:  dict[str, float] = {}
        for row in rows:
            name = row["canonical_name"]
            aliases = [a.lower() for a in (row.get("aliases") or [])]
            if name.lower() not in aliases:
                aliases.insert(0, name.lower())
            products[name] = aliases
            weights[name] = float(row.get("confidence_weight") or 0.8)
        logger.info(f"[phase_classifier] loaded {len(products)} products from taxonomy DB")
        return products, weights
    except Exception as exc:
        logger.warning(f"[phase_classifier] DB unavailable, using fallback: {exc}")
        return _FALLBACK_PRODUCTS, _FALLBACK_WEIGHTS


def _get_products() -> tuple[dict[str, list[str]], dict[str, float]]:
    global _products_cache, _weights_cache
    if _products_cache is None:
        _products_cache, _weights_cache = _load_products()
    return _products_cache, _weights_cache


def reload_products_cache() -> int:
    """Flush the in-memory cache and reload from DB. Returns product count."""
    global _products_cache, _weights_cache
    _products_cache = None
    _weights_cache = None
    products, _ = _get_products()
    return len(products)

PHASE_CONFIG = {
    "researching": {
        "weight": 1,
        "title_kw": [
            "business analyst", "solution architect", "pre-sales",
            "advisory", "strategy", "enterprise architect",
        ],
        "desc_kw": [
            "evaluating", "assessment", "exploring", "research",
            "considering", "requirements gathering", "fit gap analysis",
            "current state", "future state", "roadmap", "feasibility",
            "needs analysis", "landscape assessment",
        ],
    },
    "evaluating": {
        "weight": 2,
        "title_kw": [
            "pre-sales consultant", "solution architect", "functional lead",
            "bid manager", "rfp",
        ],
        "desc_kw": [
            "proof of concept", "poc", "pilot", "rfp", "rfi",
            "shortlist", "vendor selection", "demo", "evaluation criteria",
            "comparing solutions", "due diligence", "selection process",
            "vendor assessment",
        ],
    },
    "budgeting": {
        "weight": 2,
        "title_kw": [
            "project manager", "program director", "vp", "cio",
            "chief information", "director of it", "procurement",
        ],
        "desc_kw": [
            "business case", "budget", "roi", "investment",
            "cost benefit", "approval", "financial justification",
            "capital expenditure", "opex", "capex", "funding",
            "financial planning", "cost analysis",
        ],
    },
    "hiring": {
        "weight": 3,
        "title_kw": [
            "consultant", "administrator", "developer", "analyst",
            "architect", "specialist", "lead", "expert", "manager",
            "functional consultant", "technical consultant",
            "implementation consultant",
        ],
        "desc_kw": [
            "new implementation", "greenfield", "fresh implementation",
            "join our team", "immediate start", "contract", "permanent",
            "full time", "looking for", "seeking experienced",
        ],
    },
    "implementing": {
        "weight": 4,
        "title_kw": [
            "implementation consultant", "project manager",
            "change management", "deployment lead", "cutover manager",
            "integration developer", "data migration",
        ],
        "desc_kw": [
            "implementation", "go-live", "deployment", "migration",
            "rollout", "configure", "customization", "data migration",
            "cutover", "uat", "user acceptance testing", "system integration",
            "parallel run", "sprint", "workstream", "blueprint",
            "realization", "go live support",
        ],
    },
    "post_live": {
        "weight": 2,
        "title_kw": [
            "application support", "functional support",
            "system administrator", "production support",
            "support analyst", "enhancement analyst",
        ],
        "desc_kw": [
            "post-implementation", "post go-live", "hypercare",
            "stabilization", "optimization", "end user support",
            "production support", "break fix", "continuous improvement",
            "managed services", "application managed services",
        ],
    },
}

PHASE_LABELS = {
    "researching":  "Researching",
    "evaluating":   "Evaluating",
    "budgeting":    "Budgeting / Approving",
    "hiring":       "Hiring for Oracle",
    "implementing": "Implementing",
    "post_live":    "Post Go-Live / Support",
}

PHASE_COLORS = {
    "researching":  "#6c757d",
    "evaluating":   "#0d6efd",
    "budgeting":    "#ffc107",
    "hiring":       "#198754",
    "implementing": "#dc3545",
    "post_live":    "#0dcaf0",
}


def detect_oracle_product(title: str, description: str) -> tuple[str, float]:
    combined = f"{title} {description}".lower()
    products, weights = _get_products()

    best_product = "Oracle (General)"
    best_score = 0

    for product, keywords in products.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_product = product

    if best_score == 0:
        return "Oracle (General)", 0.3

    base_conf = min(best_score / 3.0, 1.0)
    weight = weights.get(best_product, 0.8)
    return best_product, round(base_conf * weight, 2)


def detect_phase(title: str, description: str) -> tuple[str, float]:
    title_l = title.lower() if title else ""
    desc_l = description.lower() if description else ""

    phase_scores: dict[str, float] = {}

    for phase, cfg in PHASE_CONFIG.items():
        score = 0.0
        for kw in cfg["title_kw"]:
            if kw in title_l:
                score += 1.5
        for kw in cfg["desc_kw"]:
            if kw in desc_l:
                score += 1.0
        phase_scores[phase] = score * cfg["weight"]

    if not any(v > 0 for v in phase_scores.values()):
        return "hiring", 0.4

    best_phase = max(phase_scores, key=phase_scores.get)
    total = sum(phase_scores.values())
    confidence = round(phase_scores[best_phase] / total, 2) if total else 0.4
    return best_phase, min(confidence, 1.0)


def classify(title: str, description: str, source: str = "") -> dict:
    title = clean_text(title)
    description = clean_text(description)

    product, prod_conf = detect_oracle_product(title, description)
    phase, phase_conf = detect_phase(title, description)

    combined_confidence = round((prod_conf + phase_conf) / 2, 2)

    return {
        "oracle_product": product,
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "confidence": combined_confidence,
    }
