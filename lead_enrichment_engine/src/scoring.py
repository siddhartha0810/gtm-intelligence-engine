"""
scoring.py
==========
STAGE 7 — Score & Suppress

The final stage. Marks each lead as "yes" or "no" for outreach based on:
  1. Whether they have an email address
  2. Whether that email is on the suppression list (do-not-contact list)
  3. What ZeroBounce said about the email address

Decision table (based on ZeroBounce official documentation):
  valid                                    → YES  (safe to send, <2% bounce rate)
  valid   + sub_status=gold                → YES  (high-engagement address, prioritize)
  valid   + sub_status=accept_all          → YES  (catch-all domain vetted by ZeroBounce)
  catch-all + sub_status=accept_all        → YES  (ZeroBounce vouches for this domain)
  invalid                                  → NO   (mailbox doesn't exist)
  spamtrap                                 → NO   (will destroy sender reputation)
  abuse                                    → NO   (user known to mark mail as spam)
  do_not_mail                              → NO   (role-based/disposable/toxic address)
  unknown                                  → NO   (80% are actually invalid per ZB docs)
  not_validated / missing_api_key          → NO   (never sent to ZeroBounce — unsafe to assume valid)
"""

import pandas as pd
from .utils import append_failure

# ── Status Classification ──────────────────────────────────────────────────

# Only these top-level statuses are safe to send to outright
SAFE_STATUSES = {"valid"}

# catch-all domains are only safe if ZeroBounce has vetted them
SAFE_CATCHALL_SUB = {"accept_all", "role_based_accept_all"}

# Sub-statuses within "valid" that indicate an especially valuable address
GOLD_SUB = {"gold"}


def _is_ready(row, suppressed: set) -> tuple[str, str]:
    """
    Decide if a single lead is ready for outreach.

    Returns:
      ("yes", failure_reason)  — safe to contact
      ("no",  failure_reason)  — do not contact, with reason appended
    """
    email      = str(row.get("email", "")).lower().strip()
    status     = str(row.get("email_validation_status", "")).lower().strip()
    sub_status = str(row.get("email_validation_sub_status", "")).lower().strip()
    failure    = str(row.get("failure_reason", ""))

    # No email was found at all — cannot contact
    if not email:
        return "no", append_failure(failure, "no_email_found")

    # Email is on the suppression list — must not contact
    if email in suppressed:
        return "no", append_failure(failure, "suppressed")

    # ZeroBounce confirmed this is a valid deliverable address
    if status in SAFE_STATUSES:
        return "yes", failure

    # catch-all domain, but ZeroBounce has vetted it as safe
    if status == "catch-all" and sub_status in SAFE_CATCHALL_SUB:
        return "yes", failure

    # Email was never sent to ZeroBounce (no API key, or validation was skipped)
    if not status or status == "not_validated":
        return "no", append_failure(failure, "email_not_validated")

    # ZeroBounce couldn't verify — too risky to send
    if status == "unknown":
        reason = f"email_status:unknown" + (f"({sub_status})" if sub_status else "")
        return "no", append_failure(failure, reason)

    # Everything else (invalid, spamtrap, abuse, do_not_mail, etc.) — do not send
    return "no", append_failure(
        failure, f"email_status:{status}" + (f"({sub_status})" if sub_status else "")
    )


def mark_outreach_ready(df: pd.DataFrame, suppression_path: str) -> pd.DataFrame:
    """
    Apply outreach scoring to every lead in the DataFrame.

    Loads the suppression list (emails that must never be contacted),
    then applies _is_ready() to every row and writes the result into
    the "ready_for_outreach" and "failure_reason" columns.
    """
    df = df.copy()

    # Load suppression list — file not existing is fine (treated as empty list)
    try:
        suppression = pd.read_csv(suppression_path)
        suppressed = set(
            suppression.get("email", pd.Series(dtype=str))
            .astype(str).str.lower().str.strip()
        )
    except FileNotFoundError:
        suppressed = set()

    # Apply scoring to every row at once using pandas apply
    results = df.apply(lambda r: _is_ready(r, suppressed), axis=1, result_type="expand")
    df["ready_for_outreach"] = results[0]
    df["failure_reason"]     = results[1]

    return df
