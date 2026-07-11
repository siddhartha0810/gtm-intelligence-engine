"""
phase_classifier.py
====================
Classifies a raw signal (job posting, news article) into:
  oracle_product — which product/keyword is involved (Oracle taxonomy by
                   default; any campaign's own keywords when campaign_keywords
                   is supplied — see detect_campaign_product() below)
  phase          — where the company is in its buying/adoption cycle
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

  Per signals.md rules (Oracle campaigns; generic campaigns use their own
  detect_campaign_product() confidence formula instead):
    Never set confidence > 0.75 if you cannot confirm the product by string match.
    0.90 = explicit product + company in same post (set externally, not here)
    0.80 = product named in job title
    0.75 = strong product indicator in description
    0.60 = generic/ambiguous product context
    0.50 = weak signal
    <0.40 = not stored (filtered before DB insert)

PHASE DEFINITIONS (source-agnostic — apply to any campaign's keywords):
  researching   — early awareness stage (category/product mentioned in passing)
  evaluating    — actively comparing vendors (RFP, selection keywords)
  budgeting     — budget approval cycle (capex, approvals, business case)
  hiring        — actively hiring staff for the category = strongest adoption signal
  implementing  — go-live underway (highest confidence, highest lead score)
  post_live     — live on the product (support/admin roles = expansion opportunity)
"""

import logging
import re
from pathlib import Path

from src.utils import clean_text

logger = logging.getLogger(__name__)

# Fallback used only if the technology_profiles/product_taxonomy DB tables are
# unreachable at boot — mirrors DB row id=1 ("Oracle / JDE") so a scan never
# silently runs with zero product taxonomy. NOT the primary source of truth;
# that's the DB, editable live at /technology-profiles. See
# icp_profiles/oracle_products.yaml — keep the two in sync if either changes.
_FALLBACK_YAML = Path(__file__).resolve().parent.parent.parent / "icp_profiles" / "oracle_products.yaml"


def _load_fallback_taxonomy() -> tuple[dict[str, list[str]], dict[str, float]]:
    import yaml
    data = yaml.safe_load(_FALLBACK_YAML.read_text())
    products: dict[str, list[str]] = {}
    weights:  dict[str, float] = {}
    for p in data.get("products", []):
        name = p["canonical_name"]
        products[name] = list(p.get("aliases", []))
        weights[name] = float(p.get("weight", 0.8))
    return products, weights


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
        logger.warning(f"[phase_classifier] DB unavailable, using fallback YAML: {exc}")
        return _load_fallback_taxonomy()


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
    "hiring":       "Hiring",
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


def detect_oracle_product(title: str, description: str) -> tuple[str | None, float]:
    combined = f"{title} {description}".lower()
    products, weights = _get_products()

    best_product: str | None = None
    best_score = 0

    for product, keywords in products.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_product = product

    if best_score == 0 or best_product is None:
        return None, 0.0

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


def detect_campaign_product(title: str, description: str,
                             keywords: list[str]) -> tuple[str | None, float]:
    """
    Generic product detector for universal campaigns.

    Instead of checking the Oracle taxonomy, checks whether any of the
    campaign's own keywords appear in the text. Returns the best-matching
    keyword as the detected product name.

    Args:
        title:       Job title or article headline
        description: Full text body
        keywords:    Campaign keywords, e.g. ["Salesforce", "SFDC", "Salesforce CRM"]

    Returns:
        (matched_keyword_or_None, confidence_0_to_1)
    """
    if not keywords:
        return None, 0.0

    combined = f"{title} {description}".lower()
    title_l  = title.lower() if title else ""

    best_kw: str | None = None
    best_score = 0.0

    for kw in keywords:
        kw_l = kw.strip().lower()
        if not kw_l:
            continue
        # Word-boundary match, not substring — plain .count() matched "Clari"
        # inside "ClarityQ" (a real false positive seen in production). \b
        # only anchors on the outer edges, so multi-word keywords like
        # "Head of RevOps" still match as a phrase, not word-by-word.
        pattern = re.compile(r"\b" + re.escape(kw_l) + r"\b")
        title_hits = len(pattern.findall(title_l))
        desc_hits  = len(pattern.findall(combined)) - title_hits
        score = (title_hits * 2.0) + (desc_hits * 1.0)
        if score > best_score:
            best_score = score
            best_kw = kw.strip()

    if best_score == 0 or best_kw is None:
        return None, 0.0

    # Confidence: 1 title hit = 0.60, 2+ hits = 0.80+, keyword in title alone = 0.75
    confidence = min(0.40 + (best_score * 0.15), 1.0)
    return best_kw, round(confidence, 2)


def classify(title: str, description: str, source: str = "",
             campaign_keywords: list[str] | None = None) -> dict:
    """
    Classify a raw signal into product + phase + confidence.

    Args:
        title:             Job title or article headline
        description:       Full text
        source:            Signal source name (e.g. "indeed", "news")
        campaign_keywords: If provided, use generic keyword matching instead of
                           the Oracle taxonomy. Pass the campaign's keywords list.

    Returns:
        {oracle_product, phase, phase_label, confidence}
    """
    title = clean_text(title)
    description = clean_text(description)

    if campaign_keywords:
        product, prod_conf = detect_campaign_product(title, description, campaign_keywords)
    else:
        product, prod_conf = detect_oracle_product(title, description)

    phase, phase_conf = detect_phase(title, description)

    combined_confidence = round((prod_conf + phase_conf) / 2, 2)

    return {
        "oracle_product": product,
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "confidence": combined_confidence,
    }
