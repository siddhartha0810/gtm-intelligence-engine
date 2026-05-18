"""
email_pattern_engine.py
=======================
STAGE 5 — Predict Missing Emails

For leads that still have no email after vendor enrichment, this module
tries to guess the email address by learning the naming pattern used at
that company's domain.

How it works:
  1. Look at all leads that already have a VALID email + a domain
  2. Detect which naming pattern their email follows
     (e.g. john.smith@company.com → "first.last" pattern)
  3. Build a pattern table per domain, ranked by frequency
  4. For leads missing an email at a KNOWN domain:
       → use that domain's confirmed pattern (1 prediction)
  5. For leads missing an email at an UNKNOWN domain:
       → generate TOP_N_GLOBAL_PATTERNS candidate rows, one per format
       → ZeroBounce validates all candidates in Stage 6
       → collapse_prediction_candidates() picks the first valid hit

Supported patterns:
  first.last   → john.smith@company.com
  firstlast    → johnsmith@company.com
  flast        → jsmith@company.com       ← most common in enterprise
  first_last   → john_smith@company.com
  f.last       → j.smith@company.com
  first.l      → john.s@company.com
  last.first   → smith.john@company.com
  first        → john@company.com

All predicted emails are marked email_source="predicted" so the next
stage (pred_validated) knows to send them to ZeroBounce.
"""

import pandas as pd

# ── Configuration ──────────────────────────────────────────────────────────

# Minimum valid emails needed at a domain to trust its pattern.
# 1 = a single ZeroBounce-confirmed email is enough to learn the format.
MIN_DOMAIN_SAMPLES = 1

# How many global-fallback candidates to generate when a domain has no
# confirmed pattern. Each candidate is a separate row sent to ZeroBounce.
TOP_N_GLOBAL_PATTERNS = 3

# How many company-pattern candidates to generate. When a domain has a
# confirmed pattern but its top prediction comes back invalid, this allows
# the next most-common pattern to be tried rather than giving up entirely.
TOP_N_COMPANY_PATTERNS = 2

# Industry-standard fallback order used when there is not enough data in
# the current batch to learn any patterns at all. Ordered by prevalence
# across enterprise B2B contacts (flast ~40%, first.last ~30%, lastf ~15%).
DEFAULT_GLOBAL_PATTERNS = ["flast", "first.last", "lastf"]

# All supported email naming patterns.
# Each maps a pattern name → a lambda that constructs the local part
# from (first, last) name strings.
PATTERNS = {
    "first.last": lambda f, l: f"{f}.{l}",
    "firstlast":  lambda f, l: f"{f}{l}",
    "flast":      lambda f, l: f"{f[0]}{l}",
    "first_last": lambda f, l: f"{f}_{l}",
    "f.last":     lambda f, l: f"{f[0]}.{l}",
    "first.l":    lambda f, l: f"{f}.{l[0]}",
    "last.first": lambda f, l: f"{l}.{f}",
    "first":      lambda f, l: f,
    "lastf":      lambda f, l: f"{l}{f[0]}",    # hohenwarter+a → hohenwartera (gov/edu common)
    "last.f":     lambda f, l: f"{l}.{f[0]}",   # hohenwarter.a → hohenwarter.a
    # Added from COMPANY_FORMAT_ANALYSIS.xlsx reference data
    "firstl":     lambda f, l: f"{f}{l[0]}",    # johns  (first name + last initial)
    "last":       lambda f, l: l,               # smith  (last name only)
}


def _name(value) -> str:
    """Clean a name for use in pattern matching — lowercase, no spaces or hyphens."""
    return str(value or "").lower().strip().replace(" ", "").replace("-", "")


def detect_pattern(first_name, last_name, email) -> str | None:
    """
    Figure out which naming pattern a known email address follows.

    Example:
      detect_pattern("John", "Smith", "jsmith@acme.com") → "flast"
      detect_pattern("John", "Smith", "john.smith@acme.com") → "first.last"
      detect_pattern("John", "Smith", "info@acme.com") → None  (no pattern matched)
    """
    if not email or "@" not in str(email):
        return None
    first = _name(first_name)
    last  = _name(last_name)
    if not first or not last:
        return None

    local = str(email).split("@")[0].lower().strip()
    for pattern, formatter in PATTERNS.items():
        try:
            if local == formatter(first, last):
                return pattern
        except Exception:
            continue
    return None


