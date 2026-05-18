"""
cleaner.py
==========
STAGE 1 — Clean & Deduplicate

Takes the raw input CSV and prepares it for the rest of the pipeline:
  1. Renames columns to canonical names (handles many naming variations)
  2. Validates that required columns exist
  3. Adds empty optional columns if missing
  4. Normalizes all text (strips whitespace, fixes casing)
  5. Generates a unique lead_id for each row
  6. Deduplicates:
       - Rows with the same email → keep first occurrence
       - Rows without email → deduplicate on (first_name, last_name, company)
"""

import pandas as pd
from .utils import normalize_company, normalize_email, normalize_text, make_lead_id

# ── Column Definitions ─────────────────────────────────────────────────────

# These three columns MUST exist in the input file (under any of their aliases)
REQUIRED_COLUMNS = ["first_name", "last_name", "company"]

# These columns are optional — they'll be added as empty strings if missing
OPTIONAL_COLUMNS = [
    "domain", "email", "linkedin_url", "job_title", "email_source",
    "linkedin_source", "email_validation_status", "email_validation_sub_status",
    "email_prediction_pattern", "email_prediction_confidence",
    "ready_for_outreach", "failure_reason",
]

# ── Column Name Aliases ────────────────────────────────────────────────────
# Maps many common header variations → one canonical name.
# This lets the pipeline accept CSV files from different CRMs and sources
# without the user having to rename their columns first.
_COLUMN_ALIASES = {
    "first_name":   ["first_name", "firstname", "first name", "fname", "given_name", "given name"],
    "last_name":    ["last_name",  "lastname",  "last name",  "lname", "surname", "family_name", "family name"],
    "company":      ["company", "company_name", "company name", "organization", "org", "employer", "account"],
    "domain":       ["domain", "website", "company_domain", "company domain", "web"],
    "email":        ["email", "email_address", "email address", "work_email", "work email", "business_email"],
    "linkedin_url": ["linkedin_url", "linkedin", "linkedin url", "linkedin_profile", "profile_url",
                     "person linkedin url", "person_linkedin_url", "linkedin profile url",
                     "linkedin profile", "linkedin_profile_url", "contact linkedin url"],
    "job_title":    ["job_title", "title", "job title", "position", "role"],
}


def _normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename columns to canonical names using the alias lookup table.
    Matching is case-insensitive and space-insensitive.

    Example:
      "First Name" → "first_name"
      "Company Name " → "company"   (trailing space stripped)
      "Title" → "job_title"
    """
    alias_map = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            alias_map[alias.lower().strip()] = canonical

    rename = {}
    for col in df.columns:
        mapped = alias_map.get(col.lower().strip())
        if mapped and mapped not in rename.values():
            rename[col] = mapped

    return df.rename(columns=rename)


def clean_leads(df: pd.DataFrame) -> pd.DataFrame:
    """
    Main cleaning function. Takes raw input DataFrame, returns a clean one.

    Steps:
      1. Rename columns using alias map
      2. Check that first_name, last_name, company all exist
      3. Add any missing optional columns as empty strings
      4. Normalize text in each column
      5. Generate a unique lead_id per row
      6. Mark existing emails as source="input"
      7. Deduplicate
    """
    df = df.copy()

    # Step 1: Normalize column headers
    df = _normalize_headers(df)

    # Step 2: Validate required columns exist
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"CSV is missing required column(s): {missing}. "
            f"Got columns: {list(df.columns)}. "
            f"Accepted aliases — first_name: {_COLUMN_ALIASES['first_name']}, "
            f"last_name: {_COLUMN_ALIASES['last_name']}, company: {_COLUMN_ALIASES['company']}"
        )

    # Step 3: Add missing optional columns as empty strings
    for col in OPTIONAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    # Step 4: Normalize text in each column
    df["first_name"] = df["first_name"].apply(normalize_text).str.title()    # "john" → "John"
    df["last_name"]  = df["last_name"].apply(normalize_text).str.title()     # "smith" → "Smith"
    df["company"]    = df["company"].apply(normalize_text)
    df["company_normalized"] = df["company"].apply(normalize_company)         # for dedup matching
    df["domain"]     = df["domain"].apply(lambda v: normalize_text(v).lower())
    df["email"]      = df["email"].apply(normalize_email)                     # validates @ present
    df["linkedin_url"] = df["linkedin_url"].apply(normalize_text)

    # Step 5: Generate a unique lead_id for each row
    # The ID is a hash of (first_name, last_name, company, domain) — stable across runs
    df["lead_id"] = df.apply(
        lambda r: make_lead_id(r["first_name"], r["last_name"], r["company"], r.get("domain", "")),
        axis=1,
    )

    # Step 6: Mark input data sources
    # Email: normalize any source that didn't come from the pipeline internals to "input"
    # (covers empty source AND CRM-specific labels like "salesforce", "hubspot", "crm")
    # so Stage 4 always validates emails that arrived from outside the pipeline.
    _PIPELINE_SOURCES = frozenset({"apollo", "apify", "predicted", "zoominfo", "master"})
    has_email = df["email"].str.strip() != ""
    needs_email_source = has_email & ~df["email_source"].str.strip().isin(_PIPELINE_SOURCES)
    df.loc[needs_email_source, "email_source"] = "input"

    # LinkedIn: set source to "input" for any input linkedin URL that has no source yet
    has_linkedin = df["linkedin_url"].str.strip() != ""
    df.loc[has_linkedin & (df["linkedin_source"].str.strip() == ""), "linkedin_source"] = "input"

    # Step 7: Deduplicate
    # - Leads WITH email: deduplicate on email address (same email = same person)
    # - Leads WITHOUT email: deduplicate on (first_name, last_name, company)
    email_df    = df[has_email].drop_duplicates(subset=["email"], keep="first")
    no_email_df = df[~has_email].drop_duplicates(
        subset=["first_name", "last_name", "company_normalized"], keep="first"
    )
    df = pd.concat([email_df, no_email_df], ignore_index=True)

    return df
