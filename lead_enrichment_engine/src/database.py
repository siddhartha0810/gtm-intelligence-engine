"""
database.py  (lead_enrichment_engine)
=======================================
PostgreSQL-backed persistent knowledge store for the lead enrichment pipeline.

PURPOSE:
  Caches expensive API results (Apollo, ZeroBounce) and stores learned domain
  knowledge between runs so the same company domain is never resolved twice and
  the same email is never validated twice.

HOW IT FITS IN THE SYSTEM:
  Called by pipeline.py via init_db() at startup.
  Consumed by orchestrator.py (enrichment_cache read/write) and
  domain_resolver.py (domain_knowledge read/write).

  IMPORTANT: This module does NOT own the DDL for these tables.
  The DDL lives in oracle_intent_engine/src/database.py._DDL which runs
  at startup when unified_app.py calls oracle_db.init_db().  Both engines
  share the same Inoapps-Data-DB PostgreSQL database.

KEY TABLES:
  domain_knowledge  — company_name → email_domain.  Persists across ALL runs.
                      Never expires: a correct domain stays correct indefinitely.
  email_patterns    — domain → [{pattern, count}].  Learned from contacts_master
                      (COMPANY_FORMAT_ANALYSIS.xlsx source) — tells the pattern
                      engine what naming convention a company uses (flast, first.last).
  enrichment_cache  — stores Apollo + ZeroBounce results with TTL:
                      Apollo: 30 days (APOLLO_TTL_DAYS)
                      ZeroBounce: 7 days (ZB_TTL_DAYS)
                      Checked by orchestrator.py before ANY external API call.

KEY CLASSES/FUNCTIONS:
  PipelineDB                  — main class, thread-safe via ThreadedConnectionPool
  PipelineDB.get_domain()     — returns cached domain for a company name
  PipelineDB.save_domain()    — stores a resolved domain
  PipelineDB.get_cached_enrichment() — returns cached Apollo/ZB result if not expired
  PipelineDB.save_enrichment()       — stores a vendor result with timestamp
  PipelineDB.get_email_patterns()    — returns known naming patterns for a domain
  init_db()                   — creates the singleton PipelineDB; accepts a path
                                 arg for backwards-compat but ignores it (was SQLite)
  get_db()                    — returns the active singleton

MIGRATION NOTE:
  This module was previously SQLite-backed (pipeline.db).
  The init_db(path) parameter is kept for backwards compatibility but is ignored.
  The API surface is identical so all callers work unchanged.
"""

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
import psycopg2.pool

# ── Cache TTLs (unchanged from SQLite version) ──────────────────────────────
APOLLO_TTL_DAYS = 30
ZB_TTL_DAYS     = 7

# ── Connection string — read from environment (set by unified_app.py) ────────
_ORACLE_INTENT_DSN = os.environ.get(
    "ORACLE_PG_DSN",
    "host=10.0.0.149 port=5432 dbname=Inoapps-Data-DB user=postgres password=",
)

# ── Module-level singleton ───────────────────────────────────────────────────
_db:   Optional["PipelineDB"] = None
_lock: threading.Lock          = threading.Lock()


def init_db(path: Optional[str] = None) -> "PipelineDB":
    """
    Connect to the Inoapps-Data-DB PostgreSQL database.
    The `path` argument is accepted for backwards-compatibility but ignored.
    Call once from pipeline.py before stages begin.
    """
    global _db
    with _lock:
        _db = PipelineDB()
    return _db


def get_db() -> Optional["PipelineDB"]:
    """Return the active DB instance, or None if init_db() hasn't been called."""
    return _db


def _now(offset_days: int = 0) -> datetime:
    dt = datetime.now(timezone.utc)
    if offset_days:
        dt += timedelta(days=offset_days)
    return dt


# ── Database class ───────────────────────────────────────────────────────────

