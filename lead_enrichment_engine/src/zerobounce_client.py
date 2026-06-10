"""
zerobounce_client.py
====================
STAGES 4 & 6 — Email Validation

PURPOSE:
  Verifies that email addresses actually exist and are safe to send to before
  the sales team wastes time on bounced outreach.  Called twice in the pipeline:
    Stage 4: validates Apollo/Apify-sourced emails
    Stage 6: validates pattern-predicted emails (these have a much higher
             failure rate — pattern prediction is a best guess)

HOW IT FITS IN THE SYSTEM:
  pipeline.py calls validate_emails(df, source_filter=["apollo","apify"]) for Stage 4.
  pipeline.py calls validate_emails(df, source_filter=["predicted"]) for Stage 6.
  source_filter ensures only the new emails from each stage are re-validated,
  not emails already validated in a prior stage (avoids double-spending credits).

  COST CONTROL — DB pre-check before any API call:
  Before spending credits, validate_emails() checks contacts_master via pg_master.py
  for emails already known to be valid (ZB_Valid_Email = 'Yes').  Known-valid emails
  are restored directly to the DataFrame — no credit spent.

VALIDATION MODES (auto-selected based on volume):
  BATCH API   — up to 200 emails per POST, ~70s response time.
                Synchronous — waits for the result in the same HTTP call.
  BULK FILE API — for 200+ emails: upload CSV → poll filestatus → download results CSV.
                  Asynchronous — polls every 10s, max 600s wait time.
                  Falls back to batch mode if the file upload fails.

ZEROBOUNCE STATUS CODES:
  valid       — safe to send, <2% bounce rate
  invalid     — do not send (mailbox does not exist)
  catch-all   — server accepts ALL mail (may or may not be real)
  spamtrap    — never send (will damage sender reputation permanently)
  abuse       — user marks mail as spam, avoid
  do_not_mail — role-based (info@, sales@), disposable, or toxic
  unknown     — could not verify (ZeroBounce refunds credits for these)

ZEROBOUNCE SUB-STATUS CODES:
  gold          — high-engagement address (extra positive signal)
  accept_all    — catch-all domain vetted as safe
  disposable    — temporary/throwaway address
  toxic         — known abuse / bot account
  role_based    — generic role address (info@, support@, etc.)
  mailbox_not_found — specific failure reason for invalid emails

KEY FUNCTIONS:
  validate_emails(df, source_filter) — main entry point; returns enriched DataFrame
  get_credits()                      — fetches current credit balance
  _validate_batch(emails)            — calls the batch API for ≤200 emails
  _validate_bulk_file(emails)        — uploads CSV and polls for ≥200 emails
"""

import csv
import io
import time
from typing import Optional

import pandas as pd

from .config import ZEROBOUNCE_API_KEY
from .utils import request_json, chunks

# ── API Endpoints ──────────────────────────────────────────────────────────
GETCREDITS_URL = "https://api.zerobounce.net/v2/getcredits"
BATCH_URL      = "https://bulkapi.zerobounce.net/v2/validatebatch"
SENDFILE_URL   = "https://bulkapi.zerobounce.net/v2/sendfile"
FILESTATUS_URL = "https://bulkapi.zerobounce.net/v2/filestatus"
GETFILE_URL    = "https://bulkapi.zerobounce.net/v2/getfile"

BATCH_SIZE      = 200   # max emails per batch API call
BATCH_THRESHOLD = 200   # use file API above this count
POLL_INTERVAL   = 10    # seconds between file status polls
POLL_TIMEOUT    = 600   # max seconds to wait for bulk file completion


# ── Credit Balance ─────────────────────────────────────────────────────────

