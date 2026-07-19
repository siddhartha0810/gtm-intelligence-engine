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

import hashlib
import os
import secrets
import threading
from contextlib import contextmanager
from typing import Optional
from src.utils import get_logger

def _gen_unique_key() -> str:
    """64-char URL-safe unique key (doc §6.1 — nanoid equivalent)."""
    return secrets.token_urlsafe(48)  # 48 bytes → 64-char base64url string

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False

logger = get_logger(__name__)

# ═══════════════════ CONNECTION POOL ═══════════════════════════════════════════
# ThreadedConnectionPool(max=10) — safe for up to 10 concurrent API request threads.
# The pool is created lazily on first use and held open for the process lifetime.
# ORACLE_PG_DSN env var takes priority over DB_* vars (set by unified_app.py at boot).
_pool = None  # type: ignore[assignment]  # psycopg2.pool.ThreadedConnectionPool when PG is active
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

def _get_pool():
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
        detected_at    TIMESTAMP DEFAULT NOW(),
        content_hash   TEXT
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
    CREATE TABLE IF NOT EXISTS company_email_formats (
        id                  BIGSERIAL PRIMARY KEY,
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
        is_predictable      BOOLEAN NOT NULL DEFAULT TRUE,
        recommended_action  TEXT NOT NULL DEFAULT '',
        UNIQUE (domain, format_rank)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cef_domain ON company_email_formats(domain)",
    "CREATE INDEX IF NOT EXISTS idx_cef_company_name ON company_email_formats(LOWER(company_name))",
    # search_company_email_formats() does leading-wildcard LIKE '%query%' on
    # both columns — a plain btree index (above) can't service that; only a
    # trigram GIN index can. pg_trgm ships with Postgres contrib, safe to
    # enable idempotently.
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS idx_cef_company_name_trgm ON company_email_formats USING GIN (LOWER(company_name) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_cef_domain_trgm ON company_email_formats USING GIN (LOWER(domain) gin_trgm_ops)",
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
    # scan_run_id / first_scan_run_id are what the main companies-dashboard
    # query filters on directly (get_all_companies_with_signals) — without
    # these, every dashboard load is a sequential scan on both tables.
    "CREATE INDEX IF NOT EXISTS idx_signals_scan_run ON oracle_signals(scan_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_companies_first_scan_run ON companies(first_scan_run_id)",
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

    # content_hash dedup for oracle_signals — prevents cross-source duplicates
    "ALTER TABLE oracle_signals ADD COLUMN IF NOT EXISTS content_hash TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_hash ON oracle_signals(content_hash) WHERE content_hash IS NOT NULL",

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

    # ── Fix 1: scan_run_id FK integrity ──────────────────────────────────────────
    # oracle_signals.scan_run_id and companies.first_scan_run_id were declared as
    # plain BIGINT with no FK constraint.  Null out any dangling references first
    # so existing data doesn't block the new constraint, then add ON DELETE SET NULL.
    """
    DO $$ BEGIN
        UPDATE oracle_signals SET scan_run_id = NULL
        WHERE scan_run_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM scan_runs WHERE id = oracle_signals.scan_run_id);
        ALTER TABLE oracle_signals
            ADD CONSTRAINT fk_signals_scan_run
            FOREIGN KEY (scan_run_id) REFERENCES scan_runs(id) ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$
    """,
    """
    DO $$ BEGIN
        UPDATE companies SET first_scan_run_id = NULL
        WHERE first_scan_run_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM scan_runs WHERE id = companies.first_scan_run_id);
        ALTER TABLE companies
            ADD CONSTRAINT fk_companies_scan_run
            FOREIGN KEY (first_scan_run_id) REFERENCES scan_runs(id) ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$
    """,

    # ── Fix 3: unique_key UNIQUE enforcement ─────────────────────────────────────
    # unique_key was generated by application code but never enforced at DB level.
    # Partial index excludes pre-backfill empty-string rows.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_unique_key ON companies(unique_key) WHERE unique_key != ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_unique_key  ON company_contacts(unique_key) WHERE unique_key != ''",

    # campaigns table — drives Campaign Builder / Campaigns pages
    """
    CREATE TABLE IF NOT EXISTS campaigns (
        id                    BIGSERIAL PRIMARY KEY,
        name                  TEXT NOT NULL UNIQUE,
        description           TEXT NOT NULL DEFAULT '',
        keywords              JSONB NOT NULL DEFAULT '[]',
        extra_job_suffixes    JSONB NOT NULL DEFAULT '[]',
        extra_news_templates  JSONB NOT NULL DEFAULT '[]',
        custom_job_queries    JSONB NOT NULL DEFAULT '[]',
        custom_news_queries   JSONB NOT NULL DEFAULT '[]',
        exclude_companies     JSONB NOT NULL DEFAULT '[]',
        location              TEXT NOT NULL DEFAULT '',
        max_pages             INTEGER NOT NULL DEFAULT 3,
        sources               JSONB NOT NULL DEFAULT '[]',
        query_tier            INTEGER NOT NULL DEFAULT 1,
        is_active             BOOLEAN NOT NULL DEFAULT TRUE,
        last_run_at           TIMESTAMPTZ,
        last_run_id           BIGINT REFERENCES scan_runs(id) ON DELETE SET NULL,
        total_signals         INTEGER NOT NULL DEFAULT 0,
        total_companies       INTEGER NOT NULL DEFAULT 0,
        created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_campaigns_active ON campaigns(is_active)",
    # exclude_companies — companies to never persist as a prospect for this
    # campaign, e.g. the vendor's own name. Without this, a vendor's own PR
    # wire announcements get classified as the vendor showing buying intent
    # for its own product (confirmed on a live InRule scan: InRule's own
    # "InRule Launches irAuthor Web" press release was saved as an InRule
    # lead).
    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS exclude_companies JSONB NOT NULL DEFAULT '[]'",

    # apollo_credit_log table — tracks Apollo credit consumption per pipeline step
    """
    CREATE TABLE IF NOT EXISTS apollo_credit_log (
        id             BIGSERIAL PRIMARY KEY,
        run_id         TEXT,
        step           TEXT NOT NULL,
        credits_before INTEGER,
        credits_after  INTEGER,
        credits_used   INTEGER,
        logged_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_credit_log_run ON apollo_credit_log(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_credit_log_ts  ON apollo_credit_log(logged_at DESC)",

    # outcomes table — the learning loop. Every logged reply/meeting/bounce ties
    # a real outreach result back to the company, so attribution can measure
    # which signals actually convert and the Recalibrator can retune targeting.
    """
    CREATE TABLE IF NOT EXISTS outcomes (
        id          BIGSERIAL PRIMARY KEY,
        company_id  BIGINT REFERENCES companies(id) ON DELETE SET NULL,
        contact_id  BIGINT REFERENCES company_contacts(id) ON DELETE SET NULL,
        campaign_id BIGINT REFERENCES campaigns(id) ON DELETE SET NULL,
        email       TEXT NOT NULL DEFAULT '',
        outcome     TEXT NOT NULL
                        CHECK (outcome IN ('contacted','replied','meeting',
                                           'bounced','bad','unsubscribed')),
        notes       TEXT NOT NULL DEFAULT '',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_outcomes_company ON outcomes(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_outcome ON outcomes(outcome)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_created ON outcomes(created_at DESC)",

    # account_prospects — output of glassbox_scorer.py, rerunnable (upsert on
    # campaign_id+company_id) rather than a one-off JSON file per account.
    # trace stores the full 3-state (fired/not_fired/no_evidence) rule trace
    # so a company is never penalized for evidence sources that don't cover it.
    """
    CREATE TABLE IF NOT EXISTS account_prospects (
        id               BIGSERIAL PRIMARY KEY,
        campaign_id      BIGINT REFERENCES campaigns(id) ON DELETE CASCADE,
        company_id       BIGINT REFERENCES companies(id) ON DELETE CASCADE,
        total_score      REAL NOT NULL DEFAULT 0,
        evaluable_weight REAL NOT NULL DEFAULT 0,
        tier             TEXT NOT NULL DEFAULT '',
        trace            JSONB NOT NULL DEFAULT '[]',
        scored_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (campaign_id, company_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_account_prospects_campaign ON account_prospects(campaign_id, total_score DESC)",

    # campaign_hooks — persists every hook hook_generator.py produces (the
    # Signal -> Angle -> Hook step). Contacts here come from Campaign
    # Builder's ICP flow (Apollo pass-through, not necessarily in
    # company_contacts) so fields are denormalized text rather than FKs —
    # a strict company_id/contact_id FK would silently drop most rows.
    # Saved regardless of ok/hold_back so hold-back rate is a real metric,
    # not just successful hooks.
    """
    CREATE TABLE IF NOT EXISTS campaign_hooks (
        id                      BIGSERIAL PRIMARY KEY,
        contact_name            TEXT NOT NULL DEFAULT '',
        contact_email           TEXT NOT NULL DEFAULT '',
        contact_title           TEXT NOT NULL DEFAULT '',
        linkedin_url            TEXT NOT NULL DEFAULT '',
        company_name            TEXT NOT NULL DEFAULT '',
        signal_summary          TEXT NOT NULL DEFAULT '',
        product_context         TEXT NOT NULL DEFAULT '',
        icp_research             TEXT NOT NULL DEFAULT '',
        angle                   TEXT NOT NULL DEFAULT '',
        subject                 TEXT NOT NULL DEFAULT '',
        body                    TEXT NOT NULL DEFAULT '',
        word_count              INTEGER NOT NULL DEFAULT 0,
        personalization_bucket  INTEGER,
        personalization_label   TEXT NOT NULL DEFAULT '',
        grounded                BOOLEAN,
        grounded_on             TEXT NOT NULL DEFAULT '',
        hold_back               BOOLEAN NOT NULL DEFAULT FALSE,
        ok                      BOOLEAN NOT NULL DEFAULT FALSE,
        error                   TEXT NOT NULL DEFAULT '',
        created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_campaign_hooks_angle   ON campaign_hooks(angle)",
    "CREATE INDEX IF NOT EXISTS idx_campaign_hooks_created ON campaign_hooks(created_at DESC)",

    # campaign_touches — cadence_builder.py's touches 2-5 (LinkedIn + follow-up
    # emails) for a hook already saved above. Touch 1 is the hook itself
    # (campaign_hooks row), not duplicated here.
    """
    CREATE TABLE IF NOT EXISTS campaign_touches (
        id         BIGSERIAL PRIMARY KEY,
        hook_id    BIGINT REFERENCES campaign_hooks(id) ON DELETE CASCADE,
        day        INTEGER NOT NULL,
        channel    TEXT NOT NULL,
        subject    TEXT NOT NULL DEFAULT '',
        body       TEXT NOT NULL DEFAULT '',
        notes      TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_campaign_touches_hook ON campaign_touches(hook_id)",

    # copy_lab: every generated variant (all frameworks, winners AND losers)
    # with its scores, so the framework bake-off is auditable, not asserted.
    """
    CREATE TABLE IF NOT EXISTS copy_variants (
        id                BIGSERIAL PRIMARY KEY,
        company_name      TEXT NOT NULL DEFAULT '',
        contact_name      TEXT NOT NULL DEFAULT '',
        contact_title     TEXT NOT NULL DEFAULT '',
        framework         TEXT NOT NULL DEFAULT '',
        subject           TEXT NOT NULL DEFAULT '',
        body              TEXT NOT NULL DEFAULT '',
        word_count        INTEGER NOT NULL DEFAULT 0,
        fk_grade          REAL NOT NULL DEFAULT 0,
        mechanical_score  INTEGER NOT NULL DEFAULT 0,
        judge_score       INTEGER NOT NULL DEFAULT 0,
        total_score       INTEGER NOT NULL DEFAULT 0,
        gates             JSONB NOT NULL DEFAULT '{}',
        judge             JSONB NOT NULL DEFAULT '{}',
        is_winner         BOOLEAN NOT NULL DEFAULT FALSE,
        error             TEXT NOT NULL DEFAULT '',
        created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_copy_variants_company ON copy_variants(company_name)",

    # outcomes -> campaign_hooks link, so reply/meeting rates can eventually
    # be sliced by angle. Nullable — most outcomes still won't trace back to
    # a specific hook until the frontend threads hook_id through outreach.
    "ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS hook_id BIGINT REFERENCES campaign_hooks(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_hook ON outcomes(hook_id)",

    # ats_boards registry — auto-discovered company→ATS map (ats_discovery.py).
    # The ATS signal reads this on top of the config default boards, so the
    # watch-list grows itself as companies are discovered.
    """
    CREATE TABLE IF NOT EXISTS ats_boards (
        id            BIGSERIAL PRIMARY KEY,
        company       TEXT NOT NULL DEFAULT '',
        ats           TEXT NOT NULL,
        token         TEXT NOT NULL,
        job_count     INTEGER NOT NULL DEFAULT 0,
        verified      BOOLEAN NOT NULL DEFAULT FALSE,
        is_active     BOOLEAN NOT NULL DEFAULT TRUE,
        discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (ats, token)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ats_boards_active ON ats_boards(is_active)",
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
    _ensure_contacts_trgm_indexes()


def _ensure_contacts_trgm_indexes():
    """Best-effort GIN trigram indexes on the external 280K `contacts` table
    (owned by csv_contacts.py, not this module's DDL — it may not exist in
    every environment). Its lookups do leading-wildcard LIKE on "Domain" and
    "Existing_Company", which a plain index can't serve. Run outside the main
    DDL transaction so a missing table can't roll back schema init."""
    try:
        with db_cursor() as cur:
            cur.execute("SELECT to_regclass('public.contacts') AS reg")
            if not cur.fetchone()["reg"]:
                return
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            cur.execute(
                'CREATE INDEX IF NOT EXISTS idx_contacts_domain_trgm '
                'ON contacts USING GIN (LOWER("Domain") gin_trgm_ops)'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS idx_contacts_existing_company_trgm '
                'ON contacts USING GIN (LOWER("Existing_Company") gin_trgm_ops)'
            )
        logger.info("contacts trigram indexes ensured")
    except Exception as e:
        logger.warning("Skipping contacts trigram indexes: %s", e)

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
        cur.execute("DELETE FROM review_queue")
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

# Fix 4: oracle_product normalization — maps free-text aliases to canonical names.
# Signals arrive as raw strings from scrapers; this ensures consistent product names
# in the DB so product_taxonomy canonical_name comparisons always match.
_PRODUCT_ALIAS_MAP: dict[str, str] = {
    "jde": "JD Edwards",
    "jde e1": "JD Edwards",
    "jd edwards enterpriseone": "JD Edwards",
    "jd edwards e1": "JD Edwards",
    "oracle fusion": "Oracle Cloud ERP",
    "oracle erp cloud": "Oracle Cloud ERP",
    "oracle financials cloud": "Oracle Cloud ERP",
    "oracle fusion erp": "Oracle Cloud ERP",
    "oracle hcm cloud": "Oracle HCM",
    "oracle fusion hcm": "Oracle HCM",
    "oracle global hr": "Oracle HCM",
    "oracle scm cloud": "Oracle SCM",
    "oracle supply chain cloud": "Oracle SCM",
    "oracle epm cloud": "Oracle EPM",
    "oracle hyperion": "Oracle EPM",
    "oracle planning cloud": "Oracle EPM",
    "oracle cx cloud": "Oracle CX",
    "oracle sales cloud": "Oracle CX",
    "oracle netsuite": "NetSuite",
    "oracle cloud infrastructure": "Oracle OCI",
    "oracle integration cloud": "Oracle Integration",
    "oic": "Oracle Integration",
    "oracle middleware": "Oracle Integration",
    "oracle autonomous database": "Oracle Database",
    "oracle db": "Oracle Database",
}

def _normalize_oracle_product(product: str) -> str:
    """Map scraper free-text to a canonical product name. Returns input unchanged if unknown."""
    if not product:
        return product
    return _PRODUCT_ALIAS_MAP.get(product.strip().lower(), product.strip())


def insert_signal(company_id: int, oracle_product: str, phase: str, source: str,
                  signal_type: str, job_title: str, evidence: str,
                  url: str, confidence: float, scan_run_id: int = None) -> int:
    oracle_product = _normalize_oracle_product(oracle_product)
    raw = f"{company_id}|{job_title or ''}|{source or ''}"
    content_hash = hashlib.md5(raw.encode()).hexdigest()
    with db_cursor() as cur:
        # idx_signals_hash is a PARTIAL unique index (WHERE content_hash IS NOT
        # NULL) — the conflict target must repeat that predicate or Postgres
        # raises "no unique or exclusion constraint matching the ON CONFLICT
        # specification" and the signal never lands.
        cur.execute("""
            INSERT INTO oracle_signals
                (company_id, scan_run_id, oracle_product, phase, source,
                 signal_type, job_title, evidence, url, confidence, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL DO NOTHING
            RETURNING id
        """, (company_id, scan_run_id, oracle_product, phase, source,
              signal_type, job_title, evidence, url, confidence, content_hash))
        row = cur.fetchone()
        return row["id"] if row else 0


def batch_update_signal_counts(company_ids: list) -> None:
    """Batch-update denormalized signal_count for a list of company IDs.
    Call this once after all signals for a scan batch are inserted, instead
    of running a COUNT(*) per-insert (N+1).
    """
    if not company_ids:
        return
    unique_ids = list(set(company_ids))
    with db_cursor() as cur:
        cur.execute("""
            UPDATE companies SET
                signal_count = subq.cnt,
                last_updated = NOW()
            FROM (
                SELECT company_id, COUNT(*) AS cnt
                FROM oracle_signals
                WHERE company_id = ANY(%s)
                GROUP BY company_id
            ) AS subq
            WHERE companies.id = subq.company_id
        """, (unique_ids,))

def get_signals_for_company(company_id: int):
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT * FROM oracle_signals
            WHERE company_id = %s
            ORDER BY detected_at DESC
        """, (company_id,))
        return cur.fetchall()


def get_top_signals_for_companies(names: list) -> dict:
    """Highest-confidence signal per company name (case-insensitive), as a
    one-line summary string — the grounding evidence handed to hook generation
    when signal-engine contacts are sent to Campaign Builder. One query for
    the whole batch, not one per company."""
    if not names:
        return {}
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT DISTINCT ON (LOWER(c.name))
                   c.name, s.oracle_product, s.phase, s.signal_type,
                   s.job_title, s.evidence, s.source, s.confidence
            FROM companies c
            JOIN oracle_signals s ON s.company_id = c.id
            WHERE LOWER(c.name) = ANY(%s)
            ORDER BY LOWER(c.name), s.confidence DESC, s.detected_at DESC
        """, ([n.strip().lower() for n in names if n and n.strip()],))
        out = {}
        for r in cur.fetchall():
            bits = [b for b in (r["signal_type"], r["oracle_product"], r["phase"]) if b]
            head = " / ".join(bits) if bits else "intent signal"
            detail = r["job_title"] or r["evidence"] or ""
            summary = f"{head}: {detail}" if detail else head
            out[r["name"].strip().lower()] = f"{summary} (source: {r['source']}, confidence {r['confidence']:.2f})"
        return out

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
            # company_contacts has TWO unique constraints (email, and
            # linkedin_url) but ON CONFLICT can only target one arbiter per
            # statement. The email one is handled below; a row with no email
            # (or an email that doesn't collide) can still collide on
            # linkedin_url alone — e.g. Apollo returning the same person
            # across two different title-query passes. A SAVEPOINT here means
            # that specific collision just gets skipped instead of aborting
            # the whole batch's transaction (which silently dropped every
            # contact after the colliding one, including for companies with
            # zero relation to the duplicate).
            cur.execute("SAVEPOINT sp_contact")
            try:
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
            except psycopg2.errors.UniqueViolation:
                cur.execute("ROLLBACK TO SAVEPOINT sp_contact")
                logger.warning(
                    f"[save_contacts] skipped duplicate contact for company_id={company_id} "
                    f"(linkedin_url collision): {c.get('full_name', '')}"
                )
            else:
                cur.execute("RELEASE SAVEPOINT sp_contact")
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
        # review_queue has no FK to companies — clean up manually before delete
        cur.execute(
            "DELETE FROM review_queue WHERE entity_type = 'company' AND entity_id = %s",
            (company_id,),
        )
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

        # review_queue has no FK to companies — clean up before delete
        cur.execute(
            "DELETE FROM review_queue WHERE entity_type = 'company' AND entity_id = %s",
            (drop_id,),
        )
        # Delete the duplicate (remaining orphan signals/contacts cascade)
        cur.execute("DELETE FROM companies WHERE id = %s", (drop_id,))

    return {"signals_moved": signals_moved, "contacts_moved": contacts_moved}

def delete_contact(contact_id: int) -> bool:
    """Hard-delete one contact and keep the company's contact_count in sync."""
    with db_cursor() as cur:
        # review_queue has no FK to company_contacts — clean up manually before delete
        cur.execute(
            "DELETE FROM review_queue WHERE entity_type = 'contact' AND entity_id = %s",
            (contact_id,),
        )
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
                           MAX(detected_at)                          AS latest_signal_at,
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
                    sig.latest_signal_at::text       AS latest_signal_at,
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

# ── Prediction Engine — full company_email_formats reference ─────────────────
# Every domain×format row from COMPANY-EMAIL-FORMAT-REFERENCE-GUIDE.xlsx, not
# just the engine-buildable subset in email_patterns. This is the read model
# for the Prediction Engine UI (browse/search/explain); email_patterns stays
# the lean operational table actual predictions are built from.

def upsert_company_email_formats(rows: list) -> int:
    """
    Bulk upsert full-guide format rows, one per (domain, format_rank).
    Each row is a dict — see import_email_formats.py for the field set.
    """
    if not rows:
        return 0
    cols = ["company_name", "domain", "format_rank", "format_code", "formula",
            "description", "domain_example", "share_pct", "format_count",
            "sample_emails", "contacts_280k", "validated_emails",
            "formats_found", "is_predictable", "recommended_action"]
    with db_cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            f"""INSERT INTO company_email_formats ({", ".join(cols)})
                VALUES %s
                ON CONFLICT (domain, format_rank) DO UPDATE SET
                    company_name       = EXCLUDED.company_name,
                    format_code        = EXCLUDED.format_code,
                    formula            = EXCLUDED.formula,
                    description        = EXCLUDED.description,
                    domain_example     = EXCLUDED.domain_example,
                    share_pct          = EXCLUDED.share_pct,
                    format_count       = EXCLUDED.format_count,
                    sample_emails      = EXCLUDED.sample_emails,
                    contacts_280k      = EXCLUDED.contacts_280k,
                    validated_emails   = EXCLUDED.validated_emails,
                    formats_found      = EXCLUDED.formats_found,
                    is_predictable     = EXCLUDED.is_predictable,
                    recommended_action = EXCLUDED.recommended_action""",
            [tuple(r.get(c) for c in cols) for r in rows],
            page_size=1000,
        )
    return len(rows)


def search_company_email_formats(query: str, limit: int = 20) -> list:
    """
    Search the reference guide by company name or domain (case-insensitive
    substring). Returns one row per matching domain — its primary
    (format_rank = 1) format — ordered by corpus evidence.

    contacts_280k = 0 means the row is a stray validated-email match with no
    real presence in the corpus (e.g. "Co19 Oracle" / co19.oracle.com — 1
    validated email, 0 corpus contacts) — noise, not a company. Excluded so
    every search result has actual evidence behind it.

    is_predictable = false means the primary format is "Other / unmatched" or
    a custom multi-dot code with no buildable template — there's no format to
    actually apply to a contact, so it doesn't belong in a *prediction* tool.
    Excluded here (the full row still exists in company_email_formats — see
    get_company_email_formats — for a domain someone navigates to directly).
    """
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
              AND is_predictable
              AND (LOWER(company_name) LIKE %s OR LOWER(domain) LIKE %s)
            ORDER BY contacts_280k DESC, validated_emails DESC
            LIMIT %s
        """, (q, q, limit))
        return [dict(r) for r in cur.fetchall()]


def get_company_email_formats(domain: str) -> list:
    """All ranked format rows for one domain (rank 1 = primary)."""
    domain = (domain or "").strip().lower()
    if not domain:
        return []
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT * FROM company_email_formats
            WHERE domain = %s
            ORDER BY format_rank
        """, (domain,))
        return [dict(r) for r in cur.fetchall()]


def company_email_formats_stats() -> dict:
    """Row/domain counts for the Prediction Engine overview strip.
    "domains" is scoped to exactly what search_company_email_formats surfaces
    (evidence-backed AND a buildable primary format) so the number shown
    never overstates what's actually searchable/usable."""
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT COUNT(DISTINCT domain) FILTER (WHERE contacts_280k > 0 AND is_predictable AND format_rank = 1) AS domains,
                   COUNT(*) FILTER (WHERE domain IN (
                       SELECT domain FROM company_email_formats
                       WHERE contacts_280k > 0 AND is_predictable AND format_rank = 1
                   )) AS total_rows
            FROM company_email_formats
        """)
        row = dict(cur.fetchone())
        row["predictable_domains"] = row["domains"]
        return row

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


# ── Companies list page — bulk lookups by ID ────────────────────────────────
# Split out of the /api/companies route so the SQLite backend can supply its
# own implementation (ARRAY_AGG/FILTER/ANY() have no direct SQLite equivalent).

def get_signal_aggregates_by_company(company_ids: list) -> dict:
    if not company_ids:
        return {}
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT company_id,
                   STRING_AGG(DISTINCT oracle_product, ',') AS products,
                   STRING_AGG(DISTINCT phase, ',')          AS phases,
                   STRING_AGG(DISTINCT source, ',')         AS sources,
                   MAX(confidence)                          AS max_confidence,
                   (ARRAY_AGG(url ORDER BY confidence DESC)
                    FILTER (WHERE url LIKE 'http%%'))[1]   AS source_url
            FROM oracle_signals
            WHERE company_id = ANY(%s)
            GROUP BY company_id
        """, (company_ids,))
        return {r["company_id"]: dict(r) for r in cur.fetchall()}


def get_companies_by_ids(company_ids: list) -> dict:
    if not company_ids:
        return {}
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT c.id, c.name, c.domain, c.industry, c.size, c.location, c.website,
                   c.target_product, c.status, c.source AS import_source,
                   c.first_scan_run_id, c.first_seen::text AS first_seen,
                   c.signal_count, c.contact_count, c.last_updated::text AS last_updated
            FROM companies c
            WHERE c.id = ANY(%s)
        """, (company_ids,))
        return {r["id"]: dict(r) for r in cur.fetchall()}


# ── Campaigns ─────────────────────────────────────────────────────────────────
# Backs the Campaign Builder / Campaigns pages. Kept in parity with
# database_sqlite.py so unified_app.py's oracle_db.* calls work on either backend.

def _serialize_campaign(row: Optional[dict]) -> Optional[dict]:
    """Parse JSON fields back to Python objects for API responses.
    psycopg2 already returns JSONB columns as parsed objects, so this is a
    no-op there — kept identical to the SQLite version for interchangeability."""
    if not row:
        return row
    import json
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
            cur.execute("SELECT * FROM campaigns WHERE is_active = TRUE ORDER BY created_at DESC")
        else:
            cur.execute("SELECT * FROM campaigns ORDER BY created_at DESC")
        return [_serialize_campaign(dict(r)) for r in cur.fetchall()]


def get_campaign(campaign_id: int) -> Optional[dict]:
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM campaigns WHERE id = %s", (campaign_id,))
        row = cur.fetchone()
        return _serialize_campaign(dict(row)) if row else None


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
    import json
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO campaigns
                (name, description, keywords, extra_job_suffixes, extra_news_templates,
                 custom_job_queries, custom_news_queries, location, max_pages,
                 sources, query_tier, exclude_companies)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        cid = cur.fetchone()["id"]
    return get_campaign(cid)


def update_campaign(campaign_id: int, **kwargs) -> dict:
    import json
    json_fields = {"keywords", "extra_job_suffixes", "extra_news_templates",
                   "custom_job_queries", "custom_news_queries", "sources",
                   "exclude_companies"}
    parts, vals = [], []
    for k, v in kwargs.items():
        if k in json_fields:
            parts.append(f"{k} = %s"); vals.append(json.dumps(v or []))
        else:
            parts.append(f"{k} = %s"); vals.append(v)
    if not parts:
        return get_campaign(campaign_id)
    parts.append("updated_at = NOW()")
    vals.append(campaign_id)
    with db_cursor() as cur:
        cur.execute(f"UPDATE campaigns SET {', '.join(parts)} WHERE id = %s", vals)
    return get_campaign(campaign_id)


def delete_campaign(campaign_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute("DELETE FROM campaigns WHERE id = %s", (campaign_id,))
        return cur.rowcount > 0


def update_campaign_run_stats(campaign_id: int, run_id: int,
                               signals: int, companies: int):
    with db_cursor() as cur:
        cur.execute("""
            UPDATE campaigns SET
                last_run_at      = NOW(),
                last_run_id      = %s,
                total_signals    = total_signals + %s,
                total_companies  = total_companies + %s,
                updated_at       = NOW()
            WHERE id = %s
        """, (run_id, signals, companies, campaign_id))


# ── Account prospects (generalized glassbox scoring, see glassbox_scorer.py) ──

def upsert_account_prospect(campaign_id: int, company_id: int, total_score: float,
                             evaluable_weight: float, tier: str, trace: list) -> dict:
    import json
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO account_prospects
                (campaign_id, company_id, total_score, evaluable_weight, tier, trace, scored_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (campaign_id, company_id) DO UPDATE SET
                total_score      = EXCLUDED.total_score,
                evaluable_weight = EXCLUDED.evaluable_weight,
                tier              = EXCLUDED.tier,
                trace             = EXCLUDED.trace,
                scored_at         = NOW()
            RETURNING *
        """, (campaign_id, company_id, total_score, evaluable_weight, tier, json.dumps(trace)))
        return dict(cur.fetchone())


def get_account_prospects(campaign_id: int, limit: int = 100) -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT p.*, c.name AS company_name, c.domain
            FROM account_prospects p
            JOIN companies c ON c.id = p.company_id
            WHERE p.campaign_id = %s
            ORDER BY p.total_score DESC
            LIMIT %s
        """, (campaign_id, limit))
        return [dict(r) for r in cur.fetchall()]


# ── Apollo credit tracking ──────────────────────────────────────────────────

def log_apollo_credits(run_id: str, step: str, credits_before: Optional[int], credits_after: Optional[int]) -> None:
    """Record Apollo credit consumption for one pipeline step."""
    used = None
    if credits_before is not None and credits_after is not None:
        used = credits_before - credits_after
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO apollo_credit_log (run_id, step, credits_before, credits_after, credits_used)
               VALUES (%s, %s, %s, %s, %s)""",
            (run_id, step, credits_before, credits_after, used),
        )


def get_credit_log(limit: int = 100) -> list:
    """Return recent Apollo credit log entries, newest first."""
    with db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT * FROM apollo_credit_log ORDER BY logged_at DESC LIMIT %s",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_credit_summary() -> dict:
    """Aggregate credit spend by step across all runs."""
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT step,
                   COUNT(*)          AS calls,
                   SUM(credits_used) AS total_used,
                   MAX(logged_at)    AS last_used_at
            FROM apollo_credit_log
            WHERE credits_used IS NOT NULL
            GROUP BY step
            ORDER BY total_used DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT SUM(credits_used) AS grand_total FROM apollo_credit_log WHERE credits_used IS NOT NULL")
        grand = cur.fetchone()
        return {
            "by_step":     rows,
            "grand_total": int(grand["grand_total"] or 0),
        }


# ── Audit logs ────────────────────────────────────────────────────────────────

def log_audit_event(user_id: Optional[int], user_email: str, action: str,
                    entity_type: str, entity_id: str = "",
                    old_value=None, new_value=None, ip_address: str = ""):
    import json
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO audit_logs
                (user_id, user_email, action, entity_type, entity_id,
                 old_value, new_value, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id, user_email, action, entity_type, entity_id,
            json.dumps(old_value) if old_value is not None else None,
            json.dumps(new_value) if new_value is not None else None,
            ip_address,
        ))


def get_audit_logs_list(limit: int = 100, entity_type: str = None) -> list:
    with db_cursor(commit=False) as cur:
        if entity_type:
            cur.execute(
                "SELECT * FROM audit_logs WHERE entity_type = %s ORDER BY created_at DESC LIMIT %s",
                (entity_type, limit),
            )
        else:
            cur.execute(
                "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT %s", (limit,)
            )
        return [dict(r) for r in cur.fetchall()]


# ── Outcomes (the learning loop) ──────────────────────────────────────────────

def log_outcome(outcome: str, company: str = "", email: str = "",
                contact_id: int = None, campaign_id: int = None,
                notes: str = "", hook_id: int = None) -> dict:
    """Record a real outreach result. Resolves company_id/contact_id from the
    company name or email the user knows post-send. Never overwrites — each
    logged outcome is an event (a contact can be contacted, then reply).
    hook_id (optional) traces this outcome back to the campaign_hooks row
    that produced the send, so reply/meeting rates can be sliced by angle."""
    with db_cursor() as cur:
        resolved_company_id = None
        resolved_contact_id = contact_id
        if company:
            cur.execute("SELECT id FROM companies WHERE LOWER(name) = LOWER(%s)", (company.strip(),))
            row = cur.fetchone()
            if row:
                resolved_company_id = row["id"]
        if email and resolved_contact_id is None:
            cur.execute("SELECT id, company_id FROM company_contacts WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                        (email.strip(),))
            row = cur.fetchone()
            if row:
                resolved_contact_id = row["id"]
                if resolved_company_id is None:
                    resolved_company_id = row["company_id"]

        cur.execute("""
            INSERT INTO outcomes (company_id, contact_id, campaign_id, email, outcome, notes, hook_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (resolved_company_id, resolved_contact_id, campaign_id,
              email.strip(), outcome.strip(), notes.strip(), hook_id))
        return dict(cur.fetchone())


def get_outcomes(limit: int = 200) -> list:
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT o.*, c.name AS company_name
            FROM outcomes o
            LEFT JOIN companies c ON c.id = o.company_id
            ORDER BY o.created_at DESC LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_outcome_signal_rows() -> list:
    """One row per (outcome, signal) pair — the raw input to attribution
    rollup. A company with 3 signals and 1 outcome yields 3 rows."""
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
    """One row per outcome that traces back to a campaign_hooks row (hook_id
    set) — the input to angle/personalization-bucket attribution. Unlike
    get_outcome_signal_rows(), this is 1:1 (an outcome has at most one hook),
    so no dedup is needed downstream."""
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT o.id AS outcome_id, o.outcome,
                   ch.angle, ch.personalization_bucket, ch.personalization_label
            FROM outcomes o
            JOIN campaign_hooks ch ON ch.id = o.hook_id
            WHERE o.hook_id IS NOT NULL
        """)
        return [dict(r) for r in cur.fetchall()]


# ── Campaign hooks — persists the Signal -> Angle -> Hook step ───────────────
# (see hook_generator.py / cadence_builder.py). Saved regardless of ok/hold_back
# so hold-back rate is a real metric, not just successful hooks.

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
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            hook.get("contact_name", ""), hook.get("email", ""), hook.get("title", ""),
            hook.get("linkedin_url", ""), hook.get("company", ""),
            signal_summary, product_context, icp_research,
            hook.get("angle", ""), hook.get("subject", ""), hook.get("body", ""),
            hook.get("word_count", 0),
            hook.get("personalization_bucket"), hook.get("personalization_label", ""),
            hook.get("grounded"), hook.get("grounded_on", ""),
            bool(hook.get("hold_back", False)), bool(hook.get("ok", False)),
            hook.get("error") or "",
        ))
        return cur.fetchone()["id"]


