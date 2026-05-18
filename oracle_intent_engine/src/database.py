"""
database.py — PostgreSQL backend for Oracle Intent Engine.
Uses ThreadedConnectionPool (max 10) — never saturates the server.
ORACLE_PG_DSN env var takes priority over DB_* vars so unified_app.py
can cleanly separate the oracle DB from the enrichment DB.
"""

import os
import threading
from contextlib import contextmanager
from typing import Optional
from src.utils import get_logger

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = get_logger(__name__)

# ── Connection pool ──────────────────────────────────────────────────────────
_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_pool_lock = threading.Lock()


def _dsn() -> str:
    """Resolve DSN at call-time so env vars set after import are respected.
    ORACLE_PG_DSN takes priority; falls back to individual DB_* vars."""
    dsn = os.environ.get("ORACLE_PG_DSN", "").strip()
    if not dsn:
        from src.config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
        dsn = (
            f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} "
            f"user={DB_USER} password={DB_PASSWORD}"
        )
    return dsn


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None or _pool.closed:
            dsn = _dsn()
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,          # hard cap — prevents postgres saturation
                dsn=dsn,
                connect_timeout=30,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5,
            )
            host_part = dsn.split("dbname=")[-1].split()[0] if "dbname=" in dsn else dsn
            logger.info(f"PostgreSQL pool ready (max=10) — {host_part}")
    return _pool


def close_pool():
    """Call on application shutdown to release all connections."""
    global _pool
    with _pool_lock:
        if _pool and not _pool.closed:
            _pool.closeall()
            _pool = None