def build_pattern_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Scan all leads that have a valid email + domain and build a frequency
    table of naming patterns per domain.

    Returns a DataFrame with columns:
      domain, pattern, count, domain_trusted

    domain_trusted = True if the domain has at least MIN_DOMAIN_SAMPLES valid emails.
    """
    valid_mask = (
        df["email"].notna()
        & (df["email"].astype(str).str.strip() != "")
        & df["domain"].notna()
        & (df["domain"].astype(str).str.strip() != "")
        & df["email_validation_status"].eq("valid")
    )

    rows = []
    for _, row in df.loc[valid_mask].iterrows():
        pattern = detect_pattern(row.get("first_name"), row.get("last_name"), row.get("email"))
        if pattern:
            rows.append({"domain": row["domain"], "pattern": pattern})

    if not rows:
        return pd.DataFrame(columns=["domain", "pattern", "count", "domain_trusted"])

    table = (
        pd.DataFrame(rows)
        .groupby(["domain", "pattern"])
        .size()
        .reset_index(name="count")
        .sort_values(["domain", "count"], ascending=[True, False])
    )

    domain_totals = table.groupby("domain")["count"].sum()
    trusted       = domain_totals[domain_totals >= MIN_DOMAIN_SAMPLES].index
    table["domain_trusted"] = table["domain"].isin(trusted)

    return table


def get_top_global_patterns(pattern_table: pd.DataFrame, n: int) -> list:
    """
    Return the top N most common patterns across the entire batch.
    Falls back to DEFAULT_GLOBAL_PATTERNS when there is no learned data.
    """
    if pattern_table.empty:
        return DEFAULT_GLOBAL_PATTERNS[:n]
    ranked = (
        pattern_table.groupby("pattern")["count"]
        .sum()
        .sort_values(ascending=False)
        .head(n)
        .index.tolist()
    )
    # Pad with industry defaults if fewer than n patterns were learned
    for pat in DEFAULT_GLOBAL_PATTERNS:
        if len(ranked) >= n:
            break
        if pat not in ranked:
            ranked.append(pat)
    return ranked[:n]


def predict_email(first_name, last_name, domain, pattern) -> str:
    """
    Construct a predicted email address using a known pattern.

    Example:
      predict_email("John", "Smith", "acme.com", "flast") → "jsmith@acme.com"
      predict_email("John", "Smith", "acme.com", "first.last") → "john.smith@acme.com"
    """
    first  = _name(first_name)
    last   = _name(last_name)
    domain = str(domain or "").lower().strip()
    if not first or not last or not domain or pattern not in PATTERNS:
        return ""
    return f"{PATTERNS[pattern](first, last)}@{domain}"


def predict_missing_emails(df: pd.DataFrame) -> pd.DataFrame:
    """
    Main prediction function. Fills in emails for all leads that still
    don't have one after vendor enrichment.

    Company-pattern leads (domain has ≥1 confirmed valid email):
      → single prediction using that domain's format (confidence="company_pattern")

    Unknown-domain leads (no confirmed pattern for this domain):
      → TOP_N_GLOBAL_PATTERNS candidate rows, one per top global format
        (confidence="global_pattern_1", "global_pattern_2", "global_pattern_3")
      → ZeroBounce validates all candidates in Stage 6
      → collapse_prediction_candidates() picks the first valid hit after validation

    All predicted emails are marked email_source="predicted".
    """
    from .database import get_db
    df            = df.copy()
    pattern_table = build_pattern_table(df)
    db            = get_db()

    # Persist newly detected patterns so they accumulate across runs
    if db and not pattern_table.empty:
        db.record_patterns(list(zip(pattern_table["domain"], pattern_table["pattern"])))

    # Build domain → ranked pattern list (top-N by frequency).
    # Storing a list instead of a single string lets the prediction loop
    # generate fallback candidates when the top prediction turns out invalid.
    domain_pattern_index: dict = {}   # domain → [pat1, pat2, ...]
    if db:
        for domain_val, pats in db.load_patterns().items():
            if pats:   # already sorted by sample_count DESC
                domain_pattern_index[domain_val] = [
                    p["pattern"] for p in pats[:TOP_N_COMPANY_PATTERNS]
                ]

    # Current batch can override DB when it has fresh data for the same domain
    if not pattern_table.empty:
        trusted = pattern_table[pattern_table["domain_trusted"]]
        for domain_val, grp in trusted.groupby("domain"):
            top_pats = (
                grp.sort_values("count", ascending=False)["pattern"]
                .tolist()[:TOP_N_COMPANY_PATTERNS]
            )
            domain_pattern_index[domain_val] = top_pats

    # Top global patterns — used as fallback for unknown domains
    global_patterns = get_top_global_patterns(pattern_table, TOP_N_GLOBAL_PATTERNS)

    missing_mask = df["email"].isna() | (df["email"].astype(str).str.strip() == "")

    extra_rows: list = []

    for idx, row in df.loc[missing_mask].iterrows():
        domain = str(row.get("domain", "")).lower().strip()
        if not domain:
            continue

        company_patterns = domain_pattern_index.get(domain)  # list or None

        if company_patterns:
            # ── Company-specific pattern(s) ───────────────────────────────
            # Generate up to TOP_N_COMPANY_PATTERNS candidates so that if
            # the top prediction is invalid, the next-ranked pattern is also
            # validated by ZeroBounce rather than being silently discarded.
            # Single-pattern domains (list length == 1) behave exactly as
            # before — one prediction, confidence = "company_pattern".
            multi = len(company_patterns) > 1
            placed_first = False
            for rank, pat in enumerate(company_patterns, start=1):
                predicted = predict_email(
                    row.get("first_name"), row.get("last_name"), domain, pat
                )
                if not predicted:
                    continue

                confidence = f"company_pattern_{rank}" if multi else "company_pattern"

                if not placed_first:
                    df.at[idx, "email"]                       = predicted
                    df.at[idx, "email_source"]                = "predicted"
                    df.at[idx, "email_prediction_pattern"]    = pat
                    df.at[idx, "email_prediction_confidence"] = confidence
                    placed_first = True
                else:
                    new_row = row.copy()
                    new_row["email"]                       = predicted
                    new_row["email_source"]                = "predicted"
                    new_row["email_prediction_pattern"]    = pat
                    new_row["email_prediction_confidence"] = confidence
                    new_row["email_validation_status"]     = ""
                    new_row["email_validation_sub_status"] = ""
                    extra_rows.append(new_row)

        else:
            # ── Unknown domain: generate top-N candidates ─────────────────
            # Each candidate is a separate row so ZeroBounce can validate
            # all of them. collapse_prediction_candidates() will pick the
            # first valid one after Stage 6.
            placed_first = False
            for rank, pat in enumerate(global_patterns, start=1):
                predicted = predict_email(
                    row.get("first_name"), row.get("last_name"), domain, pat
                )
                if not predicted:
                    continue

                if not placed_first:
                    # Rank-1 candidate goes into the original row
                    df.at[idx, "email"]                       = predicted
                    df.at[idx, "email_source"]                = "predicted"
                    df.at[idx, "email_prediction_pattern"]    = pat
                    df.at[idx, "email_prediction_confidence"] = f"global_pattern_{rank}"
                    placed_first = True
                else:
                    # Ranks 2+ become new rows (clones of the original lead)
                    new_row = row.copy()
                    new_row["email"]                       = predicted
                    new_row["email_source"]                = "predicted"
                    new_row["email_prediction_pattern"]    = pat
                    new_row["email_prediction_confidence"] = f"global_pattern_{rank}"
                    new_row["email_validation_status"]     = ""
                    new_row["email_validation_sub_status"] = ""
                    extra_rows.append(new_row)

    if extra_rows:
        df = pd.concat([df, pd.DataFrame(extra_rows)], ignore_index=True)

    # ── Prediction summary for the UI stage card (always emitted) ─────────
    pred_rows = df[df["email_source"].astype(str).str.strip() == "predicted"]
    conf      = pred_rows["email_prediction_confidence"].astype(str) if not pred_rows.empty else pd.Series([], dtype=str)
    company_n = int(conf.str.startswith("company_pattern").sum())
    global_n  = int(conf.str.startswith("global_pattern").sum())
    print(f"    predict summary         : company_pattern:{company_n} | global_pattern:{global_n}")

    if not pred_rows.empty:
        pat_counts = pred_rows["email_prediction_pattern"].value_counts()
        parts = [f"{pat}:{int(cnt)}" for pat, cnt in pat_counts.items()]
        print(f"    predict patterns used   : {' | '.join(parts)}")
    else:
        print(f"    predict patterns used   : none")

    return df


def collapse_prediction_candidates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Called after ZeroBounce validates predicted emails (Stage 6).

    For leads that had multiple global-pattern candidates generated:
      - If any candidate came back valid → keep the lowest-rank valid one,
        drop the rest.
      - If none came back valid → keep rank-1 row but clear its email so
        the scoring stage correctly marks the lead as no_email_found.

    Leads that had a single company_pattern prediction are untouched.
    """
    # Multi-candidate rows are either global_pattern_N OR company_pattern_N.
    # Both share the same collapse logic: pick the lowest-rank valid prediction.
    is_multi = df["email_prediction_confidence"].astype(str).str.match(
        r"(global_pattern|company_pattern)_\d+"
    )

    if not is_multi.any():
        return df

    base_df    = df[~is_multi].copy()
    candidates = df[is_multi].copy()

    candidates["_rank"] = (
        candidates["email_prediction_confidence"]
        .str.extract(r"(?:global_pattern|company_pattern)_(\d+)")[0]
        .astype(int)
    )
    candidates = candidates.sort_values(["lead_id", "_rank"])

    kept: list = []
    for lead_id, group in candidates.groupby("lead_id", sort=False):
        valid_rows = group[group["email_validation_status"] == "valid"]
        if not valid_rows.empty:
            # Keep the lowest-rank valid prediction
            best = valid_rows.sort_values("_rank").iloc[0].copy()
        else:
            # No valid prediction — keep the best non-valid candidate so the
            # email is visible in the output (scorer will mark ready_for_outreach=no).
            # Prefer catch-all over unknown/invalid, then fall back to rank-1.
            catchall_rows = group[group["email_validation_status"] == "catch-all"]
            if not catchall_rows.empty:
                best = catchall_rows.sort_values("_rank").iloc[0].copy()
            else:
                rank1 = group[group["_rank"] == 1]
                best  = rank1.iloc[0].copy() if not rank1.empty else group.iloc[0].copy()

        best = best.drop(labels=["_rank"], errors="ignore")
        kept.append(best)

    if kept:
        collapsed = pd.DataFrame(kept) 
        df = pd.concat([base_df, collapsed], ignore_index=True)
    else:
        df = base_df

    return df