def save_campaign_touches(hook_id: int, touches: list) -> None:
    if not touches:
        return
    with db_cursor() as cur:
        for t in touches:
            cur.execute("""
                INSERT INTO campaign_touches (hook_id, day, channel, subject, body, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (hook_id, t.get("day", 0), t.get("channel", ""),
                  t.get("subject", ""), t.get("body", ""), t.get("notes", "")))


def get_touches_for_hooks(hook_ids: list) -> dict:
    """Batch-fetch touches 2-5 for a set of hook ids, keyed by hook_id, each
    list ordered by day. Powers any UI that needs to show a hook's full
    cadence, not just the touch-1 opener.

    save_campaign_touches() is a plain INSERT with no uniqueness guard, so a
    hook whose cadence was built more than once (e.g. re-run from the UI)
    ends up with duplicate (day, channel) rows. Dedupe here — keep the most
    recent row per (hook_id, day, channel) — rather than at insert time, so
    a read is never wrong even if a future caller re-introduces the same
    duplication."""
    if not hook_ids:
        return {}
    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT DISTINCT ON (hook_id, day, channel)
                   hook_id, day, channel, subject, body, notes
            FROM campaign_touches
            WHERE hook_id = ANY(%s)
            ORDER BY hook_id, day, channel, created_at DESC
        """, (list(hook_ids),))
        out: dict = {}
        for row in cur.fetchall():
            out.setdefault(row["hook_id"], []).append(dict(row))
        for hook_id in out:
            out[hook_id].sort(key=lambda r: r["day"])
        return out


