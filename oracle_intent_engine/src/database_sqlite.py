"""
database_sqlite.py
==================
SQLite fallback backend — identical public API to database.py.
Auto-activated when PostgreSQL at 10.0.0.149 is not reachable.
Data stored at: DATA_TOOL/oracle_intent.db (local file, auto-created).

All functions have the same signatures and return shapes as the
PostgreSQL versions so unified_app.py works without any changes.
"""

import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from src.utils import get_logger

logger = get_logger(__name__)

# ── DB file path ─────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DB_PATH = os.path.join(_ROOT, "oracle_intent.db")

_conn_lock = threading.Lock()
_connection: Optional[sqlite3.Connection] = None


def _gen_unique_key() -> str:
    return secrets.token_urlsafe(48)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _translate_sql(sql: str) -> str:
    """Callers outside this module (auth.py, tech_profiles.py, hubspot_push.py,
    events.py, manufacturer.py, list_import.py, data_quality.py, audit.py, ...)
    write raw SQL against db.db_cursor() using Postgres syntax, since that's the
    primary backend. A handful of Postgres-only constructs have direct SQLite
    equivalents, so translate them here rather than touching every caller."""
    sql = sql.replace("%s", "?")
    sql = sql.replace("NOW()", "datetime('now')")
    sql = sql.replace("ILIKE", "LIKE")
    sql = sql.replace("::text", "").replace("::int", "").replace("::date", "")
    return sql


def _adapt_param(value):
    """Postgres callers pass Python lists straight through for TEXT[] columns
    (psycopg2 adapts them natively); sqlite3 can't bind a list at all, so
    JSON-encode it here. Read side is unaffected — callers that need the list
    back (e.g. tech_profiles.py) get a JSON string on this backend, same as
    the campaigns table's TEXT-backed array fields."""
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value


# ── Connection ────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    global _connection
    with _conn_lock:
        if _connection is None:
            _connection = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=30)
            _connection.row_factory = sqlite3.Row
            _connection.execute("PRAGMA journal_mode=WAL")
            _connection.execute("PRAGMA foreign_keys=ON")
            # Postgres compatibility shims — SQL written for the primary
            # backend calls these (data_quality.py uses REGEXP_REPLACE);
            # without them, fallback mode 500s on those queries.
            import re as _re

            def _regexp_replace(source, pattern, replacement, flags=""):
                if source is None:
                    return None
                py_flags = _re.IGNORECASE if "i" in (flags or "") else 0
                count = 0 if "g" in (flags or "") else 1
                return _re.sub(pattern, replacement, str(source), count=count, flags=py_flags)

            _connection.create_function("REGEXP_REPLACE", 3, _regexp_replace)
            _connection.create_function("REGEXP_REPLACE", 4, _regexp_replace)
            logger.info("SQLite backend ready at %s", _DB_PATH)
    return _connection


# ── Dict-cursor wrapper (matches psycopg2 DictCursor interface) ───────────────

