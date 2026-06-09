"""
orchestrator.py
===============
STAGE 3 — Vendor Enrichment

The core enrichment engine. For every lead that is missing an email or
LinkedIn URL, it calls external APIs to find them.

Vendors supported:
  Apollo  — bulk people enrichment API (email + LinkedIn from name + company + domain)
  Apify   — LinkedIn scraper (Phase 1: find LinkedIn URL, Phase 2: find email from LinkedIn)
  ZoomInfo — optional premium enrichment (disabled by default, needs domain override)

Vendor routing (default order = Apollo → Apify):
  - Apollo runs first as a bulk batch (all leads in one API call, chunked at 10)
  - Apify runs per-lead as a fallback if Apollo found nothing
  - If a lead already has both email AND LinkedIn → skip all vendors entirely
  - ZoomInfo is available in _VENDOR_FNS but not in the default route;
    add "zoominfo" to DOMAIN_OVERRIDES to use it for specific domains

Parallelism:
  - Apollo results are pre-fetched in bulk BEFORE the thread pool starts
  - The thread pool (10 workers) processes all leads concurrently
  - Each worker picks up the pre-fetched Apollo result or calls Apify

Performance tracking:
  - Every vendor call (hit or miss) is recorded by _Tracker
  - Results saved to output/vendor_performance.csv after the run
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Tuple
import pandas as pd
from tqdm import tqdm

from .utils import append_failure, request_json

# ── Constants ──────────────────────────────────────────────────────────────

MAX_WORKERS = 10   # parallel threads in the enrichment pool

# Default vendor order: Apollo first (bulk, fast), then Hunter.io (if key set),
# then Apify (LinkedIn scraper, slowest)
DEFAULT_ORDER = ["apollo", "apify"]

# Apollo API endpoints
APOLLO_USAGE_URL  = "https://api.apollo.io/api/v1/usage_stats/api_usage_stats"
APOLLO_BULK_URL   = "https://api.apollo.io/api/v1/people/bulk_match"
APOLLO_BULK_CHUNK = 10   # Apollo's bulk_match accepts max 10 records per request

# Apollo credit cost estimates (used when master key not available for real balance)
APOLLO_CREDITS_PER_HIT      = 1   # 1 credit per successful match
APOLLO_WATERFALL_CREDIT_EST = 2   # extra credits when Apollo searches external sources

# Apify timeouts
APIFY_BASE_URL      = "https://api.apify.com/v2"
APIFY_SYNC_TIMEOUT  = 270    # seconds — Apify's hard limit is 300s; stay under it
APIFY_POLL_INTERVAL = 5      # seconds between async run status polls
APIFY_POLL_TIMEOUT  = 300    # max seconds to wait for an async run

# Terminal Apify run statuses
_APIFY_DONE   = {"SUCCEEDED"}
_APIFY_FAILED = {"FAILED", "TIMED-OUT", "ABORTED"}

# Domain-specific vendor overrides — add entries here to use a different
# vendor order for specific company domains.
# Example: DOMAIN_OVERRIDES = {"salesforce.com": ["zoominfo", "apollo"]}
DOMAIN_OVERRIDES: Dict[str, List[str]] = {}


# ── Apollo Credit Balance ──────────────────────────────────────────────────

_APOLLO_EMPTY = {
    "source":           "no_key",
    "credits_remaining": None,
    "credits_used":      None,
    "credits_limit":     None,
    "rate_limit_minute": None,
    "rate_limit_hour":   None,
}


def get_apollo_credits() -> dict:
    """
    Fetch Apollo credit and rate-limit stats.

    Returns a dict with keys: source, credits_remaining, credits_used,
    credits_limit, rate_limit_minute, rate_limit_hour.

    source values:
      "api"                — successfully fetched
      "master_key_required"— 403 (standard key, needs master key for this endpoint)
      "no_key"             — APOLLO_API_KEY not set
      "error"              — network or unexpected error
    """
    from .config import APOLLO_API_KEY

    if not APOLLO_API_KEY:
        return dict(_APOLLO_EMPTY)

    try:
        data = request_json(
            "POST", APOLLO_USAGE_URL,
            json={},
            headers={"Content-Type": "application/json", "X-Api-Key": APOLLO_API_KEY},
        )
    except Exception as exc:
        err = str(exc)
        if "403" in err:
            return {**_APOLLO_EMPTY, "source": "master_key_required"}
        return {**_APOLLO_EMPTY, "source": "error"}

    if not isinstance(data, dict):
        return {**_APOLLO_EMPTY, "source": "error"}

    payload = data.get("usage") or data.get("stats") or {}
    if not payload:
        return {**_APOLLO_EMPTY, "source": "error"}

    return {
        "source":            "api",
        "credits_remaining": payload.get("credits_remaining"),
        "credits_used":      payload.get("credits_used"),
        "credits_limit":     payload.get("credits_limit"),
        "rate_limit_minute": payload.get("rate_limit_requests_per_minute"),
        "rate_limit_hour":   payload.get("rate_limit_requests_per_hour"),
    }


def _fmt_apollo_credits(info: dict) -> str:
    """Format a get_apollo_credits() result for human-readable display."""
    src = info.get("source", "")
    if src == "no_key":
        return "not checked (no APOLLO_API_KEY)"
    if src == "master_key_required":
        return "balance unavailable (standard key — master API key required)"
    if src == "error":
        return "could not fetch"
    rem  = info.get("credits_remaining")
    used = info.get("credits_used")
    lim  = info.get("credits_limit")
    parts = []
    if rem  is not None: parts.append(f"remaining={rem:,}")
    if used is not None: parts.append(f"used={used:,}")
    if lim  is not None: parts.append(f"limit={lim:,}")
    return "  ".join(parts) if parts else "unknown"


# ── Vendor Routing ─────────────────────────────────────────────────────────

def _print_apollo_limits(info: dict) -> None:
    """Print the Apollo credit/rate-limit snapshot in a readable table."""
    print(f"    Credits / limits        : {_fmt_apollo_credits(info)}")
    if info.get("source") == "api":
        rm = info.get("rate_limit_minute")
        rh = info.get("rate_limit_hour")
        if rm: print(f"    Rate limit / minute     : {rm:,}")
        if rh: print(f"    Rate limit / hour       : {rh:,}")


def _route(row: pd.Series) -> List[str]:
    """
    Decide which vendors to try for a given lead, and in what order.

    Rules:
      - If lead already has both email AND linkedin → return [] (skip all)
      - If domain is in DOMAIN_OVERRIDES → use that custom order
      - Otherwise → use DEFAULT_ORDER = ["apollo", "apify"]
    """
    domain   = str(row.get("domain",       "")).strip()
    email    = str(row.get("email",        "")).strip()
    linkedin = str(row.get("linkedin_url", "")).strip()

    if domain and domain in DOMAIN_OVERRIDES:
        return DOMAIN_OVERRIDES[domain]

    if email and linkedin:
        return []   # already complete, no enrichment needed

    return list(DEFAULT_ORDER)


# ── Performance Tracker ────────────────────────────────────────────────────

class _Tracker:
    """
    Counts hits and misses per vendor per domain.
    Used to generate output/vendor_performance.csv after the run.
    """

    def __init__(self):
        self._stats: Dict[str, Dict[str, int]] = {}
        self._domain: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._calls: Dict[str, Dict[str, int]] = {}

    def _v(self, vendor):
        return self._stats.setdefault(vendor, {"attempts": 0, "email_hits": 0, "linkedin_hits": 0, "linkedin_only": 0})

    def _d(self, domain, vendor):
        return self._domain.setdefault(domain, {}).setdefault(vendor, {"attempts": 0, "hits": 0})

    def _c(self, vendor):
        return self._calls.setdefault(vendor, {"attempts": 0, "hits": 0, "misses": 0})

    def record_call(self, vendor: str, got_any: bool) -> None:
        """Record a single API call and whether it returned any data."""
        c = self._c(vendor)
        c["attempts"] += 1
        if got_any:
            c["hits"] += 1
        else:
            c["misses"] += 1

    def record(self, vendor: str, domain: str, got_email: bool, got_linkedin: bool):
        """Record a successful enrichment hit for a specific vendor + domain."""
        v = self._v(vendor)
        v["attempts"] += 1
        if got_email:    v["email_hits"] += 1
        if got_linkedin: v["linkedin_hits"] += 1
        if got_linkedin and not got_email: v["linkedin_only"] += 1
        d = self._d(domain or "__unknown__", vendor)
        d["attempts"] += 1
        if got_email or got_linkedin:
            d["hits"] += 1

    def apollo_stats(self) -> Tuple[int, int]:
        """Return (hits, misses) for Apollo calls this run. Used in credit reporting."""
        c = self._calls.get("apollo", {})
        return c.get("hits", 0), c.get("misses", 0)

    def apollo_credit_breakdown(self) -> dict:
        """Return per-type credit breakdown for the Apollo vendor card."""
        s = self._stats.get("apollo", {})
        return {
            "email_hits":     s.get("email_hits",     0),
            "linkedin_hits":  s.get("linkedin_hits",  0),
            "linkedin_only":  s.get("linkedin_only",  0),
        }

    def save(self, path: str):
        """Write the performance stats to a CSV file."""
        rows = []
        for vendor, stats in self._stats.items():
            attempts = stats["attempts"] or 1
            rows.append({
                "vendor":        vendor,
                "domain":        "__all__",
                "attempts":      stats["attempts"],
                "email_hits":    stats["email_hits"],
                "linkedin_hits": stats["linkedin_hits"],
                "hit_rate":      round((stats["email_hits"] + stats["linkedin_hits"]) / (attempts * 2), 3),
            })
        for domain, vendors in self._domain.items():
            for vendor, stats in vendors.items():
                attempts = stats["attempts"] or 1
                rows.append({
                    "vendor":        vendor,
                    "domain":        domain,
                    "attempts":      stats["attempts"],
                    "email_hits":    "",
                    "linkedin_hits": "",
                    "hit_rate":      round(stats["hits"] / attempts, 3),
                })
        if rows:
            pd.DataFrame(rows).sort_values(["domain", "vendor"]).to_csv(path, index=False)


# ── ZoomInfo Vendor ────────────────────────────────────────────────────────

def _call_zoominfo(row: pd.Series) -> dict:
    """
    ZoomInfo enrichment — premium vendor, disabled by default.
    Only runs if "zoominfo" appears in DOMAIN_OVERRIDES for this lead's domain.
    Requires ZOOMINFO_API_KEY and ZOOMINFO_BASE_URL in .env
    """
    from .config import ZOOMINFO_API_KEY, ZOOMINFO_BASE_URL
    from .utils import request_json
    if not ZOOMINFO_API_KEY:
        return {}
    url = ZOOMINFO_BASE_URL.rstrip("/") + "/contact/enrich"
    try:
        data = request_json(
            "POST", url,
            json={
                "firstName":   row.get("first_name", ""),
                "lastName":    row.get("last_name",  ""),
                "companyName": row.get("company",    ""),
                "domain":      row.get("domain",     ""),
            },
            headers={"Authorization": f"Bearer {ZOOMINFO_API_KEY}", "Content-Type": "application/json"},
        )
        p = data.get("person", data) if isinstance(data, dict) else {}
        return {
            "email":        p.get("email") or p.get("businessEmail", ""),
            "linkedin_url": p.get("linkedin_url") or p.get("linkedinUrl") or p.get("linkedin", ""),
            "job_title":    p.get("jobTitle") or p.get("title", ""),
        }
    except Exception as exc:
        return {"error": f"zoominfo_error: {exc}"}


# ── Apollo Vendor ──────────────────────────────────────────────────────────

def _build_apollo_payload(row_dict: dict) -> dict:
    """
    Build the payload dict for one lead in an Apollo bulk_match request.

    run_waterfall_email=True tells Apollo to search external sources
    (not just its own database) when it can't find an email internally.
    This uses more credits but finds more emails.
    """
    payload: dict = {
        "first_name":             str(row_dict.get("first_name", "")).strip(),
        "last_name":              str(row_dict.get("last_name",  "")).strip(),
        "organization_name":      str(row_dict.get("company",    "")).strip(),
        "run_waterfall_email":    True,
        "reveal_personal_emails": False,   # work emails only
    }
    # Include optional signals that improve match accuracy
    if row_dict.get("domain"):
        payload["domain"] = str(row_dict["domain"]).strip()
    if row_dict.get("linkedin_url"):
        payload["linkedin_url"] = str(row_dict["linkedin_url"]).strip()
    if row_dict.get("email"):
        payload["email"] = str(row_dict["email"]).strip()
    return payload


def _parse_apollo_person(p: dict) -> dict:
    """
    Extract enrichment fields from one Apollo match result dict.

    Apollo returns a "person" object per matched lead. This function
    pulls out email, linkedin_url, and job_title, discarding emails
    that Apollo itself flagged as invalid or bounced.
    """
    if not p or not isinstance(p, dict):
        return {}

    email        = str(p.get("email") or "").strip().lower()
    email_status = str(p.get("email_status") or "").lower().strip()

    # Some plans return email under revealed_for_current_team (a dict or bool)
    if not email:
        revealed = p.get("revealed_for_current_team")
        email = str(
            (revealed if isinstance(revealed, dict) else {}).get("email") or ""
        ).strip().lower()

    # Discard emails Apollo knows are bad
    if email_status in ("unavailable", "bounced", "invalid"):
        email = ""

    linkedin = str(p.get("linkedin_url") or p.get("linkedin") or "").strip()
    title    = str(p.get("title") or p.get("headline") or "").strip()

    # Extract the company domain Apollo knows about — used to fill missing domains
    org = p.get("organization") or p.get("account") or {}
    raw_domain = str(
        org.get("primary_domain") or org.get("website_url") or org.get("domain") or ""
    ).lower().strip()
    raw_domain = re.sub(r"^https?://", "", raw_domain).lstrip("www.").split("/")[0].strip()

    return {"email": email, "linkedin_url": linkedin, "job_title": title, "org_domain": raw_domain}


def _call_apollo_bulk(payloads: list) -> list:
    """
    Call Apollo's People Bulk Enrichment API.

    Endpoint: POST https://api.apollo.io/api/v1/people/bulk_match
    Auth:     X-Api-Key header (NOT Authorization: Bearer)
    Docs:     https://docs.apollo.io/reference/people-enrichment

    Sends up to APOLLO_BULK_CHUNK (10) leads per request.
    Returns a list of result dicts (same length as input payloads).

    Each result contains: email, linkedin_url, job_title
    Or {"error": ...} if that lead's lookup failed.
    """
    from .config import APOLLO_API_KEY
    from .utils import request_json

    results: list = [{}] * len(payloads)
    if not APOLLO_API_KEY or not payloads:
        return results

    headers = {
        "Content-Type": "application/json",
        "X-Api-Key":    APOLLO_API_KEY,   # NOTE: Must be X-Api-Key, not Authorization: Bearer
    }

    # Process in chunks of APOLLO_BULK_CHUNK (Apollo's per-request limit)
    for start in range(0, len(payloads), APOLLO_BULK_CHUNK):
        chunk = payloads[start : start + APOLLO_BULK_CHUNK]
        try:
            data = request_json(
                "POST", APOLLO_BULK_URL,
                json={"details": chunk},
                headers=headers,
            )
        except Exception as exc:
            for i in range(len(chunk)):
                results[start + i] = {"error": f"apollo_error: {exc}"}
            continue

        if not isinstance(data, dict):
            continue

        # Apollo returns matches under "matches" or "people" depending on plan
        matches = data.get("matches") or data.get("people") or []
        for i, match in enumerate(matches[: len(chunk)]):
            results[start + i] = _parse_apollo_person(match) if match else {}

    return results


def _call_apollo(row: pd.Series) -> dict:
    """Single-row Apollo call — wraps _call_apollo_bulk for use in the waterfall."""
    results = _call_apollo_bulk([_build_apollo_payload(row.to_dict())])
    return results[0] if results else {}


# ── Apify Vendor ───────────────────────────────────────────────────────────

def _apify_headers() -> dict:
    from .config import APIFY_TOKEN
    return {"Authorization": f"Bearer {APIFY_TOKEN}", "Content-Type": "application/json"}


def _parse_apify_items(raw) -> list:
    """Normalize Apify dataset response — handles list or nested dict formats."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        data = raw.get("data", raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items", [])
    return []