def get_credits() -> Optional[int]:
    """
    Fetch current ZeroBounce credit balance.

    Each email validation uses 1 credit.
    Returns None if no API key is configured or the key is invalid.
    ZeroBounce returns {"Credits": -1} for invalid keys.
    """
    if not ZEROBOUNCE_API_KEY:
        return None
    try:
        data    = request_json("GET", GETCREDITS_URL, params={"api_key": ZEROBOUNCE_API_KEY})
        credits = int(data.get("Credits", -1)) if isinstance(data, dict) else -1
        return None if credits == -1 else credits
    except Exception:
        return None


def _fmt_credits(n: Optional[int]) -> str:
    """Format credit balance for display."""
    if n is None:
        return "unknown (no API key or invalid key)"
    return f"{n:,}"


# ── Batch API (≤ 200 emails) ───────────────────────────────────────────────

def _validate_batch(emails: list) -> dict:
    """
    Validate up to 200 emails using the ZeroBounce batch API.

    Sends all emails in a single POST request.
    Returns a dict mapping email → {"status": "...", "sub_status": "..."}

    If no API key is set, all emails are marked "not_validated".
    """
    if not ZEROBOUNCE_API_KEY:
        return {e: {"status": "not_validated", "sub_status": "missing_api_key"} for e in emails}

    payload = {
        "api_key":      ZEROBOUNCE_API_KEY,
        "email_batch":  [{"email_address": e} for e in emails],
    }
    try:
        data = request_json("POST", BATCH_URL, json=payload)
    except Exception as exc:
        print(f"    [zerobounce] batch error: {exc} — marking as unknown")
        return {e: {"status": "unknown", "sub_status": "api_error"} for e in emails}

    result = {}
    # Parse each email result from the response
    for item in (data.get("email_batch") or [] if isinstance(data, dict) else []):
        email = (item.get("address") or item.get("email_address", "")).lower().strip()
        if email:
            result[email] = {
                "status":     item.get("status",     "unknown"),
                "sub_status": item.get("sub_status", ""),
            }

    # Handle any API-level errors for specific addresses
    for err in (data.get("errors") or [] if isinstance(data, dict) else []):
        addr = err.get("email_address", "")
        if addr and addr != "all":
            result[addr.lower()] = {"status": "unknown", "sub_status": "api_error"}

    return result


# ── Bulk File API (> 200 emails) ───────────────────────────────────────────

def _build_csv(emails: list) -> bytes:
    """Build a simple CSV file with one email per row for the bulk file API."""
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["email_address"])
    for e in emails:
        w.writerow([e])
    return buf.getvalue().encode("utf-8")