def get_campaign_hook_stats() -> dict:
    """Angle distribution, bucket distribution, hold-back rate — the metrics
    half of the Signal -> Angle -> Hook -> Email page."""
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM campaign_hooks")
        total = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM campaign_hooks WHERE ok")
        ok = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM campaign_hooks WHERE hold_back")
        held_back = cur.fetchone()["n"]
        cur.execute("""
            SELECT angle, COUNT(*) AS n FROM campaign_hooks
            WHERE ok AND angle != '' GROUP BY angle ORDER BY n DESC
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
        cur.execute("""
            SELECT * FROM campaign_hooks ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def save_copy_variants(company_name: str, contact_name: str, contact_title: str,
                       variants: list) -> None:
    """Persist a full framework bake-off for one contact — winners and losers.
    Replaces any prior set for this (company, contact) so re-runs stay clean."""
    import json as _json
    winner_idx = max(range(len(variants)), key=lambda i: variants[i].get("total_score", 0)) if variants else -1
    with db_cursor() as cur:
        cur.execute("DELETE FROM copy_variants WHERE company_name=%s AND contact_name=%s",
                    (company_name, contact_name))
        for i, v in enumerate(variants):
            cur.execute("""
                INSERT INTO copy_variants
                    (company_name, contact_name, contact_title, framework, subject, body,
                     word_count, fk_grade, mechanical_score, judge_score, total_score,
                     gates, judge, is_winner, error)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (company_name, contact_name, contact_title, v.get("framework", ""),
                  v.get("subject", ""), v.get("body", ""), int(v.get("word_count", 0)),
                  float(v.get("fk_grade", 0)), int(v.get("mechanical_score", 0)),
                  int(v.get("judge", {}).get("judge_score", 0)), int(v.get("total_score", 0)),
                  _json.dumps(v.get("gates", {})), _json.dumps(v.get("judge", {})),
                  i == winner_idx, v.get("error", "")))


def get_copy_variants() -> list:
    """All variant sets, grouped by contact, best-first within each group.
    Shape: [{company, contact, title, variants:[...]}] ordered by winner score."""
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM copy_variants ORDER BY company_name, contact_name, total_score DESC")
        rows = [dict(r) for r in cur.fetchall()]
    groups: dict = {}
    for r in rows:
        key = (r["company_name"], r["contact_name"])
        g = groups.setdefault(key, {"company": r["company_name"], "contact": r["contact_name"],
                                    "title": r["contact_title"], "variants": []})
        g["variants"].append(r)
    out = list(groups.values())
    out.sort(key=lambda g: max((v["total_score"] for v in g["variants"]), default=0), reverse=True)
    return out


# ── ATS board registry (auto-discovery) ───────────────────────────────────────

def upsert_ats_board(company: str, ats: str, token: str,
                     job_count: int = 0, verified: bool = False) -> None:
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO ats_boards (company, ats, token, job_count, verified)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ats, token) DO UPDATE SET
                company   = COALESCE(NULLIF(EXCLUDED.company, ''), ats_boards.company),
                job_count = EXCLUDED.job_count,
                verified  = ats_boards.verified OR EXCLUDED.verified,
                is_active = TRUE
        """, (company.strip(), ats.strip(), token.strip(), int(job_count), bool(verified)))


def get_ats_boards(active_only: bool = True) -> list:
    with db_cursor(commit=False) as cur:
        if active_only:
            cur.execute("SELECT * FROM ats_boards WHERE is_active = TRUE ORDER BY job_count DESC")
        else:
            cur.execute("SELECT * FROM ats_boards ORDER BY job_count DESC")
        return [dict(r) for r in cur.fetchall()]


# ── SQLite auto-fallback ──────────────────────────────────────────────────────
# When PostgreSQL is unreachable (no office network / VPN), all public functions
# in this module are replaced by their SQLite equivalents at import time.
# unified_app.py imports `database as oracle_db` and never needs to change.

def _pg_reachable() -> bool:
    if not _PSYCOPG2_AVAILABLE:
        return False
    try:
        conn = psycopg2.connect(_dsn(), connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


def _activate_sqlite_fallback():
    import importlib
    sqlite_mod = importlib.import_module("src.database_sqlite")
    g = globals()
    for name in dir(sqlite_mod):
        if not name.startswith("_"):
            g[name] = getattr(sqlite_mod, name)
    logger.warning(
        "PostgreSQL unreachable — running on local SQLite (%s)",
        sqlite_mod._DB_PATH,
    )


if not _pg_reachable():
    _activate_sqlite_fallback()
