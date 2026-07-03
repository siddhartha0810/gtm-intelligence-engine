"""
ats_discovery.py
================
Auto-discovers which ATS platform a company uses and its board token, so the
ATS watch-list builds itself instead of being hand-seeded.

Given a company name, it generates candidate slugs (the token most companies
use is a predictable normalization of their name) and light-probes each ATS
endpoint. A 200 with open jobs = a match. Where the endpoint returns the
company's own name (Greenhouse, SmartRecruiters), the match is name-verified
to avoid a slug collision with an unrelated company.

This is the moat: whoever holds the biggest, freshest company→ATS map has the
widest unblockable intent net. Every company the pipeline detects via any
signal can have its ATS board discovered, so future scans pull its live
hiring signals first-party.

Never raises — a company with no discoverable board returns None.
"""

from __future__ import annotations

import re

import requests

from src.utils import get_logger

logger = get_logger(__name__)

_UA = "Mozilla/5.0 (compatible; oracle-intent-ats-discovery/1.0)"
_TIMEOUT = 10

# Corporate suffixes to strip before slugging
_SUFFIXES = {"inc", "llc", "ltd", "corp", "co", "company", "group", "holdings",
             "gmbh", "sa", "plc", "labs", "technologies", "technology", "the"}


def _norm_words(company: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s-]", " ", company.lower())
    words = [w for w in re.split(r"[\s-]+", cleaned) if w and w not in _SUFFIXES]
    return words


def _slug_candidates(company: str) -> list[str]:
    """Ordered most-likely-first. Joined form matches most tech companies;
    hyphenated and first-word forms cover the rest."""
    words = _norm_words(company)
    if not words:
        return []
    cands: list[str] = []
    joined = "".join(words)
    hyphen = "-".join(words)
    for c in (joined, hyphen, words[0]):
        if c and c not in cands:
            cands.append(c)
    return cands


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _name_matches(query: str, returned: str) -> bool:
    """Fuzzy: one normalized name contains the other (handles 'Stripe' vs
    'Stripe Payments'). Empty returned name = can't verify → treat as ok."""
    if not returned:
        return True
    q, r = _norm_name(query), _norm_name(returned)
    return bool(q and r) and (q in r or r in q)


def _get(url: str):
    try:
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


# ── Per-ATS light probes: return (job_count, returned_company_name) or None ───

def _probe_greenhouse(token: str):
    d = _get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
    if not d or not d.get("jobs"):
        return None
    name = (d["jobs"][0].get("company_name") or "")
    return len(d["jobs"]), name


def _probe_lever(token: str):
    d = _get(f"https://api.lever.co/v0/postings/{token}?mode=json")
    if not isinstance(d, list) or not d:
        return None
    return len(d), ""   # lever doesn't return a company name; slug is identity


def _probe_ashby(token: str):
    d = _get(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    if not d or not d.get("jobs"):
        return None
    return len(d["jobs"]), ""


def _probe_smartrecruiters(token: str):
    d = _get(f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=1")
    if not d or not d.get("content"):
        return None
    total = int(d.get("totalFound") or len(d["content"]))
    name = (d["content"][0].get("company") or {}).get("name", "")
    return total, name


_PROBES = {
    "greenhouse":      _probe_greenhouse,
    "lever":           _probe_lever,
    "ashby":           _probe_ashby,
    "smartrecruiters": _probe_smartrecruiters,
}
# Order matters: most common first, so we stop early on the likely platform.
_ATS_ORDER = ["greenhouse", "lever", "ashby", "smartrecruiters"]


def discover_board(company_name: str) -> dict | None:
    """
    Probe every ATS with every candidate slug; return the first live board.
    Result: {company, ats, token, job_count, verified}. None if none found.
    verified=True means the endpoint's own company name matched the query.
    """
    if not company_name or not company_name.strip():
        return None
    candidates = _slug_candidates(company_name)

    for ats in _ATS_ORDER:
        probe = _PROBES[ats]
        for slug in candidates:
            try:
                res = probe(slug)
            except Exception:
                res = None
            if not res:
                continue
            job_count, returned_name = res
            # For the risky first-word-only candidate, require a name match to
            # avoid grabbing an unrelated company's board.
            is_firstword = slug == candidates[-1] and len(candidates) > 1
            verified = _name_matches(company_name, returned_name)
            if is_firstword and not verified:
                continue
            logger.info("[ats-discovery] %s → %s:%s (%d jobs, verified=%s)",
                        company_name, ats, slug, job_count, verified)
            return {
                "company":   company_name.strip(),
                "ats":       ats,
                "token":     slug,
                "job_count": job_count,
                "verified":  verified,
            }
    logger.debug("[ats-discovery] no board found for %s", company_name)
    return None


def discover_boards(company_names: list[str]) -> list[dict]:
    """Discover boards for a list of companies. Returns the found boards
    (companies with no board are simply omitted)."""
    found = []
    for name in company_names:
        board = discover_board(name)
        if board:
            found.append(board)
    return found
