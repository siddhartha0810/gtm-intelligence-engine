"""
ats_signal.py
=============
ATS (Applicant Tracking System) intent signal — the highest signal-to-noise,
lowest-block source in the whole detection layer.

Companies on Greenhouse / Lever / Ashby / SmartRecruiters publish their OWN
open roles as clean public JSON. No scraping, no bot-blocking, ToS-clean —
the publisher WANTS the jobs found. A company hiring a "NetSuite
Administrator" or "Salesforce Developer" is telling you, first-party, which
systems it operates. That's a confirmed in-market signal Apollo can't see and
an HTML scraper can't reach.

Design learnings baked in (from live testing 3,200+ real postings):
  * TITLE-level match is signal; body mention is mostly noise. A query for
    "Salesforce" matched 134 postings by body but only ~7 by title — the 7
    were the real buyers (hiring someone to OPERATE Salesforce), the rest
    were AEs listing "CRM hygiene" as a nice-to-have. So we default to
    title-match only; body matches are opt-in via config.ATS_INCLUDE_BODY_MATCHES.
  * Endpoint failures are COVERAGE, not blocks — a 404 means the company uses
    a different ATS, not that we got blocked. Ramp/Notion 404 on Greenhouse
    but resolve on Ashby. So we try multiple ATS types, and a dead board just
    returns [].
  * Every emitted signal carries a verbatim evidence snippet so the downstream
    scorer/copywriter can quote the real observed signal, not hallucinate one.

Board registry lives in config.ATS_BOARDS (env-driven) — adding a company to
watch is a config entry, not a code change.
"""

from __future__ import annotations

import html
import re

import requests

from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, random_delay
from src import config

logger = get_logger(__name__)

_UA = "Mozilla/5.0 (compatible; oracle-intent-ats/1.0)"
_TIMEOUT = 15
_TAG_RE = re.compile(r"<[^>]+>")


def _get_json(url: str):
    """GET + parse JSON. Returns None on any failure — never raises."""
    try:
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        logger.debug("[ats] fetch failed %s: %s", url, e)
        return None


def _strip_html(s: str) -> str:
    if not s:
        return ""
    return clean_text(_TAG_RE.sub(" ", html.unescape(s)))


def _slug_to_name(slug: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_]", slug) if w)


# ── Adapters — each returns a list of raw posting dicts with a common shape ────
# {company, title, text, url, location, posted_at}

def _fetch_greenhouse(token: str, max_jobs: int) -> list[dict]:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    if not data or "jobs" not in data:
        return []
    jobs = data["jobs"][:max_jobs]
    company = (jobs[0].get("company_name") if jobs else "") or _slug_to_name(token)
    out = []
    for j in jobs:
        out.append({
            "company":   company,
            "title":     j.get("title", "") or "",
            "text":      _strip_html(j.get("content", "") or ""),
            "url":       j.get("absolute_url", "") or "",
            "location":  (j.get("location") or {}).get("name", "") or "",
            "posted_at": j.get("updated_at", "") or j.get("first_published", "") or "",
        })
    return out


def _fetch_lever(token: str, max_jobs: int) -> list[dict]:
    data = _get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    if not isinstance(data, list):
        return []
    company = _slug_to_name(token)
    out = []
    for p in data[:max_jobs]:
        cat = p.get("categories") or {}
        out.append({
            "company":   company,
            "title":     p.get("text", "") or "",
            "text":      clean_text(p.get("descriptionPlain", "") or ""),
            "url":       p.get("hostedUrl", "") or "",
            "location":  cat.get("location", "") or "",
            "posted_at": "",
        })
    return out


def _fetch_ashby(token: str, max_jobs: int) -> list[dict]:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    if not data or "jobs" not in data:
        return []
    company = _slug_to_name(token)
    out = []
    for j in data["jobs"][:max_jobs]:
        loc = j.get("location", "") or ""
        if isinstance(loc, dict):
            loc = loc.get("name", "") or ""
        out.append({
            "company":   company,
            "title":     j.get("title", "") or "",
            "text":      clean_text(j.get("descriptionPlain", "") or ""),
            "url":       j.get("jobUrl", "") or j.get("applyUrl", "") or "",
            "location":  loc,
            "posted_at": j.get("publishedAt", "") or "",
        })
    return out


