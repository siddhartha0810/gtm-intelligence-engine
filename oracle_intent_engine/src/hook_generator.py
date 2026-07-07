"""
hook_generator.py
=================
Generates personalised cold email hooks for a given contact + company
using Claude Haiku via the Anthropic API.

Framework: PAS (Problem → Agitate → Solution), grounded in real ICP research.
Five tension categories: Risk, Effort, Time, Cost, Identity.
Output: subject line + 3-sentence email body, under 75 words.

Usage:
    from oracle_intent_engine.src.hook_generator import generate_hook, batch_generate
    hook = generate_hook(contact, company_research, product_context)
"""

import logging
import os
import time
from typing import Any

from src import guards

logger = logging.getLogger(__name__)

# ── ICP Research Context ──────────────────────────────────────────────────────
# This is campaign-specific and has no safe generic default: a fabricated
# "target persona" would let the LLM invent plausible-sounding pain points,
# quotes, and vocabulary that aren't real — exactly what the grounding gate
# below (guards.grounding_check) exists to catch. So the default explicitly
# tells the model NOT to invent research when none was supplied, and callers
# (see /api/campaign/generate-hooks) should pass real ICP research per campaign.

_DEFAULT_ICP_RESEARCH = """
No target-persona research was provided for this campaign. Do not invent
industry-specific pain points, quotes, statistics, or vocabulary. Ground the
hook only in the contact's title and the company description given below.
"""

def _build_system_prompt(icp_research: str) -> str:
    return f"""You are a senior GTM engineer writing hyper-personalised cold email HOOKS.
A hook is the opening 1-2 sentences only — not a full email. It earns the right to be read.

ICP RESEARCH (ground your angles in this):
{icp_research}

HOOK RULES (non-negotiable):
- EXACTLY ONE SENTENCE. Never more. Period.
- The hook NAMES THE PROBLEM only. It does not solve it. It does not mention the product.
- Start with their first name
- Maximum 20 words after the name
- Plain vocabulary — every word a 14-year-old understands
- Pick ONE angle from these five tension categories:
    Risk: they've been burned by a past solution
    Effort: they're doing something manually they resent
    Time: a window is closing, a competitor is gaining
    Cost: specific dollars or deals bleeding monthly
    Identity: their credibility or board standing is at risk
- NEVER use: "leverage", "synergy", "quick question", "I wanted to reach out",
  "love what you're building", "hope this finds you", "just checking in"
- Subject line: under 8 words, no question mark, no exclamation mark

EXAMPLES of perfect hooks (one sentence, names the problem, stops):
  "Priya, most operations leads at your stage can't tell finance where the budget is actually leaking."
  "Marcus, half your team's week goes into a report that's outdated the moment it's shared."
  "Elena, the compliance deadline lands before your current process can catch up."

OUTPUT FORMAT (return exactly this JSON, nothing else):
{{
  "subject": "...",
  "body": "...",
  "angle": "Risk|Effort|Time|Cost|Identity",
  "word_count": 0
}}
"""

_DEFAULT_PRODUCT_CONTEXT = """
No product context was provided for this campaign. Reference only that the
sender has a relevant solution — do not invent a product name, features,
customers, or funding details.
"""


_ANGLE_INSTRUCTIONS: dict[str, str] = {
    "Risk": (
        "REQUIRED ANGLE: Risk — name a specific thing that is breaking or about to break. "
        "Reference what their company actually does and what could go wrong at their scale. "
        "Do NOT mention boards or AI ROI. Focus on operational risk: a bottleneck, a blind spot, "
        "a decision they're making without data. Example: 'Greg, you're shipping code review tooling "
        "but you have no visibility into whether your own team's review lag is slowing you down.'"
    ),
    "Effort": (
        "REQUIRED ANGLE: Effort — name something painful they're doing manually right now. "
        "Think about their role and company stage. What report are they pulling by hand? "
        "What meeting do they run that takes hours to prep for? What question can they not answer "
        "without Slack-threading 5 people? Be specific to their company. "
        "Example: 'Dan, every time your board asks about engineering velocity you spend a day "
        "pulling together a spreadsheet that's outdated before you share it.'"
    ),
    "Time": (
        "REQUIRED ANGLE: Time — a window is closing right now. A competitor is moving, "
        "a hiring surge is coming, a funding round is near. Be specific: mention their company, "
        "their stage, and the exact timing pressure. Do NOT be vague. "
        "Example: 'Greg, you're 3 months post-raise — the window to baseline your team's velocity "
        "before headcount doubles closes fast.'"
    ),
    "Cost": (
        "REQUIRED ANGLE: Cost — name a specific dollar amount, deal, or resource bleeding right now. "
        "This could be wasted AI tool spend, slow engineers costing them runway, missed deadlines. "
        "Be concrete: estimate the waste. Example: 'Ryan, at your burn rate, one engineer blocked "
        "on review lag for a week is $8k — and you can't see where it's happening.'"
    ),
    "Identity": (
        "REQUIRED ANGLE: Identity — their credibility with investors, board, or CEO is at risk. "
        "BUT: make it specific to their company and what they actually do — NOT a generic board ROI line. "
        "Reference their product, their stage, or a recent milestone. "
        "FORBIDDEN: 'your board will ask about AI ROI' — this is overused. Find a fresher angle. "
        "Example: 'Youssef, you're pitching investors on AI-first engineering — but you can't show "
        "them a single metric that proves it.'"
    ),
}