def _extract_apify_linkedin(item: dict) -> dict:
    """
    Pull LinkedIn URL and job title from a LinkedIn-finder actor result.
    Handles field name variations across different Apify actors.
    """
    linkedin = str(
        item.get("linkedinUrl") or item.get("linkedin_url")
        or item.get("linkedin")  or item.get("profileUrl")
        or item.get("url")       or ""
    ).strip()
    title = str(
        item.get("headline") or item.get("info")
        or item.get("jobTitle") or item.get("job_title") or ""
    ).strip()
    return {"linkedin_url": linkedin, "job_title": title}


def _extract_apify_email(item: dict) -> dict:
    """
    Pull work email from an email-finder actor result.
    Returns {} if the actor confirmed no email was found.
    """
    # blitzapi returns {"found": false} when nothing found — treat as empty
    if "found" in item and not item.get("found"):
        return {}
    email = str(
        item.get("email") or item.get("workEmail") or item.get("work_email") or ""
    ).strip().lower()
    return {"email": email}


def _run_apify_actor(actor_id: str, payload: dict) -> list:
    """
    Run an Apify actor and return its dataset items.

    Strategy:
      Attempt 1 — synchronous run (faster, up to 270s timeout)
      Attempt 2 — async run + polling (fallback if sync times out)

    Auth: Authorization: Bearer <token>
    Docs: https://docs.apify.com/api
    """
    import requests as _req
    import time as _time

    headers = _apify_headers()

    # ── Attempt 1: Synchronous run ─────────────────────────────────────────
    # Apify runs the actor and streams back results when done (max 270s)
    try:
        resp = _req.post(
            f"{APIFY_BASE_URL}/acts/{actor_id}/run-sync-get-dataset-items",
            json=payload, headers=headers, timeout=APIFY_SYNC_TIMEOUT,
        )
        resp.raise_for_status()
        return _parse_apify_items(resp.json())
    except Exception as exc:
        err = str(exc)
        is_timeout    = any(t in err for t in ("timeout", "timed out", "ReadTimeout", "ConnectTimeout"))
        is_server_err = err[:3].isdigit() and err[0] == "5"
        if not is_timeout and not is_server_err:
            raise   # 4xx or unknown error — don't fall back to async

    # ── Attempt 2: Async run + polling ────────────────────────────────────
    # Start the actor run asynchronously, then poll until it finishes
    start_resp = _req.post(
        f"{APIFY_BASE_URL}/acts/{actor_id}/runs",
        json=payload, headers=headers, timeout=30,
    )
    start_resp.raise_for_status()
    run_info   = (start_resp.json() or {}).get("data", start_resp.json() or {})
    run_id     = run_info.get("id")
    dataset_id = run_info.get("defaultDatasetId")
    status     = run_info.get("status", "READY")

    if not run_id:
        raise RuntimeError("apify async run did not return a run id")

    deadline = _time.time() + APIFY_POLL_TIMEOUT
    while status not in _APIFY_DONE and status not in _APIFY_FAILED:
        if _time.time() > deadline:
            raise TimeoutError(f"apify async run timed out after {APIFY_POLL_TIMEOUT}s")
        _time.sleep(APIFY_POLL_INTERVAL)
        poll       = _req.get(f"{APIFY_BASE_URL}/actor-runs/{run_id}", headers=headers, timeout=15)
        poll.raise_for_status()
        run_info   = (poll.json() or {}).get("data", poll.json() or {})
        status     = run_info.get("status", "RUNNING")
        dataset_id = dataset_id or run_info.get("defaultDatasetId")

    if status in _APIFY_FAILED:
        raise RuntimeError(f"apify run ended with status {status}")

    if not dataset_id:
        raise RuntimeError("apify run succeeded but returned no dataset id")

    items_resp = _req.get(
        f"{APIFY_BASE_URL}/datasets/{dataset_id}/items",
        params={"limit": 5}, headers=headers, timeout=30,
    )
    items_resp.raise_for_status()
    return _parse_apify_items(items_resp.json())


