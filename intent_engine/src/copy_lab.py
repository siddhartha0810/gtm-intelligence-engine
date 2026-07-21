"""
copy_lab.py
===========
Multi-framework cold-email variant generation with a research-grounded judge.

WHY THIS EXISTS
  A single prompt produces a single email and you never learn whether a
  different structure would have done better. This module generates the SAME
  email under three competing frameworks, scores every variant against a
  rubric built from published cold-email data, and keeps the winner — while
  persisting the losers with their scores, so the choice is auditable rather
  than asserted.

THE RUBRIC IS EVIDENCE-BASED, NOT TASTE
  Every deterministic gate below traces to a published finding:

  * Interest-CTA over a meeting/time ask.
      Gong, ~304K prospecting emails: interest-based CTAs outperform asks for
      time on cold outreach ("interest" is not a finite resource the way a
      calendar slot is). The specific day/time ask wins only AFTER the
      prospect is in-cycle.
  * First touch <= ~75 words.
      Gong: highest reply rates land under 100 words / 3-4 sentences. We use
      75 as the target so there is headroom before the cliff.
  * Reading level <= grade 6 (Flesch-Kincaid).
      Lavender, ~231K emails: copy at a 3rd-5th grade reading level sees
      materially more replies; ~70% of cold email is written at grade 10+.
      Computed here with a real FK implementation, not an LLM's guess about
      its own output.
  * Names the specific, dated event.
      Trigger/signal-based outreach reply lift is the one thing our pipeline
      can prove with a citation. NOTE: the widely-quoted "signal-based gets
      15-25%" figures come from vendor marketing with undisclosed method —
      treated here as directional only. The gate rewards naming the event
      because it is FALSIFIABLE, which is the defensible reason.

  The judge (an LLM) only scores the things a regex cannot: whether the
  observation is genuinely specific to this account, and whether a busy CRO
  would actually reply. Everything mechanical is scored mechanically.

FRAMEWORKS
  PAS        Problem -> Agitate -> Solve. Strong with signal, but buries the
             evidence behind an asserted pain and can read manipulative.
  OIQ        Observation -> Implication -> Question. Leads with the cited
             fact. Best fit when the evidence IS the asset (our case).
  CHALLENGER Insight-led reframe — teach them something about their own
             business, then connect it to the observation.

Never raises: a failed variant scores 0 and is kept in the record as failed.
"""

from __future__ import annotations

import json
import re
from typing import Any

# ── Deterministic text metrics ────────────────────────────────────────────────

_VOWELS = "aeiouy"