def _build_user_prompt(
    contact: dict[str, Any],
    company_research: dict[str, Any],
    product_context: str,
    force_angle: str | None = None,
) -> str:
    first = contact.get("first_name", "")
    title = contact.get("title", "")
    company_name = contact.get("company", "") or company_research.get("name", "")
    team_size = company_research.get("team_size", "")
    batch = company_research.get("batch", "")
    summary = company_research.get("research", {}).get("summary", "") or company_research.get("one_liner", "")
    # summary is scraped from the company's website — untrusted. Strip any
    # prompt-injection before it reaches the copywriting model.
    summary = guards.neutralize(summary)

    team_line = f"Team size: ~{team_size} people" if team_size else ""
    batch_line = f"YC batch: {batch}" if batch else ""

    angle_instruction = (
        _ANGLE_INSTRUCTIONS[force_angle]
        if force_angle and force_angle in _ANGLE_INSTRUCTIONS
        else "Pick the strongest angle from the five tension categories based on what you know about this company."
    )

    return f"""Write one cold email hook for this contact.

CONTACT:
- First name: {first}
- Title: {title}
- Company: {company_name}
{team_line}
{batch_line}

COMPANY DESCRIPTION:
{summary or "YC-backed AI/dev tool startup"}

PRODUCT TO PITCH:
{product_context}

ANGLE INSTRUCTION:
{angle_instruction}

The hook must reference what {company_name} actually does — not a generic CTO pain.
Return only the JSON object."""


def generate_hook(
    contact: dict[str, Any],
    company_research: dict[str, Any],
    product_context: str = _DEFAULT_PRODUCT_CONTEXT,
    icp_research: str = _DEFAULT_ICP_RESEARCH,
    api_key: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
    force_angle: str | None = None,
    enforce_bucket_minimum: int = 2,
) -> dict[str, Any]:
    """
    Generate one personalised email hook for a contact.

    Args:
        contact:                dict with first_name, title, company, email, linkedin_url
        company_research:       dict from icp_hunter + company_researcher
        product_context:        what's being pitched — name, positioning, differentiators.
                                No safe default; pass the real campaign's product or hooks
                                will explicitly avoid naming one (see _DEFAULT_PRODUCT_CONTEXT).
        icp_research:           target-persona research — pain points, vocabulary, triggers.
                                Same reasoning as product_context: no invented default.
        api_key:                Anthropic API key
        model:                  Claude model ID
        force_angle:            Force a specific tension angle
        enforce_bucket_minimum: Contacts below this personalization bucket are
                                returned as hold-back without calling the API.
                                Default: 2 (bucket-1 contacts never get a hook).

    Returns:
        {
            "subject": str,
            "body": str,
            "angle": str,
            "word_count": int,
            "contact_name": str,
            "company": str,
            "email": str,
            "linkedin_url": str,
            "ok": bool,
            "error": str | None,
        }
    """
    import re
    from src import llm_gateway, guards

    # ── 6-bucket personalization gate ─────────────────────────────────────────
    bucket = compute_personalization_bucket(contact, company_research)
    bucket_label = BUCKET_LABELS.get(bucket, "unknown")

    if bucket < enforce_bucket_minimum:
        return {
            **_error_result(contact, company_research,
                            f"Insufficient context (bucket {bucket}: {bucket_label}) — hold back"),
            "personalization_bucket": bucket,
            "personalization_label":  bucket_label,
            "hold_back":              True,
        }

    if not llm_gateway.is_available():
        return _error_result(contact, company_research,
                             "No LLM provider available (set GROQ/GEMINI/ANTHROPIC key or run Ollama)")

    user_prompt = _build_user_prompt(contact, company_research, product_context, force_angle)

    try:
        # Gateway: Groq/Gemini/Ollama/Anthropic + cache + budget. task="copy"
        # routes to the smart tier. api_key kept only for backwards compat —
        # gateway resolves providers from env.
        parsed = llm_gateway.complete_json(user_prompt, system=_build_system_prompt(icp_research),
                                           task="copy", max_tokens=400)
        if parsed is None:
            return _error_result(contact, company_research,
                                 "LLM returned no parseable hook")

        body = parsed.get("body", "")
        # Enforce one sentence — cut at first sentence-ending punctuation
        match = re.search(r'[.!?]', body)
        if match:
            body = body[:match.start() + 1].strip()

        # ── Grounding gate ────────────────────────────────────────────────────
        # An opener must reference a REAL, observed specific — not generic
        # flattery or a hallucinated fact. Verify the body quotes a distinctive
        # term from the evidence we actually hold.
        evidence_sources = [
            contact.get("company", "") or company_research.get("name", ""),
            contact.get("title", ""),
            company_research.get("one_liner", ""),
            company_research.get("research", {}).get("summary", ""),
        ]
        grounded, matched_term = guards.grounding_check(body, evidence_sources)

        return {
            "subject":      parsed.get("subject", ""),
            "body":         body,
            "angle":                  parsed.get("angle", ""),
            "word_count":             len(body.split()),
            "contact_name":           f"{contact.get('first_name','')} {contact.get('last_name','')}".strip(),
            "company":                contact.get("company", "") or company_research.get("name", ""),
            "title":                  contact.get("title", ""),
            "email":                  contact.get("email", ""),
            "linkedin_url":           contact.get("linkedin_url", ""),
            "personalization_bucket": bucket,
            "personalization_label":  bucket_label,
            "grounded":               grounded,
            "grounded_on":            matched_term,
            "hold_back":              False,
            "ok":                     True,
            "error":                  None,
        }

    except Exception as e:
        logger.error(f"[HookGen] Failed for {contact.get('first_name')} at {contact.get('company')}: {e}")
        return _error_result(contact, company_research, str(e))