def _call_apify_linkedin(row: pd.Series) -> dict:
    """
    Apify Phase 1 — Find LinkedIn URL from name + company.

    Runs the actor configured as APIFY_LINKEDIN_ACTOR_ID.
    Recommended actor: anchor/linkedin-people-finder
    Returns: {"linkedin_url": "...", "job_title": "..."}
    """
    from .config import APIFY_TOKEN, APIFY_LINKEDIN_ACTOR_ID
    if not APIFY_TOKEN or not APIFY_LINKEDIN_ACTOR_ID:
        return {}

    first   = str(row.get("first_name", "")).strip()
    last    = str(row.get("last_name",  "")).strip()
    company = str(row.get("company",    "")).strip()
    query   = " ".join(filter(None, [first, last, company]))

    payload = {
        "queries":           query,        # anchor/linkedin-people-finder format
        "first":             True,         # return only the best match
        "profileScraperMode": "Short",     # harvestapi format
        "firstName":         first,
        "lastName":          last,
        "maxItems":          1,
        "query":             query,
        "searchQuery":       query,
        "domain":            str(row.get("domain", "")).strip(),
    }
    try:
        items = _run_apify_actor(APIFY_LINKEDIN_ACTOR_ID, payload)
        return _extract_apify_linkedin(items[0]) if items else {}
    except Exception as exc:
        return {"error": f"apify_linkedin_error: {exc}"}