# ── DDL ─────────────────────────────────────────────────────────────────────
_DDL = [
    """
    CREATE TABLE IF NOT EXISTS companies (
        id                BIGSERIAL PRIMARY KEY,
        name              TEXT NOT NULL UNIQUE,
        domain            TEXT,
        industry          TEXT,
        size              TEXT,
        location          TEXT,
        website           TEXT,
        first_scan_run_id BIGINT,
        first_seen        TIMESTAMP DEFAULT NOW(),
        last_updated      TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oracle_signals (
        id             BIGSERIAL PRIMARY KEY,
        company_id     BIGINT REFERENCES companies(id) ON DELETE CASCADE,
        scan_run_id    BIGINT,
        oracle_product TEXT,
        phase          TEXT,
        source         TEXT,
        signal_type    TEXT,
        job_title      TEXT,
        evidence       TEXT,
        url            TEXT,
        confidence     REAL DEFAULT 0.5,
        detected_at    TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scan_runs (
        id               BIGSERIAL PRIMARY KEY,
        started_at       TIMESTAMP DEFAULT NOW(),
        completed_at     TIMESTAMP,
        status           TEXT DEFAULT 'running',
        total_signals    INTEGER DEFAULT 0,
        total_companies  INTEGER DEFAULT 0,
        search_queries   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS company_contacts (
        id                      BIGSERIAL PRIMARY KEY,
        company_id              BIGINT REFERENCES companies(id) ON DELETE CASCADE,
        full_name               TEXT,
        first_name              TEXT,
        last_name               TEXT,
        title                   TEXT,
        email                   TEXT,
        linkedin_url            TEXT,
        seniority               TEXT,
        confidence              REAL DEFAULT 0,
        is_target               INTEGER DEFAULT 0,
        source                  TEXT DEFAULT 'hunter.io',
        email_validation_status TEXT,
        fetched_at              TIMESTAMP DEFAULT NOW()
    )
    """,
    # Migrations: add columns to existing DBs that were created before these columns existed
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS email_validation_status TEXT",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS email_source TEXT DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS email_prediction_pattern TEXT DEFAULT ''",
    """
    CREATE TABLE IF NOT EXISTS master_leads (
        lead_id                     TEXT PRIMARY KEY,
        first_name                  TEXT NOT NULL DEFAULT '',
        last_name                   TEXT NOT NULL DEFAULT '',
        company                     TEXT NOT NULL DEFAULT '',
        company_normalized          TEXT NOT NULL DEFAULT '',
        domain                      TEXT NOT NULL DEFAULT '',
        email                       TEXT NOT NULL DEFAULT '',
        email_source                TEXT NOT NULL DEFAULT '',
        email_validation_status     TEXT NOT NULL DEFAULT '',
        email_validation_sub_status TEXT NOT NULL DEFAULT '',
        email_prediction_pattern    TEXT NOT NULL DEFAULT '',
        linkedin_url                TEXT NOT NULL DEFAULT '',
        linkedin_source             TEXT NOT NULL DEFAULT '',
        job_title                   TEXT NOT NULL DEFAULT '',
        phone                       TEXT NOT NULL DEFAULT '',
        mobile_phone                TEXT NOT NULL DEFAULT '',
        ready_for_outreach          TEXT NOT NULL DEFAULT '',
        failure_reason              TEXT NOT NULL DEFAULT '',
        run_count                   INTEGER NOT NULL DEFAULT 1,
        first_seen_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ml_company_norm ON master_leads(company_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_ml_domain       ON master_leads(domain)",
    "CREATE INDEX IF NOT EXISTS idx_ml_email        ON master_leads(email) WHERE email != ''",
    "CREATE INDEX IF NOT EXISTS idx_ml_outreach     ON master_leads(ready_for_outreach)",
    """
    CREATE TABLE IF NOT EXISTS domain_knowledge (
        company_normalized  TEXT PRIMARY KEY,
        company             TEXT NOT NULL,
        domain              TEXT NOT NULL,
        source              TEXT    NOT NULL DEFAULT 'auto',
        confidence          TEXT    NOT NULL DEFAULT 'medium',
        mx_validated        BOOLEAN NOT NULL DEFAULT FALSE,
        last_validated_at   TIMESTAMPTZ,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_dk_domain ON domain_knowledge(domain)",
    """
    CREATE TABLE IF NOT EXISTS email_patterns (
        domain        TEXT NOT NULL,
        pattern       TEXT NOT NULL,
        sample_count  INTEGER NOT NULL DEFAULT 1,
        last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (domain, pattern)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ep_domain ON email_patterns(domain)",
    """
    CREATE TABLE IF NOT EXISTS enrichment_cache (
        lead_id                     TEXT PRIMARY KEY,
        email                       TEXT NOT NULL DEFAULT '',
        email_source                TEXT NOT NULL DEFAULT '',
        email_validation_status     TEXT NOT NULL DEFAULT '',
        email_validation_sub_status TEXT NOT NULL DEFAULT '',
        linkedin_url                TEXT NOT NULL DEFAULT '',
        job_title                   TEXT NOT NULL DEFAULT '',
        cached_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at                  TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ec_expires ON enrichment_cache(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_signals_company  ON oracle_signals(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_signals_phase    ON oracle_signals(phase)",
    "CREATE INDEX IF NOT EXISTS idx_signals_product  ON oracle_signals(oracle_product)",
    "CREATE INDEX IF NOT EXISTS idx_contacts_company ON company_contacts(company_id)",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_company_email
        ON company_contacts(company_id, email)
        WHERE email IS NOT NULL AND email != ''
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_company_linkedin
        ON company_contacts(company_id, linkedin_url)
        WHERE linkedin_url IS NOT NULL AND linkedin_url != ''
    """,
]


# ── Core context manager ─────────────────────────────────────────────────────
@contextmanager
def db_cursor(commit: bool = True):
    """Check out a pooled connection, yield a RealDictCursor, then return it."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cur
        if commit:
            conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"DB error: {e}")
        raise
    finally:
        pool.putconn(conn)


# ── Schema init ──────────────────────────────────────────────────────────────
def init_db():
    with db_cursor() as cur:
        for stmt in _DDL:
            cur.execute(stmt)
    logger.info("PostgreSQL schema initialised")


# ── Company operations ───────────────────────────────────────────────────────
def upsert_company(name: str, domain: str = None, industry: str = None,
                   size: str = None, location: str = None, website: str = None,
                   first_scan_run_id: int = None) -> int:
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO companies (name, domain, industry, size, location, website, first_scan_run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                domain            = COALESCE(companies.domain,    EXCLUDED.domain),
                industry          = COALESCE(companies.industry,  EXCLUDED.industry),
                size              = COALESCE(companies.size,      EXCLUDED.size),
                location          = COALESCE(companies.location,  EXCLUDED.location),
                website           = COALESCE(companies.website,   EXCLUDED.website),
                last_updated      = NOW()
            RETURNING id
        """, (name, domain, industry, size, location, website, first_scan_run_id))
        return cur.fetchone()["id"]


def get_company_by_id(company_id: int) -> Optional[dict]:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM companies WHERE id = %s", (company_id,))
        return cur.fetchone()


def get_company_by_name(name: str) -> Optional[dict]:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM companies WHERE name = %s", (name,))
        return cur.fetchone()


def purge_invalid_companies(is_valid_fn) -> int:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT id, name FROM companies")
        all_companies = cur.fetchall()
    to_delete = [row["id"] for row in all_companies if not is_valid_fn(row["name"])]
    if not to_delete:
        return 0
    with db_cursor() as cur:
        cur.execute("DELETE FROM companies WHERE id = ANY(%s)", (to_delete,))
    logger.info(f"Purged {len(to_delete)} invalid company names")
    return len(to_delete)


def reset_all_data():
    with db_cursor() as cur:
        cur.execute("DELETE FROM company_contacts")
        cur.execute("DELETE FROM oracle_signals")
        cur.execute("DELETE FROM companies")
        cur.execute("DELETE FROM scan_runs")
        for seq in ("companies_id_seq", "oracle_signals_id_seq",
                    "scan_runs_id_seq", "company_contacts_id_seq"):
            cur.execute(f"ALTER SEQUENCE IF EXISTS {seq} RESTART WITH 1")
    logger.info("Oracle intent data reset")
    return {"companies": 0, "signals": 0}


# ── Signal operations ────────────────────────────────────────────────────────
def insert_signal(company_id: int, oracle_product: str, phase: str, source: str,
                  signal_type: str, job_title: str, evidence: str,
                  url: str, confidence: float, scan_run_id: int = None) -> int:
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO oracle_signals
                (company_id, scan_run_id, oracle_product, phase, source,
                 signal_type, job_title, evidence, url, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (company_id, scan_run_id, oracle_product, phase, source,
              signal_type, job_title, evidence, url, confidence))
        return cur.fetchone()["id"]


def get_signals_for_company(company_id: int):
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT * FROM oracle_signals
            WHERE company_id = %s
            ORDER BY detected_at DESC
        """, (company_id,))
        return cur.fetchall()


# ── Scan run tracking ────────────────────────────────────────────────────────
def start_scan_run(queries: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO scan_runs (search_queries) VALUES (%s) RETURNING id",
            (queries,),
        )
        return cur.fetchone()["id"]


def finish_scan_run(run_id: int, total_signals: int, total_companies: int,
                    status: str = "completed"):
    with db_cursor() as cur:
        cur.execute("""
            UPDATE scan_runs
            SET completed_at = NOW(), status = %s,
                total_signals = %s, total_companies = %s
            WHERE id = %s
        """, (status, total_signals, total_companies, run_id))


def get_latest_completed_run_id() -> Optional[int]:
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT id FROM scan_runs
            WHERE status IN ('completed', 'stopped')
            ORDER BY id DESC LIMIT 1
        """)
        row = cur.fetchone()
        return row["id"] if row else None


def get_recent_scan_runs(limit: int = 10):
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT %s
        """, (limit,))
        return cur.fetchall()


# ── Contact operations ───────────────────────────────────────────────────────
def save_contacts(company_id: int, contacts: list):
    with db_cursor() as cur:
        for c in contacts:
            cur.execute("""
                INSERT INTO company_contacts
                    (company_id, full_name, first_name, last_name, title,
                     email, linkedin_url, seniority, confidence, is_target, source,
                     email_validation_status, email_source, email_prediction_pattern)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (
                company_id,
                c.get("full_name", ""),
                c.get("first_name", ""),
                c.get("last_name", ""),
                c.get("title", ""),
                c.get("email", "") or None,
                c.get("linkedin_url", "") or None,
                c.get("seniority", ""),
                float(c.get("confidence", 0)),
                int(bool(c.get("is_target", False))),
                c.get("source", "apollo"),
                c.get("email_validation_status") or None,
                c.get("email_source", "") or "",
                c.get("email_prediction_pattern", "") or "",
            ))


def get_companies_needing_enrichment(limit: int = 50) -> list:
    """Return companies that have signals but no contacts yet, highest signal count first."""
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT c.id, c.name, c.domain, COUNT(s.id) AS signal_count
            FROM companies c
            JOIN oracle_signals s ON s.company_id = c.id
            WHERE NOT EXISTS (
                SELECT 1 FROM company_contacts cc WHERE cc.company_id = c.id
            )
            GROUP BY c.id, c.name, c.domain
            ORDER BY signal_count DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def get_enrichment_stats() -> dict:
    """Return counts for the enrichment dashboard."""
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS total FROM companies")
        total_companies = cur.fetchone()["total"]
        cur.execute("""
            SELECT COUNT(DISTINCT company_id) AS enriched
            FROM company_contacts
        """)
        enriched = cur.fetchone()["enriched"]
        cur.execute("""
            SELECT COUNT(*) AS total,
                   COUNT(CASE WHEN email IS NOT NULL AND email != '' THEN 1 END) AS with_email,
                   COUNT(CASE WHEN email_validation_status = 'valid' THEN 1 END) AS valid_email
            FROM company_contacts
        """)
        row = cur.fetchone()
        return {
            "total_companies": total_companies,
            "enriched_companies": enriched,
            "pending_companies": max(0, total_companies - enriched),
            "total_contacts": row["total"],
            "contacts_with_email": row["with_email"],
            "contacts_valid_email": row["valid_email"],
        }


def get_contacts_for_company(company_id: int) -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT * FROM company_contacts
            WHERE company_id = %s
            ORDER BY is_target DESC, confidence DESC
        """, (company_id,))
        return cur.fetchall()


def get_contacts_for_company_names(names: list) -> list:
    if not names:
        return []
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT c.name AS company_name, c.domain AS company_domain,
                   cc.full_name, cc.first_name, cc.last_name,
                   cc.email, cc.linkedin_url, cc.source
            FROM company_contacts cc
            JOIN companies c ON c.id = cc.company_id
            WHERE c.name = ANY(%s)
            ORDER BY c.name, cc.full_name
        """, (names,))
        return cur.fetchall()


# ── Company + signals (read) ─────────────────────────────────────────────────
def get_all_companies_with_signals(run_id: int = None):
    if run_id is None:
        run_id = get_latest_completed_run_id()

    with db_cursor(commit=False) as cur:
        if run_id:
            cur.execute("""
                SELECT
                    c.id, c.name, c.domain, c.industry, c.size,
                    c.location, c.website, c.first_seen::text AS first_seen,
                    c.first_scan_run_id,
                    COUNT(s.id)                                  AS signal_count,
                    STRING_AGG(DISTINCT s.oracle_product, ',')   AS products,
                    STRING_AGG(DISTINCT s.phase, ',')            AS phases,
                    STRING_AGG(DISTINCT s.source, ',')           AS sources,
                    MAX(s.confidence)                            AS max_confidence,
                    (SELECT s2.url FROM oracle_signals s2
                     WHERE s2.company_id = c.id
                       AND s2.scan_run_id = %s
                       AND s2.url LIKE 'http%%'
                     ORDER BY s2.confidence DESC LIMIT 1)       AS source_url,
                    (SELECT COUNT(*) FROM company_contacts cc
                     WHERE cc.company_id = c.id
                       AND cc.email IS NOT NULL AND cc.email != '') AS contact_count
                FROM companies c
                JOIN oracle_signals s ON s.company_id = c.id
                WHERE c.first_scan_run_id = %s
                GROUP BY c.id
                ORDER BY signal_count DESC, c.last_updated DESC
            """, (run_id, run_id))
        elif run_id == 0:
            cur.execute("""
                SELECT
                    c.id, c.name, c.domain, c.industry, c.size,
                    c.location, c.website, c.first_seen::text AS first_seen,
                    c.first_scan_run_id,
                    COUNT(s.id)                                  AS signal_count,
                    STRING_AGG(DISTINCT s.oracle_product, ',')   AS products,
                    STRING_AGG(DISTINCT s.phase, ',')            AS phases,
                    STRING_AGG(DISTINCT s.source, ',')           AS sources,
                    MAX(s.confidence)                            AS max_confidence,
                    (SELECT s2.url FROM oracle_signals s2
                     WHERE s2.company_id = c.id AND s2.url LIKE 'http%%'
                     ORDER BY s2.confidence DESC LIMIT 1)       AS source_url,
                    (SELECT COUNT(*) FROM company_contacts cc
                     WHERE cc.company_id = c.id
                       AND cc.email IS NOT NULL AND cc.email != '') AS contact_count
                FROM companies c
                JOIN oracle_signals s ON s.company_id = c.id
                GROUP BY c.id
                ORDER BY signal_count DESC
            """)
        else:
            return []

        rows = cur.fetchall()

    for row in rows:
        row["products"] = [p for p in (row.get("products") or "").split(",") if p]
        row["phases"]   = [p for p in (row.get("phases")   or "").split(",") if p]
        row["sources"]  = [s for s in (row.get("sources")  or "").split(",") if s]

    return rows


def test_connection() -> bool:
    try:
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False


# ── master_leads operations ──────────────────────────────────────────────────

def _norm_company(name: str) -> str:
    """Lowercase + strip common legal suffixes for consistent company matching."""
    import re
    n = (name or "").lower().strip()
    for suf in (" inc", " inc.", " corp", " corp.", " ltd", " ltd.", " llc",
                " l.l.c", " group", " co.", " co", " gmbh", " s.a.", " plc",
                " ag", " nv", " bv", " lp", " llp", " limited", " limited."):
        if n.endswith(suf):
            n = n[: -len(suf)].strip()
    return re.sub(r"\s+", " ", n).strip()


def upsert_master_leads(records: list) -> int:
    """
    Upsert a batch of enriched contacts into master_leads.

    Non-destructive: existing non-empty values are never overwritten by empty ones.
    Designed to be called after Apollo enrichment + ZeroBounce validation.

    Each record dict must have 'lead_id'. All other fields are optional.
    Returns number of records processed.
    """
    if not records:
        return 0

    fields = [
        "lead_id", "first_name", "last_name", "company", "company_normalized",
        "domain", "email", "email_source", "email_validation_status",
        "email_validation_sub_status", "email_prediction_pattern",
        "linkedin_url", "linkedin_source", "job_title",
        "phone", "mobile_phone", "ready_for_outreach", "failure_reason",
    ]

    rows = []
    for r in records:
        row = {f: str(r.get(f) or "").strip() for f in fields}
        # Never persist invalid emails — blank them so a prior good email is preserved
        if row.get("email_validation_status") == "invalid":
            row["email"]                       = ""
            row["email_source"]                = ""
            row["email_validation_status"]     = ""
            row["email_validation_sub_status"] = ""
        if not row.get("company_normalized") and row.get("company"):
            row["company_normalized"] = _norm_company(row["company"])
        rows.append(row)

    col_list = ", ".join(fields)
    placeholders = ", ".join(f"%({f})s" for f in fields)
    # Non-destructive update: only replace with new value if new value is non-empty
    update_cols = [f for f in fields if f != "lead_id"]
    set_clause  = ",\n            ".join(
        f"{c} = CASE WHEN EXCLUDED.{c} <> '' THEN EXCLUDED.{c} ELSE master_leads.{c} END"
        for c in update_cols
    )

    with db_cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO master_leads ({col_list}, first_seen_at, last_updated_at)
            VALUES ({placeholders}, NOW(), NOW())
            ON CONFLICT (lead_id) DO UPDATE SET
                {set_clause},
                run_count       = master_leads.run_count + 1,
                last_updated_at = NOW()
            """,
            rows,
        )
    return len(rows)


def get_master_leads_by_email(emails: list) -> dict:
    """
    Look up master_leads by email address (case-insensitive).
    Returns {email_lower: record_dict}. Used by ZeroBounce pre-check.
    """
    if not emails:
        return {}
    clean = [e.lower().strip() for e in emails if e and e.strip()]
    if not clean:
        return {}
    with db_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT * FROM master_leads
            WHERE LOWER(email) = ANY(%s)
              AND email_validation_status IN ('valid','invalid','catch-all','spamtrap','abuse','do_not_mail')
            """,
            (clean,),
        )
        return {row["email"].lower(): dict(row) for row in cur.fetchall()}


def get_master_leads_by_company(company_normalized: str) -> list:
    """Return all master_leads for a given normalised company name."""
    with db_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT * FROM master_leads
            WHERE company_normalized = %s
            ORDER BY
                CASE email_validation_status
                    WHEN 'valid'     THEN 0
                    WHEN 'catch-all' THEN 1
                    ELSE 2 END,
                last_updated_at DESC
            """,
            (_norm_company(company_normalized),),
        )
        return cur.fetchall()


def master_leads_stats() -> dict:
    """Row counts for the master_leads table."""
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT
                COUNT(*)                                                     AS total,
                COUNT(CASE WHEN email != ''              THEN 1 END)         AS with_email,
                COUNT(CASE WHEN email_validation_status = 'valid' THEN 1 END) AS valid_email,
                COUNT(CASE WHEN ready_for_outreach = 'yes'        THEN 1 END) AS ready
            FROM master_leads
        """)
        row = cur.fetchone()
        return dict(row)
