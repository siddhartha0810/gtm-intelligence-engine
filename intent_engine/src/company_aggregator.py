"""
Groups raw classified signals by company.
Determines the dominant phase and product per company.
Deduplicates by (company_name, job_title, source).
"""

from collections import defaultdict, Counter
from src.utils import get_logger, clean_text, is_valid_company_name
from src import lead_scorer
from src import staffing_filter

logger = get_logger(__name__)

PHASE_PRIORITY = {
    "implementing": 6,
    "hiring":       5,
    "budgeting":    4,
    "evaluating":   3,
    "researching":  2,
    "post_live":    1,
}


def _normalise_company(name: str) -> str:
    name = clean_text(name)
    suffixes = [" Inc", " Inc.", " Corp", " Corp.", " Ltd", " Ltd.",
                " LLC", " L.L.C", " Group", " Co.", " Co", " GmbH",
                " S.A.", " PLC", " plc", " AG", " NV", " BV"]
    for s in suffixes:
        if name.endswith(s):
            name = name[: -len(s)]
    return name.lower().strip()


def aggregate(classified_signals: list[dict]) -> list[dict]:
    """
    Input : list of dicts — each has keys from BaseSignal + phase_classifier output.
    Output: list of aggregated company dicts ready for DB insert and export.
    """
    buckets: dict[str, list[dict]] = defaultdict(list)
    seen: set[tuple] = set()

    for sig in classified_signals:
        company_raw = sig.get("company_name", "").strip()
        if not company_raw:
            continue

        key = (
            _normalise_company(company_raw),
            sig.get("job_title", "").lower()[:60],
            sig.get("source", ""),
        )
        if key in seen:
            continue
        seen.add(key)

        norm_key = _normalise_company(company_raw)
        buckets[norm_key].append(sig)

    aggregated = []
    skipped_staffing = 0
    skipped_invalid = 0
    for norm_name, signals in buckets.items():
        representative = max(signals, key=lambda s: s.get("confidence", 0))
        company_name = representative["company_name"]

        # Final guard: reject names that aren't real company names
        if not is_valid_company_name(company_name):
            skipped_invalid += 1
            continue

        # Pure staffing firms excluded from lead output (retained in DB for market intelligence)
        if staffing_filter.is_staffing_firm(company_name):
            skipped_staffing += 1
            continue

        phases = [s["phase"] for s in signals if s.get("phase")]
        products = [s["detected_product"] for s in signals if s.get("detected_product")]
        sources = list({s["source"] for s in signals if s.get("source")})

        dominant_phase = _dominant_phase(phases)
        dominant_product = Counter(products).most_common(1)[0][0] if products else "Oracle (General)"

        evidence_items = [
            f"[{s['source'].upper()}] {s['job_title']}" for s in signals[:5]
        ]

        company = {
            "company_name": company_name,
            "domain": representative.get("domain", ""),
            "location": representative.get("location", ""),
            "industry": representative.get("industry", ""),
            "size": representative.get("size", ""),
            "website": representative.get("website", ""),
            "detected_product": dominant_product,
            "all_products": list(set(products)),
            "phase": dominant_phase,
            "all_phases": list(set(phases)),
            "sources": sources,
            "signal_count": len(signals),
            "confidence": round(sum(s.get("confidence", 0) for s in signals) / len(signals), 2),
            "evidence": " | ".join(evidence_items),
            "signals": signals,
        }
        lead_scorer.annotate(company)
        aggregated.append(company)

    aggregated.sort(key=lambda c: c["priority_score"], reverse=True)
    if skipped_staffing:
        logger.info(f"Skipped {skipped_staffing} staffing/SI firms during aggregation")
    if skipped_invalid:
        logger.info(f"Skipped {skipped_invalid} invalid/non-company names during aggregation")
    logger.info(f"Aggregated {len(classified_signals)} signals → {len(aggregated)} companies")
    return aggregated


def _dominant_phase(phases: list[str]) -> str:
    if not phases:
        return "hiring"
    phase_counts = Counter(phases)
    weighted = {p: count * PHASE_PRIORITY.get(p, 1) for p, count in phase_counts.items()}
    return max(weighted, key=weighted.get)