def _call_apify_email(row: pd.Series) -> dict:
    """
    Apify Phase 2 — Find work email using the LinkedIn URL found in Phase 1.

    Runs the actor configured as APIFY_EMAIL_ACTOR_ID.
    Recommended actor: blitzapi/linkedin-email-finder
    Requires linkedin_url to be set on the row — returns {} if missing.
    Returns: {"email": "..."}
    """
    from .config import APIFY_TOKEN, APIFY_EMAIL_ACTOR_ID
    if not APIFY_TOKEN or not APIFY_EMAIL_ACTOR_ID:
        return {}

    linkedin_url = str(row.get("linkedin_url", "")).strip()
    if not linkedin_url:
        return {}   # email actors need a LinkedIn URL as anchor

    payload = {
        "linkedinUrl":  linkedin_url,
        "profileUrl":   linkedin_url,
        "profileUrls":  [linkedin_url],
        "firstName":    str(row.get("first_name", "")).strip(),
        "lastName":     str(row.get("last_name",  "")).strip(),
        "domain":       str(row.get("domain",     "")).strip(),
    }
    try:
        items = _run_apify_actor(APIFY_EMAIL_ACTOR_ID, payload)
        return _extract_apify_email(items[0]) if items else {}
    except Exception as exc:
        return {"error": f"apify_email_error: {exc}"}


