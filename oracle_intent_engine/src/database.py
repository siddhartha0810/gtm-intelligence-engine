"""
database.py  (oracle_intent_engine)
=====================================
PostgreSQL backend for the entire Oracle Intent Engine.

PURPOSE:
  All persistent state for the Oracle Intent side of the tool lives here:
  companies, signals, contacts, scan runs, auth users, audit logs, events,
  technology profiles, and more.  This module owns the DDL (CREATE TABLE),
  the connection pool, and every read/write function.

HOW IT FITS IN THE SYSTEM:
  - unified_app.py imports this module and calls all db.* functions for
    Oracle Intent API endpoints.
  - enrichment_worker.py (and apollo_enrichment.py) call company_contacts
    write functions after enrichment completes.
  - scan_worker.py calls upsert_company() and upsert_signal() during scraping.

KEY CLASSES/FUNCTIONS:
  db_cursor(commit)         — context manager that borrows from the pool,
                              auto-commits or rolls back, then returns connection
  init_db()                 — creates tables if missing; called at startup
  upsert_company()          — inserts or updates a company row; maintains
                              denormalised signal_count via UPDATE after insert
  upsert_signal()           — inserts a signal and increments company.signal_count
  get_all_companies_with_signals() — main read for the companies tab
  upsert_company_contact()  — inserts/updates a contact; increments contact_count
  get_contacts_for_export() — returns contacts joined to company for CSV export

DEPENDENCIES:
  - psycopg2 (threaded connection pool, DictCursor)
  - Inoapps-Data-DB PostgreSQL on 10.0.0.149:5432
  - ORACLE_PG_DSN env var (set by unified_app.py at startup)

IMPORTANT:
  - Uses ThreadedConnectionPool(max=10) — never open more than 10 concurrent
    connections or the pool will block.
  - ORACLE_PG_DSN env var takes priority over DB_* vars so unified_app.py
    can cleanly separate oracle DB from the enrichment DB connection strings.
  - denormalized signal_count and contact_count on the companies table are
    maintained on every insert via UPDATE — never query COUNT(*) in hot paths.
"""

import os
import secrets
import threading
from contextlib import contextmanager
from typing import Optional
from src.utils import get_logger

def _gen_unique_key() -> str:
    """64-char URL-safe unique key (doc §6.1 — nanoid equivalent)."""
    return secrets.token_urlsafe(48)  # 48 bytes → 64-char base64url string

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = get_logger(__name__)

# ═══════════════════ CONNECTION POOL ═══════════════════════════════════════════
# ThreadedConnectionPool(max=10) — safe for up to 10 concurrent API request threads.
# The pool is created lazily on first use and held open for the process lifetime.
# ORACLE_PG_DSN env var takes priority over DB_* vars (set by unified_app.py at boot).
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
    global _pool
    with _pool_lock:
        if _pool and not _pool.closed:
            _pool.closeall()
            _pool = None

