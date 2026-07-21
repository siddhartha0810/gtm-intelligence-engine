"""
data_quality.py
===============
Data Quality Engine — runs before any record enters the Review Queue.

Checks:
  1. Mandatory fields (name for company; first_name + last_name for contact)
  2. Email format validation (regex)
  3. Domain format validation
  4. Duplicate detection — fuzzy match against existing companies / contacts
  5. Suspicious data flags (all-caps, placeholder values, test data)

Each issue has:
  severity: "critical" | "warning" | "info"
  code:     machine-readable code (e.g. "missing_name", "duplicate_company")
  message:  human-readable description
  field:    the field that triggered the issue (if applicable)

Critical issues block the record from being approved.
Warnings appear in the Review Queue for human judgment.
Info items are surfaced in the slide-over detail panel.
"""

import re
from typing import Optional

import intent_engine.src.database as db

# ── Regex validators ──────────────────────────────────────────────────────────
_EMAIL_RE  = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?(\.[a-z]{2,})+$")
_PLACEHOLDER = {"test", "example", "sample", "demo", "fake", "dummy", "n/a", "na", "tbd", "xxx"}


def _issue(severity: str, code: str, message: str, field: str = "") -> dict:
    return {"severity": severity, "code": code, "message": message, "field": field}


# ── Company DQE ───────────────────────────────────────────────────────────────

def run_dqe_on_company(record: dict) -> list:
    issues = []
    name   = str(record.get("name") or "").strip()
    domain = str(record.get("domain") or "").strip().lower()

    # Mandatory
    if not name:
        issues.append(_issue("critical", "missing_name", "Company name is required", "name"))
        return issues  # nothing else to check

    # Placeholder detection
    if name.lower() in _PLACEHOLDER:
        issues.append(_issue("critical", "placeholder_name", f"'{name}' looks like placeholder data", "name"))

    # ALL CAPS
    if name == name.upper() and len(name) > 3:
        issues.append(_issue("warning", "all_caps_name", "Company name is all-caps — verify formatting", "name"))

    # Domain format
    if domain:
        clean = re.sub(r"^https?://", "", domain).lstrip("www.").split("/")[0]
        if not _DOMAIN_RE.match(clean):
            issues.append(_issue("warning", "invalid_domain", f"Domain '{domain}' format looks invalid", "domain"))

    # Duplicate detection — exact + fuzzy match
    dup = _find_duplicate_company(name)
    if dup:
        issues.append(_issue(
            "warning", "duplicate_company",
            f"Possible duplicate: existing company '{dup['name']}' (id={dup['id']})",
            "name",
        ))

    return issues


def _find_duplicate_company(name: str) -> Optional[dict]:
    """Check for exact name match or high-similarity match."""
    clean = _normalise(name)
    with db.db_cursor(commit=False) as cur:
        # Exact normalised match
        cur.execute(
            "SELECT id, name FROM companies WHERE LOWER(REGEXP_REPLACE(name, '[^a-z0-9]', '', 'gi')) = %s LIMIT 1",
            (re.sub(r"[^a-z0-9]", "", clean),),
        )
        row = cur.fetchone()
        if row:
            return dict(row)

        # Trigram-like: check if cleaned name is substring of any existing company (and vice versa)
        cur.execute(
            """SELECT id, name FROM companies
               WHERE LOWER(name) LIKE %s OR %s LIKE CONCAT('%%', LOWER(name), '%%')
               LIMIT 1""",
            (f"%{clean}%", clean),
        )
        row = cur.fetchone()
    return dict(row) if row else None


# ── Contact DQE ───────────────────────────────────────────────────────────────

def run_dqe_on_contact(record: dict) -> list:
    issues = []
    first = str(record.get("first_name") or "").strip()
    last  = str(record.get("last_name")  or "").strip()
    email = str(record.get("email")      or "").strip().lower()

    # Mandatory
    if not first:
        issues.append(_issue("critical", "missing_first_name", "First name is required", "first_name"))
    if not last:
        issues.append(_issue("critical", "missing_last_name", "Last name is required", "last_name"))
    if not first or not last:
        return issues

    # Placeholder detection
    for field, val in [("first_name", first), ("last_name", last)]:
        if val.lower() in _PLACEHOLDER:
            issues.append(_issue("critical", "placeholder_name", f"'{val}' looks like placeholder data", field))

    # Email format
    if email and not _EMAIL_RE.match(email):
        issues.append(_issue("warning", "invalid_email", f"Email '{email}' format is invalid", "email"))

    # Duplicate detection
    if email:
        dup = _find_duplicate_contact_by_email(email)
        if dup:
            issues.append(_issue(
                "warning", "duplicate_contact",
                f"Contact with email '{email}' already exists (id={dup['id']})",
                "email",
            ))
    else:
        dup = _find_duplicate_contact_by_name(first, last)
        if dup:
            issues.append(_issue(
                "info", "possible_duplicate_contact",
                f"Contact '{first} {last}' at '{dup.get('company_name', '')}' may already exist",
                "name",
            ))

    return issues


def _find_duplicate_contact_by_email(email: str) -> Optional[dict]:
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT id, first_name, last_name FROM company_contacts WHERE LOWER(email) = %s LIMIT 1",
            (email,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _find_duplicate_contact_by_name(first: str, last: str) -> Optional[dict]:
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT cc.id, cc.first_name, cc.last_name, c.name AS company_name
               FROM company_contacts cc
               LEFT JOIN companies c ON c.id = cc.company_id
               WHERE LOWER(cc.first_name) = %s AND LOWER(cc.last_name) = %s
               LIMIT 1""",
            (first.lower(), last.lower()),
        )
        row = cur.fetchone()
    return dict(row) if row else None


# ── Batch DQE (used by status lifecycle promotion) ────────────────────────────

def promote_staged_companies(limit: int = 100) -> dict:
    """
    Run DQE on all 'staged' companies and move them to:
      - 'pending_review' if any warnings
      - 'approved' if no issues at all
      - 'staged' (unchanged) if critical issues (flag in review queue)

    Returns { promoted_approved, promoted_review, blocked }
    """
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT id, name, domain FROM companies WHERE status='staged' LIMIT %s",
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    approved, review, blocked = 0, 0, 0

    for row in rows:
        issues = run_dqe_on_company(row)
        criticals = [i for i in issues if i["severity"] == "critical"]
        warnings  = [i for i in issues if i["severity"] == "warning"]

        if criticals:
            # Keep staged, record issues in enrichment_data
            _set_company_status(row["id"], "staged", issues)
            blocked += 1
        elif warnings:
            _set_company_status(row["id"], "pending_review", issues)
            review += 1
        else:
            _set_company_status(row["id"], "approved", [])
            approved += 1

    return {"promoted_approved": approved, "promoted_review": review, "blocked": blocked}


def _set_company_status(company_id: int, status: str, issues: list) -> None:
    import json
    with db.db_cursor() as cur:
        cur.execute(
            """UPDATE companies
               SET status=%s,
                   enrichment_data = enrichment_data || %s::jsonb,
                   last_updated=NOW()
               WHERE id=%s""",
            (status, json.dumps({"dqe_issues": issues}), company_id),
        )


def _normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