def _call_apify(row: pd.Series) -> dict:
    """
    Full Apify enrichment — two phases combined.

    Phase 1: Find LinkedIn URL (skipped if lead already has one)
    Phase 2: Find email using LinkedIn URL (skipped if lead already has email,
             or if Phase 1 returned no LinkedIn URL)

    A failed Phase 2 is a soft failure — the LinkedIn URL from Phase 1
    is still returned even if Phase 2 errors out.
    """
    result: dict = {}
    cur_linkedin = str(row.get("linkedin_url", "")).strip()
    cur_email    = str(row.get("email",        "")).strip()

    # Phase 1: Get LinkedIn URL
    if not cur_linkedin:
        li = _call_apify_linkedin(row)
        if li.get("error"):
            return li   # hard failure — propagate up
        if li.get("linkedin_url"):
            result["linkedin_url"] = li["linkedin_url"]
            cur_linkedin           = li["linkedin_url"]
        if li.get("job_title"):
            result["job_title"] = li["job_title"]

    # Phase 2: Get email via LinkedIn URL
    if not cur_email and cur_linkedin:
        enriched_row = row.copy()
        if result.get("linkedin_url"):
            enriched_row["linkedin_url"] = result["linkedin_url"]
        em = _call_apify_email(enriched_row)
        if em.get("error"):
            result.setdefault("_phase2_error", em["error"])   # soft failure
        elif em.get("email"):
            result["email"] = em["email"]

    return result


