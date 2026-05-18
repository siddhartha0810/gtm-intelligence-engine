"""
pg_master.py
============
PostgreSQL-backed permanent master store for the Lead Enrichment Engine.

Stores every enriched lead from every pipeline run, accumulating data
across runs.  Never expires.  Referenced by:
  - domain_resolver.py  — skip re-resolving domains for known companies
  - orchestrator.py     — skip Apollo/Apify for leads already enriched
  - pipeline.py         — persist results and surface cumulative stats
"""

import contextlib
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:
    import psycopg2
    import psycopg2.extras
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False


# ── Table definition ───────────────────────────────────────────────────────

_CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS master_leads (
        lead_id                      TEXT PRIMARY KEY,
        first_name                   TEXT DEFAULT '',
        last_name                    TEXT DEFAULT '',
        company                      TEXT DEFAULT '',
        company_normalized           TEXT DEFAULT '',
        domain                       TEXT DEFAULT '',
        email                        TEXT DEFAULT '',
        email_source                 TEXT DEFAULT '',
        email_validation_status      TEXT DEFAULT '',
        email_validation_sub_status  TEXT DEFAULT '',
        email_prediction_pattern     TEXT DEFAULT '',
        linkedin_url                 TEXT DEFAULT '',
        linkedin_source              TEXT DEFAULT '',
        job_title                    TEXT DEFAULT '',
        ready_for_outreach           TEXT DEFAULT '',
        failure_reason               TEXT DEFAULT '',
        run_count                    INTEGER DEFAULT 1,
        first_seen_at                TEXT DEFAULT CURRENT_TIMESTAMP,
        last_updated_at              TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ml_company ON master_leads (company_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_ml_domain  ON master_leads (domain)",
    "CREATE INDEX IF NOT EXISTS idx_ml_email   ON master_leads (email)",
]

_FIELDS = [
    "lead_id", "first_name", "last_name", "company", "company_normalized",
    "domain", "email", "email_source", "email_validation_status",
    "email_validation_sub_status", "email_prediction_pattern",
    "linkedin_url", "linkedin_source", "job_title",
    "ready_for_outreach", "failure_reason",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Module-level singleton ─────────────────────────────────────────────────

import os as _os

def _build_oracle_dsn() -> str:
    """Build DSN from environment variables — never hardcode credentials."""
    # ORACLE_PG_DSN takes priority (set by unified_app.py at startup)
    dsn = _os.environ.get("ORACLE_PG_DSN", "").strip()
    if dsn:
        return dsn
    host     = _os.environ.get("DB_HOST", "localhost")
    port     = _os.environ.get("DB_PORT", "5432")
    dbname   = _os.environ.get("DB_NAME", "oracle_intent")
    user     = _os.environ.get("DB_USER", "postgres")
    password = _os.environ.get("DB_PASSWORD", "")
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


_pg_master: Optional["PGMasterStore"] = None


def init_pg_master(connection_string: str = "") -> "PGMasterStore":
    """Initialise the master store. Uses ORACLE_PG_DSN env var if no DSN given."""
    global _pg_master
    dsn = connection_string.strip() or _build_oracle_dsn()
    _pg_master = PGMasterStore(dsn)
    return _pg_master


def get_pg_master() -> Optional["PGMasterStore"]:
    # Auto-initialise on first call so callers don't need explicit init
    global _pg_master
    if _pg_master is None:
        _pg_master = PGMasterStore(_build_oracle_dsn())
    return _pg_master


# ── Store class ────────────────────────────────────────────────────────────

class PGMasterStore:
    """PostgreSQL-backed permanent master store."""

    def __init__(self, connection_string: str):
        if not _HAS_PSYCOPG2:
            raise ImportError(
                "psycopg2-binary is required for the PostgreSQL master store.\n"
                "Install it with:  pip install psycopg2-binary"
            )
        self._dsn = connection_string
        self._init_table()

    @contextlib.contextmanager
    def _conn(self):
        conn = psycopg2.connect(self._dsn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_table(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                for stmt in _CREATE_STATEMENTS:
                    cur.execute(stmt)

    def upsert_master_leads(self, records: List[Dict]) -> int:
        if not records:
            return 0
        now = _now()
        rows = []
        for r in records:
            row = {f: str(r.get(f) or "").strip() for f in _FIELDS}
            # Never persist invalid emails — strip them so the upsert's
            # _keep_better logic preserves any previously-good value instead.
            if row.get("email_validation_status") == "invalid":
                row["email"]                       = ""
                row["email_source"]                = ""
                row["email_validation_status"]     = ""
                row["email_validation_sub_status"] = ""
            row["first_seen_at"]   = now
            row["last_updated_at"] = now
            rows.append(row)

        update_cols = [c for c in _FIELDS if c != "lead_id"]

        def _keep_better(col):
            return (
                f"{col} = CASE WHEN EXCLUDED.{col} != '' "
                f"THEN EXCLUDED.{col} ELSE master_leads.{col} END"
            )

        set_clause  = ",\n                    ".join(_keep_better(c) for c in update_cols)
        set_clause += ",\n                    run_count       = master_leads.run_count + 1"
        set_clause += ",\n                    last_updated_at = EXCLUDED.last_updated_at"

        all_fields   = _FIELDS + ["first_seen_at", "last_updated_at"]
        col_list     = ", ".join(all_fields)
        placeholders = ", ".join(f"%({f})s" for f in all_fields)

        sql = f"""
            INSERT INTO master_leads ({col_list})
            VALUES ({placeholders})
            ON CONFLICT (lead_id) DO UPDATE SET
                {set_clause}
        """

        with self._conn() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, sql, rows, page_size=200)
        return len(rows)

    def get_master_leads_by_ids(self, lead_ids: List[str]) -> Dict[str, Dict]:
        if not lead_ids:
            return {}
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM master_leads WHERE lead_id = ANY(%s) AND email != ''",
                    (lead_ids,),
                )
                rows = cur.fetchall()
        return {r["lead_id"]: dict(r) for r in rows}

    def get_master_domains_for_companies(self, company_norms: List[str]) -> Dict[str, str]:
        if not company_norms:
            return {}
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT company_normalized, domain, COUNT(*) AS cnt
                    FROM master_leads
                    WHERE company_normalized = ANY(%s) AND domain != ''
                    GROUP BY company_normalized, domain
                    ORDER BY company_normalized,
                             SUM(CASE WHEN email_validation_status = 'valid' THEN 1 ELSE 0 END) DESC,
                             COUNT(*) DESC
                    """,
                    (company_norms,),
                )
                rows = cur.fetchall()
        result: Dict[str, str] = {}
        for r in rows:
            if r["company_normalized"] not in result:
                result[r["company_normalized"]] = r["domain"]
        return result

    def get_contacts_by_company(self, company_names: List[str]) -> Dict[str, List[Dict]]:
        """
        Return validated contacts keyed by company_normalized for the given company names.

        Accepts raw company name strings, normalises them internally, then queries
        master_leads for rows that have a non-empty, valid email.  Only rows with
        email_validation_status = 'valid' (or any non-empty email when no status
        is set) are returned so callers get actionable contacts only.

        Returns: { company_normalized -> [contact_dict, ...] }
        """
        import re

        def _norm(v: str) -> str:
            v = v.lower()
            v = re.sub(
                r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|co|company|plc|private|pvt)\b",
                "", v,
            )
            v = re.sub(r"[^a-z0-9]+", " ", v)
            return re.sub(r"\s+", " ", v).strip()

        norms = [_norm(n) for n in company_names if n]
        if not norms:
            return {}

        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM   master_leads
                    WHERE  company_normalized = ANY(%s)
                      AND  email != ''
                      AND  (email_validation_status = 'valid' OR email_validation_status = '')
                    ORDER  BY company_normalized, ready_for_outreach DESC
                    """,
                    (norms,),
                )
                rows = cur.fetchall()

        result: Dict[str, List[Dict]] = {}
        for r in rows:
            key = r["company_normalized"]
            result.setdefault(key, []).append(dict(r))
        return result

    def get_validation_by_email(self, emails: List[str]) -> Dict[str, Dict]:
        """
        Return known validation status for the given email addresses from master_leads.
        Used by ZeroBounce pre-check to skip re-validating emails already in the DB.
        Only returns rows with a definitive, non-empty validation status.
        """
        if not emails:
            return {}
        clean = [e.lower().strip() for e in emails if e]
        if not clean:
            return {}
        _DEFINITIVE = ["valid", "invalid", "catch-all", "spamtrap", "abuse", "do_not_mail"]
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT email, email_validation_status, email_validation_sub_status
                       FROM master_leads
                       WHERE LOWER(email) = ANY(%s)
                         AND email_validation_status = ANY(%s)""",
                    (clean, _DEFINITIVE),
                )
                rows = cur.fetchall()
        return {r["email"].lower(): dict(r) for r in rows}

    def find_contacts_by_name_company(self, leads: List[Dict]) -> Dict[str, Dict]:
        """
        Look up leads in master_leads by (first_name, last_name, company_normalized).
        Fallback for leads that don't match by lead_id (e.g. sourced from a different pipeline).
        Only returns records that have a non-empty email.
        Returns dict keyed by "firstname|lastname|company_normalized".
        """
        if not leads:
            return {}
        result: Dict[str, Dict] = {}
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for lead in leads:
                    fn = str(lead.get("first_name") or "").lower().strip()
                    ln = str(lead.get("last_name") or "").lower().strip()
                    cn = str(lead.get("company_normalized") or "").lower().strip()
                    if not fn or not ln or not cn:
                        continue
                    key = f"{fn}|{ln}|{cn}"
                    if key in result:
                        continue
                    cur.execute(
                        """SELECT * FROM master_leads
                           WHERE LOWER(first_name) = %s AND LOWER(last_name) = %s
                             AND company_normalized = %s AND email != ''
                           ORDER BY
                               CASE email_validation_status
                                   WHEN 'valid'     THEN 0
                                   WHEN 'catch-all' THEN 1
                                   ELSE 2 END,
                               last_updated_at DESC
                           LIMIT 1""",
                        (fn, ln, cn),
                    )
                    row = cur.fetchone()
                    if row:
                        result[key] = dict(row)
        return result

    def master_stats(self) -> Dict:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM master_leads")
                total = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM master_leads WHERE email != ''")
                with_email = cur.fetchone()[0]
                cur.execute(
                    "SELECT COUNT(*) FROM master_leads WHERE email_validation_status = 'valid'"
                )
                valid = cur.fetchone()[0]
                cur.execute(
                    "SELECT COUNT(*) FROM master_leads WHERE ready_for_outreach = 'yes'"
                )
                ready = cur.fetchone()[0]
        return {"total": total, "with_email": with_email, "valid": valid, "ready": ready}
