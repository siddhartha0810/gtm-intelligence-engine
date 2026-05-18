"""
config.py
=========
Central place for ALL configuration.
Reads API keys from the .env file and defines file paths used across the pipeline.

HOW TO SET UP:
  1. Copy .env.example to .env
  2. Fill in your API keys in .env
  3. Never commit .env to git — it contains secrets
"""

import os
from dotenv import load_dotenv

# ── Load .env file ─────────────────────────────────────────────────────────
# python-dotenv reads the .env file and puts all key=value pairs into
# os.environ so we can access them with os.getenv()
load_dotenv()

# ── API Keys ───────────────────────────────────────────────────────────────
# Apollo.io — used to find emails and LinkedIn URLs from name + company
# Get your key from: app.apollo.io → Settings → Integrations → API
# Auth method: X-Api-Key header (NOT Authorization: Bearer)
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "").strip()

# ZeroBounce — used to validate whether an email address actually exists
# Get your key from: app.zerobounce.net → API → API Key
ZEROBOUNCE_API_KEY = os.getenv("ZEROBOUNCE_API_KEY", "").strip()

# ZoomInfo — optional premium enrichment (not used in default routing)
# Only activates if you add "zoominfo" to DOMAIN_OVERRIDES in orchestrator.py
ZOOMINFO_API_KEY  = os.getenv("ZOOMINFO_API_KEY",  "").strip()
ZOOMINFO_BASE_URL = os.getenv("ZOOMINFO_BASE_URL",  "https://api.zoominfo.com").strip()

# Apify — used as a fallback when Apollo finds nothing
# Phase 1: finds LinkedIn URL from name + company
# Phase 2: finds work email from LinkedIn URL
# Get your token from: console.apify.com → Settings → Integrations
APIFY_TOKEN             = os.getenv("APIFY_TOKEN",             "").strip()
APIFY_LINKEDIN_ACTOR_ID = os.getenv("APIFY_LINKEDIN_ACTOR_ID", "").strip()
APIFY_EMAIL_ACTOR_ID    = os.getenv("APIFY_EMAIL_ACTOR_ID",    "").strip()

# ── File Paths ─────────────────────────────────────────────────────────────
# Input files — place these in the input/ folder before running
INPUT_LEADS      = "input/leads.csv"           # main leads file (auto-generated from xlsx)
DOMAIN_LOOKUP    = "input/domain_lookup.csv"   # manual company → domain mappings (auto-updated)
SUPPRESSION_LIST = "input/suppression_list.csv" # emails that must never be contacted

# Output files — written automatically after the pipeline finishes
OUTPUT_FINAL = "output/final_outreach_ready.csv"  # enriched leads with ready_for_outreach flag
OUTPUT_AUDIT = "output/audit_log.csv"             # row counts at each pipeline stage

# Database
DB_PATH = "input/pipeline.db"   # SQLite knowledge store — auto-created, never edit manually

# ── PostgreSQL pipeline I/O (optional) ────────────────────────────────────
# Set PG_CONNECTION_STRING to read leads from Postgres and write results back.
# Leave blank to use CSV files only.
# Format: postgresql://user:password@host:5432/dbname
PG_CONNECTION_STRING = os.getenv("PG_CONNECTION_STRING", "").strip()
PG_INPUT_TABLE       = os.getenv("PG_INPUT_TABLE",  "leads").strip()
PG_OUTPUT_TABLE      = os.getenv("PG_OUTPUT_TABLE", "enriched_leads").strip()

# ── PostgreSQL master store ────────────────────────────────────────────────
# Permanent cross-run accumulation of all enriched leads.
# Configure via individual PG_* vars (or set PG_MASTER_CONNECTION_STRING directly).
PG_HOST     = os.getenv("PG_HOST",     "").strip()
PG_PORT     = os.getenv("PG_PORT",     "5432").strip()
PG_DB       = os.getenv("PG_DB",       "").strip()
PG_USER     = os.getenv("PG_USER",     "").strip()
PG_PASSWORD = os.getenv("PG_PASSWORD", "").strip()

PG_MASTER_CONNECTION_STRING = os.getenv("PG_MASTER_CONNECTION_STRING", "").strip()
if not PG_MASTER_CONNECTION_STRING and PG_HOST and PG_DB and PG_USER:
    PG_MASTER_CONNECTION_STRING = (
        f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    )