# ── Vendor Function Registry ───────────────────────────────────────────────

_VENDOR_FNS: Dict[str, Callable] = {
    "zoominfo": _call_zoominfo,
    "apollo":   _call_apollo,
    "apify":    _call_apify,
}


# ── Per-Lead Enrichment ────────────────────────────────────────────────────

def _enrich_lead(idx, row_dict: dict, order: List[str],
                 apollo_cache: Optional[dict] = None) -> dict:
    """
    Try each vendor in priority order for a single lead.

    Stops as soon as both email AND linkedin_url are filled.
    Returns a dict of field updates to apply to the DataFrame row.

    apollo_cache: pre-fetched Apollo results (avoids calling Apollo
                  individually per lead — all Apollo calls were batched earlier)
    """
    updates: dict       = {}
    failures: list      = []
    vendor_calls: list  = []
    cur_email    = str(row_dict.get("email",        "")).strip()
    cur_linkedin = str(row_dict.get("linkedin_url", "")).strip()

    for vendor in order:
        # Stop as soon as we have both fields — no need to try more vendors
        if cur_email and cur_linkedin:
            break

        row_series = pd.Series(row_dict)

        # Use pre-fetched Apollo result from the bulk cache (if available)
        if vendor == "apollo" and apollo_cache is not None:
            result = apollo_cache.get(idx, {})
        else:
            result = _VENDOR_FNS[vendor](row_series)

        if result.get("error"):
            failures.append(result["error"])
            vendor_calls.append((vendor, False))
            continue

        email    = str(result.get("email",        "")).lower().strip()
        linkedin = str(result.get("linkedin_url", "")).strip()
        title    = str(result.get("job_title",    "")).strip()

        got_email_now    = False
        got_linkedin_now = False

        if email and not cur_email:
            updates["email"]        = email
            updates["email_source"] = vendor
            cur_email               = email
            got_email_now           = True

        if linkedin and not cur_linkedin:
            updates["linkedin_url"]    = linkedin
            updates["linkedin_source"] = vendor
            cur_linkedin               = linkedin
            got_linkedin_now           = True

        if title and not row_dict.get("job_title", "").strip():
            updates.setdefault("job_title", title)

        # If Apollo returned the company's domain and the lead has none, use it.
        # This feeds into the prediction engine for companies that slipped past
        # the domain resolver (gov entities, unusual names, etc.)
        org_domain = str(result.get("org_domain", "")).strip()
        if org_domain and not row_dict.get("domain", "").strip() and "domain" not in updates:
            updates["domain"] = org_domain

        vendor_calls.append((vendor, got_email_now or got_linkedin_now))

    if failures:
        updates["_failures"] = failures

    updates["_vendor_calls"] = vendor_calls
    return updates


# ── Public API ─────────────────────────────────────────────────────────────

