"""
utils.py
========
Shared helper functions used across all pipeline modules.
Nothing here is pipeline-specific — these are general-purpose utilities
for text cleaning, HTTP requests, and error handling.
"""

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


# ── Timestamp ──────────────────────────────────────────────────────────────

def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string. Used in audit logs."""
    return datetime.now(timezone.utc).isoformat()


# ── Text Normalization ─────────────────────────────────────────────────────
# These functions clean up messy input data so comparisons and deduplication
# work reliably even when data comes from different sources.

def normalize_text(value: Any) -> str:
    """Convert any value to a clean string. Turns NaN/None into empty string."""
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_name(value: Any) -> str:
    """
    Clean a person's name for use in lead ID hashing.
    Lowercases and strips everything except letters, hyphens, and apostrophes.
    Example: "O'Brien-Smith " → "o'brien-smith"
    """
    value = normalize_text(value).lower()
    return re.sub(r"[^a-zA-Z'-]", "", value)


def normalize_company(value: Any) -> str:
    """
    Strip legal suffixes and punctuation from a company name so that
    'Acme Inc.', 'ACME LLC', and 'acme corporation' all match each other.
    Used for deduplication and domain lookup.
    Example: "Oracle Corporation Ltd." → "oracle"
    """
    value = normalize_text(value).lower()
    # Remove common legal suffixes
    value = re.sub(
        r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|co|company|plc|private|pvt)\b",
        "",
        value,
    )
    # Replace non-alphanumeric characters with spaces, then collapse whitespace
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_domain(value: Any) -> str:
    """
    Strip protocol, www, and path from a URL to get a bare domain.
    Example: "https://www.microsoft.com/en-us" → "microsoft.com"
    """
    value = normalize_text(value).lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    return value.split("/")[0].strip()


def normalize_email(value: Any) -> str:
    """
    Lowercase and validate an email string.
    Returns empty string if the value doesn't look like an email.
    """
    value = normalize_text(value).lower()
    return value if "@" in value else ""


# ── Lead ID ────────────────────────────────────────────────────────────────

def make_lead_id(first_name: str, last_name: str, company: str, domain: str = "") -> str:
    """
    Generate a stable 24-character unique ID for a lead.
    Built by hashing: normalized first name | last name | company | domain.
    Same person at same company always gets the same ID, even across runs.
    Used to deduplicate and track leads consistently.
    """
    raw = (
        f"{normalize_name(first_name)}"
        f"|{normalize_name(last_name)}"
        f"|{normalize_company(company)}"
        f"|{normalize_domain(domain)}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


# ── List Utilities ─────────────────────────────────────────────────────────

def chunks(records: List[Any], size: int) -> Iterable[List[Any]]:
    """
    Split a list into fixed-size chunks.
    Used to batch API calls — e.g. ZeroBounce accepts max 200 emails per call.
    Example: chunks([1,2,3,4,5], 2) → [1,2], [3,4], [5]
    """
    for i in range(0, len(records), size):
        yield records[i : i + size]


def append_failure(current: Any, message: str) -> str:
    """
    Add a new failure message to a lead's failure_reason field
    without overwriting any previous failures.
    Example: append_failure("no_email_found", "suppressed") → "no_email_found; suppressed"
    """
    current = str(current or "").strip()
    message = str(message or "").strip()
    if not message:
        return current
    if not current:
        return message
    return f"{current}; {message}"


# ── HTTP Request Helper ────────────────────────────────────────────────────

class VendorError(Exception):
    """Raised when a vendor API returns an error we should retry."""
    pass


@retry(
    retry=retry_if_exception_type((requests.RequestException, VendorError)),
    wait=wait_exponential(multiplier=1, min=1, max=20),  # waits 1s, 2s, 4s... up to 20s between retries
    stop=stop_after_attempt(3),   # give up after 3 total attempts
    reraise=True,                 # re-raise the exception if all retries fail
)
def request_json(method: str, url: str, **kwargs) -> Dict[str, Any] | list:
    """
    Make an HTTP request and return the parsed JSON response.

    Features:
    - Automatic retry (up to 3 times) on network errors and 5xx server errors
    - Respects 429 Rate Limit responses — reads the Retry-After header and waits
    - Raises VendorError for 4xx/5xx so calling code can handle failures cleanly
    - 60 second timeout on all requests

    Usage:
        data = request_json("GET", "https://api.example.com/data", params={"q": "hello"})
        data = request_json("POST", "https://api.example.com/submit", json={"key": "value"})
    """
    response = requests.request(method, url, timeout=60, **kwargs)

    # 429 = Too Many Requests — wait the amount the API tells us, then retry
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 5))
        time.sleep(max(retry_after, 5))
        raise VendorError("Rate limited — will retry")

    # 5xx = server-side error — worth retrying
    if response.status_code >= 500:
        raise VendorError(f"Server error {response.status_code}: {response.text[:500]}")

    # 4xx = client-side error (bad key, bad request) — don't retry
    if response.status_code >= 400:
        raise VendorError(f"Client error {response.status_code}: {response.text[:500]}")

    # Empty response body is valid (some APIs return 200 with no body)
    if not response.text:
        return {}

    return response.json()