def _syllables(word: str) -> int:
    """Approximate syllable count — standard heuristic used by FK implementations."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    count, prev_vowel = 0, False
    for ch in w:
        is_vowel = ch in _VOWELS
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if w.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def flesch_kincaid_grade(text: str) -> float:
    """US grade level. 0.39*(words/sentences) + 11.8*(syllables/words) - 15.59."""
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"[A-Za-z']+", text)
    if not sentences or not words:
        return 0.0
    syl = sum(_syllables(w) for w in words)
    return round(0.39 * (len(words) / len(sentences)) + 11.8 * (syl / len(words)) - 15.59, 1)


# Phrases that ask for the prospect's TIME (weaker on cold, per Gong) vs.
# phrases that ask only for INTEREST (stronger on cold).
_TIME_ASK = re.compile(
    r"\b(\d+\s*(min|minute|minutes)|quick call|hop on a call|book a|schedule a|"
    r"grab (?:15|20|30)|calendar|meeting|demo|chat (?:this|next) week)\b", re.I)
_INTEREST_ASK = re.compile(
    r"(worth a look|want me to send|should i send|open to seeing|interested in seeing|"
    r"want the|worth sharing|shall i send|curious|make sense to|worth exploring|"
    r"want to see)", re.I)

_BANNED = [
    "leverage", "synergy", "quick question", "i wanted to reach out",
    "love what you're building", "hope this finds you", "just checking in",
    "circling back", "touching base", "i hope you're well",
]


def deterministic_scores(subject: str, body: str, evidence_text: str,
                          contact_first: str = "") -> dict[str, Any]:
    """Everything measurable without an LLM. Returns per-gate pass/fail plus
    a 0-60 mechanical score. The LLM judge adds up to 40 more."""
    full = f"{body}"
    words = re.findall(r"[A-Za-z']+", full)
    wc = len(words)
    fk = flesch_kincaid_grade(full)

    # Does the copy name a distinctive, checkable term from the evidence?
    # (Company name alone does NOT count — that's the failure mode we already
    # documented: "Qualys can't predict churn" name-drops and says nothing.)
    stop = {contact_first.lower(), "the", "and", "your", "you", "with", "that",
            "this", "have", "for", "are", "can", "not", "but", "their", "they"}
    ev_terms = {t.lower() for t in re.findall(r"[A-Za-z0-9][\w'\-\.]{3,}", evidence_text or "")}
    ev_terms -= stop
    body_terms = {t.lower() for t in re.findall(r"[A-Za-z0-9][\w'\-\.]{3,}", full)}
    matched = sorted(ev_terms & body_terms)
    # A date or number in the copy is the strongest falsifiability marker
    has_date_or_number = bool(re.search(r"\b(\d{1,3}%|\$\d|\b\d{1,4}\b|last (month|quarter|week)|"
                                        r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", full, re.I))

    time_ask = bool(_TIME_ASK.search(full))
    interest_ask = bool(_INTEREST_ASK.search(full))
    banned_hit = [b for b in _BANNED if b in full.lower()]

    gates = {
        "length_ok":       wc <= 75 and wc >= 8,
        "reading_level_ok": fk <= 6.0,
        "interest_cta":    interest_ask and not time_ask,
        "names_evidence":  len(matched) > 0,
        "falsifiable":     has_date_or_number or len(matched) >= 2,
        "no_banned_vocab": not banned_hit,
    }
    # 10 points per gate = 60 mechanical max
    score = sum(10 for v in gates.values() if v)
    return {
        "gates": gates, "mechanical_score": score,
        "word_count": wc, "fk_grade": fk,
        "matched_evidence_terms": matched[:6],
        "banned_hits": banned_hit,
        "time_ask": time_ask, "interest_ask": interest_ask,
    }


def _ensure_named_opening(body: str, first: str) -> str:
    """Mechanically guarantee direct address by first name — the prompt asks
    for it, but under thin evidence the model sometimes drops it to save
    words. hook_generator.py enforced this the same way (never left to the
    model alone); copy_lab didn't, which is why early bake-off winners read
    as generic despite passing every other gate. A body already opening with
    the name is left untouched."""
    b = (body or "").strip()
    if not first or not b:
        return b
    if re.match(rf"^{re.escape(first)}\b", b, re.I):
        return b
    lead = b[0].lower() + b[1:] if b[:1].isupper() and not b[:2].isupper() else b
    return f"{first}, {lead}"


# ── Framework prompts ─────────────────────────────────────────────────────────

_SHARED_RULES = """
HARD RULES (these are scored mechanically after you write — violating them loses):
- Body MUST open with the contact's first name as direct address, e.g. "Yasuyuki, ..." —
  not buried later, not "Hi Yasuyuki," as a greeting. This is enforced mechanically after
  generation if you skip it, but the sentence reads better when you write it this way
  yourself rather than having it grafted on.
- Body <= 75 words. Shorter wins ties.
- Reading level: US grade 6 or below. Short words, short sentences. No jargon
  ("leverage", "utilize", "predictive revenue intelligence" -> say it plainly).
- MUST name the specific event from the EVIDENCE, in plain words, ideally with
  its date or number. The company name alone is NOT specificity.
- CTA must ask for INTEREST, never for time. Good: "Want me to send what we
  found?" / "Worth a look?" Bad: "15 minutes?" / "book a call" / "quick chat".
- Never invent a fact, number, date or quote that is not in the EVIDENCE.
- Never use: leverage, synergy, quick question, I wanted to reach out, love
  what you're building, hope this finds you, just checking in, circling back.
- Subject: under 7 words, no "?" and no "!".
Return ONLY JSON: {"subject": "...", "body": "..."}
"""

FRAMEWORKS: dict[str, str] = {
    "OIQ": """You write B2B cold emails using OBSERVATION -> IMPLICATION -> QUESTION.
Sentence 1: state the observed, dated fact from the EVIDENCE. Neutral, no drama.
Sentence 2: what that usually means for someone in their seat (the implication).
Sentence 3: one question that asks for interest.
Lead with the fact. Do not assert a pain you cannot see.
""" + _SHARED_RULES,

    "PAS": """You write B2B cold emails using PROBLEM -> AGITATE -> SOLVE.
Sentence 1: name the problem, anchored to the specific event in the EVIDENCE.
Sentence 2: the cost of leaving it alone — concrete, not dramatic.
Sentence 3: one line on the fix + a question asking for interest.
Do not manufacture urgency the evidence does not support.
""" + _SHARED_RULES,

    "CHALLENGER": """You write B2B cold emails using an INSIGHT-LED REFRAME.
Sentence 1: a specific, non-obvious insight about how companies like theirs
  actually lose revenue — something they likely have not framed this way.
