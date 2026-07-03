"""
cadence_builder.py
==================
Generates a full 5-touch multichannel outreach sequence per contact using
Claude Haiku, starting from the hook already created by hook_generator.py.

Touch structure (proven B2B SaaS cadence):
  Day 1  → Email 1      : The personalised hook (already generated)
  Day 3  → LinkedIn     : Connection request with 1-line note
  Day 5  → Email 2      : Value-add follow-up (different angle, no "just checking in")
  Day 8  → LinkedIn msg : Reference the connection, 1 question
  Day 12 → Email 3      : Closing-the-loop breakup (makes it easy to say no)

Output format: list of touch dicts, one sequence per contact.
Also exports as Apollo-compatible CSV for direct sequence upload.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior B2B outbound specialist building multichannel sequences.
You have already written the opening email hook for this contact. Now build touches 2-5.

RULES (non-negotiable):
- LinkedIn note (touch 2): MAX 300 characters. No pitch — just earn the connection.
- Email follow-up (touch 3): 2 sentences max. New angle — NOT a repeat of touch 1. Add a specific value (stat, insight, peer example). Never "just following up" or "circling back".
- LinkedIn message (touch 4): 1 sentence referencing the connection. Ask 1 yes/no question.
- Breakup email (touch 5): 1-2 sentences. Make it easy to say no. Closes the loop — never desperate.

Each touch must reference what the COMPANY actually does. Not generic.
Subject lines: under 8 words, no question mark, no exclamation mark.

Return EXACTLY this JSON (no markdown, no extra keys):
{
  "touch_2_linkedin_note": "...",
  "touch_3_email_subject": "...",
  "touch_3_email_body": "...",
  "touch_4_linkedin_msg": "...",
  "touch_5_email_subject": "...",
  "touch_5_email_body": "..."
}"""


def build_sequence(
    hook: dict[str, Any],
    api_key: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
) -> dict[str, Any]:
    """
    Generate touches 2–5 for a contact whose touch 1 hook is already in `hook`.

    Args:
        hook: A hook dict from hook_generator.generate_hook()
        api_key: Anthropic API key
        model: Claude model to use

    Returns:
        {
            "contact_name": str,
            "company": str,
            "email": str,
            "linkedin_url": str,
            "touches": [
                {"day": 1,  "channel": "email",    "subject": ..., "body": ...},
                {"day": 3,  "channel": "linkedin",  "body": ...},
                {"day": 5,  "channel": "email",    "subject": ..., "body": ...},
                {"day": 8,  "channel": "linkedin",  "body": ...},
                {"day": 12, "channel": "email",    "subject": ..., "body": ...},
            ],
            "ok": bool,
            "error": str | None,
        }
    """
    from src import llm_gateway

    if not hook.get("ok"):
        return _error(hook, "Source hook failed — no content to build sequence from")

    if not llm_gateway.is_available():
        return _error(hook, "No LLM provider available (set GROQ/GEMINI/ANTHROPIC key or run Ollama)")

    first_name   = (hook.get("contact_name") or "").split()[0]
    company      = hook.get("company", "")
    title        = hook.get("title", "")
    hook_subject = hook.get("subject", "")
    hook_body    = hook.get("body", "")
    angle        = hook.get("angle", "")

    user_prompt = f"""Contact: {first_name}, {title} at {company}
Touch 1 already written:
  Subject: {hook_subject}
  Body: {hook_body}
  Angle used: {angle}

Build touches 2–5 for this contact. Reference what {company} actually does.
Avoid repeating the {angle} angle — use a different one for touch 3."""

    try:
        parsed = llm_gateway.complete_json(user_prompt, system=_SYSTEM_PROMPT,
                                           task="copy", max_tokens=600)
        if parsed is None:
            return _error(hook, "LLM returned no parseable sequence")

        touches = [
            {
                "day":     1,
                "channel": "email",
                "subject": hook_subject,
                "body":    hook_body,
                "notes":   f"Angle: {angle}",
            },
            {
                "day":     3,
                "channel": "linkedin_connect",
                "subject": "",
                "body":    parsed.get("touch_2_linkedin_note", ""),
                "notes":   "LinkedIn connection request — 300 char limit",
            },
            {
                "day":     5,
                "channel": "email",
                "subject": parsed.get("touch_3_email_subject", ""),
                "body":    parsed.get("touch_3_email_body", ""),
                "notes":   "Follow-up — new angle, value-add",
            },
            {
                "day":     8,
                "channel": "linkedin_message",
                "subject": "",
                "body":    parsed.get("touch_4_linkedin_msg", ""),
                "notes":   "LinkedIn DM after connection accepted",
            },
            {
                "day":     12,
                "channel": "email",
                "subject": parsed.get("touch_5_email_subject", ""),
                "body":    parsed.get("touch_5_email_body", ""),
                "notes":   "Closing the loop — breakup email",
            },
        ]

        return {
            "contact_name": hook.get("contact_name", ""),
            "company":      company,
            "email":        hook.get("email", ""),
            "linkedin_url": hook.get("linkedin_url", ""),
            "title":        title,
            "touches":      touches,
            "ok":           True,
            "error":        None,
        }

    except Exception as e:
        logger.error("[CadenceBuilder] Failed for %s at %s: %s", first_name, company, e)
        return _error(hook, str(e))


def _error(hook: dict, msg: str) -> dict:
    return {
        "contact_name": hook.get("contact_name", ""),
        "company":      hook.get("company", ""),
        "email":        hook.get("email", ""),
        "linkedin_url": hook.get("linkedin_url", ""),
        "title":        hook.get("title", ""),
        "touches":      [],
        "ok":           False,
        "error":        msg,
    }


def batch_build_sequences(
    hooks: list[dict[str, Any]],
    api_key: str | None = None,
    delay: float = 0.3,
) -> list[dict[str, Any]]:
    """
    Build full sequences for a list of hooks.
    Only processes hooks where ok=True.
    """
    results = []
    for hook in hooks:
        seq = build_sequence(hook, api_key=api_key)
        results.append(seq)
        if delay and hook.get("ok"):
            time.sleep(delay)
    return results


def sequences_to_csv_rows(sequences: list[dict[str, Any]]) -> list[dict]:
    """
    Flatten sequences to CSV rows — one row per touch.
    Compatible with Apollo sequence import format.
    """
    rows = []
    for seq in sequences:
        if not seq.get("ok"):
            continue
        for touch in seq.get("touches", []):
            rows.append({
                "Contact Name":  seq["contact_name"],
                "Company":       seq["company"],
                "Email":         seq["email"],
                "LinkedIn URL":  seq["linkedin_url"],
                "Title":         seq["title"],
                "Day":           touch["day"],
                "Channel":       touch["channel"],
                "Subject":       touch.get("subject", ""),
                "Body":          touch.get("body", ""),
                "Notes":         touch.get("notes", ""),
            })
    return rows