def _validate_bulk_file(emails: list) -> dict:
    """
    Validate any number of emails using ZeroBounce's bulk file API.

    Three-step process:
      Step 1: Upload CSV file (sendfile)
      Step 2: Poll until processing is complete (filestatus)
      Step 3: Download the results CSV (getfile)

    Falls back to batch API if file upload fails.
    """
    if not ZEROBOUNCE_API_KEY:
        return {e: {"status": "not_validated", "sub_status": "missing_api_key"} for e in emails}

    csv_bytes = _build_csv(emails)

    # ── Step 1: Upload the CSV file ────────────────────────────────────────
    try:
        import requests as _req
        resp = _req.post(
            SENDFILE_URL,
            data={
                "api_key":              ZEROBOUNCE_API_KEY,
                "email_address_column": 1,
                "has_header_row":       "true",
            },
            files={"file": ("emails.csv", csv_bytes, "text/csv")},
            timeout=60,
        )
        resp.raise_for_status()
        send_data = resp.json()
    except Exception as exc:
        print(f"    [zerobounce] sendfile error: {exc} — falling back to batch mode")
        result = {}
        for chunk in chunks(emails, BATCH_SIZE):
            result.update(_validate_batch(chunk))
        return result

    if not send_data.get("success"):
        print(f"    [zerobounce] sendfile rejected: {send_data.get('error_message')}")
        result = {}
        for chunk in chunks(emails, BATCH_SIZE):
            result.update(_validate_batch(chunk))
        return result

    file_id = send_data["file_id"]
    print(f"    [zerobounce] bulk upload accepted (file_id={file_id[:8]}...), polling...")

    # ── Step 2: Poll until ZeroBounce finishes processing ─────────────────
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        try:
            status_data = request_json(
                "GET", FILESTATUS_URL,
                params={"api_key": ZEROBOUNCE_API_KEY, "file_id": file_id},
            )
        except Exception as exc:
            print(f"    [zerobounce] filestatus error: {exc}")
            time.sleep(POLL_INTERVAL)
            continue

        pct         = status_data.get("complete_percentage", "0%")
        file_status = status_data.get("file_status", "")
        print(f"    [zerobounce] {file_status} {pct}")

        if file_status == "Complete":
            break
        time.sleep(POLL_INTERVAL)
    else:
        print(f"    [zerobounce] bulk validation timed out after {POLL_TIMEOUT}s")
        return {e: {"status": "unknown", "sub_status": "bulk_timeout"} for e in emails}

    # ── Step 3: Download the results CSV ──────────────────────────────────
    try:
        import requests as _req
        resp = _req.get(
            GETFILE_URL,
            params={"api_key": ZEROBOUNCE_API_KEY, "file_id": file_id},
            timeout=120,
        )
        resp.raise_for_status()
        # ZeroBounce returns JSON on error, CSV on success
        if "application/json" in resp.headers.get("Content-Type", ""):
            err = resp.json()
            print(f"    [zerobounce] getfile error: {err.get('error_message')}")
            return {e: {"status": "unknown", "sub_status": "getfile_error"} for e in emails}
        result_csv = resp.content.decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"    [zerobounce] getfile error: {exc}")
        return {e: {"status": "unknown", "sub_status": "getfile_error"} for e in emails}

    # Parse the returned CSV into our standard result format
    result = {}
    reader = csv.DictReader(io.StringIO(result_csv))
    for row in reader:
        email = (row.get("Email Address") or row.get("email_address") or "").lower().strip()
        if email:
            result[email] = {
                "status":     (row.get("ZB Status")     or row.get("status")     or "unknown").lower().strip(),
                "sub_status": (row.get("ZB Sub Status") or row.get("sub_status") or "").lower().strip(),
            }

    if len(result) != len(emails):
        missing = len(emails) - len(result)
        print(f"    [zerobounce] !! count mismatch: submitted {len(emails)}, received {len(result)} ({missing} missing — will be marked 'unknown')")

    return result


# ── Public API ─────────────────────────────────────────────────────────────