def _error_result(
    contact: dict[str, Any],
    company_research: dict[str, Any],
    error: str,
) -> dict[str, Any]:
    return {
        "subject":      "",
        "body":         "",
        "angle":        "",
        "word_count":   0,
        "contact_name": f"{contact.get('first_name','')} {contact.get('last_name','')}".strip(),
        "company":      contact.get("company", "") or company_research.get("name", ""),
        "title":        contact.get("title", ""),
        "email":        contact.get("email", ""),
        "linkedin_url": contact.get("linkedin_url", ""),
        "ok":           False,
        "error":        error,
    }


# ── 6-Bucket Personalization System (ColdIQ pattern) ──────────────────────────
# Depth of personalization depends on available context.
# Bucket 1 = no context → hold back, do NOT send.
# Bucket 6 = deep research → highest open + reply rates.
#
# The bucket is exported alongside each hook so the SDR/sequence tool
# knows which contacts are ready to send and which need more research.

def compute_personalization_bucket(
    contact: dict,
    company_research: dict,
) -> int:
    """
    Score the available context depth for a contact.

    Returns:
        6 — Deep: LinkedIn activity + specific company metric + recent news
        5 — Signal-grounded: primary intent signal + company summary
        4 — Trigger-based: funding event or hiring burst
        3 — ICP-resonant: industry + role pain point only
        2 — Generic + social proof
        1 — No context — HOLD BACK, do not send
    """
    score = 0

    # Company context
    summary = (company_research.get("research", {}) or {}).get("summary", "") \
               or company_research.get("one_liner", "")
    if len(summary) > 80:     score += 2
    elif len(summary) > 20:   score += 1

    # Specific signal / trigger
    if company_research.get("batch"):       score += 1  # YC batch
    if company_research.get("team_size"):   score += 1
    if contact.get("linkedin_url"):         score += 1
    if contact.get("title"):                score += 1

    # Recent company news or research
    news = (company_research.get("research", {}) or {}).get("recent_news", [])
    if news:                                score += 1
    if len(news) >= 2:                      score += 1

    # Map raw score (0-8) to bucket 1-6
    if score <= 1:   return 1  # hold back
    if score <= 2:   return 2
    if score <= 3:   return 3
    if score <= 4:   return 4
    if score <= 6:   return 5
    return 6


BUCKET_LABELS = {
    6: "deep",
    5: "signal-grounded",
    4: "trigger-based",
    3: "icp-resonant",
    2: "generic",
    1: "hold-back",
}


_ANGLE_ROTATION = ["Time", "Risk", "Effort", "Cost", "Identity"]


def batch_generate(
    contacts: list[dict[str, Any]],
    company_map: dict[str, dict[str, Any]],
    product_context: str = _DEFAULT_PRODUCT_CONTEXT,
    icp_research: str = _DEFAULT_ICP_RESEARCH,
    api_key: str | None = None,
    delay: float = 0.3,
) -> list[dict[str, Any]]:
    """
    Generate hooks for a list of contacts, rotating through all 5 angles
    so no two consecutive contacts share the same angle.

    company_map: {company_name: company_research_dict}
    Returns list of hook dicts in same order as contacts.
    """
    results: list[dict[str, Any]] = []
    for i, contact in enumerate(contacts):
        co_name = contact.get("company", "")
        co_research = company_map.get(co_name, {"name": co_name})
        angle = _ANGLE_ROTATION[i % len(_ANGLE_ROTATION)]
        hook = generate_hook(contact, co_research, product_context, icp_research,
                             api_key=api_key, force_angle=angle)
        results.append(hook)
        if delay:
            time.sleep(delay)
    return results
