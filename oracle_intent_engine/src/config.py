"""
config.py  (oracle_intent_engine)
==================================
Central configuration loader for the Oracle Intent Engine.

PURPOSE:
  Single source of truth for all API keys, database connection details, rate-limit
  settings, and the master list of search queries that drive the job-board scrapers.
  All secrets come from oracle_intent_engine/.env — never hardcoded.

HOW IT FITS IN THE SYSTEM:
  Imported at the top of almost every oracle_intent_engine module.
  unified_app.py loads the .env file BEFORE importing this module, so any env vars
  set by unified_app.py (e.g. ORACLE_PG_DSN) are already visible when config
  attributes are first read.

KEY ATTRIBUTES:
  DB_*                  — PostgreSQL connection details for Inoapps-Data-DB
  APOLLO_API_KEY        — used by apollo_enrichment.py (X-Api-Key header, NOT Bearer)
  ZEROBOUNCE_API_KEY    — used by apollo_enrichment.py for email validation
  ORACLE_SEARCH_QUERIES — 100+ job-board queries that drive the scanner
  JDE_MANUFACTURING_QUERIES — extra queries for the JDE Manufacturing Focus mode
  NEWS_QUERIES          — queries consumed by news_signal.py
  MAX_PAGES             — per-source page cap (prevents runaway scraping costs)
  SCAN_DELAY_MIN/MAX    — seconds to sleep between HTTP requests (politeness tier)

DEPENDENCIES:
  - python-dotenv (reads oracle_intent_engine/.env)
  - No DB or API calls occur at import time
"""

import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "Inoapps-Data-DB")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
BING_NEWS_KEY = os.getenv("BING_NEWS_KEY", "")

# Hunter.io — free tier: 25 domain searches/month → decision-maker contacts
# Get key at: https://hunter.io/api (free signup)
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")

# Apollo.io — people search + email reveal
# Get key at: https://developer.apollo.io/
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")

# ZeroBounce — email validation (1 credit per email)
# Get key at: https://app.zerobounce.net/
ZEROBOUNCE_API_KEY = os.getenv("ZEROBOUNCE_API_KEY", "")

# ZoomInfo — alternative contact-discovery provider (enterprise API)
# Auth: POST /authenticate with username+password → JWT (60 min)
ZOOMINFO_USERNAME = os.getenv("ZOOMINFO_USERNAME", "").strip()
ZOOMINFO_PASSWORD = os.getenv("ZOOMINFO_PASSWORD", "").strip()

# Adzuna — free job board API (250 calls/day free)
# Register at: https://developer.adzuna.com/
ADZUNA_APP_ID  = os.getenv("ADZUNA_APP_ID",  "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")

# ScrapeGraphAI — set SCRAPEGRAPH_MODEL to enable LLM scraping
# Free/local:  SCRAPEGRAPH_MODEL=ollama/llama3.1
# Paid/better: SCRAPEGRAPH_MODEL=anthropic/claude-haiku-4-5-20251001  (set SCRAPEGRAPH_API_KEY too)
SCRAPEGRAPH_MODEL     = os.getenv("SCRAPEGRAPH_MODEL", "")
SCRAPEGRAPH_API_KEY   = os.getenv("SCRAPEGRAPH_API_KEY", "")
SCRAPEGRAPH_OLLAMA_URL = os.getenv("SCRAPEGRAPH_OLLAMA_URL", "http://localhost:11434")

# Ollama local LLM — company extraction fallback (free, runs locally)
# Install Ollama from ollama.ai, then: ollama pull llama3.2
OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

SCAN_DELAY_MIN = float(os.getenv("SCAN_DELAY_MIN", "2"))
SCAN_DELAY_MAX = float(os.getenv("SCAN_DELAY_MAX", "6"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "3"))

# 280K contacts CSV — used to match detected companies with known contacts
CONTACTS_CSV_PATH = os.getenv(
    "CONTACTS_CSV_PATH",
    r"C:\Users\sidhartha\OneDrive\Desktop\280K\ALL_CONTACTS_CONSOLIDATED.csv"
)

FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "oracle-intent-secret")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5001"))