def enrich(df: pd.DataFrame, checkpoint_fn: Optional[Callable] = None) -> pd.DataFrame:
    """
    Main enrichment function. Processes all leads that are missing
    an email or LinkedIn URL.

    Steps:
      1. Identify leads that need enrichment
      2. Show Apollo credit balance (before)
      3. Pre-fetch all Apollo results in one bulk call
      4. Run per-lead enrichment in a thread pool (10 workers)
      5. Apply updates back to the DataFrame
      6. Show Apollo credit balance (after)
      7. Save vendor performance stats

    checkpoint_fn: optional callback to save progress mid-run (every 50 leads)
    """
    df      = df.copy()
    tracker = _Tracker()

    # Ensure all output columns exist
    for col in ["email_source", "linkedin_source", "failure_reason", "job_title"]:
        if col not in df.columns:
            df[col] = ""

    # Find leads that need enrichment (missing email OR linkedin)
    needs = df.index[
        df["email"].astype(str).str.strip().eq("")
        | df["linkedin_url"].astype(str).str.strip().eq("")
    ].tolist()

    # ── Enrichment cache + master store check ─────────────────────────────
    # Two-layer lookup before any API calls:
    #   Layer 1 — enrichment_cache (30-day TTL, fast lookup)
    #   Layer 2 — contacts_master  (read-only Salesforce export, ZB-validated only)
    # A hit in either layer skips Apollo/Apify entirely for that lead.
    from .database import get_db
    db = get_db()
    if db and needs and "lead_id" in df.columns:
        lead_ids = [str(df.at[idx, "lead_id"]) for idx in needs]

        # Layer 1: short-TTL cache
        cached = db.get_cached_leads(lead_ids)

        # Layer 2: permanent master — fills gaps not covered by the TTL cache
        still_missing = [lid for lid in lead_ids if lid not in cached]
        if still_missing:
            from .pg_master import get_pg_master
            pg_master = get_pg_master()
            if pg_master:
                try:
                    from_master = pg_master.get_master_leads_by_ids(still_missing)
                    cached.update(from_master)
                except Exception as exc:
                    print(f"    [orchestrator] PG master lookup failed: {exc}")

        if cached:
            restored = 0
            for idx in list(needs):
                rec = cached.get(str(df.at[idx, "lead_id"]))
                if not rec:
                    continue
                if rec.get("email"):
                    src_  = rec.get("email_source", "master")
                    vstat = rec.get("email_validation_status", "")
                    # Skip predicted emails that were invalidated in a previous run.
                    # They were built on a bad domain; the domain fix must be allowed
                    # to drive a fresh prediction instead of re-injecting stale data.
                    if src_ == "predicted" and vstat == "invalid":
                        pass
                    else:
                        df.at[idx, "email"]                       = rec["email"]
                        df.at[idx, "email_source"]                = src_
                        df.at[idx, "email_validation_status"]     = vstat
                        df.at[idx, "email_validation_sub_status"] = rec.get("email_validation_sub_status", "")
                if rec.get("linkedin_url"):
                    df.at[idx, "linkedin_url"]    = rec["linkedin_url"]
                    df.at[idx, "linkedin_source"] = rec.get("linkedin_source", "master")
                if rec.get("job_title"):
                    df.at[idx, "job_title"] = rec["job_title"]
                restored += 1
            cached_ids = set(cached.keys())
            needs      = [idx for idx in needs if str(df.at[idx, "lead_id"]) not in cached_ids]
            print(f"    enrichment cache + master: {restored} lead(s) restored — skipping API calls")

    # ── Layer 3: name+company fallback ────────────────────────────────────────
    # Catches leads whose lead_id differs from what's in master (e.g. sourced
    # from the Oracle scraper or a different pipeline run).  Matches by
    # (first_name, last_name, company_normalized) instead.
    if needs and "company_normalized" in df.columns:
        from .pg_master import get_pg_master as _get_pg
        _pg = _get_pg()
        remaining_rows = [df.loc[idx].to_dict() for idx in needs]
        nc_hits: dict = {}
        if _pg:
            try:
                nc_hits.update(_pg.find_contacts_by_name_company(remaining_rows))
            except Exception as exc:
                print(f"    [orchestrator] PG name+company lookup failed: {exc}")
        if nc_hits:
            nc_restored = 0
            nc_found_idx: set = set()
            for idx in list(needs):
                row = df.loc[idx]
                fn  = str(row.get("first_name") or "").lower().strip()
                ln  = str(row.get("last_name")  or "").lower().strip()
                cn  = str(row.get("company_normalized") or "").lower().strip()
                rec = nc_hits.get(f"{fn}|{ln}|{cn}")
                if not rec:
                    continue
                restored_something = False
                if rec.get("email"):
                    src_  = rec.get("email_source", "master")
                    vstat = rec.get("email_validation_status", "")
                    if not (src_ == "predicted" and vstat == "invalid"):
                        df.at[idx, "email"]                       = rec["email"]
                        df.at[idx, "email_source"]                = src_
                        df.at[idx, "email_validation_status"]     = vstat
                        df.at[idx, "email_validation_sub_status"] = rec.get("email_validation_sub_status", "")
                        restored_something = True
                if rec.get("linkedin_url"):
                    df.at[idx, "linkedin_url"]    = rec["linkedin_url"]
                    df.at[idx, "linkedin_source"] = rec.get("linkedin_source", "master")
                    restored_something = True
                if rec.get("job_title"):
                    df.at[idx, "job_title"] = rec["job_title"]
                if restored_something:
                    nc_found_idx.add(idx)
                    nc_restored += 1
            needs = [idx for idx in needs if idx not in nc_found_idx]
            if nc_restored:
                print(f"    name+company lookup     : {nc_restored} lead(s) restored from master — skipping API calls")

    total = len(needs)
    if total == 0:
        print("    orchestrator: all leads already complete")
        # Emit zero-credit lines so the UI Apollo card shows "0 credits" instead of placeholder
        print(f"    Leads routed to Apollo  : 0 of 0 total")
        print(f"    Apollo calls made       : 0  (hits=0  misses=0)")
        print(f"    Apollo hit rate         : 0%")
        print(f"    Apollo email credits    : 0  (email found for 0 lead(s))")
        print(f"    Apollo linkedin credits : 0  (linkedin found for 0 lead(s))")
        print(f"    Apollo linkedin only    : 0  (linkedin found, no email)")
        tracker.save("output/vendor_performance.csv")
        return df

    # ── Apollo Credit Check (BEFORE) ───────────────────────────────────────
    apollo_leads_est = sum(1 for idx in needs if "apollo" in _route(df.loc[idx]))
    apollo_before    = get_apollo_credits()
    src              = apollo_before.get("source", "")

    print(f"\n    {'-'*50}")
    print(f"    Apollo Rate Limits  [BEFORE enrichment]")
    print(f"    {'-'*50}")
    print(f"    Leads routed to Apollo  : {apollo_leads_est:,} of {total:,} total")
    if apollo_leads_est > 0:
        print(f"    Credit note             : run_waterfall_email=True is active.")
        print(f"      Apollo searches external sources when its own DB has no match.")
        print(f"      Cost: ~{APOLLO_CREDITS_PER_HIT}–{APOLLO_WATERFALL_CREDIT_EST} credits per lead matched (varies by plan).")
    _print_apollo_limits(apollo_before)
    print(f"    {'-'*50}\n")

    # ── Build per-lead work list ───────────────────────────────────────────
    rows_to_process = [
        (idx, df.loc[idx].to_dict(), _route(df.loc[idx]))
        for idx in needs
    ]

    # ── Pre-fetch ALL Apollo results in one bulk batch ────────────────────
    # This is much more efficient than calling Apollo once per lead.
    # Apollo's bulk_match handles up to 10 leads per request.
    apollo_routed = [
        (idx, row_dict)
        for idx, row_dict, order in rows_to_process
        if "apollo" in order
    ]
    if apollo_routed:
        bulk_payloads = [_build_apollo_payload(rd) for _, rd in apollo_routed]
        bulk_results  = _call_apollo_bulk(bulk_payloads)
        apollo_cache  = {idx: res for (idx, _), res in zip(apollo_routed, bulk_results)}
    else:
        apollo_cache = {}

    # ── Thread pool: enrich all leads in parallel ──────────────────────────
    pbar      = tqdm(total=total, desc="    enriching", unit="lead", leave=False)
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_map = {
            pool.submit(_enrich_lead, idx, row_dict, order, apollo_cache): (idx, row_dict)
            for idx, row_dict, order in rows_to_process
        }

        for future in as_completed(future_map):
            idx, row_dict = future_map[future]
            domain = str(row_dict.get("domain", "")).strip()

            try:
                updates = future.result()
            except Exception as exc:
                df.at[idx, "failure_reason"] = append_failure(
                    df.at[idx, "failure_reason"], f"enrichment_error: {exc}"
                )
                pbar.update(1)
                completed += 1
                continue

            # Apply field updates to the DataFrame
            got_email    = "email"        in updates
            got_linkedin = "linkedin_url" in updates
            failures     = updates.pop("_failures",     [])
            vendor_calls = updates.pop("_vendor_calls", [])

            for field, value in updates.items():
                df.at[idx, field] = value

            if failures:
                df.at[idx, "failure_reason"] = append_failure(
                    df.at[idx, "failure_reason"], "; ".join(failures)
                )

            # Record vendor call stats for the performance report
            for vendor, got_any in vendor_calls:
                tracker.record_call(vendor, got_any)

            source = updates.get("email_source") or updates.get("linkedin_source", "")
            if source:
                tracker.record(source, domain, got_email, got_linkedin)

            # Print to terminal when a lead is successfully enriched
            if got_email or got_linkedin:
                fields = " + ".join(
                    f for f, g in [("email", got_email), ("linkedin", got_linkedin)] if g
                )
                name = f"{row_dict.get('first_name', '')} {row_dict.get('last_name', '')}".strip()
                tqdm.write(f"    [{source}] {name} -> {fields}")

            pbar.update(1)
            completed += 1

            # Save checkpoint every 50 leads so a crash doesn't lose all progress
            if checkpoint_fn and completed % 50 == 0:
                checkpoint_fn(df, "enrichment_partial")

    pbar.close()
    print(f"    orchestrator: {total}/{total} leads processed")

    # ── Apollo Credit Check (AFTER) ────────────────────────────────────────
    apollo_hits, apollo_misses = tracker.apollo_stats()
    bd = tracker.apollo_credit_breakdown()
    apollo_after = get_apollo_credits()

    print(f"\n    {'-'*50}")
    print(f"    Apollo Rate Limits  [AFTER enrichment]")
    print(f"    {'-'*50}")
    print(f"    Apollo calls made       : {apollo_hits + apollo_misses:,}  (hits={apollo_hits:,}  misses={apollo_misses:,})")
    if apollo_hits + apollo_misses > 0:
        print(f"    Apollo hit rate         : {apollo_hits / (apollo_hits + apollo_misses) * 100:.0f}%")
    print(f"    Apollo email credits    : {bd['email_hits']:,}  (email found for {bd['email_hits']:,} lead(s))")
    print(f"    Apollo linkedin credits : {bd['linkedin_hits']:,}  (linkedin found for {bd['linkedin_hits']:,} lead(s))")
    print(f"    Apollo linkedin only    : {bd['linkedin_only']:,}  (linkedin found, no email)")
    _print_apollo_limits(apollo_after)
    print(f"    {'-'*50}\n")

    tracker.save("output/vendor_performance.csv")
    return df