class PipelineDB:
    """
    Thread-safe PostgreSQL knowledge store for the lead enrichment pipeline.
    Drop-in replacement for the previous SQLite PipelineDB.
    """

    def __init__(self, dsn: str = _ORACLE_INTENT_DSN):
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=5, dsn=dsn,
            connect_timeout=30,
        )

    @contextmanager
    def _conn(self):
        conn = self._pool.getconn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    # ── Domain knowledge ───────────────────────────────────────────────────

    def load_domains(self) -> Dict[str, Dict]:
        """Return all domain records keyed by company_normalized."""
        with self._conn() as cur:
            cur.execute("SELECT * FROM domain_knowledge")
            return {r["company_normalized"]: dict(r) for r in cur.fetchall()}

    def upsert_domain(
        self,
        company:            str,
        company_normalized: str,
        domain:             str,
        source:             str  = "auto",
        confidence:         str  = "medium",
        mx_validated:       bool = False,
    ) -> None:
        now = _now()
        with self._conn() as cur:
            cur.execute(
                """
                INSERT INTO domain_knowledge
                    (company_normalized, company, domain, source, confidence,
                     mx_validated, last_validated_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (company_normalized) DO UPDATE SET
                    domain            = CASE
                        WHEN EXCLUDED.confidence = 'high'
                          OR domain_knowledge.confidence != 'high'
                        THEN EXCLUDED.domain
                        ELSE domain_knowledge.domain
                    END,
                    source            = EXCLUDED.source,
                    confidence        = CASE
                        WHEN EXCLUDED.confidence = 'high' THEN 'high'
                        ELSE domain_knowledge.confidence
                    END,
                    mx_validated      = EXCLUDED.mx_validated,
                    last_validated_at = EXCLUDED.last_validated_at,
                    updated_at        = EXCLUDED.updated_at
                """,
                (
                    company_normalized, company, domain, source, confidence,
                    mx_validated, now, now, now,
                ),
            )

    def remove_domains(self, company_norms: List[str]) -> int:
        if not company_norms:
            return 0
        with self._conn() as cur:
            cur.execute(
                "DELETE FROM domain_knowledge WHERE company_normalized = ANY(%s)",
                (company_norms,),
            )
            return cur.rowcount

    def import_csv(self, csv_path: str) -> int:
        import pandas as pd
        from .utils import normalize_company
        from pathlib import Path
        if not Path(csv_path).exists():
            return 0
        existing = self.load_domains()
        df = pd.read_csv(csv_path)
        imported = 0
        for _, row in df.iterrows():
            company    = str(row.get("company", "")).strip()
            domain     = str(row.get("domain",  "")).strip().lower()
            confidence = str(row.get("confidence", "medium")).lower().strip()
            source     = str(row.get("source",     "csv")).strip()
            if not company or not domain:
                continue
            norm = normalize_company(company)
            if confidence != "high" and norm in existing:
                continue
            self.upsert_domain(
                company=company, company_normalized=norm, domain=domain,
                source=source, confidence=confidence,
            )
            imported += 1
        return imported

    def export_csv(self, csv_path: str) -> None:
        import pandas as pd
        rows = [
            {"company": r["company"], "domain": r["domain"],
             "source": r["source"], "confidence": r["confidence"]}
            for r in sorted(
                self.load_domains().values(),
                key=lambda x: x["confidence"] + x["company"],
            )
        ]
        if rows:
            pd.DataFrame(rows).to_csv(csv_path, index=False)

    # ── Email patterns ─────────────────────────────────────────────────────

    def load_patterns(self) -> Dict[str, List[Dict]]:
        with self._conn() as cur:
            cur.execute(
                "SELECT * FROM email_patterns ORDER BY domain, sample_count DESC"
            )
            result: Dict[str, List] = {}
            for r in cur.fetchall():
                result.setdefault(r["domain"], []).append(dict(r))
        return result

    def record_patterns(self, pairs: List[Tuple[str, str]]) -> None:
        if not pairs:
            return
        now = _now()
        with self._conn() as cur:
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO email_patterns (domain, pattern, sample_count, last_seen_at)
                VALUES (%s, %s, 1, %s)
                ON CONFLICT (domain, pattern) DO UPDATE SET
                    sample_count = email_patterns.sample_count + 1,
                    last_seen_at = EXCLUDED.last_seen_at
                """,
                [(d, p, now) for d, p in pairs],
            )

    # ── Enrichment cache ───────────────────────────────────────────────────

    def get_cached_leads(self, lead_ids: List[str]) -> Dict[str, Dict]:
        if not lead_ids:
            return {}
        now = _now()
        with self._conn() as cur:
            cur.execute(
                """
                SELECT * FROM enrichment_cache
                WHERE lead_id = ANY(%s)
                  AND (expires_at IS NULL OR expires_at > %s)
                """,
                (lead_ids, now),
            )
            return {r["lead_id"]: dict(r) for r in cur.fetchall()}

    def cache_leads(self, records: List[Dict], ttl_days: int = APOLLO_TTL_DAYS) -> None:
        if not records:
            return
        now     = _now()
        expires = _now(ttl_days)
        rows = []
        for r in records:
            rows.append({
                "lead_id":                  str(r.get("lead_id") or ""),
                "email":                    str(r.get("email") or ""),
                "email_source":             str(r.get("email_source") or ""),
                "email_validation_status":  str(r.get("email_validation_status") or ""),
                "email_validation_sub_status": str(r.get("email_validation_sub_status") or ""),
                "linkedin_url":             str(r.get("linkedin_url") or ""),
                "job_title":                str(r.get("job_title") or ""),
                "cached_at":                now,
                "expires_at":               expires,
            })
        with self._conn() as cur:
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO enrichment_cache
                    (lead_id, email, email_source, email_validation_status,
                     email_validation_sub_status, linkedin_url, job_title,
                     cached_at, expires_at)
                VALUES (%(lead_id)s, %(email)s, %(email_source)s,
                        %(email_validation_status)s, %(email_validation_sub_status)s,
                        %(linkedin_url)s, %(job_title)s, %(cached_at)s, %(expires_at)s)
                ON CONFLICT (lead_id) DO UPDATE SET
                    email                       = EXCLUDED.email,
                    email_source                = EXCLUDED.email_source,
                    email_validation_status     = EXCLUDED.email_validation_status,
                    email_validation_sub_status = EXCLUDED.email_validation_sub_status,
                    linkedin_url                = EXCLUDED.linkedin_url,
                    job_title                   = EXCLUDED.job_title,
                    cached_at                   = EXCLUDED.cached_at,
                    expires_at                  = EXCLUDED.expires_at
                """,
                rows,
            )

    def purge_expired(self) -> int:
        with self._conn() as cur:
            cur.execute(
                "DELETE FROM enrichment_cache WHERE expires_at < %s", (_now(),)
            )
            return cur.rowcount

    def evict_leads(self, lead_ids: List[str]) -> None:
        if not lead_ids:
            return
        with self._conn() as cur:
            cur.execute(
                "DELETE FROM enrichment_cache WHERE lead_id = ANY(%s)",
                (lead_ids,),
            )

    # ── Stats ──────────────────────────────────────────────────────────────

    def stats(self) -> Dict:
        with self._conn() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM domain_knowledge")
            domains = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM email_patterns")
            patterns = cur.fetchone()["n"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM enrichment_cache WHERE expires_at > %s",
                (_now(),),
            )
            cached = cur.fetchone()["n"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM contacts_master"
                " WHERE UPPER(TRIM(zb_valid_email)) = 'YES'"
            )
            master = cur.fetchone()["n"]
        return {"domains": domains, "patterns": patterns,
                "cached_leads": cached, "master_leads": master}

    # ── master_leads delegated helpers (used by domain_resolver fallback) ──
    # These mirror the SQLite PipelineDB API so domain_resolver.py works
    # when pg_master is unavailable.

    def get_master_domains_for_companies(self, company_norms: List[str]) -> Dict[str, str]:
        if not company_norms:
            return {}
        with self._conn() as cur:
            cur.execute(
                """
                SELECT
                    LOWER(REGEXP_REPLACE(
                        COALESCE(NULLIF(new_company,''), NULLIF(existing_company,'')),
                        '\\s+(llc|inc|ltd|corp|limited|plc|llp|gmbh|sa|ag|nv|bv|co)\\.?$',
                        '', 'i'
                    ))                               AS company_normalized,
                    domain,
                    COUNT(*)                         AS cnt,
                    SUM(CASE WHEN validated_email_status = 'valid' THEN 1 ELSE 0 END) AS valid_cnt
                FROM contacts_master
                WHERE LOWER(REGEXP_REPLACE(
                          COALESCE(NULLIF(new_company,''), NULLIF(existing_company,'')),
                          '\\s+(llc|inc|ltd|corp|limited|plc|llp|gmbh|sa|ag|nv|bv|co)\\.?$',
                          '', 'i'
                      )) = ANY(%s)
                  AND domain IS NOT NULL AND domain != ''
                  AND UPPER(TRIM(zb_valid_email)) = 'YES'
                GROUP BY company_normalized, domain
                ORDER BY company_normalized, valid_cnt DESC, cnt DESC
                """,
                (company_norms,),
            )
            result: Dict[str, str] = {}
            for r in cur.fetchall():
                key = r["company_normalized"]
                if key not in result:
                    result[key] = r["domain"]
        return result

    def get_validation_by_email(self, emails: List[str]) -> Dict[str, Dict]:
        if not emails:
            return {}
        clean = [e.lower().strip() for e in emails if e]
        if not clean:
            return {}
        with self._conn() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(NULLIF(validated_email,''), NULLIF(email,''))  AS email,
                    validated_email_status                                   AS email_validation_status,
                    ''                                                       AS email_validation_sub_status
                FROM contacts_master
                WHERE LOWER(COALESCE(NULLIF(validated_email,''), NULLIF(email,''))) = ANY(%s)
                  AND UPPER(TRIM(zb_valid_email)) = 'YES'
                  AND validated_email_status IN
                      ('valid','invalid','catch-all','spamtrap','abuse','do_not_mail')
                """,
                (clean,),
            )
            return {r["email"].lower(): dict(r) for r in cur.fetchall() if r.get("email")}

    def find_contacts_by_name_company(self, leads: List[Dict]) -> Dict[str, Dict]:
        if not leads:
            return {}
        result: Dict[str, Dict] = {}
        with self._conn() as cur:
            for lead in leads:
                fn = str(lead.get("first_name") or "").lower().strip()
                ln = str(lead.get("last_name")  or "").lower().strip()
                cn = str(lead.get("company_normalized") or "").lower().strip()
                if not fn or not ln or not cn:
                    continue
                key = f"{fn}|{ln}|{cn}"
                if key in result:
                    continue
                cur.execute(
                    """
                    SELECT
                        id::TEXT                                                               AS lead_id,
                        firstname                                                              AS first_name,
                        lastname                                                               AS last_name,
                        title                                                                  AS job_title,
                        COALESCE(NULLIF(validated_email,''), NULLIF(email,''))                 AS email,
                        validated_email_status                                                 AS email_validation_status,
                        COALESCE(NULLIF(linkedin_url__c,''), NULLIF(linkedin_url_enriched,'')) AS linkedin_url,
                        domain,
                        COALESCE(NULLIF(new_company,''), NULLIF(existing_company,''))          AS company,
                        phone, mailingstreet AS street, mailingcity AS city,
                        mailingstate AS state, mailingcountry AS country,
                        mailingpostalcode AS postal_code
                    FROM contacts_master
                    WHERE LOWER(firstname) = %s
                      AND LOWER(lastname)  = %s
                      AND LOWER(REGEXP_REPLACE(
                              COALESCE(NULLIF(new_company,''), NULLIF(existing_company,'')),
                              '\\s+(llc|inc|ltd|corp|limited|plc|llp|gmbh|sa|ag|nv|bv|co)\\.?$',
                              '', 'i'
                          )) = %s
                      AND UPPER(TRIM(zb_valid_email)) = 'YES'
                      AND COALESCE(NULLIF(validated_email,''), NULLIF(email,'')) IS NOT NULL
                    ORDER BY
                        CASE validated_email_status
                            WHEN 'valid'     THEN 0
                            WHEN 'catch-all' THEN 1
                            ELSE 2 END
                    LIMIT 1
                    """,
                    (fn, ln, cn),
                )
                row = cur.fetchone()
                if row:
                    result[key] = dict(row)
        return result

    # ── contacts_master write (no-op — read-only Salesforce export) ──────────

    def upsert_master_leads(self, records: List[Dict]) -> int:
        """contacts_master is a read-only Salesforce export — writes are no-ops."""
        return 0

    def get_master_leads_by_ids(self, lead_ids: List[str]) -> Dict[str, Dict]:
        """Look up contacts by Salesforce ID. Only returns ZB-validated contacts."""
        if not lead_ids:
            return {}
        with self._conn() as cur:
            cur.execute(
                """
                SELECT
                    id::TEXT                                                               AS lead_id,
                    firstname                                                              AS first_name,
                    lastname                                                               AS last_name,
                    title                                                                  AS job_title,
                    COALESCE(NULLIF(validated_email,''), NULLIF(email,''))                 AS email,
                    validated_email_status                                                 AS email_validation_status,
                    COALESCE(NULLIF(linkedin_url__c,''), NULLIF(linkedin_url_enriched,'')) AS linkedin_url,
                    domain,
                    COALESCE(NULLIF(new_company,''), NULLIF(existing_company,''))          AS company,
                    phone, mailingstreet AS street, mailingcity AS city,
                    mailingstate AS state, mailingcountry AS country,
                    mailingpostalcode AS postal_code
                FROM contacts_master
                WHERE id::TEXT = ANY(%s)
                  AND UPPER(TRIM(zb_valid_email)) = 'YES'
                """,
                (lead_ids,),
            )
            return {r["lead_id"]: dict(r) for r in cur.fetchall()}

    def master_stats(self) -> Dict:
        """Row counts from contacts_master."""
        with self._conn() as cur:
            cur.execute("""
                SELECT
                    COUNT(*)                                                              AS total,
                    COUNT(COALESCE(NULLIF(validated_email,''), NULLIF(email,'')))         AS with_email,
                    COUNT(CASE WHEN UPPER(TRIM(zb_valid_email)) = 'YES' THEN 1 END)      AS valid,
                    COUNT(CASE WHEN UPPER(TRIM(zb_valid_email)) = 'YES'
                               AND (hasoptedoutemail IS NULL OR hasoptedoutemail = FALSE)
                               THEN 1 END)                                                AS ready
                FROM contacts_master
            """)
            return dict(cur.fetchone())
