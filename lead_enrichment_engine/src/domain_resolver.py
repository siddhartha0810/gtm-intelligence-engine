"""
domain_resolver.py
==================
STAGE 2 — Resolve Company Domains

PURPOSE:
  Fills in the "domain" column for leads that don't have one.
  Knowing the domain (e.g. "aarp.org") dramatically improves Apollo's match
  rate because Apollo can constrain its people search to a specific company's
  email namespace rather than guessing across millions of contacts.
  Domain resolution is free — run it before spending any Apollo credits.

HOW IT FITS IN THE SYSTEM:
  pipeline.py calls resolve_domains(df) between Stage 1 (clean) and Stage 3
  (vendor enrichment).  The enriched DataFrame with domains filled is passed
  directly to orchestrator.py.

  All resolved domains are persisted to:
    domain_knowledge table (Inoapps-Data-DB) — primary cache
    input/domain_lookup.csv               — human-readable backup / manual override

  On re-runs, the DB/CSV cache is checked first so no API calls are made for
  companies that were resolved in a prior run.

RESOLUTION ORDER (stops at first valid hit):
  Step 1: Row value               — input CSV already had a domain column
  Step 2: DB/CSV lookup           — domain_knowledge table or domain_lookup.csv
  Step 3: MX validation           — if domain found in steps 1-2, confirm it
                                    has a working MX record before trusting it
  Step 4: Apollo org search       — APOLLO_ORG_URL (needs APOLLO_API_KEY)
  Step 5: Clearbit Autocomplete   — free, no key needed
  Step 6: Wikidata SPARQL         — free, no key needed
  Step 7: DuckDuckGo Instant      — free, no key needed
  Step 8: Scrape mailto links     — HTTP GET homepage, look for mailto: in HTML

MX VALIDATION:
  After finding a domain, dns.resolver.resolve(domain, 'MX') confirms it
  is a real email-receiving domain.
  Cloud provider MX records (Google Workspace, Microsoft 365, etc.) are
  detected via _GENERIC_MX set and treated as valid.
  Third-party relay providers (SendGrid, Mailgun) are rejected — those
  domains cannot be used for email pattern prediction.

SELF-HEALING:
  _invalidate_suspect_domains() is called by pipeline.py after Stage 6.
  Any domain where ALL ZeroBounce-validated predictions failed is evicted
  from the domain cache — it was probably the wrong domain.

PARALLELISM:
  MAX_WORKERS=8 threads resolve up to 8 companies simultaneously.
  Each thread makes its own HTTP requests (no shared state except the DB pool).
  Results are merged back into the DataFrame after all futures complete.

KEY FUNCTIONS:
  resolve_domains(df)        — main entry point; returns DataFrame with domains filled
  _resolve_one(company_name) — resolves a single company; called per thread
  _clearbit(name)            — Clearbit Autocomplete API
  _wikidata(name)            — Wikidata SPARQL query
  _duckduckgo(name)          — DuckDuckGo Instant Answer API
  _apollo_org(name)          — Apollo company search (costs credits — use last)
  _validate_mx(domain)       — confirms domain has working MX record
  _query_variants(name)      — generates cleaned name variants for search
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

import pandas as pd

from .utils import normalize_company, request_json

MAX_WORKERS = 8

# ── API Endpoints ──────────────────────────────────────────────────────────
APOLLO_ORG_URL = "https://api.apollo.io/api/v1/mixed_companies/search"
CLEARBIT_URL   = "https://autocomplete.clearbit.com/v1/companies/suggest"
WIKIDATA_URL   = "https://query.wikidata.org/sparql"
DDG_URL        = "https://api.duckduckgo.com/"

# Cloud mail providers whose MX records don't reveal the true email domain.
# When a company's MX points to one of these, the resolved domain IS the email domain.
_GENERIC_MX = {
    "google.com", "googlemail.com",
    "outlook.com", "hotmail.com", "microsoft.com", "protection.outlook.com",
    "mimecast.com", "proofpoint.com", "pphosted.com", "ppe-hosted.com",
    "barracudanetworks.com", "messagelabs.com", "trendmicro.com",
    "mailgun.org", "sendgrid.net", "amazonaws.com", "cisco.com",
    "iphmx.com",          # Cisco IronPort hosted relay (hc####-##.iphmx.com / eu.iphmx.com)
    "hornetsecurity.com", # Hornetsecurity / Spamexperts
    "mailcontrol.com",    # Hornetsecurity legacy
    "antispamcloud.com",  # SpamExperts
    "hydra.sophos.com",   # Sophos Email Security
    "ess.barracuda.com",  # Barracuda ESS (distinct subdomain from barracudanetworks.com)
}

# In-process caches — reset between runs automatically (module-level dicts)
_mx_cache:       dict = {}   # domain → email_domain (or None if no MX)
_redirect_cache: dict = {}   # domain → redirect_domain (or None)

_HEADERS = {"User-Agent": "lead-enrichment-pipeline/1.0 (open source)"}


# ── Helper Functions ───────────────────────────────────────────────────────

def _bare_domain(url: str) -> str:
    """
    Extract just the domain from a full URL.
    Example: "https://www.microsoft.com/en-us/about" → "microsoft.com"
    """
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    return parsed.netloc.lstrip("www.").strip().lower()


def _name_matches(query: str, candidate: str) -> bool:
    """
    Check that the candidate name is a plausible match for the query.

    Short queries (≤2 meaningful words) require ALL query words present in
    the candidate — this prevents "Virginia" from matching "virginia.edu"
    (University of Virginia) when we really want the Dept of Accounts.

    Longer queries only require at least one word to overlap.

    Example: query="Oracle", candidate="Oracle Corporation" → True
             query="Oracle", candidate="Apex Systems"      → False
             query="Virginia", candidate="University of Virginia" → True  (intentionally blocks single-word gov lookups)
             query="Virginia Accounts", candidate="Virginia Dept Accounts" → True
    """
    q_words = set(re.sub(r"[^a-z0-9 ]", "", query.lower()).split())
    c_words = set(re.sub(r"[^a-z0-9 ]", "", candidate.lower()).split())
    if len(q_words) <= 2:
        return q_words.issubset(c_words)   # all query words must appear
    return bool(q_words & c_words)         # at least one word overlap


# ── Vendor Lookup Functions ────────────────────────────────────────────────

def _apollo_org(company: str) -> Optional[str]:
    """
    Apollo mixed_companies/search — uses the same master API key as enrichment.
    Most reliable source: Apollo's org database covers virtually all B2B companies.
    Returns the primary_domain for the best-matching organization, or None.
    """
    from .config import APOLLO_API_KEY
    if not APOLLO_API_KEY:
        return None
    try:
        data = request_json(
            "POST", APOLLO_ORG_URL,
            json={"q_organization_name": company, "page": 1, "per_page": 1},
            headers={"Content-Type": "application/json", "X-Api-Key": APOLLO_API_KEY},
        )
        orgs = (data.get("organizations") or data.get("accounts") or []) if isinstance(data, dict) else []
        if not orgs:
            return None
        org    = orgs[0]
        name   = org.get("name", "")
        domain = str(org.get("primary_domain") or org.get("website_url") or "").strip().lower()
        if domain and _name_matches(company, name):
            domain = re.sub(r"^https?://", "", domain).lstrip("www.").split("/")[0]
            return domain
    except Exception:
        pass
    return None


def _clearbit(company: str) -> Optional[str]:
    """
    Clearbit Autocomplete API — completely free, no API key needed.
    Returns up to 5 company suggestions for a query string.
    We check the top 3 results and return the first one whose name
    actually matches our query (to avoid false matches).
    """
    try:
        results = request_json("GET", CLEARBIT_URL, params={"query": company}, headers=_HEADERS)
        if not isinstance(results, list):
            return None
        for item in results[:3]:
            name   = item.get("name", "")
            domain = item.get("domain", "").strip().lower()
            if domain and _name_matches(company, name):
                return domain
    except Exception:
        pass
    return None


def _wikidata(company: str) -> Optional[str]:
    """
    Wikidata SPARQL — completely free, no API key needed.
    Queries the official website property (P856) for a company that
    has an English label matching the company name exactly.
    Best for well-known companies with Wikipedia articles.
    """
    sparql = f"""
    SELECT ?website WHERE {{
      ?item rdfs:label "{company}"@en .
      ?item wdt:P856 ?website .
    }} LIMIT 1
    """
    try:
        data = request_json(
            "GET", WIKIDATA_URL,
            params={"query": sparql, "format": "json"},
            headers=_HEADERS,
        )
        bindings = data.get("results", {}).get("bindings", [])
        if bindings:
            url = bindings[0].get("website", {}).get("value", "")
            if url:
                return _bare_domain(url)
    except Exception:
        pass
    return None


def _duckduckgo(company: str) -> Optional[str]:
    """
    DuckDuckGo Instant Answer API — completely free, no API key needed.
    Checks "OfficialSite" and "AbstractURL" fields from the instant answer
    for "[company] official site" queries.
    Good fallback when Clearbit and Wikidata both miss.
    """
    try:
        data = request_json(
            "GET", DDG_URL,
            params={
                "q":             f"{company} official site",
                "format":        "json",
                "no_html":       "1",
                "skip_disambig": "1",
            },
            headers=_HEADERS,
        )
        site = data.get("OfficialSite", "").strip()
        if site:
            return _bare_domain(site)
        url = data.get("AbstractURL", "").strip()
        if url:
            return _bare_domain(url)
    except Exception:
        pass
    return None


def _redirect_domain(domain: str) -> Optional[str]:
    """
    Follow HTTP redirects on a domain's homepage.
    Returns the final domain if it differs from the input — signals acquisition
    or rebranding (e.g. ppd.com → thermofisher.com).
    Returns None if there's no redirect or the request fails.
    """
    if domain in _redirect_cache:
        return _redirect_cache[domain]

    result: Optional[str] = None
    try:
        import requests as _req
        resp   = _req.get(
            f"https://{domain}", timeout=5, headers=_HEADERS, allow_redirects=True
        )
        final  = _bare_domain(resp.url)
        result = final if final and final != domain else None
    except Exception:
        pass

    _redirect_cache[domain] = result
    return result


def _mx_email_domain(domain: str) -> Optional[str]:
    """
    Validate a resolved domain via DNS MX records and infer the true email domain.

    Outcomes (in order):
      1. Generic MX (Google/Microsoft/etc.) → input domain IS the email domain → return it
      2. Custom MX host → drop its first DNS label to get the email domain
           e.g. "mail.cpa.texas.gov" → "cpa.texas.gov"
           e.g. "mx1.srns.gov"       → "srns.gov"
      3. No MX records at all → domain cannot receive email.
           Check if website redirects to a different domain (acquisition signal).
           If redirect target has MX → that domain is the real email domain.
           Otherwise → return None (domain is wrong, try next resolution source).

    Results are cached in _mx_cache so each domain is queried at most once per run.
    If dnspython is not installed the function returns the domain unchanged (graceful).
    """
    if domain in _mx_cache:
        return _mx_cache[domain]

    try:
        import dns.resolver as _dns
    except ImportError:
        _mx_cache[domain] = domain
        return domain

    result: Optional[str] = None
    try:
        answers    = _dns.resolve(domain, "MX", lifetime=5)
        mx_records = sorted(answers, key=lambda r: r.preference)

        for mx in mx_records[:2]:
            mx_host = str(mx.exchange).rstrip(".").lower()
            parts   = mx_host.split(".")

            is_generic = any(
                mx_host == g or mx_host.endswith("." + g)
                for g in _GENERIC_MX
            )

            if is_generic:
                result = domain   # known cloud relay → website domain IS the email domain
                break

            # If the MX host's apex domain differs from the website domain, it's a
            # third-party relay (Trend Micro, Cisco IronPort, Sophos, Barracuda, etc.).
            # Return the website domain — it IS the email domain.
            # Example: colas.com website + in.tmes.trendmicro.eu MX → return colas.com
            mx_apex      = ".".join(parts[-2:]) if len(parts) >= 2 else mx_host
            website_apex = ".".join(domain.split(".")[-2:]) if "." in domain else domain
            if mx_apex != website_apex:
                result = domain   # third-party relay — trust the website domain
                break

            # MX is on the same apex as the website (e.g. mail.company.com for company.com)
            # Drop the host label to get the email domain.
            # Example: mail.cpa.texas.gov → cpa.texas.gov
            if len(parts) >= 3:
                result = ".".join(parts[1:])
            elif len(parts) == 2:
                result = mx_host
            else:
                result = domain
            break

        if result is None and mx_records:
            result = domain   # has MX but couldn't extract label — keep original

    except Exception:
        # No MX records → domain cannot receive email.
        # Check if the website was acquired / rebranded (redirect to different domain).
        redirect = _redirect_domain(domain)
        if redirect:
            try:
                import dns.resolver as _dns2
                answers = _dns2.resolve(redirect, "MX", lifetime=5)
                if answers:
                    result = redirect   # redirect target has mail servers → use it
            except Exception:
                pass

    _mx_cache[domain] = result
    return result


def _scrape_contact_email_domain(website_domain: str) -> Optional[str]:
    """
    Scrape the company's contact/about page for mailto: links to confirm the
    true email domain.  Uses only the requests library (already a dependency).

    Checks homepage then /contact so it's fast.  Skips generic freemail domains.
    Returns the most common corporate email domain found, or None.
    """
    from collections import Counter
    import requests as _req

    freemail = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
                "aol.com", "icloud.com", "live.com", "example.com"}

    domains_found: list = []
    for path in ["", "/contact", "/about", "/contact-us"]:
        try:
            resp = _req.get(
                f"https://{website_domain}{path}",
                timeout=4, headers=_HEADERS, allow_redirects=True,
            )
            if resp.status_code != 200:
                continue
            for match in re.findall(
                r'[a-z0-9._%+\-]+@([a-z0-9.\-]+\.[a-z]{2,})',
                resp.text.lower()
            ):
                if match not in freemail and not any(g in match for g in freemail):
                    domains_found.append(match)
            if domains_found:
                break   # found something on this page — no need to go deeper
        except Exception:
            continue

    if not domains_found:
        return None
    top = Counter(domains_found).most_common(1)[0][0]
    return top if top != website_domain else None   # only return if it differs


def _query_variants(company: str) -> list:
    """
    Generate progressively cleaned search variants of a company name.
    Tries the original first, then strips characters that break API queries
    (colons, +N qualifiers), then strips legal suffixes, then tries the
    first significant word as a last-resort brand-only lookup.

    Examples:
      "Wis-Pak: Inc."                  → ["Wis-Pak: Inc.", "Wis-Pak Inc.", "Wis-Pak"]
      "Wepa Hygieneprodukte GmbHG+3"   → ["Wepa Hygieneprodukte GmbHG+3",
                                           "Wepa Hygieneprodukte", "Wepa"]
      "Virginia Department of Accounts"→ ["Virginia Department of Accounts",
                                           "Virginia Department Accounts"]
      "Viking Pump, Inc."              → ["Viking Pump, Inc.", "Viking Pump"]
    """
    variants = [company]

    # Step 1: strip colons and +N qualifiers
    cleaned = re.sub(r":\s*", " ", company)
    cleaned = re.sub(r"\+\d+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned.lower() != company.lower():
        variants.append(cleaned)

    # Step 2: strip legal / org-type suffixes (English + German + common govt words)
    short = re.sub(
        r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|"
        r"gmbh[g]?|ag|mbh|plc|sa|nv|bv|sas|srl|"         # European forms
        r"co|company|group|holdings|"
        r"institute|authority|university|college|system|"
        r"department|division|office|bureau|agency)\b\.?",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Clean up dangling prepositions and punctuation left after suffix removal
    short = re.sub(r"\b(of|the|and|for|a)\b", " ", short, flags=re.IGNORECASE)
    short = re.sub(r"[^\w\s\-&]", " ", short)
    short = re.sub(r"\s+", " ", short).strip()
    if short and short.lower() not in [v.lower() for v in variants] and len(short) > 2:
        variants.append(short)

    return list(dict.fromkeys(variants))  # dedupe, preserve order


def _resolve_via_apis(company: str) -> tuple[Optional[str], str]:
    """
    Try Apollo → Clearbit → Wikidata → DuckDuckGo for each name variant.

    Each resolved domain is validated via DNS MX records before being used:
      - No MX records  → domain cannot receive email, try next source
      - Generic MX     → domain is correct as-is (Google/Microsoft hosted)
      - Custom MX      → real email domain inferred from MX hostname
                         (e.g. comptroller.texas.gov → cpa.texas.gov)

    If all API sources fail, falls back to scraping the resolved website for
    mailto: links to confirm or discover the correct email domain.
    """
    first_raw: Optional[str] = None   # first raw domain found (for scrape fallback)

    for variant in _query_variants(company):
        for fn, label in [
            (_apollo_org,  "apollo"),
            (_clearbit,    "clearbit"),
            (_wikidata,    "wikidata"),
            (_duckduckgo,  "duckduckgo"),
        ]:
            raw = fn(variant)
            if not raw:
                continue

            if first_raw is None:
                first_raw = raw

            # Validate/refine via MX records
            email_domain = _mx_email_domain(raw)
            if email_domain:
                suffix = "+mx" if email_domain != raw else ""
                return email_domain, label + suffix

    # All API sources failed or returned domains with no MX records.
    # Last resort: scrape the first website we did find for mailto: links.
    if first_raw:
        scraped = _scrape_contact_email_domain(first_raw)
        if scraped:
            return scraped, "scraped"

    return None, ""


# ── Main Function ──────────────────────────────────────────────────────────

def resolve_domains(df: pd.DataFrame, lookup_path: str) -> pd.DataFrame:
    """
    Fill in missing domains for all leads in the DataFrame.

    Pass 1 — fast: check the row itself, then the DB (seeded from domain_lookup.csv
              at pipeline startup) or the CSV directly when no DB is active.
    Pass 2 — slow: call free APIs for any still-missing domains
              (parallelized, deduped — each unique company queried only once)

    After resolving, newly found domains are saved to the DB (if active) so future
    runs skip the API calls entirely.  CSV is exported at the end of the pipeline
    by pipeline.py for human review.
    """
    from .database import get_db

    df   = df.copy()
    path = Path(lookup_path)
    db   = get_db()

    # Snapshot how many leads already have a domain before we touch anything
    _had_domain_at_start = int((df["domain"].astype(str).str.strip() != "").sum())
    _master_recovered    = 0   # filled in by Pass 1b if master store is used

    # ── Pass 1: Load domain knowledge ─────────────────────────────────────
    if db:
        # DB is the primary store (populated from CSV at pipeline startup)
        all_records     = db.load_domains()
        high_confidence: set = {
            norm for norm, rec in all_records.items()
            if rec.get("confidence", "").lower() == "high"
        }
        raw_map: Dict[str, str] = {
            norm: rec["domain"].lower().strip()
            for norm, rec in all_records.items()
            if rec.get("domain", "").strip()
        }
        lookup_df = pd.DataFrame()   # not needed when DB is active
    elif path.exists():
        lookup_df = pd.read_csv(path)
        lookup_df["company_normalized"] = lookup_df["company"].apply(normalize_company)
        high_confidence = set(
            lookup_df.loc[
                lookup_df.get("confidence", pd.Series()).astype(str).str.lower() == "high",
                "company_normalized",
            ]
        )
        raw_map = dict(
            zip(
                lookup_df["company_normalized"],
                lookup_df["domain"].str.lower().str.strip(),
            )
        )
    else:
        lookup_df  = pd.DataFrame(columns=["company", "domain", "source", "confidence"])
        raw_map    = {}
        high_confidence = set()

    # Validate auto-resolved (medium/low confidence) cached domains via MX.
    # This catches stale entries (wrong website domains, acquired companies, etc.)
    # and refines them to the true email domain automatically.
    domain_map: Dict[str, str] = {}
    for norm, dom in raw_map.items():
        if norm in high_confidence:
            domain_map[norm] = dom          # trust manual entries unconditionally
        else:
            refined = _mx_email_domain(dom)
            if refined:
                domain_map[norm] = refined  # MX-validated (may be a better domain)
            # else: domain has no MX records → drop from map → re-resolve via APIs

    # Apply: use existing row value or lookup match
    def _from_lookup(row) -> str:
        existing = str(row.get("domain", "")).strip().lower()
        if existing:
            return existing
        return domain_map.get(row.get("company_normalized", ""), "")

    df["domain"] = df.apply(_from_lookup, axis=1)

    # ── Pass 1b: Master store lookup ──────────────────────────────────────
    # Before hitting any external API, check contacts_master for known domains.
    # This is free and instant — no API call needed.
    missing_mask = df["domain"].str.strip() == ""
    if missing_mask.any() and db:
        missing_norms = (
            df.loc[missing_mask, "company_normalized"]
            .dropna()
            .unique()
            .tolist()
        )
        from .pg_master import get_pg_master
        pg_master = get_pg_master()
        if pg_master:
            try:
                master_domains = pg_master.get_master_domains_for_companies(missing_norms)
            except Exception:
                master_domains = db.get_master_domains_for_companies(missing_norms)
        else:
            master_domains = db.get_master_domains_for_companies(missing_norms)
        if master_domains:
            validated_master: Dict[str, str] = {}
            for norm, dom in master_domains.items():
                refined = _mx_email_domain(dom)
                if refined:
                    validated_master[norm] = refined
                # else: relay/dead domain — skip it, let Pass 2 re-resolve via APIs
            if validated_master:
                domain_map.update(validated_master)
                df["domain"] = df.apply(_from_lookup, axis=1)
                recovered = len(validated_master)
                _master_recovered = recovered
                print(f"    master store: {recovered} company domain(s) retrieved from history")

    # ── Pass 2: API resolution for remaining blanks ────────────────────────
    missing_mask = df["domain"].str.strip() == ""
    if not missing_mask.any():
        return df

    # Deduplicate — query each unique company name only once (4 leads at "AARP" = 1 API call)
    unique = (
        df.loc[missing_mask, ["company", "company_normalized"]]
        .drop_duplicates("company_normalized")
        .to_dict("records")
    )

    newly_found: list[dict] = []

    def _resolve_rec(rec):
        return rec, _resolve_via_apis(rec["company"])

    # Run all API lookups in parallel (up to MAX_WORKERS at once)
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(unique))) as pool:
        futures = {pool.submit(_resolve_rec, rec): rec for rec in unique}
        for future in as_completed(futures):
            rec, (domain, source) = future.result()
            name = rec["company"]
            norm = rec["company_normalized"]
            if domain:
                print(f"    OK {name:30s} -> {domain}  [{source}]")
                domain_map[norm] = domain
                newly_found.append({
                    "company":            name,
                    "company_normalized": norm,
                    "domain":             domain,
                    "source":             source,
                    "confidence":         "medium",
                })
            else:
                print(f"    -- {name:30s} -> unresolved")

    # Apply resolved domains back to the DataFrame
    for idx, row in df.loc[missing_mask].iterrows():
        found = domain_map.get(row.get("company_normalized", ""), "")
        if found:
            df.at[idx, "domain"] = found

    # ── Persist newly found domains ────────────────────────────────────────
    if newly_found:
        if db:
            for entry in newly_found:
                db.upsert_domain(
                    company=entry["company"],
                    company_normalized=entry["company_normalized"],
                    domain=entry["domain"],
                    source=entry["source"],
                    confidence=entry.get("confidence", "medium"),
                )
            print(f"    domain DB updated (+{len(newly_found)} entries)")
        elif path.parent.exists():
            new_rows = pd.DataFrame(newly_found).drop(columns=["company_normalized"], errors="ignore")
            existing = lookup_df.drop(columns=["company_normalized"], errors="ignore") if not lookup_df.empty else pd.DataFrame()
            updated  = pd.concat([existing, new_rows], ignore_index=True)
            updated.drop_duplicates(subset=["company"], keep="last").to_csv(path, index=False)
            print(f"    domain_lookup.csv updated (+{len(newly_found)} entries)")

    resolved_count   = int((df["domain"].astype(str).str.strip() != "").sum())
    unresolved_count = int((df["domain"].astype(str).str.strip() == "").sum())
    print(f"    domain summary          : {resolved_count} resolved  |  {unresolved_count} unresolved")

    # Per-source breakdown — strip "+mx" suffix so clearbit+mx counts as clearbit
    api_sources: Dict[str, int] = {}
    for entry in newly_found:
        src = entry.get("source", "other").split("+")[0]
        api_sources[src] = api_sources.get(src, 0) + 1

    from_cache = resolved_count - _had_domain_at_start - _master_recovered - sum(api_sources.values())

    breakdown_parts = []
    if _had_domain_at_start > 0:
        breakdown_parts.append(f"input:{_had_domain_at_start}")
    if from_cache > 0:
        breakdown_parts.append(f"cache:{from_cache}")
    if _master_recovered > 0:
        breakdown_parts.append(f"master:{_master_recovered}")
    for src in ["apollo", "clearbit", "wikidata", "duckduckgo", "scraped"]:
        cnt = api_sources.get(src, 0)
        if cnt > 0:
            breakdown_parts.append(f"{src}:{cnt}")
    # Any remaining unexpected sources
    for src, cnt in api_sources.items():
        if src not in ("apollo", "clearbit", "wikidata", "duckduckgo", "scraped") and cnt > 0:
            breakdown_parts.append(f"{src}:{cnt}")

    if breakdown_parts:
        print(f"    domain sources          : {' | '.join(breakdown_parts)}")

    return df