# agentic_harvester_signal.py watch list — comma-separated URLs, e.g. a
# procurement portal's open-tenders page or an Oracle partner directory.
# Adding a new source to watch is editing this list, not writing a scraper.
AGENTIC_HARVESTER_URLS = [
    u.strip() for u in os.getenv("AGENTIC_HARVESTER_URLS", "").split(",") if u.strip()
]

# ── Role suffixes used by the auto-generator for new taxonomy products ────────
# When a product is added to the taxonomy but has no entry in QUERIES_BY_PRODUCT,
# these suffixes are crossed with the canonical name and multi-word aliases to
# produce search queries automatically.
_ROLE_SUFFIXES = [
    "consultant",
    "implementation consultant",
    "functional consultant",
    "technical consultant",
    "administrator",
    "project manager",
    "developer",
    "upgrade",
    "implementation",
    "migration consultant",
]


def generate_queries_for_product(canonical_name: str, aliases: list[str]) -> list[str]:
    """
    Auto-generate job-board search queries for a taxonomy product that has no
    handcrafted entry in QUERIES_BY_PRODUCT.

    Strategy:
      - canonical_name × _ROLE_SUFFIXES  → core queries
      - aliases with 3+ words            → used directly (already search-query quality)
      - aliases with 2 words             → paired with top 3 suffixes
    """
    seen: set[str] = set()
    queries: list[str] = []

    def _add(q: str) -> None:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            queries.append(q)

    for suffix in _ROLE_SUFFIXES:
        _add(f"{canonical_name} {suffix}")

    for alias in aliases:
        words = alias.strip().split()
        titled = " ".join(w.capitalize() for w in words)
        if len(words) >= 3:
            _add(titled)
        elif len(words) == 2:
            for suffix in ("consultant", "implementation", "administrator"):
                _add(f"{titled} {suffix}")

    return queries