Sentence 2: tie it to the observed event in the EVIDENCE.
Sentence 3: one question asking for interest.
Teach, do not pitch. The insight must be defensible, not a platitude.
""" + _SHARED_RULES,
}

_JUDGE_SYSTEM = """You are a hard-to-impress CRO at a 300-person B2B SaaS company.
You get 40+ cold emails a day. Score ONE email on things a regex cannot measure.

Score each 0-10 (be stingy; 7+ means genuinely good):
- specificity: does it reference something true and particular to MY company,
  not a category truism? A line that would read identically for any company
  in my industry scores 0-2.
- credibility: does it sound like a person who did the work, or like a
  template? Manufactured urgency, flattery, or vague claims score low.
- reply_likelihood: would I actually reply? Not "is it well written" — would
  I type a response.

Return ONLY JSON:
{"specificity": n, "credibility": n, "reply_likelihood": n, "verdict": "<12 words why>"}
"""


def _judge(subject: str, body: str, evidence_text: str, title: str, company: str) -> dict:
    from src import llm_gateway
    prompt = (f"My title: {title} at {company}\n"
              f"What is actually true about my company (the sender's evidence):\n{evidence_text}\n\n"
              f"THE EMAIL\nSubject: {subject}\nBody: {body}")
    parsed = llm_gateway.complete_json(prompt, system=_JUDGE_SYSTEM, task="reason", max_tokens=200)
    if not isinstance(parsed, dict):
        return {"specificity": 0, "credibility": 0, "reply_likelihood": 0,
                "verdict": "judge unavailable", "judge_score": 0}
    s = max(0, min(10, int(parsed.get("specificity", 0) or 0)))
    c = max(0, min(10, int(parsed.get("credibility", 0) or 0)))
    r = max(0, min(10, int(parsed.get("reply_likelihood", 0) or 0)))
    # Weighted mean of three 0-10 scores (reply_likelihood double — it's the
    # outcome we want), then scaled to a 0-40 band so mechanical (0-60) + judge
    # (0-40) = a clean 0-100 total.
    weighted_mean = (s + c + r * 2) / 4        # 0-10
    return {"specificity": s, "credibility": c, "reply_likelihood": r,
            "verdict": str(parsed.get("verdict", ""))[:120],
            "judge_score": round(weighted_mean * 4)}  # 0-40


def generate_variants(contact: dict, evidence_text: str, product_context: str,
                      frameworks: list[str] | None = None) -> list[dict]:
    """One variant per framework, each fully scored. Sorted best-first.
    Never raises — a failed generation is returned with score 0 and an error."""
    from src import llm_gateway

    frameworks = frameworks or list(FRAMEWORKS.keys())
    first = (contact.get("first_name") or "").strip()
    company = contact.get("company", "")
    title = contact.get("title", "")

    user_prompt = (
        f"WRITE TO: {first} {contact.get('last_name','')}, {title} at {company}\n\n"
        f"EVIDENCE (everything you may claim must come from here):\n{evidence_text}\n\n"
        f"WHAT WE SELL (use plain words, not this marketing phrasing):\n{product_context}\n"
    )

    out: list[dict] = []
    for fw in frameworks:
        rec: dict[str, Any] = {"framework": fw, "subject": "", "body": "", "error": ""}
        try:
            if not llm_gateway.is_available():
                raise RuntimeError("no LLM provider available")
            parsed = llm_gateway.complete_json(
                user_prompt, system=FRAMEWORKS[fw], task="copy", max_tokens=400)
            if not isinstance(parsed, dict):
                raise RuntimeError("model returned no JSON")
            rec["subject"] = str(parsed.get("subject", "")).strip()
            rec["body"] = re.sub(r"\s+", " ", str(parsed.get("body", ""))).strip()
            rec["body"] = _ensure_named_opening(rec["body"], first)
        except Exception as e:  # never raise — a dead variant is data too
            rec["error"] = str(e)[:120]

        if rec["body"]:
            det = deterministic_scores(rec["subject"], rec["body"], evidence_text, first)
            rec.update(det)
            j = _judge(rec["subject"], rec["body"], evidence_text, title, company)
            rec["judge"] = j
            rec["total_score"] = det["mechanical_score"] + j["judge_score"]
        else:
            rec.update({"gates": {}, "mechanical_score": 0, "word_count": 0, "fk_grade": 0.0,
                        "matched_evidence_terms": [], "banned_hits": [],
                        "judge": {"judge_score": 0, "verdict": rec["error"] or "no output"},
                        "total_score": 0})
        out.append(rec)

    out.sort(key=lambda r: r["total_score"], reverse=True)
    return out