def _fetch_smartrecruiters(token: str, max_jobs: int) -> list[dict]:
    # List endpoint is title-only (no body) — perfect for title-level intent.
    data = _get_json(f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100")
    if not data or "content" not in data:
        return []
    out = []
    for p in data["content"][:max_jobs]:
        loc = p.get("location") or {}
        company = (p.get("company") or {}).get("name") or _slug_to_name(token)
        out.append({
            "company":   company,
            "title":     p.get("name", "") or "",
            "text":      "",  # list mode has no description; title carries the signal
            "url":       (p.get("ref", "") or "").replace("api.smartrecruiters.com/v1",
                                                          "jobs.smartrecruiters.com"),
            "location":  loc.get("fullLocation", "") or loc.get("city", "") or "",
            "posted_at": p.get("releasedDate", "") or "",
        })
    return out


_ADAPTERS = {
    "greenhouse":      _fetch_greenhouse,
    "lever":           _fetch_lever,
    "ashby":           _fetch_ashby,
    "smartrecruiters": _fetch_smartrecruiters,
}


def _evidence_snippet(text: str, keyword: str, span: int = 60) -> str:
    idx = text.lower().find(keyword.lower())
    if idx < 0:
        return ""
    start = max(0, idx - span)
    end = min(len(text), idx + len(keyword) + span)
    return ("..." if start > 0 else "") + text[start:end].strip() + ("..." if end < len(text) else "")


def _merged_boards() -> list[dict]:
    """Config default boards + auto-discovered registry (database.ats_boards),
    deduped by ats:token. DB access is best-effort — if it's unavailable
    (e.g. guided_run with no DB), fall back to config alone."""
    boards = list(getattr(config, "ATS_BOARDS", []))
    # Dedup case-insensitively on both ats and token (ATS tokens are
    # case-insensitive, so "Ramp" and "ramp" are the same board).
    seen = {f"{b.get('ats','').lower()}:{b.get('token','').lower()}" for b in boards}
    try:
        from src import database as db
        for r in db.get_ats_boards(active_only=True):
            key = f"{(r.get('ats') or '').lower()}:{(r.get('token') or '').lower()}"
            if key not in seen and r.get("ats") and r.get("token"):
                seen.add(key)
                boards.append({"ats": r["ats"], "token": r["token"]})
    except Exception as e:
        logger.debug("[ats] registry unavailable, using config boards only: %s", e)
    return boards


class ATSSignal(BaseSignal):
    source_name = "ats"

    def fetch(self, query: str = "", location: str = "", max_pages: int = 3,
              keywords: list[str] | None = None) -> list[dict]:
        """
        Pull open roles from every configured ATS board and emit a signal for
        each posting whose TITLE (or body, if enabled) matches an intent
        keyword. `keywords` comes from the campaign; falls back to [query].
        """
        boards = _merged_boards()
        if not boards:
            return []

        intent = [k.strip() for k in (keywords or ([query] if query else [])) if k and k.strip()]
        if not intent:
            return []  # ATS without an intent keyword set would emit every job — refuse

        include_body = bool(getattr(config, "ATS_INCLUDE_BODY_MATCHES", False))
        max_jobs = int(getattr(config, "ATS_MAX_JOBS_PER_BOARD", 300))

        signals: list[dict] = []
        for board in boards:
            ats = (board.get("ats") or "").lower()
            token = board.get("token") or ""
            adapter = _ADAPTERS.get(ats)
            if not adapter or not token:
                continue

            try:
                postings = adapter(token, max_jobs)
            except Exception as e:
                logger.debug("[ats] adapter %s/%s failed: %s", ats, token, e)
                continue

            for p in postings:
                title_l = p["title"].lower()
                body_l = p["text"].lower()

                matched_kw = next((k for k in intent if k.lower() in title_l), None)
                match_where = "title"
                if not matched_kw and include_body:
                    matched_kw = next((k for k in intent if k.lower() in body_l), None)
                    match_where = "body"
                if not matched_kw:
                    continue

                if location and location.lower() not in (p["location"] or "").lower():
                    # location filter is best-effort — skip only if a filter was given
                    if p["location"]:
                        continue

                evidence = _evidence_snippet(p["text"] or p["title"], matched_kw)
                signals.append(self._make_signal(
                    company_name=p["company"],
                    job_title=p["title"],
                    description=truncate(p["text"] or p["title"], 2000),
                    url=p["url"],
                    location=p["location"],
                    posted_date=p["posted_at"],
                    extra={
                        "signal_type":  "ats_hiring",
                        "ats":          ats,
                        "matched_keyword": matched_kw,
                        "match_where":  match_where,   # "title" = high signal, "body" = weak
                        "evidence":     evidence,
                    },
                ))

            random_delay(0.3, 0.8)  # polite pause between boards

        logger.info("[ats] %d boards → %d intent signals (keywords=%s)",
                    len(boards), len(signals), intent[:5])
        return signals