# ── Proven queries per canonical product name ─────────────────────────────────
# Pipeline reads only the queries whose product is active in the taxonomy.
# When a new product is added to the taxonomy AND is not listed here,
# generate_queries_for_product() is called automatically.
QUERIES_BY_PRODUCT: dict[str, list[str]] = {
    # ── JD Edwards ────────────────────────────────────────────────────
    "JD Edwards": [
        "JD Edwards consultant",
        "JDE EnterpriseOne implementation",
        "JD Edwards ERP upgrade",
        "JDE technical developer",
        "JD Edwards functional consultant",
        "JDE CNC administrator",
        "JD Edwards project manager",
        "JDE EnterpriseOne support analyst",
        "JDE system administrator",
        "JDE basis administrator",
        "JDE solution architect",
        "JDE orchestrator developer",
        "JDE security administrator",
        "JDE report developer",
        "JD Edwards business analyst",
        # High-yield confirmed (tested May 2026)
        "JD Edwards 9.2 upgrade",
        "JD Edwards upgrade project manager",
        # Migration
        "JD Edwards migration Oracle Cloud",
        "JDE to Oracle Cloud migration",
        "JDE EnterpriseOne cloud migration",
        # Verticals — manufacturing
        "JD Edwards manufacturing consultant",
        "JDE MRP work orders bill of materials",
        "JD Edwards shop floor manufacturing ERP",
        "JDE discrete manufacturing implementation",
        # Verticals — construction & home building
        "JD Edwards construction ERP consultant",
        "JDE job costing homebuilder",
        "JD Edwards EnterpriseOne construction",
        "JDE land development procurement",
        # Verticals — energy & utilities
        "JD Edwards energy oil gas ERP",
        "JDE EnterpriseOne utilities consultant",
        # Verticals — agriculture & distribution
        "JD Edwards agriculture ERP consultant",
        "JDE food beverage agribusiness implementation",
        "JD Edwards distribution consultant",
        "JDE wholesale distribution implementation",
    ],
    # ── JD Edwards World ─────────────────────────────────────────────
    "JD Edwards World": [
        "JD Edwards World consultant",
        "JDE World administrator",
        "JD Edwards World AS400 administrator",
        "JDE World upgrade EnterpriseOne",
        "JD Edwards World to EnterpriseOne migration",
        "JDE World technical developer",
        "JD Edwards World support analyst",
    ],
    # ── Oracle Cloud ERP (Fusion) ─────────────────────────────────────
    "Oracle Cloud ERP": [
        "Oracle Cloud ERP consultant",
        "Oracle Fusion ERP implementation",
        "Oracle Financials Cloud consultant",
        "Oracle ERP Cloud migration",
        "Oracle Fusion Cloud implementation manager",
        "Oracle Financials Cloud project manager",
        "Oracle Cloud ERP project manager",
        "Oracle Fusion ERP developer",
        "Oracle Cloud ERP functional consultant",
        "Oracle Fusion financials administrator",
    ],
    # ── Oracle E-Business Suite ───────────────────────────────────────
    "Oracle E-Business Suite": [
        "Oracle E-Business Suite consultant",
        "Oracle EBS implementation",
        "Oracle EBS R12 upgrade",
        "Oracle EBS functional consultant",
        "Oracle EBS technical developer",
        "Oracle E-Business Suite project manager",
        "Oracle EBS migration cloud",
        "Oracle EBS financials consultant",
        "Oracle EBS HRMS consultant",
        "Oracle EBS supply chain consultant",
        "Oracle Apps DBA",
        "Oracle EBS database administrator",
    ],
    # ── Oracle PeopleSoft ─────────────────────────────────────────────
    "Oracle PeopleSoft": [
        "Oracle PeopleSoft consultant",
        "PeopleSoft HCM implementation",
        "PeopleSoft Financials consultant",
        "PeopleSoft FSCM consultant",
        "PeopleSoft technical developer",
        "PeopleSoft upgrade consultant",
        "PeopleSoft to Oracle Cloud migration",
        "PeopleSoft campus solutions consultant",
        "PeopleSoft administrator",
        "PeopleSoft project manager",
    ],
    # ── Oracle NetSuite ───────────────────────────────────────────────
    "Oracle NetSuite": [
        "NetSuite implementation consultant",
        "Oracle NetSuite ERP",
        "NetSuite administrator",
        "NetSuite ERP project manager",
        "NetSuite developer",
        "NetSuite functional consultant",
        "NetSuite SuiteScript developer",
        "NetSuite OneWorld implementation",
        "NetSuite ERP migration",
    ],
    # ── Oracle HCM Cloud ─────────────────────────────────────────────
    "Oracle HCM Cloud": [
        "Oracle HCM Cloud consultant",
        "Oracle Fusion HCM implementation",
        "Oracle Global HR Cloud consultant",
        "Oracle HCM Cloud project manager",
        "Oracle Payroll Cloud consultant",
        "Oracle HCM Cloud administrator",
        "Oracle HCM Cloud functional consultant",
        "Oracle Recruiting Cloud consultant",
        "Oracle Learning Cloud consultant",
    ],
    # ── Oracle SCM Cloud ─────────────────────────────────────────────
    "Oracle SCM Cloud": [
        "Oracle SCM Cloud consultant",
        "Oracle Supply Chain Cloud implementation",
        "Oracle Procurement Cloud consultant",
        "Oracle Manufacturing Cloud consultant",
        "Oracle SCM Cloud project manager",
        "Oracle Order Management Cloud consultant",
        "Oracle Inventory Cloud consultant",
        "Oracle OTM consultant",
    ],
}

# ── JDE Manufacturing Focus queries ─────────────────────────────────────────
# Used when "JDE Manufacturing Focus" is enabled in Engine Control.
# These target manufacturing end-users specifically — not staffing/consulting firms.
JDE_MANUFACTURING_QUERIES = [
    # Core JDE manufacturing roles (end-user companies hiring these = implementing JDE)
    "JD Edwards EnterpriseOne manufacturing ERP manager",
    "JDE manufacturing systems administrator",
    "JD Edwards production planning MRP manager",
    "JDE shop floor control work orders director",
    "JD Edwards discrete manufacturing project manager",
    "JDE process manufacturing implementation lead",
    "JD Edwards bill of materials routing engineer",
    "JDE demand planning supply chain manager manufacturing",
    "JD Edwards quality management manufacturing director",
    # Industry verticals — manufacturing companies hiring JDE roles
    "JD Edwards automotive manufacturing ERP",
    "JDE aerospace defense ERP implementation",
    "JD Edwards industrial equipment manufacturer ERP",
    "JDE food beverage manufacturing ERP manager",
    "JD Edwards chemical manufacturing ERP consultant",
    "JDE electronics manufacturer ERP systems",
    "JD Edwards metal fabrication ERP project",
    "JDE plastics rubber manufacturing systems manager",
    "JD Edwards packaging manufacturer ERP",
    "JDE pharmaceutical manufacturing ERP systems",
    # Migration signals — manufacturing companies moving off legacy
    "JD Edwards Oracle Cloud migration manufacturing director",
    "JDE EnterpriseOne upgrade manufacturing company",
    "migrating JDE manufacturing Oracle Cloud project manager",
    "JD Edwards to Oracle Cloud ERP manufacturing",
    # Construction & home building (separate from general JDE)
    "JD Edwards construction job costing project director",
    "JDE EnterpriseOne homebuilder land development",
    "JD Edwards construction procurement manager",
]

