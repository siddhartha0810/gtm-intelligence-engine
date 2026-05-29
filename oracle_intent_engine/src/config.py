import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "oracle_intent")
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

ORACLE_SEARCH_QUERIES = [
    # ── Oracle Cloud ERP (Fusion) ──────────────────────────────────────
    "Oracle Cloud ERP consultant",
    "Oracle Fusion ERP implementation",
    "Oracle Financials Cloud",
    "Oracle ERP Cloud migration",
    "Oracle Fusion Cloud implementation manager",
    "Oracle Financials Cloud project manager",
    # ── Oracle HCM Cloud ──────────────────────────────────────────────
    "Oracle HCM Cloud consultant",
    "Oracle Fusion HCM implementation",
    "Oracle Global HR Cloud",
    "Oracle HCM Cloud project manager",
    "Oracle Payroll Cloud consultant",
    # ── Oracle SCM Cloud ──────────────────────────────────────────────
    "Oracle SCM Cloud consultant",
    "Oracle Supply Chain Cloud implementation",
    "Oracle Procurement Cloud consultant",
    "Oracle Manufacturing Cloud consultant",
    # ── Oracle EPM Cloud ──────────────────────────────────────────────
    "Oracle EPM Cloud consultant",
    "Oracle Hyperion implementation",
    "Oracle Planning Cloud",
    "Oracle Hyperion Financial Management consultant",
    "Oracle Hyperion Planning administrator",
    "Oracle EPM Cloud project manager",
    # ── Oracle CX Cloud ───────────────────────────────────────────────
    "Oracle CX Cloud consultant",
    "Oracle Sales Cloud implementation",
    "Oracle Service Cloud consultant",
    "Oracle CPQ Cloud consultant",
    # ── NetSuite ──────────────────────────────────────────────────────
    "NetSuite implementation consultant",
    "Oracle NetSuite ERP",
    "NetSuite administrator",
    "NetSuite ERP project manager",
    # ── OCI / Infrastructure ──────────────────────────────────────────
    "Oracle Cloud Infrastructure architect",
    "OCI migration consultant",
    "Oracle OCI cloud engineer",
    # ── Oracle Integration ────────────────────────────────────────────
    "Oracle Integration Cloud OIC",
    "Oracle middleware consultant",
    "Oracle SOA Suite integration developer",
    # ── Oracle Database ───────────────────────────────────────────────
    "Oracle Autonomous Database migration",
    "Oracle Database administrator",
    "Oracle Database DBA consultant",
    # ── Oracle E-Business Suite (EBS) — legacy, massive install base ──
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
    # ── Oracle PeopleSoft — HR/Finance, huge public sector base ───────
    "Oracle PeopleSoft consultant",
    "PeopleSoft HCM implementation",
    "PeopleSoft Financials consultant",
    "PeopleSoft FSCM consultant",
    "PeopleSoft technical developer",
    "PeopleSoft upgrade consultant",
    "PeopleSoft to Oracle Cloud migration",
    "PeopleSoft campus solutions consultant",
    # ── Oracle Siebel CRM — legacy, still active in telco/insurance ───
    "Oracle Siebel CRM consultant",
    "Siebel CRM implementation",
    "Siebel to Oracle CX migration",
    "Oracle Siebel developer",
    # ── JD Edwards — core ─────────────────────────────────────────────
    "JD Edwards consultant",
    "JDE EnterpriseOne implementation",
    "JD Edwards ERP upgrade",
    "JDE technical developer",
    "JD Edwards functional consultant",
    "JDE CNC administrator",
    "JD Edwards migration Oracle Cloud",
    "JDE EnterpriseOne support analyst",
    # JD Edwards — Manufacturing
    "JD Edwards manufacturing consultant",
    "JDE MRP work orders bill of materials",
    "JD Edwards shop floor manufacturing ERP",
    "JDE discrete manufacturing implementation",
    # JD Edwards — Construction & Home Building
    "JD Edwards construction ERP consultant",
    "JDE job costing homebuilder",
    "JD Edwards EnterpriseOne construction",
    "JDE land development procurement",
    "JD Edwards home builder ERP",
    # JD Edwards — Energy & Utilities
    "JD Edwards energy oil gas ERP",
    "JDE EnterpriseOne utilities consultant",
    "JD Edwards upstream downstream ERP",
    "JDE energy sector implementation",
    # JD Edwards — Agriculture
    "JD Edwards agriculture ERP consultant",
    "JDE food beverage agribusiness implementation",
    "JD Edwards agricultural distribution",
    # JD Edwards — Distribution & Logistics
    "JD Edwards distribution consultant",
    "JDE inventory procurement sales order",
    "JD Edwards supply chain distribution",
    "JDE wholesale distribution implementation",
    # High-yield queries confirmed working (tested May 2026)
    "JD Edwards 9.2 upgrade",             # 772+ results, very specific version-upgrade intent
    "JD Edwards upgrade project manager",  # 1,000+ results, clear upgrade cycle signal
    "JDE system administrator",            # 6,000+ results, broad but catches active JDE shops
]

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