class _Cur:
    """Thin wrapper: row['col'] and .get() work just like psycopg2 DictCursor."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._cur = conn.cursor()

    def execute(self, sql: str, params=()):
        sql = _translate_sql(sql)
        self._cur.execute(sql, [_adapt_param(p) for p in params])

    def executemany(self, sql: str, seq):
        sql = _translate_sql(sql)
        self._cur.executemany(sql, [[_adapt_param(p) for p in row] for row in seq])

    def fetchone(self) -> Optional[dict]:
        row = self._cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self) -> list:
        return [dict(r) for r in self._cur.fetchall()]

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount


@contextmanager
def db_cursor(commit: bool = True):
    conn = _get_conn()
    cur = _Cur(conn)
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise


# ── DDL ───────────────────────────────────────────────────────────────────────

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS companies (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        name              TEXT NOT NULL UNIQUE,
        domain            TEXT,
        industry          TEXT,
        size              TEXT,
        location          TEXT,
        website           TEXT,
        first_scan_run_id INTEGER,
        first_seen        TEXT DEFAULT (datetime('now')),
        last_updated      TEXT DEFAULT (datetime('now')),
        technology_profile_id INTEGER,
        status            TEXT NOT NULL DEFAULT 'staged',
        unique_key        TEXT NOT NULL DEFAULT '',
        hubspot_id        TEXT NOT NULL DEFAULT '',
        hubspot_synced_at TEXT,
        source            TEXT NOT NULL DEFAULT 'scan',
        company_type      TEXT NOT NULL DEFAULT 'prospect',
        phone             TEXT NOT NULL DEFAULT '',
        number_of_employees INTEGER,
        about_us          TEXT NOT NULL DEFAULT '',
        billing_city      TEXT NOT NULL DEFAULT '',
        billing_state     TEXT NOT NULL DEFAULT '',
        billing_country   TEXT NOT NULL DEFAULT '',
        duns_number       TEXT NOT NULL DEFAULT '',
        oracle_solutions_summary TEXT NOT NULL DEFAULT '',
        oracle_cloud_solutions   TEXT NOT NULL DEFAULT '',
        oracle_on_premise_solutions TEXT NOT NULL DEFAULT '',
        oracle_relationship_type TEXT NOT NULL DEFAULT '',
        oracle_version           TEXT NOT NULL DEFAULT '',
        number_of_oracle_users   INTEGER,
        target_product           TEXT NOT NULL DEFAULT '',
        detected_products        TEXT NOT NULL DEFAULT '',
        product_confidence_scores TEXT NOT NULL DEFAULT '{}',
        enrichment_data          TEXT NOT NULL DEFAULT '{}',
        signal_count             INTEGER NOT NULL DEFAULT 0,
        contact_count            INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oracle_signals (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id     INTEGER REFERENCES companies(id) ON DELETE CASCADE,
        scan_run_id    INTEGER,
        oracle_product TEXT,
        phase          TEXT,
        source         TEXT,
        signal_type    TEXT,
        job_title      TEXT,
        evidence       TEXT,
        url            TEXT,
        confidence     REAL DEFAULT 0.5,
        signal_tier    TEXT DEFAULT 'P2',
        detected_at    TEXT DEFAULT (datetime('now')),
        content_hash   TEXT UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scan_runs (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at            TEXT DEFAULT (datetime('now')),
        completed_at          TEXT,
        status                TEXT DEFAULT 'running',
        total_signals         INTEGER DEFAULT 0,
        total_companies       INTEGER DEFAULT 0,
        search_queries        TEXT,
        technology_profile_id INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS company_contacts (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id              INTEGER REFERENCES companies(id) ON DELETE CASCADE,
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
        fetched_at              TEXT DEFAULT (datetime('now')),
        email_source            TEXT DEFAULT '',
        email_prediction_pattern TEXT DEFAULT '',
        target_product          TEXT NOT NULL DEFAULT '',
        ready_for_outreach      INTEGER NOT NULL DEFAULT 0,
        phone                   TEXT NOT NULL DEFAULT '',
        mobile_phone            TEXT NOT NULL DEFAULT '',
        city                    TEXT NOT NULL DEFAULT '',
        state                   TEXT NOT NULL DEFAULT '',
        country                 TEXT NOT NULL DEFAULT '',
        do_not_call             INTEGER NOT NULL DEFAULT 0,
        do_not_email            INTEGER NOT NULL DEFAULT 0,
        person_has_moved        INTEGER NOT NULL DEFAULT 0,
        oracle_alignment        TEXT NOT NULL DEFAULT '',
        hubspot_id              TEXT NOT NULL DEFAULT '',
        unique_key              TEXT NOT NULL DEFAULT '',
        status                  TEXT NOT NULL DEFAULT 'staged',
        hubspot_synced_at       TEXT,
        domain                  TEXT NOT NULL DEFAULT '',
        industry                TEXT NOT NULL DEFAULT '',
        location                TEXT NOT NULL DEFAULT '',
        job_function            TEXT NOT NULL DEFAULT '',
        level                   TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        email         TEXT NOT NULL UNIQUE,
        name          TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL DEFAULT '',
        role          TEXT NOT NULL DEFAULT 'analyst',
        is_active     INTEGER NOT NULL DEFAULT 1,
        last_login    TEXT,
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER,
        user_email   TEXT NOT NULL DEFAULT '',
        action       TEXT NOT NULL,
        entity_type  TEXT NOT NULL,
        entity_id    TEXT NOT NULL DEFAULT '',
        old_value    TEXT,
        new_value    TEXT,
        ip_address   TEXT NOT NULL DEFAULT '',
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS technology_profiles (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        name                 TEXT NOT NULL UNIQUE,
        description          TEXT NOT NULL DEFAULT '',
        keywords             TEXT NOT NULL DEFAULT '',
        target_websites      TEXT NOT NULL DEFAULT '',
        competitor_domains   TEXT NOT NULL DEFAULT '',
        partner_domains      TEXT NOT NULL DEFAULT '',
        manufacturer_domain  TEXT NOT NULL DEFAULT '',
        oracle_products      TEXT NOT NULL DEFAULT '',
        is_active            INTEGER NOT NULL DEFAULT 1,
        created_at           TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hubspot_config (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        api_key          TEXT NOT NULL DEFAULT '',
        portal_id        TEXT NOT NULL DEFAULT '',
        sync_status      TEXT NOT NULL DEFAULT 'idle',
        last_sync_at     TEXT,
        companies_synced INTEGER NOT NULL DEFAULT 0,
        contacts_synced  INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS engine_configs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        engine_type TEXT NOT NULL UNIQUE,
        is_enabled  INTEGER NOT NULL DEFAULT 1,
        config_json TEXT NOT NULL DEFAULT '{}',
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS email_patterns (
        domain        TEXT NOT NULL,
        pattern       TEXT NOT NULL,
        sample_count  INTEGER NOT NULL DEFAULT 1,
        last_seen_at  TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (domain, pattern)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS company_email_formats (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name        TEXT NOT NULL,
        domain              TEXT NOT NULL,
        format_rank         INTEGER NOT NULL DEFAULT 1,
        format_code         TEXT NOT NULL,
        formula             TEXT NOT NULL DEFAULT '',
        description         TEXT NOT NULL DEFAULT '',
        domain_example      TEXT NOT NULL DEFAULT '',
        share_pct           REAL NOT NULL DEFAULT 0,
        format_count        INTEGER NOT NULL DEFAULT 0,
        sample_emails       TEXT NOT NULL DEFAULT '',
        contacts_280k       INTEGER NOT NULL DEFAULT 0,
        validated_emails    INTEGER NOT NULL DEFAULT 0,
        formats_found       INTEGER NOT NULL DEFAULT 1,
        is_predictable      INTEGER NOT NULL DEFAULT 1,
        recommended_action  TEXT NOT NULL DEFAULT '',
        UNIQUE (domain, format_rank)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS domain_knowledge (
        company_normalized  TEXT PRIMARY KEY,
        company             TEXT NOT NULL,
        domain              TEXT NOT NULL,
        source              TEXT NOT NULL DEFAULT 'auto',
        confidence          TEXT NOT NULL DEFAULT 'medium',
        mx_validated        INTEGER NOT NULL DEFAULT 0,
        last_validated_at   TEXT,
        created_at          TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        name                  TEXT NOT NULL,
        event_type            TEXT NOT NULL DEFAULT 'conference',
        technology_profile_id INTEGER,
        location              TEXT NOT NULL DEFAULT '',
        event_date            TEXT,
        description           TEXT NOT NULL DEFAULT '',
        attendee_count        INTEGER NOT NULL DEFAULT 0,
        created_at            TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS manufacturer_contacts (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name            TEXT NOT NULL DEFAULT '',
        last_name             TEXT NOT NULL DEFAULT '',
        email                 TEXT NOT NULL DEFAULT '',
        phone                 TEXT NOT NULL DEFAULT '',
        company               TEXT NOT NULL DEFAULT '',
        job_title             TEXT NOT NULL DEFAULT '',
        technology_profile_id INTEGER,
        oracle_alignment      TEXT NOT NULL DEFAULT '',
        linkedin_url          TEXT NOT NULL DEFAULT '',
        hubspot_id            TEXT NOT NULL DEFAULT '',
        source                TEXT NOT NULL DEFAULT '',
        created_at            TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS campaigns (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        name                  TEXT NOT NULL UNIQUE,
        description           TEXT NOT NULL DEFAULT '',
        keywords              TEXT NOT NULL DEFAULT '[]',
        extra_job_suffixes    TEXT NOT NULL DEFAULT '[]',
        extra_news_templates  TEXT NOT NULL DEFAULT '[]',
        custom_job_queries    TEXT NOT NULL DEFAULT '[]',
        custom_news_queries   TEXT NOT NULL DEFAULT '[]',
        location              TEXT NOT NULL DEFAULT '',
        max_pages             INTEGER NOT NULL DEFAULT 3,
        sources               TEXT NOT NULL DEFAULT '[]',
        query_tier            INTEGER NOT NULL DEFAULT 1,
        is_active             INTEGER NOT NULL DEFAULT 1,
        last_run_at           TEXT,
        last_run_id           INTEGER,
        total_signals         INTEGER NOT NULL DEFAULT 0,
        total_companies       INTEGER NOT NULL DEFAULT 0,
        created_at            TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_campaigns_active ON campaigns(is_active)",
    # Mirrors database.py — companies to never persist as a prospect for this
    # campaign (e.g. the vendor's own name).
    "ALTER TABLE campaigns ADD COLUMN exclude_companies TEXT NOT NULL DEFAULT '[]'",
    """
    CREATE TABLE IF NOT EXISTS import_batches (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        file_name     TEXT NOT NULL,
        entity_type   TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'pending',
        record_count  INTEGER NOT NULL DEFAULT 0,
        success_count INTEGER NOT NULL DEFAULT 0,
        error_count   INTEGER NOT NULL DEFAULT 0,
        error_log     TEXT NOT NULL DEFAULT '[]',
        s3_key        TEXT NOT NULL DEFAULT '',
        created_by    INTEGER,
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at  TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS apollo_credit_log (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id         TEXT,
        step           TEXT NOT NULL,
        credits_before INTEGER,
        credits_after  INTEGER,
        credits_used   INTEGER,
        logged_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # product_taxonomy — per-profile Oracle product aliases, feeds seed_default_profile()
    """
    CREATE TABLE IF NOT EXISTS product_taxonomy (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        technology_profile_id INTEGER REFERENCES technology_profiles(id) ON DELETE CASCADE,
        canonical_name        TEXT NOT NULL,
        aliases               TEXT NOT NULL DEFAULT '[]',
        category              TEXT NOT NULL DEFAULT '',
        confidence_weight     REAL NOT NULL DEFAULT 1.0,
        is_active             INTEGER NOT NULL DEFAULT 1,
        created_at            TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at            TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (technology_profile_id, canonical_name)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pt_profile ON product_taxonomy(technology_profile_id)",

    # enrichment_cache — short-TTL Apollo/ZeroBounce cache
    """
    CREATE TABLE IF NOT EXISTS enrichment_cache (
        lead_id                     TEXT PRIMARY KEY,
        email                       TEXT NOT NULL DEFAULT '',
        email_source                TEXT NOT NULL DEFAULT '',
        email_validation_status     TEXT NOT NULL DEFAULT '',
        email_validation_sub_status TEXT NOT NULL DEFAULT '',
        linkedin_url                TEXT NOT NULL DEFAULT '',
        job_title                   TEXT NOT NULL DEFAULT '',
        cached_at                   TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at                  TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ec_expires ON enrichment_cache(expires_at)",

    # event_attendees — links events to company_contacts
    """
    CREATE TABLE IF NOT EXISTS event_attendees (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id   INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        contact_id INTEGER NOT NULL REFERENCES company_contacts(id) ON DELETE CASCADE,
        role       TEXT NOT NULL DEFAULT 'attendee'
                       CHECK (role IN ('attendee','speaker','organiser','sponsor')),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (event_id, contact_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ea_event   ON event_attendees(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_ea_contact ON event_attendees(contact_id)",

    # manufacturer_links — links manufacturer_contacts to companies
    """
    CREATE TABLE IF NOT EXISTS manufacturer_links (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        manufacturer_contact_id INTEGER NOT NULL REFERENCES manufacturer_contacts(id) ON DELETE CASCADE,
        company_id              INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        link_type               TEXT NOT NULL DEFAULT 'partner'
                                    CHECK (link_type IN ('partner','reseller','implementer','support','other')),
        created_at              TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (manufacturer_contact_id, company_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ml2_company ON manufacturer_links(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_ml2_mfr     ON manufacturer_links(manufacturer_contact_id)",

    # import_mapping_templates — saved column-mapping presets for list_import.py
    """
    CREATE TABLE IF NOT EXISTS import_mapping_templates (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        entity_type TEXT NOT NULL CHECK (entity_type IN ('contact','company','event','manufacturer')),
        mappings    TEXT NOT NULL DEFAULT '{}',
        created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (name, entity_type)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_imt_type ON import_mapping_templates(entity_type)",

    # review_queue — human review queue for flagged company/contact records
    """
    CREATE TABLE IF NOT EXISTS review_queue (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type  TEXT NOT NULL CHECK (entity_type IN ('company','contact')),
        entity_id    INTEGER NOT NULL,
        issue_type   TEXT NOT NULL CHECK (issue_type IN (
                         'duplicate','data_quality','conflict',
                         'enrichment_conflict','missing_mandatory_field','fuzzy_match'
                     )),
        severity     TEXT NOT NULL DEFAULT 'warning'
                         CHECK (severity IN ('critical','warning','info')),
        status       TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','approved','rejected','auto_resolved')),
        issue_detail TEXT,
        notes        TEXT,
        resolved_by  TEXT,
        resolved_at  TEXT,
        created_at   TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status)",
    "CREATE INDEX IF NOT EXISTS idx_review_queue_entity ON review_queue(entity_type, entity_id)",

    # Indexes
    "CREATE INDEX IF NOT EXISTS idx_credit_log_run ON apollo_credit_log(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_credit_log_ts  ON apollo_credit_log(logged_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_signals_company     ON oracle_signals(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_signals_phase       ON oracle_signals(phase)",
    "CREATE INDEX IF NOT EXISTS idx_signals_product     ON oracle_signals(oracle_product)",
    "CREATE INDEX IF NOT EXISTS idx_signals_tier        ON oracle_signals(signal_tier)",
    "CREATE INDEX IF NOT EXISTS idx_signals_scan_run    ON oracle_signals(scan_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_companies_first_scan_run ON companies(first_scan_run_id)",
    # Migrations for existing DBs — ADD COLUMN is idempotent via IF NOT EXISTS equivalent
    "ALTER TABLE oracle_signals ADD COLUMN signal_tier TEXT DEFAULT 'P2'",
    "ALTER TABLE technology_profiles ADD COLUMN competitor_domains TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE technology_profiles ADD COLUMN partner_domains TEXT NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS idx_contacts_company    ON company_contacts(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_companies_sigcount  ON companies(signal_count DESC)",
    "CREATE INDEX IF NOT EXISTS idx_al_created          ON audit_logs(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_users_email         ON users(email)",
    "CREATE INDEX IF NOT EXISTS idx_ep_domain           ON email_patterns(domain)",
    "CREATE INDEX IF NOT EXISTS idx_dk_domain           ON domain_knowledge(domain)",

    # outcomes — the learning loop (mirrors database.py)
    """
    CREATE TABLE IF NOT EXISTS outcomes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id  INTEGER REFERENCES companies(id) ON DELETE SET NULL,
        contact_id  INTEGER REFERENCES company_contacts(id) ON DELETE SET NULL,
        campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
        email       TEXT NOT NULL DEFAULT '',
        outcome     TEXT NOT NULL
                        CHECK (outcome IN ('contacted','replied','meeting',
                                           'bounced','bad','unsubscribed')),
        notes       TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_outcomes_company ON outcomes(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_outcome ON outcomes(outcome)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_created ON outcomes(created_at DESC)",

    # campaign_hooks / campaign_touches — mirrors database.py
    """
    CREATE TABLE IF NOT EXISTS campaign_hooks (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_name            TEXT NOT NULL DEFAULT '',
        contact_email           TEXT NOT NULL DEFAULT '',
        contact_title           TEXT NOT NULL DEFAULT '',
        linkedin_url            TEXT NOT NULL DEFAULT '',
        company_name            TEXT NOT NULL DEFAULT '',
        signal_summary          TEXT NOT NULL DEFAULT '',
        product_context         TEXT NOT NULL DEFAULT '',
        icp_research            TEXT NOT NULL DEFAULT '',
        angle                   TEXT NOT NULL DEFAULT '',
        subject                 TEXT NOT NULL DEFAULT '',
        body                    TEXT NOT NULL DEFAULT '',
        word_count              INTEGER NOT NULL DEFAULT 0,
        personalization_bucket  INTEGER,
        personalization_label   TEXT NOT NULL DEFAULT '',
        grounded                INTEGER,
        grounded_on             TEXT NOT NULL DEFAULT '',
        hold_back               INTEGER NOT NULL DEFAULT 0,
        ok                      INTEGER NOT NULL DEFAULT 0,
        error                   TEXT NOT NULL DEFAULT '',
        created_at              TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_campaign_hooks_angle   ON campaign_hooks(angle)",
    "CREATE INDEX IF NOT EXISTS idx_campaign_hooks_created ON campaign_hooks(created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS campaign_touches (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        hook_id    INTEGER REFERENCES campaign_hooks(id) ON DELETE CASCADE,
        day        INTEGER NOT NULL,
        channel    TEXT NOT NULL,
        subject    TEXT NOT NULL DEFAULT '',
        body       TEXT NOT NULL DEFAULT '',
        notes      TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_campaign_touches_hook ON campaign_touches(hook_id)",
    "ALTER TABLE outcomes ADD COLUMN hook_id INTEGER REFERENCES campaign_hooks(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_hook ON outcomes(hook_id)",

    # ats_boards registry — auto-discovered company→ATS map (mirrors database.py)
    """
    CREATE TABLE IF NOT EXISTS ats_boards (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        company       TEXT NOT NULL DEFAULT '',
        ats           TEXT NOT NULL,
        token         TEXT NOT NULL,
        job_count     INTEGER NOT NULL DEFAULT 0,
        verified      INTEGER NOT NULL DEFAULT 0,
        is_active     INTEGER NOT NULL DEFAULT 1,
        discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (ats, token)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ats_boards_active ON ats_boards(is_active)",
]

# ── Public API ────────────────────────────────────────────────────────────────

def init_db():
    with db_cursor() as cur:
        for stmt in _DDL:
            try:
                cur.execute(stmt)
            except Exception as e:
                logger.debug("DDL skip: %s", e)
    logger.info("SQLite schema ready at %s", _DB_PATH)
    seed_engine_configs()


def log_apollo_credits(run_id: str, step: str, credits_before: int | None, credits_after: int | None) -> None:
    """Record Apollo credit consumption for one pipeline step."""
    used = None
    if credits_before is not None and credits_after is not None:
        used = credits_before - credits_after
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO apollo_credit_log (run_id, step, credits_before, credits_after, credits_used, logged_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, step, credits_before, credits_after, used, _now()),
        )


def get_credit_log(limit: int = 100) -> list[dict]:
    """Return recent Apollo credit log entries, newest first."""
    with db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT * FROM apollo_credit_log ORDER BY logged_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_credit_summary() -> dict:
    """Aggregate credit spend by step across all runs."""
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT step,
                   COUNT(*)        AS calls,
                   SUM(credits_used) AS total_used,
                   MAX(logged_at)  AS last_used_at
            FROM apollo_credit_log
            WHERE credits_used IS NOT NULL
            GROUP BY step
            ORDER BY total_used DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT SUM(credits_used) AS grand_total FROM apollo_credit_log WHERE credits_used IS NOT NULL")
        grand = cur.fetchone()
        return {
            "by_step":    rows,
            "grand_total": int(grand["grand_total"] or 0),
        }


def test_connection() -> bool:
    try:
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


def close_pool():
    global _connection
    with _conn_lock:
        if _connection:
            _connection.close()
            _connection = None


# ── Companies ─────────────────────────────────────────────────────────────────

def upsert_company(name: str, domain: str = None, industry: str = None,
                   size: str = None, location: str = None, website: str = None,
                   first_scan_run_id: int = None) -> int:
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO companies
                (name, domain, industry, size, location, website,
                 first_scan_run_id, unique_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                domain       = COALESCE(companies.domain,    excluded.domain),
                industry     = COALESCE(companies.industry,  excluded.industry),
                size         = COALESCE(companies.size,      excluded.size),
                location     = COALESCE(companies.location,  excluded.location),
                website      = COALESCE(companies.website,   excluded.website),
                unique_key   = CASE WHEN companies.unique_key = ''
                                    THEN excluded.unique_key
                                    ELSE companies.unique_key END,
                last_updated = datetime('now')
            RETURNING id
        """, (name, domain, industry, size, location, website,
              first_scan_run_id, _gen_unique_key()))
        row = cur.fetchone()
        if row:
            return row["id"]
    # fallback if RETURNING not supported
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT id FROM companies WHERE name = ?", (name,))
        return cur.fetchone()["id"]


def get_company_by_id(company_id: int) -> Optional[dict]:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
        return cur.fetchone()


def get_company_by_name(name: str) -> Optional[dict]:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM companies WHERE name = ?", (name,))
        return cur.fetchone()


def get_all_company_names() -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT name FROM companies ORDER BY name")
        return [r["name"] for r in cur.fetchall()]


def get_company_ids_by_names(names: list) -> list:
    if not names:
        return []
    ph = ",".join("?" * len(names))
    with db_cursor(commit=False) as cur:
        cur.execute(f"SELECT id, name FROM companies WHERE name IN ({ph})", names)
        return cur.fetchall()


def purge_invalid_companies(is_valid_fn) -> int:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT id, name FROM companies")
        rows = cur.fetchall()
    to_delete = [r["id"] for r in rows if not is_valid_fn(r["name"])]
    if not to_delete:
        return 0
    with db_cursor() as cur:
        for cid in to_delete:
            cur.execute("DELETE FROM companies WHERE id = ?", (cid,))
    return len(to_delete)


def reset_all_data():
    with db_cursor() as cur:
        for tbl in ["oracle_signals", "company_contacts", "companies", "scan_runs"]:
            cur.execute(f"DELETE FROM {tbl}")
    logger.warning("All data reset (SQLite)")


def delete_company(company_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        return cur.rowcount > 0


def merge_companies(keep_id: int, drop_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute("UPDATE oracle_signals   SET company_id = ? WHERE company_id = ?", (keep_id, drop_id))
        cur.execute("UPDATE company_contacts SET company_id = ? WHERE company_id = ?", (keep_id, drop_id))
        cur.execute("DELETE FROM companies WHERE id = ?", (drop_id,))
        cur.execute("""
            UPDATE companies SET
                signal_count  = (SELECT COUNT(*) FROM oracle_signals   WHERE company_id = id),
                contact_count = (SELECT COUNT(*) FROM company_contacts WHERE company_id = id AND email != '')
            WHERE id = ?
        """, (keep_id,))
    return {"kept": keep_id, "dropped": drop_id}


def set_company_target_product(company_id: int, product: str):
    with db_cursor() as cur:
        cur.execute("UPDATE companies SET target_product = ? WHERE id = ?", (product, company_id))


def set_company_domain(company_id: int, domain: str):
    with db_cursor() as cur:
        cur.execute("UPDATE companies SET domain = ? WHERE id = ?", (domain, company_id))


def backfill_target_product() -> int:
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT c.id, GROUP_CONCAT(DISTINCT s.oracle_product) AS products
            FROM companies c
            JOIN oracle_signals s ON s.company_id = c.id
            WHERE c.target_product = '' AND s.oracle_product != ''
            GROUP BY c.id
        """)
        rows = cur.fetchall()
    count = 0
    for row in rows:
        first = (row.get("products") or "").split(",")[0].strip()
        if first:
            with db_cursor() as cur:
                cur.execute("UPDATE companies SET target_product = ? WHERE id = ?", (first, row["id"]))
            count += 1
    return count


def get_companies_needing_enrichment(limit: int = 50, company_ids: list = None) -> list:
    with db_cursor(commit=False) as cur:
        if company_ids:
            ph = ",".join("?" * len(company_ids))
            cur.execute(f"SELECT * FROM companies WHERE id IN ({ph}) LIMIT ?", company_ids + [limit])
        else:
            cur.execute("SELECT * FROM companies WHERE contact_count = 0 LIMIT ?", (limit,))
        return cur.fetchall()


def get_all_companies_with_signals(run_id: int = None) -> list:
    if run_id is None:
        run_id = get_latest_completed_run_id()

    with db_cursor(commit=False) as cur:
        if run_id:
            cur.execute("""
                SELECT
                    c.id, c.name, c.domain, c.industry, c.size,
                    c.location, c.website, c.first_seen,
                    c.first_scan_run_id, c.source AS import_source,
                    COALESCE(NULLIF(c.target_product, ''),
                             GROUP_CONCAT(DISTINCT s.oracle_product)) AS target_product,
                    COUNT(s.id)                             AS signal_count,
                    GROUP_CONCAT(DISTINCT s.oracle_product) AS products,
                    GROUP_CONCAT(DISTINCT s.phase)          AS phases,
                    GROUP_CONCAT(DISTINCT s.source)         AS sources,
                    MAX(s.confidence)                       AS max_confidence,
                    MAX(s.detected_at)                      AS latest_signal_at,
                    (SELECT url FROM oracle_signals
                     WHERE company_id = c.id AND scan_run_id = ? AND url LIKE 'http%'
                     ORDER BY confidence DESC LIMIT 1)      AS source_url,
                    COALESCE(ct.contact_count, 0)           AS contact_count
                FROM companies c
                LEFT JOIN oracle_signals s
                    ON s.company_id = c.id AND s.scan_run_id = ?
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS contact_count
                    FROM company_contacts
                    WHERE email IS NOT NULL AND email != ''
                    GROUP BY company_id
                ) ct ON ct.company_id = c.id
                WHERE c.first_scan_run_id = ?
                GROUP BY c.id
                ORDER BY signal_count DESC, c.last_updated DESC
            """, (run_id, run_id, run_id))
        else:
            cur.execute("""
                SELECT
                    c.id, c.name, c.domain, c.industry, c.size,
                    c.location, c.website, c.first_seen,
                    c.first_scan_run_id, c.source AS import_source,
                    COALESCE(NULLIF(c.target_product, ''),
                             GROUP_CONCAT(DISTINCT s.oracle_product)) AS target_product,
                    COUNT(s.id)                             AS signal_count,
                    GROUP_CONCAT(DISTINCT s.oracle_product) AS products,
                    GROUP_CONCAT(DISTINCT s.phase)          AS phases,
                    GROUP_CONCAT(DISTINCT s.source)         AS sources,
                    MAX(s.confidence)                       AS max_confidence,
                    MAX(s.detected_at)                      AS latest_signal_at,
                    NULL                                    AS source_url,
                    COALESCE(ct.contact_count, 0)           AS contact_count
                FROM companies c
                LEFT JOIN oracle_signals s ON s.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS contact_count
                    FROM company_contacts WHERE email != ''
                    GROUP BY company_id
                ) ct ON ct.company_id = c.id
                GROUP BY c.id
                ORDER BY signal_count DESC, c.last_updated DESC
            """)
        rows = cur.fetchall()

    for row in rows:
        row["products"] = [p for p in (row.get("products") or "").split(",") if p]
        row["phases"]   = [p for p in (row.get("phases")   or "").split(",") if p]
        row["sources"]  = [s for s in (row.get("sources")  or "").split(",") if s]
    return rows


# ── Signals ───────────────────────────────────────────────────────────────────

def _compute_signal_tier(phase: str, confidence: float, source: str) -> str:
    """
    P0/P1/P2 urgency tiers (janskuba/go-to-market-orchestrator pattern).
    P0 = 48-hour response window — act before the RFP window closes.
    P1 = 1-week response window.
    P2 = contextual / monitoring.
    """
    _P0_PHASES = {"implementing", "evaluating"}
    _P1_PHASES = {"hiring", "budgeting"}
    if phase in _P0_PHASES and confidence >= 0.80:
        return "P0"
    if phase in _P0_PHASES and confidence >= 0.65:
        return "P1"
    if phase in _P1_PHASES and confidence >= 0.70:
        return "P1"
    return "P2"


def insert_signal(company_id: int, oracle_product: str, phase: str, source: str,
                  signal_type: str = None, job_title: str = None, evidence: str = None,
                  url: str = None, confidence: float = 0.5, scan_run_id: int = None,
                  content_hash: str = None) -> Optional[int]:
    signal_tier = _compute_signal_tier(phase or "", confidence or 0.5, source or "")
    try:
        with db_cursor() as cur:
            cur.execute("""
                INSERT INTO oracle_signals
                    (company_id, scan_run_id, oracle_product, phase, source,
                     signal_type, job_title, evidence, url, confidence,
                     signal_tier, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_hash) DO NOTHING
            """, (company_id, scan_run_id, oracle_product, phase, source,
                  signal_type, job_title, evidence, url, confidence,
                  signal_tier, content_hash))
            sig_id = cur.lastrowid
        with db_cursor() as cur:
            cur.execute(
                "UPDATE companies SET signal_count = signal_count + 1 WHERE id = ?",
                (company_id,),
            )
        return sig_id
    except Exception as e:
        logger.error("insert_signal error: %s", e)
        return None


def batch_update_signal_counts(company_ids: list) -> None:
    for cid in company_ids:
        with db_cursor() as cur:
            cur.execute("""
                UPDATE companies SET
                    signal_count = (SELECT COUNT(*) FROM oracle_signals WHERE company_id = ?)
                WHERE id = ?
            """, (cid, cid))


def get_signals_for_company(company_id: int) -> list:
    with db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT * FROM oracle_signals WHERE company_id = ? ORDER BY detected_at DESC",
            (company_id,),
        )
        return cur.fetchall()


def get_top_signals_for_companies(names: list) -> dict:
    """Mirrors database.py — highest-confidence signal per company name as a
    one-line summary. SQLite has no DISTINCT ON, so rank in Python instead."""
    wanted = [n.strip().lower() for n in names if n and n.strip()]
    if not wanted:
        return {}
    placeholders = ",".join("?" for _ in wanted)
    with db_cursor(commit=False) as cur:
        cur.execute(f"""
            SELECT c.name, s.oracle_product, s.phase, s.signal_type,
                   s.job_title, s.evidence, s.source, s.confidence, s.detected_at
            FROM companies c
            JOIN oracle_signals s ON s.company_id = c.id
            WHERE LOWER(c.name) IN ({placeholders})
            ORDER BY s.confidence DESC, s.detected_at DESC
        """, wanted)
        out = {}
        for r in cur.fetchall():
            key = (r["name"] or "").strip().lower()
            if key in out:
                continue  # rows arrive best-first; keep only the top one
            bits = [b for b in (r["signal_type"], r["oracle_product"], r["phase"]) if b]
            head = " / ".join(bits) if bits else "intent signal"
            detail = r["job_title"] or r["evidence"] or ""
            summary = f"{head}: {detail}" if detail else head
            out[key] = f"{summary} (source: {r['source']}, confidence {(r['confidence'] or 0):.2f})"
        return out


# ── Review queue — mirrors database.py ───────────────────────────────────────
# The Postgres versions use NOW(), CONCAT(), and ANY(%s), none of which exist
# in SQLite, so without these mirrors the Review Queue crashes in fallback mode.

def add_to_review_queue(entity_type: str, entity_id: int, issue_type: str,
                         severity: str = 'warning', issue_detail: dict = None) -> dict:
    import json
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO review_queue (entity_type, entity_id, issue_type, severity, issue_detail)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT DO NOTHING""",
            (entity_type, entity_id, issue_type, severity,
             json.dumps(issue_detail) if issue_detail else None),
        )
        new_id = cur.lastrowid
        if not new_id:
            return {}
        cur.execute("SELECT * FROM review_queue WHERE id = ?", (new_id,))
        row = cur.fetchone()
        return dict(row) if row else {}


def list_review_queue(status: str = None, entity_type: str = None,
                       limit: int = 100, offset: int = 0) -> list:
    with db_cursor(commit=False) as cur:
        wheres, params = [], []
        if status:
            wheres.append("rq.status=?"); params.append(status)
        if entity_type:
            wheres.append("rq.entity_type=?"); params.append(entity_type)
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        cur.execute(
            f"""SELECT rq.*,
                       CASE rq.entity_type
                           WHEN 'company' THEN c.name
                           WHEN 'contact' THEN cc.first_name || ' ' || cc.last_name
                       END AS entity_name
                FROM review_queue rq
                LEFT JOIN companies c ON rq.entity_type='company' AND c.id=rq.entity_id
                LEFT JOIN company_contacts cc ON rq.entity_type='contact' AND cc.id=rq.entity_id
                {where_sql}
                ORDER BY rq.created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        )
        return [dict(r) for r in cur.fetchall()]


def resolve_review_queue_item(item_id: int, status: str,
                               notes: str = None, resolved_by: str = None) -> dict:
    with db_cursor() as cur:
        cur.execute(
            """UPDATE review_queue
               SET status=?, notes=?, resolved_by=?,
                   resolved_at=datetime('now'), updated_at=datetime('now')
               WHERE id=?""",
            (status, notes, resolved_by, item_id),
        )
        cur.execute("SELECT * FROM review_queue WHERE id = ?", (item_id,))
        row = cur.fetchone()
        return dict(row) if row else {}


def bulk_resolve_review_queue(item_ids: list, status: str, resolved_by: str = None):
    if not item_ids:
        return
    placeholders = ",".join("?" for _ in item_ids)
    with db_cursor() as cur:
        cur.execute(
            f"""UPDATE review_queue
                SET status=?, resolved_by=?, resolved_at=datetime('now'), updated_at=datetime('now')
                WHERE id IN ({placeholders})""",
            [status, resolved_by] + list(item_ids),
        )


# ── Scan runs ─────────────────────────────────────────────────────────────────

def start_scan_run(queries: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO scan_runs (search_queries, status) VALUES (?, 'running') RETURNING id",
            (queries,),
        )
        row = cur.fetchone()
        return row["id"] if row else cur.lastrowid


def finish_scan_run(run_id: int, total_signals: int, total_companies: int,
                    status: str = "completed"):
    with db_cursor() as cur:
        cur.execute("""
            UPDATE scan_runs SET
                completed_at = datetime('now'), status = ?,
                total_signals = ?, total_companies = ?
            WHERE id = ?
        """, (status, total_signals, total_companies, run_id))


def get_latest_completed_run_id() -> Optional[int]:
    with db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT id FROM scan_runs WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row["id"] if row else None


def get_recent_scan_runs(limit: int = 10) -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,))
        return cur.fetchall()


def purge_scan_companies(run_id: int) -> int:
    with db_cursor() as cur:
        cur.execute("DELETE FROM companies WHERE first_scan_run_id = ?", (run_id,))
        return cur.rowcount


# ── Contacts ──────────────────────────────────────────────────────────────────

def save_contacts(company_id: int, contacts: list):
    for c in contacts:
        email = (c.get("email") or "").strip().lower()
        with db_cursor() as cur:
            cur.execute("""
                INSERT INTO company_contacts
                    (company_id, first_name, last_name, full_name, title, email,
                     linkedin_url, seniority, confidence, is_target, source,
                     email_validation_status, target_product, ready_for_outreach,
                     unique_key, domain, city, state, country)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            """, (
                company_id,
                c.get("first_name", ""),
                c.get("last_name", ""),
                c.get("full_name") or f"{c.get('first_name','')} {c.get('last_name','')}".strip(),
                c.get("title", ""),
                email,
                c.get("linkedin_url", ""),
                c.get("seniority", ""),
                float(c.get("confidence", 0)),
                int(c.get("is_target", 0)),
                c.get("source", "apollo"),
                c.get("email_validation_status", ""),
                c.get("target_product", ""),
                int(bool(c.get("ready_for_outreach", False))),
                _gen_unique_key(),
                c.get("domain", ""),
                c.get("city", ""),
                c.get("state", ""),
                c.get("country", ""),
            ))
    with db_cursor() as cur:
        cur.execute("""
            UPDATE companies SET
                contact_count = (SELECT COUNT(*) FROM company_contacts
                                 WHERE company_id = ? AND email != '')
            WHERE id = ?
        """, (company_id, company_id))


def get_contacts_for_company(company_id: int) -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT * FROM company_contacts
            WHERE company_id = ?
            ORDER BY confidence DESC, fetched_at DESC
        """, (company_id,))
        return cur.fetchall()


def get_contact_by_id(contact_id: int) -> Optional[dict]:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM company_contacts WHERE id = ?", (contact_id,))
        return cur.fetchone()


def delete_contact(contact_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute("DELETE FROM company_contacts WHERE id = ?", (contact_id,))
        return cur.rowcount > 0


def update_contact_email(contact_id: int, email: str = None, status: str = None,
                         source: str = None, pattern: str = None,
                         ready_for_outreach: bool = None):
    parts, vals = [], []
    if email is not None:
        parts.append("email = ?"); vals.append(email.strip().lower())
    if status is not None:
        parts.append("email_validation_status = ?"); vals.append(status)
    if source is not None:
        parts.append("email_source = ?"); vals.append(source)
    if pattern is not None:
        parts.append("email_prediction_pattern = ?"); vals.append(pattern)
    if ready_for_outreach is not None:
        parts.append("ready_for_outreach = ?"); vals.append(int(ready_for_outreach))
    if not parts:
        return
    vals.append(contact_id)
    with db_cursor() as cur:
        cur.execute(f"UPDATE company_contacts SET {', '.join(parts)} WHERE id = ?", vals)


def get_contacts_for_company_names(names: list) -> list:
    if not names:
        return []
    ph = ",".join("?" * len(names))
    with db_cursor(commit=False) as cur:
        cur.execute(f"""
            SELECT cc.*, c.name AS company_name, c.domain AS company_domain
            FROM company_contacts cc
            JOIN companies c ON c.id = cc.company_id
            WHERE c.name IN ({ph})
        """, names)
        return cur.fetchall()


def find_existing_contact(company_id: int, email: str = None,
                          linkedin_url: str = None) -> Optional[dict]:
    with db_cursor(commit=False) as cur:
        if email:
            cur.execute(
                "SELECT * FROM company_contacts WHERE company_id = ? AND email = ?",
                (company_id, email.lower()),
            )
            row = cur.fetchone()
            if row:
                return row
        if linkedin_url:
            cur.execute(
                "SELECT * FROM company_contacts WHERE company_id = ? AND linkedin_url = ?",
                (company_id, linkedin_url),
            )
            return cur.fetchone()
    return None


def get_contacts_master_match(emails: list = None) -> list:
    if not emails:
        return []
    ph = ",".join("?" * len(emails))
    with db_cursor(commit=False) as cur:
        cur.execute(
            f"SELECT * FROM company_contacts WHERE email IN ({ph})",
            [e.lower() for e in emails],
        )
        return cur.fetchall()


def get_enrichment_stats() -> dict:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM companies")
        total_companies = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM company_contacts")
        total_contacts = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM company_contacts WHERE email != '' AND email IS NOT NULL")
        with_email = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM company_contacts WHERE ready_for_outreach = 1")
        ready = cur.fetchone()["n"]
    return {
        "total_companies": total_companies,
        "total_contacts": total_contacts,
        "contacts_with_email": with_email,
        "ready_for_outreach": ready,
    }


# ── Product intel ─────────────────────────────────────────────────────────────

def aggregate_product_intel() -> dict:
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT oracle_product,
                   COUNT(DISTINCT company_id) AS company_count,
                   AVG(confidence)            AS avg_confidence
            FROM oracle_signals
            WHERE oracle_product != '' AND oracle_product IS NOT NULL
            GROUP BY oracle_product
            ORDER BY company_count DESC
        """)
        rows = cur.fetchall()
    return {
        r["oracle_product"]: {
            "company_count": r["company_count"],
            "avg_confidence": round(float(r["avg_confidence"] or 0), 2),
        }
        for r in rows
    }


# ── Master leads (API-compatible stubs — table removed in main DB) ─────────────

def master_leads_stats() -> dict:
    return {"total": 0, "ready_for_outreach": 0}


def upsert_master_leads(records: list) -> int:
    return 0


def get_master_leads_by_email(emails: list) -> dict:
    return {}


def get_master_leads_by_company(company_normalized: str) -> list:
    return []


# ── Email patterns ────────────────────────────────────────────────────────────

def load_domain_patterns(domains: list = None) -> dict:
    with db_cursor(commit=False) as cur:
        if domains:
            ph = ",".join("?" * len(domains))
            cur.execute(
                f"SELECT domain, pattern FROM email_patterns WHERE domain IN ({ph}) ORDER BY sample_count DESC",
                domains,
            )
        else:
            cur.execute("SELECT domain, pattern FROM email_patterns")
        rows = cur.fetchall()
    result: dict = {}
    for r in rows:
        result.setdefault(r["domain"], []).append(r["pattern"])
    return result


def upsert_email_patterns(rows: list) -> int:
    count = 0
    for row in rows:
        with db_cursor() as cur:
            cur.execute("""
                INSERT INTO email_patterns (domain, pattern)
                VALUES (?, ?)
                ON CONFLICT(domain, pattern) DO UPDATE SET
                    sample_count = sample_count + 1,
                    last_seen_at = datetime('now')
            """, (row.get("domain", ""), row.get("pattern", "")))
            count += 1
    return count


def email_patterns_stats() -> dict:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(DISTINCT domain) AS d, COUNT(*) AS p FROM email_patterns")
        row = cur.fetchone()
    return {"domains": row["d"], "patterns": row["p"]}


# ── Prediction Engine — full company_email_formats reference ─────────────────

def upsert_company_email_formats(rows: list) -> int:
    if not rows:
        return 0
    cols = ["company_name", "domain", "format_rank", "format_code", "formula",
            "description", "domain_example", "share_pct", "format_count",
            "sample_emails", "contacts_280k", "validated_emails",
            "formats_found", "is_predictable", "recommended_action"]
    ph = ", ".join("?" * len(cols))
    with db_cursor() as cur:
        for r in rows:
            cur.execute(
                f"""INSERT INTO company_email_formats ({", ".join(cols)})
                    VALUES ({ph})
                    ON CONFLICT(domain, format_rank) DO UPDATE SET
                        company_name       = excluded.company_name,
                        format_code        = excluded.format_code,
                        formula            = excluded.formula,
                        description        = excluded.description,
                        domain_example     = excluded.domain_example,
                        share_pct          = excluded.share_pct,
                        format_count       = excluded.format_count,
                        sample_emails      = excluded.sample_emails,
                        contacts_280k      = excluded.contacts_280k,
                        validated_emails   = excluded.validated_emails,
                        formats_found      = excluded.formats_found,
                        is_predictable     = excluded.is_predictable,
                        recommended_action = excluded.recommended_action""",
                tuple(r.get(c) for c in cols),
            )
    return len(rows)


def search_company_email_formats(query: str, limit: int = 20) -> list:
    # contacts_280k = 0 means a stray validated-email match with no real
    # corpus presence — noise, not a company. is_predictable = 0 means the
    # primary format has no buildable template ("Other / unmatched" or a
    # custom multi-dot code) — nothing to actually apply. See the Postgres
    # version's docstring in database.py for concrete examples of both.
    q = f"%{(query or '').strip().lower()}%"
    if not q.strip("%"):
        return []
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT company_name, domain, format_code, formula, domain_example,
                   share_pct, formats_found, contacts_280k, validated_emails,
                   is_predictable
            FROM company_email_formats
            WHERE format_rank = 1
              AND contacts_280k > 0
              AND is_predictable = 1
              AND (LOWER(company_name) LIKE ? OR LOWER(domain) LIKE ?)
            ORDER BY contacts_280k DESC, validated_emails DESC
            LIMIT ?
        """, (q, q, limit))
        return [dict(r) for r in cur.fetchall()]


def get_company_email_formats(domain: str) -> list:
    domain = (domain or "").strip().lower()
    if not domain:
        return []
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT * FROM company_email_formats
            WHERE domain = ?
            ORDER BY format_rank
        """, (domain,))
        return [dict(r) for r in cur.fetchall()]


def company_email_formats_stats() -> dict:
    # "domains" scoped to exactly what search_company_email_formats surfaces
    # (evidence-backed AND a buildable primary format) — see database.py.
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT COUNT(DISTINCT domain) AS n FROM company_email_formats
            WHERE contacts_280k > 0 AND is_predictable = 1 AND format_rank = 1
        """)
        domains = cur.fetchone()["n"]
        cur.execute("""
            SELECT COUNT(*) AS n FROM company_email_formats
            WHERE domain IN (
                SELECT domain FROM company_email_formats
                WHERE contacts_280k > 0 AND is_predictable = 1 AND format_rank = 1
            )
        """)
        total_rows = cur.fetchone()["n"]
    return {"domains": domains, "total_rows": total_rows, "predictable_domains": domains}


# ── HubSpot ───────────────────────────────────────────────────────────────────

def get_hubspot_config() -> dict:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM hubspot_config ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    return row or {
        "api_key": "", "portal_id": "", "sync_status": "idle",
        "companies_synced": 0, "contacts_synced": 0,
    }


def upsert_hubspot_config(api_key: str, portal_id: str) -> dict:
    existing = get_hubspot_config()
    with db_cursor() as cur:
        if existing.get("id"):
            cur.execute("""
                UPDATE hubspot_config
                SET api_key = ?, portal_id = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (api_key, portal_id, existing["id"]))
        else:
            cur.execute(
                "INSERT INTO hubspot_config (api_key, portal_id) VALUES (?, ?)",
                (api_key, portal_id),
            )
    return get_hubspot_config()


def update_hubspot_sync_status(status: str, companies: int = 0, contacts: int = 0):
    cfg = get_hubspot_config()
    if cfg.get("id"):
        with db_cursor() as cur:
            cur.execute("""
                UPDATE hubspot_config SET
                    sync_status = ?, last_sync_at = datetime('now'),
                    companies_synced = ?, contacts_synced = ?,
                    updated_at = datetime('now')
                WHERE id = ?
            """, (status, companies, contacts, cfg["id"]))


# ── Engine configs ────────────────────────────────────────────────────────────

_DEFAULT_CONFIGS = [
    ("oracle_intent",   True,  '{"max_pages": 3, "location": "United States"}'),
    ("lead_enrichment", True,  '{"provider": "apollo", "max_per_company": 10}'),
]


def seed_engine_configs():
    for engine_type, is_enabled, config_json in _DEFAULT_CONFIGS:
        with db_cursor() as cur:
            cur.execute("""
                INSERT INTO engine_configs (engine_type, is_enabled, config_json)
                VALUES (?, ?, ?)
                ON CONFLICT(engine_type) DO NOTHING
            """, (engine_type, int(is_enabled), config_json))


def list_engine_configs() -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM engine_configs ORDER BY engine_type")
        return cur.fetchall()


def update_engine_config(engine_type: str, is_enabled: bool = None,
                         config_json: dict = None) -> dict:
    parts, vals = [], []
    if is_enabled is not None:
        parts.append("is_enabled = ?"); vals.append(int(is_enabled))
    if config_json is not None:
        parts.append("config_json = ?"); vals.append(json.dumps(config_json))
    parts.append("updated_at = datetime('now')")
    vals.append(engine_type)
    with db_cursor() as cur:
        cur.execute(
            f"UPDATE engine_configs SET {', '.join(parts)} WHERE engine_type = ?", vals
        )
        cur.execute("SELECT * FROM engine_configs WHERE engine_type = ?", (engine_type,))
        return cur.fetchone() or {}


# ── Users ─────────────────────────────────────────────────────────────────────
# No functions here — auth.py owns user-management (get_user_by_email,
# create_user, list_users, update_last_login, etc.) and calls through
# db.db_cursor(), which this module already monkey-patches on fallback. A
# parallel set of user functions used to live here but had zero callers
# (auth.py never routes through this module by name) — removed to avoid a
# second, silently-unused implementation drifting from the real one.

# ── Audit logs ────────────────────────────────────────────────────────────────

def log_audit_event(user_id: int, user_email: str, action: str,
                    entity_type: str, entity_id: str = "",
                    old_value=None, new_value=None, ip_address: str = ""):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO audit_logs
                (user_id, user_email, action, entity_type, entity_id,
                 old_value, new_value, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, user_email, action, entity_type, entity_id,
            json.dumps(old_value) if old_value is not None else None,
            json.dumps(new_value) if new_value is not None else None,
            ip_address,
        ))


# ── Companies list page — bulk lookups by ID ────────────────────────────────
# SQLite equivalent of database.py's ARRAY_AGG/FILTER/ANY() version — those
# have no direct SQLite equivalent, so this is a separate, natively-written query.

def get_signal_aggregates_by_company(company_ids: list) -> dict:
    if not company_ids:
        return {}
    placeholders = ",".join("?" for _ in company_ids)
    with db_cursor(commit=False) as cur:
        cur.execute(f"""
            SELECT company_id,
                   GROUP_CONCAT(DISTINCT oracle_product) AS products,
                   GROUP_CONCAT(DISTINCT phase)           AS phases,
                   GROUP_CONCAT(DISTINCT source)          AS sources,
                   MAX(confidence)                        AS max_confidence
            FROM oracle_signals
            WHERE company_id IN ({placeholders})
            GROUP BY company_id
        """, company_ids)
        agg = {r["company_id"]: dict(r) for r in cur.fetchall()}

        cur.execute(f"""
            SELECT company_id, url FROM (
                SELECT company_id, url,
                       ROW_NUMBER() OVER (PARTITION BY company_id ORDER BY confidence DESC) AS rn
                FROM oracle_signals
                WHERE company_id IN ({placeholders}) AND url LIKE 'http%'
            ) WHERE rn = 1
        """, company_ids)
        for r in cur.fetchall():
            agg.setdefault(r["company_id"], {})["source_url"] = r["url"]
        return agg


def get_companies_by_ids(company_ids: list) -> dict:
    if not company_ids:
        return {}
    placeholders = ",".join("?" for _ in company_ids)
    with db_cursor(commit=False) as cur:
        cur.execute(f"""
            SELECT c.id, c.name, c.domain, c.industry, c.size, c.location, c.website,
                   c.target_product, c.status, c.source AS import_source,
                   c.first_scan_run_id, c.first_seen AS first_seen,
                   c.signal_count, c.contact_count, c.last_updated AS last_updated
            FROM companies c
            WHERE c.id IN ({placeholders})
        """, company_ids)
        return {r["id"]: dict(r) for r in cur.fetchall()}


# ── Campaigns ─────────────────────────────────────────────────────────────────

def _serialize_campaign(row: dict) -> dict:
    """Parse JSON fields back to Python objects for API responses."""
    if not row:
        return row
    for field in ("keywords", "extra_job_suffixes", "extra_news_templates",
                  "custom_job_queries", "custom_news_queries", "sources",
                  "exclude_companies"):
        val = row.get(field)
        if isinstance(val, str):
            try:
                row[field] = json.loads(val)
            except Exception:
                row[field] = []
    return row


def list_campaigns(active_only: bool = False) -> list:
    with db_cursor(commit=False) as cur:
        if active_only:
            cur.execute("SELECT * FROM campaigns WHERE is_active = 1 ORDER BY created_at DESC")
        else:
            cur.execute("SELECT * FROM campaigns ORDER BY created_at DESC")
        return [_serialize_campaign(r) for r in cur.fetchall()]


def get_campaign(campaign_id: int) -> Optional[dict]:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
        return _serialize_campaign(cur.fetchone())


def create_campaign(
    name: str,
    description: str = "",
    keywords: list = None,
    extra_job_suffixes: list = None,
    extra_news_templates: list = None,
    custom_job_queries: list = None,
    custom_news_queries: list = None,
    location: str = "",
    max_pages: int = 3,
    sources: list = None,
    query_tier: int = 1,
    exclude_companies: list = None,
) -> dict:
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO campaigns
                (name, description, keywords, extra_job_suffixes, extra_news_templates,
                 custom_job_queries, custom_news_queries, location, max_pages,
                 sources, query_tier, exclude_companies)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, (
            name.strip(),
            description.strip(),
            json.dumps(keywords or []),
            json.dumps(extra_job_suffixes or []),
            json.dumps(extra_news_templates or []),
            json.dumps(custom_job_queries or []),
            json.dumps(custom_news_queries or []),
            location.strip(),
            max_pages,
            json.dumps(sources or []),
            query_tier,
            json.dumps(exclude_companies or []),
        ))
        row = cur.fetchone()
        cid = row["id"] if row else cur.lastrowid
    return get_campaign(cid)


def update_campaign(campaign_id: int, **kwargs) -> dict:
    json_fields = {"keywords", "extra_job_suffixes", "extra_news_templates",
                   "custom_job_queries", "custom_news_queries", "sources",
                   "exclude_companies"}
    parts, vals = [], []
    for k, v in kwargs.items():
        if k in json_fields:
            parts.append(f"{k} = ?"); vals.append(json.dumps(v or []))
        else:
            parts.append(f"{k} = ?"); vals.append(v)
    if not parts:
        return get_campaign(campaign_id)
    parts.append("updated_at = datetime('now')")
    vals.append(campaign_id)
    with db_cursor() as cur:
        cur.execute(f"UPDATE campaigns SET {', '.join(parts)} WHERE id = ?", vals)
    return get_campaign(campaign_id)


def delete_campaign(campaign_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
        return cur.rowcount > 0


def update_campaign_run_stats(campaign_id: int, run_id: int,
                               signals: int, companies: int):
    with db_cursor() as cur:
        cur.execute("""
            UPDATE campaigns SET
                last_run_at      = datetime('now'),
                last_run_id      = ?,
                total_signals    = total_signals + ?,
                total_companies  = total_companies + ?,
                updated_at       = datetime('now')
            WHERE id = ?
        """, (run_id, signals, companies, campaign_id))


def get_audit_logs_list(limit: int = 100, entity_type: str = None) -> list:
    with db_cursor(commit=False) as cur:
        if entity_type:
            cur.execute(
                "SELECT * FROM audit_logs WHERE entity_type = ? ORDER BY created_at DESC LIMIT ?",
                (entity_type, limit),
            )
        else:
            cur.execute(
                "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return cur.fetchall()


# ── Outcomes (the learning loop) — mirrors database.py ────────────────────────

def log_outcome(outcome: str, company: str = "", email: str = "",
                contact_id: int = None, campaign_id: int = None,
                notes: str = "", hook_id: int = None) -> dict:
    with db_cursor() as cur:
        resolved_company_id = None
        resolved_contact_id = contact_id
        if company:
            cur.execute("SELECT id FROM companies WHERE LOWER(name) = LOWER(?)", (company.strip(),))
            row = cur.fetchone()
            if row:
                resolved_company_id = row["id"]
        if email and resolved_contact_id is None:
            cur.execute("SELECT id, company_id FROM company_contacts WHERE LOWER(email) = LOWER(?) LIMIT 1",
                        (email.strip(),))
            row = cur.fetchone()
            if row:
                resolved_contact_id = row["id"]
                if resolved_company_id is None:
                    resolved_company_id = row["company_id"]

        cur.execute("""
            INSERT INTO outcomes (company_id, contact_id, campaign_id, email, outcome, notes, hook_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (resolved_company_id, resolved_contact_id, campaign_id,
              email.strip(), outcome.strip(), notes.strip(), hook_id))
        new_id = cur.lastrowid
        cur.execute("SELECT * FROM outcomes WHERE id = ?", (new_id,))
        return dict(cur.fetchone())


def get_outcomes(limit: int = 200) -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT o.*, c.name AS company_name
            FROM outcomes o
            LEFT JOIN companies c ON c.id = o.company_id
            ORDER BY o.created_at DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_outcome_signal_rows() -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT o.id AS outcome_id, o.outcome,
                   s.signal_type, s.oracle_product, s.phase, s.source
            FROM outcomes o
            JOIN oracle_signals s ON s.company_id = o.company_id
        """)
        return [dict(r) for r in cur.fetchall()]


def get_outcome_totals() -> dict:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT outcome, COUNT(*) AS n FROM outcomes GROUP BY outcome")
        return {r["outcome"]: int(r["n"]) for r in cur.fetchall()}


def get_outcome_hook_rows() -> list:
    """Mirrors database.py — one row per outcome traced back to a campaign_hooks
    row, the input to angle/personalization-bucket attribution."""
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT o.id AS outcome_id, o.outcome,
                   ch.angle, ch.personalization_bucket, ch.personalization_label
            FROM outcomes o
            JOIN campaign_hooks ch ON ch.id = o.hook_id
            WHERE o.hook_id IS NOT NULL
        """)
        return [dict(r) for r in cur.fetchall()]


# ── Campaign hooks — mirrors database.py ──────────────────────────────────────

def save_campaign_hook(hook: dict, signal_summary: str = "",
                       product_context: str = "", icp_research: str = "") -> int:
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO campaign_hooks (
                contact_name, contact_email, contact_title, linkedin_url, company_name,
                signal_summary, product_context, icp_research,
                angle, subject, body, word_count,
                personalization_bucket, personalization_label,
                grounded, grounded_on, hold_back, ok, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            hook.get("contact_name", ""), hook.get("email", ""), hook.get("title", ""),
            hook.get("linkedin_url", ""), hook.get("company", ""),
            signal_summary, product_context, icp_research,
            hook.get("angle", ""), hook.get("subject", ""), hook.get("body", ""),
            hook.get("word_count", 0),
            hook.get("personalization_bucket"), hook.get("personalization_label", ""),
            int(bool(hook.get("grounded"))) if hook.get("grounded") is not None else None,
            hook.get("grounded_on", ""),
            int(bool(hook.get("hold_back", False))), int(bool(hook.get("ok", False))),
            hook.get("error") or "",
        ))
        return cur.lastrowid


def save_campaign_touches(hook_id: int, touches: list) -> None:
    if not touches:
        return
    with db_cursor() as cur:
        for t in touches:
            cur.execute("""
                INSERT INTO campaign_touches (hook_id, day, channel, subject, body, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (hook_id, t.get("day", 0), t.get("channel", ""),
                  t.get("subject", ""), t.get("body", ""), t.get("notes", "")))


def get_campaign_hook_stats() -> dict:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM campaign_hooks")
        total = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM campaign_hooks WHERE ok")
        ok = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM campaign_hooks WHERE hold_back")
        held_back = cur.fetchone()["n"]
        cur.execute("""
            SELECT angle, COUNT(*) AS n FROM campaign_hooks
            WHERE ok = 1 AND angle != '' GROUP BY angle ORDER BY n DESC
        """)
        by_angle = {r["angle"]: r["n"] for r in cur.fetchall()}
        cur.execute("""
            SELECT personalization_bucket AS bucket, COUNT(*) AS n FROM campaign_hooks
            WHERE personalization_bucket IS NOT NULL GROUP BY personalization_bucket ORDER BY bucket
        """)
        by_bucket = {r["bucket"]: r["n"] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) AS n FROM campaign_touches")
        touches = cur.fetchone()["n"]
    return {
        "total_hooks": total, "ok_hooks": ok, "held_back": held_back,
        "by_angle": by_angle, "by_bucket": by_bucket, "total_touches": touches,
    }


def get_recent_campaign_hooks(limit: int = 50) -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM campaign_hooks ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]


# ── ATS board registry (auto-discovery) — mirrors database.py ─────────────────

def upsert_ats_board(company: str, ats: str, token: str,
                     job_count: int = 0, verified: bool = False) -> None:
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO ats_boards (company, ats, token, job_count, verified)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (ats, token) DO UPDATE SET
                company   = CASE WHEN excluded.company != '' THEN excluded.company ELSE ats_boards.company END,
                job_count = excluded.job_count,
                verified  = CASE WHEN ats_boards.verified = 1 OR excluded.verified = 1 THEN 1 ELSE 0 END,
                is_active = 1
        """, (company.strip(), ats.strip(), token.strip(), int(job_count), 1 if verified else 0))


def get_ats_boards(active_only: bool = True) -> list:
    with db_cursor(commit=False) as cur:
        if active_only:
            cur.execute("SELECT * FROM ats_boards WHERE is_active = 1 ORDER BY job_count DESC")
        else:
            cur.execute("SELECT * FROM ats_boards ORDER BY job_count DESC")
        return [dict(r) for r in cur.fetchall()]