NEWS_QUERIES = [
    # Go-live / completion announcements
    "Oracle Cloud ERP go live 2024",
    "Oracle Fusion ERP implementation go live",
    "company selects Oracle Cloud ERP",
    "Oracle Cloud ERP digital transformation announcement",
    "goes live Oracle Cloud ERP enterprise",
    "Oracle ERP implementation completed",
    # HCM
    "Oracle HCM Cloud deployment announcement",
    "Oracle Fusion HCM go live",
    "company implements Oracle HCM Cloud",
    # SCM / EPM
    "Oracle SCM Cloud implementation announcement",
    "Oracle EPM Cloud go live finance",
    "Oracle Planning Cloud implementation",
    # NetSuite
    "NetSuite ERP implementation go live",
    "company migrates to NetSuite ERP",
    "NetSuite cloud ERP announcement",
    # OCI / Database
    "Oracle OCI cloud migration announcement",
    "migrates to Oracle Cloud Infrastructure",
    "Oracle Autonomous Database implementation",
    # Press release / partner signals
    "selects Oracle Cloud ERP announcement press release",
    "Oracle ERP transformation press release 2024",
    "implements Oracle Fusion Cloud applications",
    "Oracle partner implementation success 2024",
    # Industry-specific
    "manufacturing Oracle Cloud ERP implementation",
    "retail Oracle Cloud ERP go live",
    "financial services Oracle Cloud ERP",
    "healthcare Oracle Cloud ERP implementation",
    "public sector Oracle Cloud ERP",
    # Competitive migration
    "SAP to Oracle Cloud migration",
    "migrating from SAP to Oracle",
    "Oracle replaces SAP ERP",
    # JD Edwards news
    "JD Edwards implementation go live",
    "company upgrades JD Edwards EnterpriseOne",
    "JDE ERP transformation announcement",
    "migrating from JD Edwards to Oracle Cloud",
    "JD Edwards digital transformation",
    "JDE EnterpriseOne upgrade announcement",
    "company selects JD Edwards ERP",
    "JDE to Oracle Cloud migration",
    # Oracle E-Business Suite (EBS) news — large legacy install base
    "Oracle E-Business Suite go live implementation",
    "Oracle EBS upgrade announcement",
    "company migrates from Oracle EBS to cloud",
    "Oracle EBS R12 implementation go live",
    "Oracle EBS modernization cloud migration",
    "Oracle EBS digital transformation announcement",
    # PeopleSoft news — HR/Finance, public sector and higher education
    "Oracle PeopleSoft upgrade implementation",
    "PeopleSoft HCM go live announcement",
    "company upgrades PeopleSoft ERP",
    "PeopleSoft to Oracle Cloud migration announcement",
    "PeopleSoft campus solutions implementation",
    "university PeopleSoft implementation go live",
    # Siebel CRM news — telco, insurance, financial services
    "Oracle Siebel CRM upgrade implementation",
    "Siebel to Oracle CX Cloud migration",
    "company replaces Siebel CRM Oracle",
    # Hyperion news — CFO / finance office
    "Oracle Hyperion implementation go live",
    "Oracle Hyperion upgrade announcement",
    "company deploys Oracle Hyperion EPM",
    # Oracle Analytics / BI news
    "Oracle Analytics Cloud implementation",
    "Oracle BI implementation announcement",
    "Oracle Analytics go live company",
]