# ═══════════════════ DDL — TABLE DEFINITIONS ════════════════════════════════════
# All tables for the Oracle Intent Engine are created here via CREATE TABLE IF NOT EXISTS.
# init_db() runs these DDL statements at startup — safe to run repeatedly.
# Changing column types requires a separate migration script; never alter these in-place.
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
    # target_product: Oracle product this contact should be pitched (JD Edwards, Oracle Fusion, ...)
    # copied from the company's dominant signal at enrichment time.
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS target_product TEXT NOT NULL DEFAULT ''",
    # ready_for_outreach: Stage-7 scoring result — valid email OR catch-all + LinkedIn present.
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS ready_for_outreach BOOLEAN NOT NULL DEFAULT FALSE",
    # master_leads table intentionally removed — dropped 2026-06-08
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

    # NEW TABLES — Unified Platform Expansion (Phase 1-4)

    # users & rbac
    """
    CREATE TABLE IF NOT EXISTS users (
        id            BIGSERIAL PRIMARY KEY,
        email         TEXT NOT NULL UNIQUE,
        name          TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL DEFAULT '',
        role          TEXT NOT NULL DEFAULT 'analyst'
                          CHECK (role IN ('owner','admin','analyst','viewer','recruitment')),
        is_active     BOOLEAN NOT NULL DEFAULT TRUE,
        last_login    TIMESTAMPTZ,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_email  ON users(email)",
    "CREATE INDEX IF NOT EXISTS idx_users_role   ON users(role)",

    # technology profiles
    """
    CREATE TABLE IF NOT EXISTS technology_profiles (
        id                   BIGSERIAL PRIMARY KEY,
        name                 TEXT NOT NULL UNIQUE,
        description          TEXT NOT NULL DEFAULT '',
        keywords             TEXT[] NOT NULL DEFAULT '{}',
        target_websites      TEXT[] NOT NULL DEFAULT '{}',
        competitor_domains   TEXT[] NOT NULL DEFAULT '{}',
        partner_domains      TEXT[] NOT NULL DEFAULT '{}',
        manufacturer_domain  TEXT NOT NULL DEFAULT '',
        oracle_products      TEXT[] NOT NULL DEFAULT '{}',
        is_active            BOOLEAN NOT NULL DEFAULT TRUE,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tp_active ON technology_profiles(is_active)",

    # product taxonomy
    """
    CREATE TABLE IF NOT EXISTS product_taxonomy (
        id                    BIGSERIAL PRIMARY KEY,
        technology_profile_id BIGINT REFERENCES technology_profiles(id) ON DELETE CASCADE,
        canonical_name        TEXT NOT NULL,
        aliases               TEXT[] NOT NULL DEFAULT '{}',
        category              TEXT NOT NULL DEFAULT '',
        confidence_weight     REAL NOT NULL DEFAULT 1.0,
        is_active             BOOLEAN NOT NULL DEFAULT TRUE,
        created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (technology_profile_id, canonical_name)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pt_profile ON product_taxonomy(technology_profile_id)",

    # audit logs
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id           BIGSERIAL PRIMARY KEY,
        user_id      BIGINT REFERENCES users(id) ON DELETE SET NULL,
        user_email   TEXT NOT NULL DEFAULT '',
        action       TEXT NOT NULL,
        entity_type  TEXT NOT NULL,
        entity_id    TEXT NOT NULL DEFAULT '',
        old_value    JSONB,
        new_value    JSONB,
        ip_address   TEXT NOT NULL DEFAULT '',
        created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_al_entity    ON audit_logs(entity_type, entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_al_user      ON audit_logs(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_al_created   ON audit_logs(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_al_action    ON audit_logs(action)",

    # events intelligence
    """
    CREATE TABLE IF NOT EXISTS events (
        id                    BIGSERIAL PRIMARY KEY,
        name                  TEXT NOT NULL,
        event_type            TEXT NOT NULL DEFAULT 'conference'
                                  CHECK (event_type IN
                                    ('conference','webinar','workshop','roundtable',
                                     'trade_show','summit','other')),
        technology_profile_id BIGINT REFERENCES technology_profiles(id) ON DELETE SET NULL,
        location              TEXT NOT NULL DEFAULT '',
        event_date            DATE,
        description           TEXT NOT NULL DEFAULT '',
        attendee_count        INTEGER NOT NULL DEFAULT 0,
        created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_date    ON events(event_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_events_profile ON events(technology_profile_id)",
    """
    CREATE TABLE IF NOT EXISTS event_attendees (
        id         BIGSERIAL PRIMARY KEY,
        event_id   BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        contact_id BIGINT NOT NULL REFERENCES company_contacts(id) ON DELETE CASCADE,
        role       TEXT NOT NULL DEFAULT 'attendee'
                       CHECK (role IN ('attendee','speaker','organiser','sponsor')),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (event_id, contact_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ea_event   ON event_attendees(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_ea_contact ON event_attendees(contact_id)",

    # manufacturer intelligence
    """
    CREATE TABLE IF NOT EXISTS manufacturer_contacts (
        id                    BIGSERIAL PRIMARY KEY,
        first_name            TEXT NOT NULL DEFAULT '',
        last_name             TEXT NOT NULL DEFAULT '',
        email                 TEXT NOT NULL DEFAULT '',
        phone                 TEXT NOT NULL DEFAULT '',
        company               TEXT NOT NULL DEFAULT '',
        job_title             TEXT NOT NULL DEFAULT '',
        technology_profile_id BIGINT REFERENCES technology_profiles(id) ON DELETE SET NULL,
        oracle_alignment      TEXT NOT NULL DEFAULT '',
        oracle_department     TEXT NOT NULL DEFAULT '',
        oracle_team           TEXT NOT NULL DEFAULT '',
        linkedin_url          TEXT NOT NULL DEFAULT '',
        hubspot_id            TEXT NOT NULL DEFAULT '',
        source                TEXT NOT NULL DEFAULT '',
        created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mc_company  ON manufacturer_contacts(company)",
    "CREATE INDEX IF NOT EXISTS idx_mc_email    ON manufacturer_contacts(email)",
    "CREATE INDEX IF NOT EXISTS idx_mc_profile  ON manufacturer_contacts(technology_profile_id)",
    """
    CREATE TABLE IF NOT EXISTS manufacturer_links (
        id                      BIGSERIAL PRIMARY KEY,
        manufacturer_contact_id BIGINT NOT NULL REFERENCES manufacturer_contacts(id) ON DELETE CASCADE,
        company_id              BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        link_type               TEXT NOT NULL DEFAULT 'partner'
                                    CHECK (link_type IN ('partner','reseller','implementer','support','other')),
        created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (manufacturer_contact_id, company_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ml2_company ON manufacturer_links(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_ml2_mfr     ON manufacturer_links(manufacturer_contact_id)",

    # list import
    """
    CREATE TABLE IF NOT EXISTS import_mapping_templates (
        id          BIGSERIAL PRIMARY KEY,
        name        TEXT NOT NULL,
        entity_type TEXT NOT NULL CHECK (entity_type IN ('contact','company','event','manufacturer')),
        mappings    JSONB NOT NULL DEFAULT '{}',
        created_by  BIGINT REFERENCES users(id) ON DELETE SET NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (name, entity_type)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_imt_type ON import_mapping_templates(entity_type)",
    """
    CREATE TABLE IF NOT EXISTS import_batches (
        id                  BIGSERIAL PRIMARY KEY,
        file_name           TEXT NOT NULL,
        entity_type         TEXT NOT NULL CHECK (entity_type IN ('contact','company','event','manufacturer')),
        mapping_template_id BIGINT REFERENCES import_mapping_templates(id) ON DELETE SET NULL,
        status              TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','processing','completed','failed')),
        record_count        INTEGER NOT NULL DEFAULT 0,
        success_count       INTEGER NOT NULL DEFAULT 0,
        error_count         INTEGER NOT NULL DEFAULT 0,
        error_log           JSONB NOT NULL DEFAULT '[]',
        s3_key              TEXT NOT NULL DEFAULT '',
        created_by          BIGINT REFERENCES users(id) ON DELETE SET NULL,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at        TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ib_status ON import_batches(status)",
    "CREATE INDEX IF NOT EXISTS idx_ib_type   ON import_batches(entity_type)",
    "CREATE INDEX IF NOT EXISTS idx_ib_user   ON import_batches(created_by)",

    # MIGRATIONS — Expand existing tables with new columns
    # All use ADD COLUMN IF NOT EXISTS — safe to run on existing DBs

    # companies: add 27 hubspot mvp fields + lifecycle + profile link
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS technology_profile_id  BIGINT REFERENCES technology_profiles(id) ON DELETE SET NULL",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS status                 TEXT NOT NULL DEFAULT 'staged' CHECK (status IN ('staged','pending_review','approved','pushed_to_hubspot','rejected'))",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS unique_key             TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS hubspot_id             TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS hubspot_synced_at      TIMESTAMPTZ",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS source                 TEXT NOT NULL DEFAULT 'scan'",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS company_type           TEXT NOT NULL DEFAULT 'prospect'",
    # HubSpot Company Information
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS phone                  TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS number_of_employees    INTEGER",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS about_us               TEXT NOT NULL DEFAULT ''",
    # HubSpot Billing Address
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS billing_street         TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS billing_city           TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS billing_state          TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS billing_postal_code    TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS billing_country        TEXT NOT NULL DEFAULT ''",
    # HubSpot Company Information (Custom)
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS duns_number            TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS holding_type           TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS number_of_locations    INTEGER",
    # HubSpot Oracle / Products
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS oracle_solutions_summary     TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS oracle_cloud_solutions       TEXT[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS oracle_on_premise_solutions  TEXT[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS oracle_relationship_type     TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS oracle_support_end_date      DATE",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS oracle_version               TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS number_of_oracle_users       INTEGER",
    # HubSpot Inoapps Relationship
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS inoapps_account_manager      TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS inoapps_account_tier         TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS inoapps_relationship_type    TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS inoapps_services_summary     TEXT NOT NULL DEFAULT ''",
    # Marketing product target — manually set or auto-derived from signals
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS target_product               TEXT NOT NULL DEFAULT ''",
    # Internal computed/enrichment fields
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS detected_products            TEXT[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS product_confidence_scores    JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS enrichment_data              JSONB NOT NULL DEFAULT '{}'",

    # company_contacts: add 22 hubspot mvp fields + lifecycle
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS salutation           TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS suffix               TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS phone                TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS mobile_phone         TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS job_function         TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS level                TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS city                 TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS state                TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS country              TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS do_not_call          BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS do_not_email         BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS creation_source      TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS person_has_moved     BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS oracle_alignment      TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS oracle_department     TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS oracle_team          TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS hubspot_id           TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS unique_key           TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS status               TEXT NOT NULL DEFAULT 'staged' CHECK (status IN ('staged','pending_review','approved','pushed_to_hubspot','rejected'))",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS hubspot_synced_at    TIMESTAMPTZ",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS street               TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS postal_code          TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS domain               TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS industry             TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE company_contacts ADD COLUMN IF NOT EXISTS location             TEXT NOT NULL DEFAULT ''",

    # scan_runs: link to technology profile
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS technology_profile_id BIGINT REFERENCES technology_profiles(id) ON DELETE SET NULL",

    # denormalized signal/contact counts for fast order by
    # These avoid full aggregation scans on every page load.
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS signal_count  INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS contact_count INTEGER NOT NULL DEFAULT 0",

    # indexes on new columns
    "CREATE INDEX IF NOT EXISTS idx_companies_status       ON companies(status)",
    "CREATE INDEX IF NOT EXISTS idx_companies_profile      ON companies(technology_profile_id)",
    "CREATE INDEX IF NOT EXISTS idx_companies_hubspot      ON companies(hubspot_id) WHERE hubspot_id != ''",
    "CREATE INDEX IF NOT EXISTS idx_companies_signal_count ON companies(signal_count DESC, last_updated DESC)",
    "CREATE INDEX IF NOT EXISTS idx_contacts_status        ON company_contacts(status)",
    "CREATE INDEX IF NOT EXISTS idx_contacts_hubspot       ON company_contacts(hubspot_id) WHERE hubspot_id != ''",

    # hubspot_config table
    """
CREATE TABLE IF NOT EXISTS hubspot_config (
    id              BIGSERIAL PRIMARY KEY,
    api_key         TEXT NOT NULL DEFAULT '',
    portal_id       TEXT NOT NULL DEFAULT '',
    sync_status     TEXT NOT NULL DEFAULT 'idle'
                        CHECK (sync_status IN ('idle','running','error','success')),
    last_sync_at    TIMESTAMPTZ,
    companies_synced INT NOT NULL DEFAULT 0,
    contacts_synced  INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
""",
    # engine_configs table
    """
CREATE TABLE IF NOT EXISTS engine_configs (
    id                  BIGSERIAL PRIMARY KEY,
    engine_type         TEXT NOT NULL UNIQUE
                            CHECK (engine_type IN (
                                'scraping','enrichment','skills_parsing',
                                'fuzzy_matching','data_quality','hubspot_sync'
                            )),
    is_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    schedule_expression TEXT NOT NULL DEFAULT '0 2 * * *',
    last_run_status     TEXT,
    last_run_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
""",
    # review_queue table (proper separate table per design doc)
    """
CREATE TABLE IF NOT EXISTS review_queue (
    id           BIGSERIAL PRIMARY KEY,
    entity_type  TEXT NOT NULL CHECK (entity_type IN ('company','contact')),
    entity_id    BIGINT NOT NULL,
    issue_type   TEXT NOT NULL CHECK (issue_type IN (
                     'duplicate','data_quality','conflict',
                     'enrichment_conflict','missing_mandatory_field','fuzzy_match'
                 )),
    severity     TEXT NOT NULL DEFAULT 'warning'
                     CHECK (severity IN ('critical','warning','info')),
    status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','rejected','auto_resolved')),
    issue_detail JSONB,
    notes        TEXT,
    resolved_by  TEXT,
    resolved_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
""",
    "CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status)",
    "CREATE INDEX IF NOT EXISTS idx_review_queue_entity ON review_queue(entity_type, entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_engine_configs_type ON engine_configs(engine_type)",
]

# core context manager
@contextmanager
def db_cursor(commit: bool = True):
    """
    Context manager: borrow a connection from the pool, yield a RealDictCursor,
    then commit (or rollback on exception) and return the connection to the pool.

    Args:
        commit: If True (default), commit after the with block exits cleanly.
                Pass False for read-only queries to skip the unnecessary commit.

    Usage:
        with db_cursor() as cur:
            cur.execute("INSERT INTO companies (name) VALUES (%s)", ("Acme",))
        # auto-committed here

    Raises:
        psycopg2.Error: Re-raised after rollback if the query fails.
    """
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

# ═══════════════════ SCHEMA INIT ════════════════════════════════════════════════
def init_db():
    """
    Create all tables if they do not exist, then run one-time backfills.
    Safe to call on every startup — uses CREATE TABLE IF NOT EXISTS.
    Called by unified_app.py lifespan() at server boot.
    """
    with db_cursor() as cur:
        for stmt in _DDL:
            cur.execute(stmt)
    logger.info("PostgreSQL schema initialised")
    _backfill_unique_keys()
    _backfill_signal_counts()

def _backfill_unique_keys():
    """One-time backfill: assign unique_key to any existing rows that have an empty value."""
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM companies WHERE unique_key = ''")
        co_missing = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM company_contacts WHERE unique_key = ''")
        cc_missing = cur.fetchone()["n"]

    if co_missing == 0 and cc_missing == 0:
        return

    with db_cursor() as cur:
        if co_missing:
            cur.execute("SELECT id FROM companies WHERE unique_key = ''")
            ids = [r["id"] for r in cur.fetchall()]
            for cid in ids:
                cur.execute(
                    "UPDATE companies SET unique_key = %s WHERE id = %s",
                    (_gen_unique_key(), cid),
                )
            logger.info("Backfilled unique_key for %d companies", co_missing)

        if cc_missing:
            cur.execute("SELECT id FROM company_contacts WHERE unique_key = ''")
            ids = [r["id"] for r in cur.fetchall()]
            for cid in ids:
                cur.execute(
                    "UPDATE company_contacts SET unique_key = %s WHERE id = %s",
                    (_gen_unique_key(), cid),
                )
            logger.info("Backfilled unique_key for %d contacts", cc_missing)

def _backfill_signal_counts() -> None:
    """Sync denormalized signal_count / contact_count for any company that has 0
    but actually has rows — happens on first boot after the columns were added."""
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT COUNT(*) AS n FROM companies c
            WHERE c.signal_count = 0
              AND EXISTS (SELECT 1 FROM oracle_signals s WHERE s.company_id = c.id)
        """)
        need_backfill = cur.fetchone()["n"]

    if need_backfill == 0:
        return

    logger.info("Backfilling signal_count / contact_count for %d companies …", need_backfill)
    with db_cursor() as cur:
        cur.execute("""
            UPDATE companies c
            SET signal_count  = COALESCE(s.cnt, 0),
                contact_count = COALESCE(cc.cnt, 0)
            FROM (
                SELECT company_id, COUNT(*) AS cnt
                FROM oracle_signals
                GROUP BY company_id
            ) s
            LEFT JOIN (
                SELECT company_id, COUNT(*) AS cnt
                FROM company_contacts
                WHERE email IS NOT NULL AND email != ''
                GROUP BY company_id
            ) cc ON cc.company_id = s.company_id
            WHERE s.company_id = c.id
              AND c.signal_count = 0
        """)
        logger.info("signal_count / contact_count backfill complete")

# company operations
def upsert_company(name: str, domain: str = None, industry: str = None,
                   size: str = None, location: str = None, website: str = None,
                   first_scan_run_id: int = None) -> int:
    """
    Insert a new company or update an existing one (matched on unique name).

    Uses COALESCE on all nullable fields so existing non-NULL values are never
    overwritten by a new NULL from a later scan run.  Only the first scan's data
    wins for each field; subsequent scans only update last_updated.

    Returns:
        The company's database ID (whether newly inserted or existing).
    """
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO companies (name, domain, industry, size, location, website,
                                   first_scan_run_id, unique_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                domain            = COALESCE(companies.domain,    EXCLUDED.domain),
                industry          = COALESCE(companies.industry,  EXCLUDED.industry),
                size              = COALESCE(companies.size,      EXCLUDED.size),
                location          = COALESCE(companies.location,  EXCLUDED.location),
                website           = COALESCE(companies.website,   EXCLUDED.website),
                unique_key        = CASE
                    WHEN companies.unique_key = '' THEN EXCLUDED.unique_key
                    ELSE companies.unique_key
                END,
                last_updated      = NOW()
            RETURNING id
        """, (name, domain, industry, size, location, website,
              first_scan_run_id, _gen_unique_key()))
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

# ═══════════════════ SIGNAL OPERATIONS ══════════════════════════════════════════
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
        signal_id = cur.fetchone()["id"]
        # Keep denormalized count in sync
        cur.execute("""
            UPDATE companies
            SET signal_count = (SELECT COUNT(*) FROM oracle_signals WHERE company_id = %s),
                last_updated = NOW()
            WHERE id = %s
        """, (company_id, company_id))
        return signal_id

def get_signals_for_company(company_id: int):
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT * FROM oracle_signals
            WHERE company_id = %s
            ORDER BY detected_at DESC
        """, (company_id,))
        return cur.fetchall()

# scan run tracking
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


def purge_scan_companies(run_id: int) -> int:
    """Delete all companies first discovered in the given scan run.

    Signals and contacts cascade automatically (ON DELETE CASCADE).
    Returns the number of companies deleted.
    """
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM companies WHERE first_scan_run_id = %s RETURNING id",
            (run_id,),
        )
        return len(cur.fetchall())

# contact operations
def save_contacts(company_id: int, contacts: list):
    with db_cursor() as cur:
        # Backfill company domain from Apollo contact data if missing
        if contacts:
            apollo_domain = next(
                (c.get("domain", "").strip().lower() for c in contacts
                 if c.get("domain", "").strip() and c.get("source") == "apollo"),
                ""
            )
            if apollo_domain:
                cur.execute("""
                    UPDATE companies SET domain = %s
                    WHERE id = %s AND (domain IS NULL OR domain = '')
                """, (apollo_domain, company_id))

        for c in contacts:
            cur.execute("""
                INSERT INTO company_contacts
                    (company_id, full_name, first_name, last_name, title,
                     email, linkedin_url, seniority, confidence, is_target, source,
                     email_validation_status, email_source, email_prediction_pattern,
                     phone, street, city, state, country, postal_code,
                     unique_key, target_product, ready_for_outreach,
                     domain, industry, location)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (company_id, email) WHERE email IS NOT NULL AND email != '' DO UPDATE SET
                    target_product = CASE WHEN EXCLUDED.target_product <> '' THEN EXCLUDED.target_product
                                          ELSE company_contacts.target_product END,
                    ready_for_outreach = EXCLUDED.ready_for_outreach OR company_contacts.ready_for_outreach,
                    title      = CASE WHEN EXCLUDED.title <> '' THEN EXCLUDED.title
                                      ELSE company_contacts.title END,
                    linkedin_url = COALESCE(NULLIF(EXCLUDED.linkedin_url,''), company_contacts.linkedin_url),
                    seniority  = CASE WHEN EXCLUDED.seniority <> '' THEN EXCLUDED.seniority
                                      ELSE company_contacts.seniority END,
                    confidence = GREATEST(EXCLUDED.confidence, company_contacts.confidence),
                    source     = CASE WHEN EXCLUDED.source IN ('apollo','apollo.io')
                                      THEN EXCLUDED.source ELSE company_contacts.source END,
                    email_validation_status = COALESCE(NULLIF(EXCLUDED.email_validation_status,''),
                                                       company_contacts.email_validation_status, ''),
                    is_target  = GREATEST(EXCLUDED.is_target, company_contacts.is_target),
                    phone      = CASE WHEN EXCLUDED.phone <> '' THEN EXCLUDED.phone
                                      ELSE company_contacts.phone END,
                    street     = CASE WHEN EXCLUDED.street <> '' THEN EXCLUDED.street
                                      ELSE company_contacts.street END,
                    city       = CASE WHEN EXCLUDED.city <> '' THEN EXCLUDED.city
                                      ELSE company_contacts.city END,
                    state      = CASE WHEN EXCLUDED.state <> '' THEN EXCLUDED.state
                                      ELSE company_contacts.state END,
                    country    = CASE WHEN EXCLUDED.country <> '' THEN EXCLUDED.country
                                      ELSE company_contacts.country END,
                    postal_code = CASE WHEN EXCLUDED.postal_code <> '' THEN EXCLUDED.postal_code
                                       ELSE company_contacts.postal_code END,
                    domain     = CASE WHEN EXCLUDED.domain <> '' THEN EXCLUDED.domain
                                      ELSE company_contacts.domain END,
                    industry   = CASE WHEN EXCLUDED.industry <> '' THEN EXCLUDED.industry
                                      ELSE company_contacts.industry END,
                    location   = CASE WHEN EXCLUDED.location <> '' THEN EXCLUDED.location
                                      ELSE company_contacts.location END
            """, (
                company_id,
                c.get("full_name", ""),
                c.get("first_name", ""),
                c.get("last_name", ""),
                c.get("title") or c.get("job_title") or "",
                c.get("email", "") or None,
                c.get("linkedin_url", "") or None,
                c.get("seniority", ""),
                float(c.get("confidence", 0)),
                int(bool(c.get("is_target", False))),
                c.get("source", "apollo"),
                c.get("email_validation_status") or "",
                c.get("email_source", "") or "",
                c.get("email_prediction_pattern", "") or "",
                c.get("phone", "") or "",
                c.get("street", "") or "",
                c.get("city", "") or "",
                c.get("state", "") or "",
                c.get("country", "") or "",
                c.get("postal_code", "") or "",
                _gen_unique_key(),
                c.get("target_product", "") or "",
                bool(c.get("ready_for_outreach", False)),
                c.get("domain", "") or "",
                c.get("industry", "") or "",
                c.get("location", "") or "",
            ))
        # Keep denormalized contact_count in sync after batch insert
        cur.execute("""
            UPDATE companies
            SET contact_count = (
                SELECT COUNT(*) FROM company_contacts
                WHERE company_id = %s AND email IS NOT NULL AND email != ''
            )
            WHERE id = %s
        """, (company_id, company_id))

def get_companies_needing_enrichment(limit: int = 50, company_ids: list = None) -> list:
    """Return companies needing enrichment — signal-backed first, then CSV imports.

    company_ids: optional explicit selection — only these companies are returned.
                 When provided, skips the "no contacts" filter so already-enriched
                 companies can be re-enriched (e.g. to predict missing emails).
    """
    if company_ids:
        # Explicit selection: always process, regardless of existing contacts
        where_clause = "WHERE c.id = ANY(%s)"
        params: tuple = (company_ids, limit)
    else:
        # Auto selection: only pick companies that have no contacts yet
        where_clause = """WHERE NOT EXISTS (
                SELECT 1 FROM company_contacts cc WHERE cc.company_id = c.id
            )"""
        params = (limit,)

    with db_cursor(commit=False) as cur:
        cur.execute(f"""
            SELECT c.id, c.name, c.domain,
                   COALESCE(NULLIF(c.target_product, ''), sig.top_product, '') AS target_product,
                   COALESCE(sig.signal_count, 0) AS signal_count
            FROM companies c
            LEFT JOIN (
                SELECT company_id,
                       COUNT(*) AS signal_count,
                       (ARRAY_AGG(oracle_product ORDER BY confidence DESC NULLS LAST))[1] AS top_product
                FROM oracle_signals
                GROUP BY company_id
            ) sig ON sig.company_id = c.id
            {where_clause}
            ORDER BY signal_count DESC, c.last_updated DESC
            LIMIT %s
        """, params)
        return cur.fetchall()

def get_company_ids_by_names(names: list) -> list:
    """Resolve company names → ids (used after list import to auto-enrich)."""
    if not names:
        return []
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT id FROM companies WHERE name = ANY(%s)", (names,))
        return [row["id"] for row in cur.fetchall()]


def get_all_company_names() -> list[str]:
    """Return all company names in the DB — used for fuzzy dedup during import."""
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT name FROM companies WHERE name IS NOT NULL ORDER BY name")
        return [row["name"] for row in cur.fetchall()]


def find_existing_contact(
    email: str = "",
    linkedin_url: str = "",
    first_name: str = "",
    last_name: str = "",
) -> Optional[dict]:
    """
    Check company_contacts for an existing record matching by email,
    linkedin_url, or first+last name.  Returns the first match, or None.
    Used as a pre-check before spending Apollo/ZeroBounce credits on import.
    """
    try:
        with db_cursor(commit=False) as cur:
            if email:
                cur.execute(
                    "SELECT first_name, last_name, title, email, linkedin_url,"
                    "       email_validation_status AS validation_status, email_source"
                    " FROM company_contacts"
                    " WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                    (email.strip(),),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)
            if linkedin_url:
                cur.execute(
                    "SELECT first_name, last_name, title, email, linkedin_url,"
                    "       email_validation_status AS validation_status, email_source"
                    " FROM company_contacts"
                    " WHERE linkedin_url = %s LIMIT 1",
                    (linkedin_url.strip(),),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)
            if first_name and last_name:
                cur.execute(
                    "SELECT first_name, last_name, title, email, linkedin_url,"
                    "       email_validation_status AS validation_status, email_source"
                    " FROM company_contacts"
                    " WHERE LOWER(first_name) = LOWER(%s) AND LOWER(last_name) = LOWER(%s)"
                    " LIMIT 1",
                    (first_name.strip(), last_name.strip()),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)
    except Exception as e:
        logger.debug(f"find_existing_contact failed: {e}")
    return None


def get_contacts_master_match(
    email: str = "",
    linkedin_url: str = "",
    first_name: str = "",
    last_name: str = "",
) -> Optional[dict]:
    """
    Check contacts_master (Salesforce CRM export) for a matching contact.
    Tries email, then linkedin_url, then first+last name.
    Returns a normalised dict with keys: email, linkedin_url, job_title, validation_status.
    Returns None if no match or table is absent.
    READ-ONLY — never writes to contacts_master.
    """
    try:
        with db_cursor(commit=False) as cur:
            sel = _build_cm_select(cur)
            email_col = _cm_col(cur, 'email')
            val_email_col = _cm_col(cur, 'validated_email')
            fn_col = _cm_col(cur, 'firstname')
            ln_col = _cm_col(cur, 'lastname')
            li_col = (
                f"COALESCE(NULLIF({_cm_col(cur, 'linkedin_url__c')},''::text),"
                f"NULLIF({_cm_col(cur, 'linkedin_url_enriched')},''::text))"
            )

            def _first(query: str, params: tuple) -> Optional[dict]:
                cur.execute(query, params)
                row = cur.fetchone()
                return dict(row) if row else None

            if email:
                hit = _first(
                    f"SELECT {sel} FROM contacts_master"
                    f" WHERE LOWER(COALESCE(NULLIF({val_email_col},''::text),NULLIF({email_col},''::text)))"
                    f"     = LOWER(%s) LIMIT 1",
                    (email.strip(),),
                )
                if hit:
                    return hit

            if linkedin_url:
                hit = _first(
                    f"SELECT {sel} FROM contacts_master"
                    f" WHERE {li_col} = %s LIMIT 1",
                    (linkedin_url.strip(),),
                )
                if hit:
                    return hit

            if first_name and last_name:
                hit = _first(
                    f"SELECT {sel} FROM contacts_master"
                    f" WHERE LOWER({fn_col}) = LOWER(%s)"
                    f"   AND LOWER({ln_col}) = LOWER(%s) LIMIT 1",
                    (first_name.strip(), last_name.strip()),
                )
                if hit:
                    return hit
    except Exception as e:
        logger.debug(f"get_contacts_master_match failed (contacts_master unavailable): {e}")
    return None


def get_enrichment_stats() -> dict:
    """Return counts for the enrichment dashboard."""
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM companies)                                       AS total_companies,
                (SELECT COUNT(DISTINCT company_id) FROM company_contacts)              AS enriched_companies,
                (SELECT COUNT(*) FROM companies c
                 WHERE NOT EXISTS (
                     SELECT 1 FROM company_contacts cc WHERE cc.company_id = c.id
                 ))                                                                    AS pending_companies,
                (SELECT COUNT(*) FROM company_contacts)                                AS total_contacts,
                (SELECT COUNT(*) FROM company_contacts
                 WHERE email IS NOT NULL AND email != '')                              AS with_email,
                (SELECT COUNT(*) FROM company_contacts
                 WHERE email_validation_status = 'valid')                              AS valid_email
        """)
        row = cur.fetchone()
        return {
            "total_companies":      row["total_companies"],
            "enriched_companies":   row["enriched_companies"],
            "pending_companies":    row["pending_companies"],
            "total_contacts":       row["total_contacts"],
            "contacts_with_email":  row["with_email"],
            "contacts_valid_email": row["valid_email"],
        }

# product intelligence aggregation
# Products that are primarily cloud-delivered
_CLOUD_PRODUCTS = {
    "Oracle Cloud ERP", "Oracle HCM", "Oracle SCM", "Oracle EPM",
    "Oracle CX", "NetSuite", "Oracle OCI", "Oracle Integration",
}
# Products that are primarily on-premise / legacy
_ONPREM_PRODUCTS = {
    "JD Edwards", "Oracle Database", "Oracle APEX",
}
# Products that can be either (treated as cloud for classification)
_BOTH_PRODUCTS = {
    "Oracle Database",  # can be cloud-hosted too
}

def aggregate_product_intel() -> dict:
    """
    Read oracle_signals grouped by company, classify products as Cloud or On-Premise,
    and write back to companies.oracle_cloud_solutions / oracle_on_premise_solutions /
    detected_products / product_confidence_scores.

    Returns {"updated": N, "companies_processed": N}.
    """
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT company_id,
                   oracle_product,
                   MAX(confidence) AS max_conf,
                   COUNT(*)        AS signal_count
            FROM oracle_signals
            WHERE oracle_product IS NOT NULL AND oracle_product <> ''
            GROUP BY company_id, oracle_product
        """)
        rows = cur.fetchall()

    # Build per-company product maps
    from collections import defaultdict
    company_products: dict = defaultdict(lambda: {"cloud": set(), "onprem": set(), "scores": {}})
    for row in rows:
        cid     = row["company_id"]
        product = row["oracle_product"]
        conf    = float(row["max_conf"] or 0)
        company_products[cid]["scores"][product] = round(conf, 3)
        if product in _ONPREM_PRODUCTS and product not in _CLOUD_PRODUCTS:
            company_products[cid]["onprem"].add(product)
        else:
            company_products[cid]["cloud"].add(product)

    updated = 0
    import json as _json
    with db_cursor(commit=True) as cur:
        # Step 1: Update companies that have signal data
        for cid, data in company_products.items():
            cloud  = sorted(data["cloud"])
            onprem = sorted(data["onprem"])
            all_p  = sorted(data["cloud"] | data["onprem"])
            scores = data["scores"]
            cur.execute("""
                UPDATE companies
                   SET oracle_cloud_solutions      = %s,
                       oracle_on_premise_solutions = %s,
                       detected_products           = %s,
                       product_confidence_scores   = %s
                 WHERE id = %s
            """, (cloud, onprem, all_p, _json.dumps(scores), cid))
            updated += 1

        # Step 2: For all remaining companies with a target_product but no
        # signal-derived product data, auto-populate from target_product
        cur.execute("""
            SELECT id, target_product
            FROM companies
            WHERE target_product IS NOT NULL AND target_product <> ''
              AND (
                (detected_products IS NULL OR cardinality(detected_products) = 0)
                OR (
                    cardinality(oracle_cloud_solutions) = 0
                    AND cardinality(oracle_on_premise_solutions) = 0
                )
              )
        """)
        fallback_rows = cur.fetchall()
        for row in fallback_rows:
            product = row["target_product"]
            is_onprem = product in _ONPREM_PRODUCTS and product not in _CLOUD_PRODUCTS
            cloud_arr  = [] if is_onprem else [product]
            onprem_arr = [product] if is_onprem else []
            cur.execute("""
                UPDATE companies
                   SET oracle_cloud_solutions      = %s,
                       oracle_on_premise_solutions = %s,
                       detected_products           = CASE
                           WHEN cardinality(detected_products) = 0 OR detected_products IS NULL
                           THEN %s ELSE detected_products END
                 WHERE id = %s
            """, (cloud_arr, onprem_arr, [product], row["id"]))
            updated += 1

    return {"updated": updated, "companies_processed": len(company_products) + len(fallback_rows)}

def backfill_target_product() -> int:
    """Set target_product from the dominant oracle_signal product for companies that have none."""
    with db_cursor() as cur:
        cur.execute("""
            UPDATE companies c
            SET    target_product = sub.top_product
            FROM (
                SELECT DISTINCT ON (company_id)
                       company_id,
                       oracle_product AS top_product
                FROM   oracle_signals
                WHERE  oracle_product IS NOT NULL
                  AND  oracle_product NOT IN ('', 'Oracle (General)')
                GROUP  BY company_id, oracle_product
                ORDER  BY company_id, COUNT(*) DESC
            ) sub
            WHERE sub.company_id = c.id
              AND (c.target_product IS NULL OR c.target_product = '')
        """)
        return cur.rowcount

def set_company_target_product(company_id: int, product: str) -> None:
    with db_cursor() as cur:
        cur.execute(
            "UPDATE companies SET target_product = %s WHERE id = %s",
            (product.strip(), company_id),
        )

def set_company_domain(company_id: int, domain: str) -> None:
    """Save a domain resolved during enrichment (only fills if currently empty)."""
    with db_cursor() as cur:
        cur.execute(
            """UPDATE companies SET domain = %s
               WHERE id = %s AND (domain IS NULL OR domain = '')""",
            (domain.strip().lower(), company_id),
        )

def delete_company(company_id: int) -> bool:
    """Hard-delete one company. Signals and contacts cascade (ON DELETE CASCADE)."""
    with db_cursor() as cur:
        cur.execute("DELETE FROM companies WHERE id = %s", (company_id,))
        return cur.rowcount > 0

def merge_companies(keep_id: int, drop_id: int) -> dict:
    """
    Merge drop_id into keep_id:
      - Reassign all signals from drop_id → keep_id (skip exact-URL dupes)
      - Reassign contacts from drop_id → keep_id (skip duplicate linkedin_url)
      - Backfill any missing fields on the kept company from the dropped one
      - Delete the dropped company
    Returns {"signals_moved": N, "contacts_moved": N}.
    """
    with db_cursor() as cur:
        # Move signals (ignore exact duplicates by source_url)
        cur.execute("""
            UPDATE oracle_signals SET company_id = %s
            WHERE company_id = %s
              AND url NOT IN (
                  SELECT url FROM oracle_signals WHERE company_id = %s AND url IS NOT NULL
              )
        """, (keep_id, drop_id, keep_id))
        signals_moved = cur.rowcount

        # Move contacts (skip duplicates by linkedin_url when present)
        cur.execute("""
            UPDATE company_contacts SET company_id = %s
            WHERE company_id = %s
              AND (linkedin_url IS NULL OR linkedin_url = ''
                   OR linkedin_url NOT IN (
                       SELECT linkedin_url FROM company_contacts
                       WHERE company_id = %s AND linkedin_url IS NOT NULL AND linkedin_url != ''
                   ))
        """, (keep_id, drop_id, keep_id))
        contacts_moved = cur.rowcount

        # Backfill missing fields on the kept company from the dropped one
        cur.execute("""
            UPDATE companies k
            SET
                domain   = COALESCE(NULLIF(k.domain, ''),   d.domain),
                industry = COALESCE(NULLIF(k.industry, ''), d.industry),
                location = COALESCE(NULLIF(k.location, ''), d.location),
                website  = COALESCE(NULLIF(k.website, ''),  d.website)
            FROM companies d
            WHERE k.id = %s AND d.id = %s
        """, (keep_id, drop_id))

        # Sync contact_count on the kept company
        cur.execute("""
            UPDATE companies SET contact_count = (
                SELECT COUNT(*) FROM company_contacts
                WHERE company_id = %s AND email IS NOT NULL AND email != ''
            ) WHERE id = %s
        """, (keep_id, keep_id))

        # Delete the duplicate (remaining orphan signals/contacts cascade)
        cur.execute("DELETE FROM companies WHERE id = %s", (drop_id,))

    return {"signals_moved": signals_moved, "contacts_moved": contacts_moved}

def delete_contact(contact_id: int) -> bool:
    """Hard-delete one contact and keep the company's contact_count in sync."""
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM company_contacts WHERE id = %s RETURNING company_id",
            (contact_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        cur.execute("""
            UPDATE companies
            SET contact_count = (
                SELECT COUNT(*) FROM company_contacts
                WHERE company_id = %s AND email IS NOT NULL AND email != ''
            )
            WHERE id = %s
        """, (row["company_id"], row["company_id"]))
        return True

def get_contacts_for_company(company_id: int) -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT * FROM company_contacts
            WHERE company_id = %s
            ORDER BY is_target DESC, confidence DESC
        """, (company_id,))
        return cur.fetchall()

def get_contact_by_id(contact_id: int):
    with db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT * FROM company_contacts WHERE id = %s",
            (contact_id,)
        )
        return cur.fetchone()


def update_contact_email(
    contact_id: int,
    email: str,
    email_validation_status: str,
    email_source: str,
    ready_for_outreach: bool,
) -> None:
    with db_cursor() as cur:
        cur.execute("""
            UPDATE company_contacts
            SET email = %s,
                email_validation_status = %s,
                email_source = %s,
                ready_for_outreach = %s
            WHERE id = %s
        """, (email, email_validation_status, email_source, ready_for_outreach, contact_id))


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

# company + signals (read)
def get_all_companies_with_signals(run_id: int = None):
    if run_id is None:
        run_id = get_latest_completed_run_id()

    with db_cursor(commit=False) as cur:
        if run_id:
            # CTE approach: pre-aggregate signals and contacts once — eliminates
            # per-row correlated subqueries that caused O(n) extra round-trips.
            cur.execute("""
                WITH sig AS (
                    SELECT company_id,
                           COUNT(*)                                  AS signal_count,
                           STRING_AGG(DISTINCT oracle_product, ',')  AS products,
                           STRING_AGG(DISTINCT phase, ',')           AS phases,
                           STRING_AGG(DISTINCT source, ',')          AS sources,
                           MAX(confidence)                           AS max_confidence,
                           (ARRAY_AGG(url ORDER BY confidence DESC)
                            FILTER (WHERE url LIKE 'http%%'))[1]     AS source_url
                    FROM oracle_signals
                    WHERE scan_run_id = %s
                    GROUP BY company_id
                ),
                ct AS (
                    SELECT company_id, COUNT(*) AS contact_count
                    FROM company_contacts
                    WHERE email IS NOT NULL AND email != ''
                    GROUP BY company_id
                )
                SELECT
                    c.id, c.name, c.domain, c.industry, c.size,
                    c.location, c.website, c.first_seen::text AS first_seen,
                    c.first_scan_run_id, c.source AS import_source,
                    COALESCE(NULLIF(c.target_product,''), sig.products) AS target_product,
                    COALESCE(sig.signal_count, 0)   AS signal_count,
                    COALESCE(sig.products, '')       AS products,
                    COALESCE(sig.phases, '')         AS phases,
                    COALESCE(sig.sources, '')        AS sources,
                    sig.max_confidence,
                    sig.source_url,
                    COALESCE(ct.contact_count, 0)   AS contact_count
                FROM companies c
                JOIN sig ON sig.company_id = c.id
                LEFT JOIN ct ON ct.company_id = c.id
                WHERE c.first_scan_run_id = %s
                ORDER BY signal_count DESC, c.last_updated DESC
            """, (run_id, run_id))
        elif run_id == 0:
            # All companies (show_all=1): CTE approach — pre-aggregate once.
            cur.execute("""
                WITH sig AS (
                    SELECT company_id,
                           COUNT(*)                                  AS signal_count,
                           STRING_AGG(DISTINCT oracle_product, ',')  AS products,
                           STRING_AGG(DISTINCT phase, ',')           AS phases,
                           STRING_AGG(DISTINCT source, ',')          AS sources,
                           MAX(confidence)                           AS max_confidence,
                           (ARRAY_AGG(url ORDER BY confidence DESC)
                            FILTER (WHERE url LIKE 'http%%'))[1]     AS source_url
                    FROM oracle_signals
                    GROUP BY company_id
                ),
                ct AS (
                    SELECT company_id, COUNT(*) AS contact_count
                    FROM company_contacts
                    WHERE email IS NOT NULL AND email != ''
                    GROUP BY company_id
                )
                SELECT
                    c.id, c.name, c.domain, c.industry, c.size,
                    c.location, c.website, c.first_seen::text AS first_seen,
                    c.first_scan_run_id, c.source AS import_source,
                    COALESCE(NULLIF(c.target_product,''), sig.products) AS target_product,
                    COALESCE(sig.signal_count, 0)   AS signal_count,
                    COALESCE(sig.products, '')       AS products,
                    COALESCE(sig.phases, '')         AS phases,
                    COALESCE(sig.sources, '')        AS sources,
                    sig.max_confidence,
                    sig.source_url,
                    COALESCE(ct.contact_count, 0)   AS contact_count
                FROM companies c
                LEFT JOIN sig ON sig.company_id = c.id
                LEFT JOIN ct  ON ct.company_id  = c.id
                ORDER BY signal_count DESC, c.last_updated DESC
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

# ═══════════════════ CONTACTS_MASTER — READ-ONLY SALESFORCE EXPORT ══════════════
# contacts_master is populated by Salesforce exports and NEVER written to by this engine.
# All functions here are read-only.  upsert_master_leads() is a no-op for API compat.

_CM_COL_CACHE: dict | None = None

def _cm_col(cur, want_lower: str) -> str:
    """
    Return the properly-quoted column expression for contacts_master.
    Salesforce exports may use PascalCase ("FirstName") or lowercase.
    Queries information_schema once and caches the result.
    """
    global _CM_COL_CACHE
    if _CM_COL_CACHE is None:
        try:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'contacts_master'"
            )
            actual = {r[0].lower(): r[0] for r in cur.fetchall()}
            _CM_COL_CACHE = actual
        except Exception:
            _CM_COL_CACHE = {}
    actual = _CM_COL_CACHE
    # Look up case-insensitively; return quoted actual name, or NULL if absent
    name = actual.get(want_lower)
    return f'"{name}"' if name else "NULL"

def _build_cm_select(cur) -> str:
    """Build the SELECT column list for contacts_master using actual column names."""
    def col(want: str, alias: str) -> str:
        return f"{_cm_col(cur, want)} AS {alias}"

    linkedin = (
        f"COALESCE(NULLIF({_cm_col(cur, 'linkedin_url__c')},''::text), "
        f"NULLIF({_cm_col(cur, 'linkedin_url_enriched')},''::text))"
    )
    company_col = (
        f"COALESCE(NULLIF({_cm_col(cur, 'new_company')},''::text), "
        f"NULLIF({_cm_col(cur, 'existing_company')},''::text))"
    )
    email_col = (
        f"COALESCE(NULLIF({_cm_col(cur, 'validated_email')},''::text), "
        f"NULLIF({_cm_col(cur, 'email')},''::text))"
    )
    return f"""
        ctid::text                                AS lead_id,
        {col('firstname', 'first_name')},
        {col('lastname', 'last_name')},
        {col('title', 'job_title')},
        {email_col}                               AS email,
        {col('validated_email_status', 'email_validation_status')},
        {linkedin}                                AS linkedin_url,
        {col('domain', 'domain')},
        {company_col}                             AS company,
        {col('phone', 'phone')},
        {col('mailingstreet', 'street')},
        {col('mailingcity', 'city')},
        {col('mailingstate', 'state')},
        {col('mailingcountry', 'country')},
        {col('mailingpostalcode', 'postal_code')}
    """

def _cm_zb_filter(cur) -> str:
    col = _cm_col(cur, 'zb_valid_email')
    return f"UPPER(TRIM({col})) = 'YES'" if col != "NULL" else "TRUE"

def _cm_norm_expr(cur) -> str:
    new_co = _cm_col(cur, 'new_company')
    exist_co = _cm_col(cur, 'existing_company')
    coalesce = f"COALESCE({new_co}, {exist_co}, ''::text)"
    return (
        f"LOWER(REGEXP_REPLACE({coalesce},"
        f" '\\\\s+(llc|inc|ltd|corp|limited|plc|llp|gmbh|sa|ag|nv|bv|co)\\\\.?$',"
        f" '', 'i'))"
    )

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
    NO-OP — contacts_master is a read-only Salesforce export.

    This function exists for API compatibility with pg_master.py's PGMasterStore,
    which is also a no-op.  Never writes to contacts_master.  Returns 0 always.
    """
    return 0

def get_master_leads_by_email(emails: list) -> dict:
    """
    Look up contacts_master by email address (case-insensitive).
    Returns {email_lower: record_dict}. Returns {} if table absent or columns wrong.
    """
    if not emails:
        return {}
    clean = [e.lower().strip() for e in emails if e and e.strip()]
    if not clean:
        return {}
    try:
        with db_cursor(commit=False) as cur:
            sel = _build_cm_select(cur)
            email_col = _cm_col(cur, 'email')
            val_email_col = _cm_col(cur, 'validated_email')
            zb = _cm_zb_filter(cur)
            cur.execute(
                f"""
                SELECT {sel}
                FROM contacts_master
                WHERE LOWER(COALESCE(NULLIF({val_email_col},''::text),
                                     NULLIF({email_col},''::text))) = ANY(%s)
                  AND {zb}
                """,
                (clean,),
            )
            rows = cur.fetchall()
            return {dict(r)["email"].lower(): dict(r) for r in rows if dict(r).get("email")}
    except Exception as e:
        logger.debug(f"get_master_leads_by_email failed (contacts_master unavailable): {e}")
        return {}

def get_master_leads_by_company(company_normalized: str) -> list:
    """
    Return contacts from contacts_master for a given company name.
    Returns [] if table absent or columns mismatched.
    """
    norm = _norm_company(company_normalized)
    try:
        with db_cursor(commit=False) as cur:
            sel = _build_cm_select(cur)
            zb = _cm_zb_filter(cur)
            norm_expr = _cm_norm_expr(cur)
            val_status_col = _cm_col(cur, 'validated_email_status')
            cur.execute(
                f"""
                SELECT {sel}
                FROM contacts_master
                WHERE {norm_expr} = %s
                  AND {zb}
                ORDER BY
                    CASE {val_status_col}
                        WHEN 'valid'     THEN 0
                        WHEN 'catch-all' THEN 1
                        ELSE 2 END
                LIMIT 50
                """,
                (norm,),
            )
            return cur.fetchall()
    except Exception as e:
        logger.debug(f"get_master_leads_by_company failed (contacts_master unavailable): {e}")
        return []

def master_leads_stats() -> dict:
    """Row counts for contacts_master. Returns zeros if table absent."""
    try:
        with db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT
                    COUNT(*)                                                                             AS total,
                    COUNT(CASE WHEN COALESCE(zb_valid_email, validated_email, email, '') != '' THEN 1 END) AS with_email,
                    COUNT(CASE WHEN validated_email_status = 'valid'                           THEN 1 END) AS valid_email,
                    COUNT(CASE WHEN validated_email_status = 'valid'
                                AND (hasoptedoutemail IS NULL OR hasoptedoutemail = FALSE) THEN 1 END) AS ready
                FROM contacts_master
            """)
            row = cur.fetchone()
            return dict(row)
    except Exception as e:
        logger.error(f"master_leads_stats failed: {e}", exc_info=True)
        return {"total": 0, "with_email": 0, "valid_email": 0, "ready": 0}

# email pattern operations
def load_domain_patterns(domains: list = None) -> dict:
    """
    Load email naming patterns from the email_patterns reference table.

    If `domains` is given, only returns patterns for those domains (fast per-run
    lookup).  If None, loads ALL known domains (used to pre-cache at startup).

    Returns: { domain: [pattern1, pattern2, ...] }
    Patterns are ordered by sample_count DESC so the highest-evidence format
    comes first — that's the one the prediction engine tries first.
    """
    with db_cursor(commit=False) as cur:
        if domains:
            cur.execute(
                """SELECT domain, pattern
                   FROM email_patterns
                   WHERE domain = ANY(%s)
                   ORDER BY domain, sample_count DESC""",
                (list(domains),),
            )
        else:
            cur.execute(
                """SELECT domain, pattern
                   FROM email_patterns
                   ORDER BY domain, sample_count DESC"""
            )
        rows = cur.fetchall()

    result: dict = {}
    for r in rows:
        result.setdefault(r["domain"], []).append(r["pattern"])
    return result

def upsert_email_patterns(rows: list) -> int:
    """
    Bulk upsert (domain, pattern, sample_count) tuples into email_patterns.
    Uses GREATEST so live-validated counts are never downgraded by imports.
    Returns the number of rows processed.
    """
    if not rows:
        return 0
    with db_cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO email_patterns (domain, pattern, sample_count, last_seen_at)
               VALUES %s
               ON CONFLICT (domain, pattern) DO UPDATE SET
                   sample_count = GREATEST(email_patterns.sample_count, EXCLUDED.sample_count),
                   last_seen_at = NOW()""",
            [(r[0], r[1], r[2]) for r in rows],
            template="(%s, %s, %s, NOW())",
            page_size=500,
        )
    return len(rows)

def email_patterns_stats() -> dict:
    """Row counts for the email_patterns reference table."""
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS total_rows, COUNT(DISTINCT domain) AS domains FROM email_patterns")
        row = cur.fetchone()
        cur.execute("""
            SELECT pattern, COUNT(*) AS n, SUM(sample_count) AS total_samples
            FROM email_patterns
            GROUP BY pattern
            ORDER BY total_samples DESC
        """)
        dist = [dict(r) for r in cur.fetchall()]
    return {"total_rows": row["total_rows"], "domains": row["domains"], "distribution": dist}

# hubspot_config helpers
def get_hubspot_config() -> dict:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM hubspot_config ORDER BY id LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else {}

def upsert_hubspot_config(api_key: str, portal_id: str) -> dict:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO hubspot_config (api_key, portal_id)
               VALUES (%s, %s)
               ON CONFLICT DO NOTHING
               RETURNING *""",
            (api_key, portal_id),
        )
        row = cur.fetchone()
        if row:
            return dict(row)
        cur.execute(
            """UPDATE hubspot_config SET api_key=%s, portal_id=%s, updated_at=NOW()
               WHERE id=(SELECT id FROM hubspot_config ORDER BY id LIMIT 1)
               RETURNING *""",
            (api_key, portal_id),
        )
        row = cur.fetchone()
        return dict(row) if row else {}

def update_hubspot_sync_status(status: str, companies: int = 0, contacts: int = 0):
    with db_cursor() as cur:
        cur.execute(
            """UPDATE hubspot_config
               SET sync_status=%s, last_sync_at=NOW(),
                   companies_synced=%s, contacts_synced=%s, updated_at=NOW()
               WHERE id=(SELECT id FROM hubspot_config ORDER BY id LIMIT 1)""",
            (status, companies, contacts),
        )

# engine_configs helpers
def seed_engine_configs():
    """Seed default engine configs if not present."""
    engines = ['scraping','enrichment','skills_parsing','fuzzy_matching','data_quality','hubspot_sync']
    with db_cursor() as cur:
        for eng in engines:
            cur.execute(
                """INSERT INTO engine_configs (engine_type) VALUES (%s)
                   ON CONFLICT (engine_type) DO NOTHING""",
                (eng,),
            )

def list_engine_configs() -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM engine_configs ORDER BY engine_type")
        return [dict(r) for r in cur.fetchall()]

def update_engine_config(engine_type: str, is_enabled: bool = None,
                          schedule_expression: str = None,
                          last_run_status: str = None) -> dict:
    with db_cursor() as cur:
        if is_enabled is not None:
            cur.execute(
                "UPDATE engine_configs SET is_enabled=%s, updated_at=NOW() WHERE engine_type=%s",
                (is_enabled, engine_type),
            )
        if schedule_expression is not None:
            cur.execute(
                "UPDATE engine_configs SET schedule_expression=%s, updated_at=NOW() WHERE engine_type=%s",
                (schedule_expression, engine_type),
            )
        if last_run_status is not None:
            cur.execute(
                "UPDATE engine_configs SET last_run_status=%s, last_run_at=NOW(), updated_at=NOW() WHERE engine_type=%s",
                (last_run_status, engine_type),
            )
        cur.execute("SELECT * FROM engine_configs WHERE engine_type=%s", (engine_type,))
        return dict(cur.fetchone())

# review_queue helpers
def add_to_review_queue(entity_type: str, entity_id: int, issue_type: str,
                         severity: str = 'warning', issue_detail: dict = None) -> dict:
    import json
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO review_queue (entity_type, entity_id, issue_type, severity, issue_detail)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT DO NOTHING
               RETURNING *""",
            (entity_type, entity_id, issue_type, severity,
             json.dumps(issue_detail) if issue_detail else None),
        )
        row = cur.fetchone()
        return dict(row) if row else {}

def list_review_queue(status: str = None, entity_type: str = None,
                       limit: int = 100, offset: int = 0) -> list:
    with db_cursor(commit=False) as cur:
        wheres, params = [], []
        if status:
            wheres.append("rq.status=%s"); params.append(status)
        if entity_type:
            wheres.append("rq.entity_type=%s"); params.append(entity_type)
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        cur.execute(
            f"""SELECT rq.*,
                       CASE rq.entity_type
                           WHEN 'company' THEN c.name
                           WHEN 'contact' THEN CONCAT(cc.first_name,' ',cc.last_name)
                       END AS entity_name
                FROM review_queue rq
                LEFT JOIN companies c ON rq.entity_type='company' AND c.id=rq.entity_id
                LEFT JOIN company_contacts cc ON rq.entity_type='contact' AND cc.id=rq.entity_id
                {where_sql}
                ORDER BY rq.created_at DESC
                LIMIT %s OFFSET %s""",
            params + [limit, offset],
        )
        return [dict(r) for r in cur.fetchall()]

def resolve_review_queue_item(item_id: int, status: str,
                               notes: str = None, resolved_by: str = None) -> dict:
    with db_cursor() as cur:
        cur.execute(
            """UPDATE review_queue
               SET status=%s, notes=%s, resolved_by=%s,
                   resolved_at=NOW(), updated_at=NOW()
               WHERE id=%s RETURNING *""",
            (status, notes, resolved_by, item_id),
        )
        return dict(cur.fetchone())

def bulk_resolve_review_queue(item_ids: list, status: str, resolved_by: str = None):
    with db_cursor() as cur:
        cur.execute(
            """UPDATE review_queue
               SET status=%s, resolved_by=%s, resolved_at=NOW(), updated_at=NOW()
               WHERE id = ANY(%s)""",
            (status, resolved_by, item_ids),
        )