def validate_emails(df: pd.DataFrame, source_filter: list | None = None) -> pd.DataFrame:
    """
    Validate emails in the DataFrame using ZeroBounce.

    source_filter: if provided, only validate emails whose email_source
                   is in this list. This is how the pipeline separates:
                   Stage 4: source_filter=["input", "apollo", "apify"]
                   Stage 6: source_filter=["predicted"]

    Emails that were already validated in a prior stage are skipped
    (won't be sent to ZeroBounce again, saving credits).

    Results are written into:
      email_validation_status     — e.g. "valid", "invalid", "unknown"
      email_validation_sub_status — e.g. "mailbox_not_found", "gold", "accept_all"
    """
    df = df.copy()

    for col in ["email_validation_status", "email_validation_sub_status"]:
        if col not in df.columns:
            df[col] = ""

    # Build mask: rows with an email that match the source filter
    mask = df["email"].notna() & (df["email"].astype(str).str.strip() != "")
    if source_filter is not None:
        mask = mask & df["email_source"].isin(source_filter)

    # Skip emails already validated in a previous stage.
    # "not_validated" and empty are treated as unvalidated — anything else
    # (valid, invalid, catch-all, etc.) means ZeroBounce already ran.
    _UNVALIDATED = {"", "not_validated"}
    already_validated = ~df["email_validation_status"].astype(str).str.strip().isin(_UNVALIDATED)
    mask = mask & ~already_validated

    # ── DB pre-check: restore validation status for known emails ──────────────
    # Before spending any ZeroBounce credits, check contacts_master for emails
    # already validated (ZB_Valid_Email = Yes).  Restores the known status
    # directly onto the DataFrame so those rows never reach the API.
    candidate_emails = (
        df.loc[mask, "email"].astype(str).str.lower().str.strip()
        .drop_duplicates().tolist()
    )
    if candidate_emails:
        try:
            from .pg_master import get_pg_master
            _pg = get_pg_master()
            known: dict = {}
            if _pg:
                try:
                    known.update(_pg.get_validation_by_email(candidate_emails))
                except Exception:
                    pass
            if known:
                emails_col = df.loc[mask, "email"].astype(str).str.lower().str.strip()
                db_resolved = emails_col.isin(known)
                for em, rec in known.items():
                    hit = mask & (df["email"].astype(str).str.lower().str.strip() == em)
                    df.loc[hit, "email_validation_status"]     = rec["email_validation_status"]
                    df.loc[hit, "email_validation_sub_status"] = rec.get("email_validation_sub_status", "")
                mask = mask & ~db_resolved
                db_hit_count = int(db_resolved.sum())
                if db_hit_count:
                    print(f"    [zerobounce] {db_hit_count} email(s) resolved from DB — skipping API")
        except Exception:
            pass  # non-fatal: fall through to normal API validation

    emails_to_validate = (
        df.loc[mask, "email"].astype(str).str.lower().str.strip()
        .drop_duplicates().tolist()
    )
    if not emails_to_validate:
        print(f"    [zerobounce] no new emails to validate")
        return df

    # ── Show balance and cost estimate before calling API ──────────────────
    balance_before = get_credits()
    count          = len(emails_to_validate)
    print(f"\n    {'-'*50}")
    print(f"    ZeroBounce Credit Check")
    print(f"    {'-'*50}")
    print(f"    Emails to validate  : {count:,}")
    print(f"    Credits before      : {_fmt_credits(balance_before)}")
    if balance_before is not None:
        after_estimate = balance_before - count
        if after_estimate < 0:
            print(f"    !! WARNING: not enough credits (need {count:,}, have {balance_before:,})")
            print(f"    !! Top up at zerobounce.net before continuing")
        else:
            print(f"    Est. credits after  : {after_estimate:,}")
    print(f"    {'-'*50}\n")

    # ── Call the appropriate API based on volume ───────────────────────────
    all_results: dict = {}
    if len(emails_to_validate) > BATCH_THRESHOLD:
        # Large batch — use the async file upload API
        all_results = _validate_bulk_file(emails_to_validate)
    else:
        # Small batch — use the synchronous batch API
        for batch in chunks(emails_to_validate, BATCH_SIZE):
            all_results.update(_validate_batch(batch))

    # ── Apply results back to the DataFrame ───────────────────────────────
    emails_col = df.loc[mask, "email"].astype(str).str.lower().str.strip()
    df.loc[mask, "email_validation_status"]     = emails_col.map(
        lambda e: all_results.get(e, {"status": "unknown"})["status"]
    )
    df.loc[mask, "email_validation_sub_status"] = emails_col.map(
        lambda e: all_results.get(e, {}).get("sub_status", "")
    )

    # ── Show actual credits used ───────────────────────────────────────────
    balance_after  = get_credits()
    actually_used  = (
        (balance_before - balance_after)
        if balance_before is not None and balance_after is not None else None
    )
    print(f"    Credits after       : {_fmt_credits(balance_after)}", end="")
    if actually_used is not None:
        print(f"  (used {actually_used:,})", end="")
    print()

    # Print a summary of validation outcomes
    statuses = df.loc[mask, "email_validation_status"].value_counts()
    for status, n in statuses.items():
        print(f"    {status:<20}: {n:,}")
    print()

    return df
