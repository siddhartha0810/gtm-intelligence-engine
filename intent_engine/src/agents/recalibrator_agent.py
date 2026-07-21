"""
recalibrator_agent.py
=====================
The back of the GTM loop — turns real outreach outcomes into a proposed
targeting change. This is the learning layer: run 1 finds leads, outcomes
get logged, the Recalibrator reads which signals actually converted and
proposes what to double down on and what to drop. Human-approved before
anything changes (Gate G4).

Design discipline: the PROPOSAL is computed deterministically from the
attribution numbers — the agent never invents conversion rates. The LLM
only writes the human-readable rationale around the ranking the data already
produced. Numbers from code, narrative from the model.

Degraded path: no LLM → the deterministic proposal still stands, with a
templated rationale. Insufficient data → returns a clear "need more outcomes"
status instead of over-fitting on 2 data points.
"""

from __future__ import annotations

from src.agents.base_agent import BaseAgent
from src import llm_gateway
from src.utils import get_logger

logger = get_logger(__name__)

_MIN_OUTCOMES = 5          # below this, proposals are low-confidence
_MIN_VOLUME = 2            # a dimension value needs >= this many outcomes to judge

_SYSTEM_PROMPT = (
    "You are a GTM analyst. You are given attribution numbers (which signal "
    "types, products, phases, and sources produced replies and meetings) and a "
    "deterministic recommendation already computed from those numbers. Write a "
    "2-4 sentence rationale a founder can act on. Reference the actual rates. "
    "Do NOT invent numbers or contradict the recommendation. Plain text only."
)


def _top(table: list[dict], key: str = "meeting_rate") -> list[dict]:
    return [r for r in table if r.get("total", 0) >= _MIN_VOLUME]


def _build_proposal(attr: dict) -> dict:
    """Deterministic: rank each dimension by conversion, pick winners/losers."""
    def winners(table):
        rows = _top(table)
        return [r["value"] for r in rows if r["positive_rate"] > 0][:3]

    def losers(table):
        rows = _top(table)
        return [r["value"] for r in rows if r["positive"] == 0]

    sources = attr.get("by_source", [])
    products = attr.get("by_product", [])
    phases = attr.get("by_phase", [])
    sig_types = attr.get("by_signal_type", [])

    return {
        "prioritize_sources":    winners(sources),
        "deprioritize_sources":  losers(sources),
        "prioritize_products":   winners(products),
        "prioritize_phases":     winners(phases),
        "best_signal_types":     winners(sig_types),
    }


class RecalibratorAgent(BaseAgent):
    name = "recalibrator"
    description = ("Reads outreach attribution and proposes a targeting change "
                   "— which sources/products/phases to prioritize or drop. "
                   "Numbers computed deterministically; human-approved (G4).")
    required_fields = ["attribution"]

    def _execute(self, payload: dict) -> dict:
        attr = payload.get("attribution") or {}
        headline = attr.get("headline", {})
        total = int(headline.get("total_outcomes", 0))

        if total == 0:
            return {
                "status": "no_data",
                "message": "No outcomes logged yet. Log replies/meetings via "
                           "/api/outcomes, then recalibrate.",
                "proposal": None,
            }

        proposal = _build_proposal(attr)
        confidence = "high" if total >= 20 else "medium" if total >= _MIN_OUTCOMES else "low"

        # LLM rationale (narrative only — the proposal is already fixed).
        rationale = ""
        degraded = False
        if llm_gateway.is_available():
            prompt = (
                f"Attribution headline: {headline}\n"
                f"By source: {attr.get('by_source')}\n"
                f"By product: {attr.get('by_product')}\n"
                f"By phase: {attr.get('by_phase')}\n"
                f"Recommendation (already decided): {proposal}\n\n"
                "Write the rationale."
            )
            rationale = llm_gateway.complete(prompt, system=_SYSTEM_PROMPT, task="reason", max_tokens=300)

        if not rationale:
            degraded = True
            rationale = _template_rationale(proposal, headline, confidence)

        return {
            "status":         "ok" if total >= _MIN_OUTCOMES else "low_confidence",
            "confidence":     confidence,
            "outcomes_seen":  total,
            "min_recommended": _MIN_OUTCOMES,
            "headline":       headline,
            "proposal":       proposal,
            "rationale":      rationale,
            "_degraded":      degraded,
        }


def _template_rationale(proposal: dict, headline: dict, confidence: str) -> str:
    parts = []
    if proposal.get("prioritize_sources"):
        parts.append(f"Prioritize sources: {', '.join(proposal['prioritize_sources'])}.")
    if proposal.get("deprioritize_sources"):
        parts.append(f"Drop non-converting sources: {', '.join(proposal['deprioritize_sources'])}.")
    if proposal.get("prioritize_products"):
        parts.append(f"Best-converting products: {', '.join(proposal['prioritize_products'])}.")
    parts.append(f"Based on {headline.get('total_outcomes', 0)} outcomes "
                 f"({headline.get('meetings', 0)} meetings) — {confidence} confidence.")
    return " ".join(parts)
