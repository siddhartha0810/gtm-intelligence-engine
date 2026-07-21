"""
strategist_agent.py
===================
The front of the GTM loop — does what a founder does in week one.

Takes a free-text prompt ("find mid-market manufacturers hiring Salesforce
admins in Texas") and produces a structured campaign spec: target keywords,
signal sources, location, and an ICP hypothesis note. The spec maps 1:1 to
the campaigns table, so the output can be saved with db.create_campaign()
and launched through the existing campaign-run pipeline — the Strategist
parameterizes machinery that already exists (query_builder crosses the
keywords with role suffixes; the scan pipeline does the rest).

Degraded path ("no breakers"): when no LLM is reachable, a heuristic
extractor pulls keywords from quoted phrases and capitalized terms in the
prompt so the flow still completes — marked degraded so the UI can say
"review these keywords before launching".
"""

from __future__ import annotations

import re

from src.agents.base_agent import BaseAgent
from src import llm_gateway
from src.utils import get_logger

logger = get_logger(__name__)

# Sources a campaign scan can actually execute (see pipeline.py scrapers dict).
_ALLOWED_SOURCES = [
    "indeed", "linkedin", "ziprecruiter", "adzuna", "totaljobs", "cwjobs",
    "news", "agentic_harvester",
]
_DEFAULT_SOURCES = ["linkedin", "news"]

_SYSTEM_PROMPT = """You are a founding GTM strategist. Given a product or lead-hunting request, \
produce a signal-scan campaign spec as strict JSON — no prose, no markdown fences.

Schema:
{
  "name": "short campaign name (max 60 chars)",
  "description": "one sentence: who we're hunting and why",
  "keywords": ["2-6 product/technology keywords a target company would mention in job posts or news"],
  "extra_job_suffixes": ["0-4 extra role suffixes specific to this market, e.g. 'revenue operations'"],
  "extra_news_templates": ["0-3 extra news query phrases, e.g. 'raises series B'"],
  "location": "geographic filter or empty string for worldwide",
  "sources": ["subset of: indeed, linkedin, ziprecruiter, adzuna, totaljobs, cwjobs, news, agentic_harvester"],
  "icp_hypothesis": "1-2 sentences: the testable hypothesis about who buys and which signal proves they're in-market"
}

Rules:
- keywords are things TARGET COMPANIES write (product names, technologies), never generic words like "software" or "leads"
- prefer sources ["linkedin", "news"] unless the request implies job boards or arbitrary websites
- if the request names a region/country/city, put it in location"""

_STOPWORDS = {
    "find", "get", "me", "leads", "for", "companies", "company", "hiring",
    "using", "that", "are", "with", "who", "in", "the", "a", "an", "and",
    "of", "on", "at", "to", "any", "all", "looking", "want", "need", "show",
}


def _heuristic_spec(prompt: str, location: str) -> dict:
    """Keyword extraction without an LLM: quoted phrases first, then
    capitalized multi-word runs, then leftover non-stopword tokens."""
    keywords: list[str] = []

    for quoted in re.findall(r'["\'“”]([^"\'“”]{2,60})["\'“”]', prompt):
        keywords.append(quoted.strip())

    if not keywords:
        for run in re.findall(r"\b(?:[A-Z][A-Za-z0-9+.#-]*(?:\s+[A-Z][A-Za-z0-9+.#-]*)*)\b", prompt):
            if run.lower() not in _STOPWORDS and len(run) > 2:
                keywords.append(run.strip())

    if not keywords:
        keywords = [w for w in re.findall(r"[A-Za-z0-9+.#-]{3,}", prompt)
                    if w.lower() not in _STOPWORDS][:4]

    # Dedupe, cap
    seen: set[str] = set()
    deduped = []
    for kw in keywords:
        k = kw.lower()
        if k not in seen:
            seen.add(k)
            deduped.append(kw)
    keywords = deduped[:6]

    name = " ".join(prompt.split()[:8])
    return {
        "name":                 (name[:57] + "...") if len(name) > 60 else name,
        "description":          f"Auto-generated from prompt: {prompt[:140]}",
        "keywords":             keywords,
        "extra_job_suffixes":   [],
        "extra_news_templates": [],
        "location":             location,
        "sources":              list(_DEFAULT_SOURCES),
        "icp_hypothesis":       "Heuristic spec (no LLM available) — review keywords before launching.",
        "_degraded":            True,
    }


def _sanitize(spec: dict, prompt: str, location: str) -> dict:
    """Enforce the schema regardless of what the LLM returned."""
    keywords = [str(k).strip() for k in (spec.get("keywords") or []) if str(k).strip()][:6]
    if not keywords:
        # LLM answered but gave no usable keywords — recover via heuristics
        return _heuristic_spec(prompt, location)

    sources = [s for s in (spec.get("sources") or []) if s in _ALLOWED_SOURCES]
    name = str(spec.get("name") or " ".join(keywords[:3]))[:60].strip()

    return {
        "name":                 name,
        "description":          str(spec.get("description") or "")[:300].strip(),
        "keywords":             keywords,
        "extra_job_suffixes":   [str(s).strip() for s in (spec.get("extra_job_suffixes") or []) if str(s).strip()][:4],
        "extra_news_templates": [str(t).strip() for t in (spec.get("extra_news_templates") or []) if str(t).strip()][:3],
        "location":             str(spec.get("location") or location).strip(),
        "sources":              sources or list(_DEFAULT_SOURCES),
        "icp_hypothesis":       str(spec.get("icp_hypothesis") or "").strip(),
    }


class StrategistAgent(BaseAgent):
    name = "strategist"
    description = ("Turns a free-text lead-hunting prompt into a launchable "
                   "campaign spec (keywords, sources, location, ICP hypothesis).")
    required_fields = ["prompt"]

    def _execute(self, payload: dict) -> dict:
        prompt = str(payload["prompt"]).strip()
        location = str(payload.get("location", "") or "").strip()

        spec = llm_gateway.complete_json(
            f"Request: {prompt}" + (f"\nRegion hint: {location}" if location else ""),
            system=_SYSTEM_PROMPT,
            task="reason",
            max_tokens=600,
        )
        if spec is None:
            logger.info("[strategist] LLM unavailable/unparseable — using heuristic spec")
            return _heuristic_spec(prompt, location)

        return _sanitize(spec, prompt, location)
