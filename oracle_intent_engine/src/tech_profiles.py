"""
tech_profiles.py
================
CRUD operations for Technology Profiles and Product Taxonomy.

Technology Profiles are the root configuration objects that make the
platform multi-product.  Each profile defines:
  - keywords[]          → fed to scrapers and signal classifiers
  - target_websites[]   → domains the scrapers crawl
  - competitor_domains[]→ filtered out of results
  - oracle_products[]   → product names matched by phase classifier
  - manufacturer_domain → domain of the technology vendor

Product Taxonomy rows are children of a profile and provide canonical
product names + aliases for the phase/product classifier.

On first init, a default "Oracle / JDE" profile is seeded automatically
so the existing scrapers keep working without manual configuration.
"""

from typing import Optional
import oracle_intent_engine.src.database as db

# ── Default seed profile ─────────────────────────────────────────────────────
_ORACLE_SEED = {
    "name": "Oracle / JDE",
    "description": "Oracle ERP, JD Edwards, Oracle Cloud, Oracle HCM, Oracle SCM",
    "keywords": [
        # JD Edwards
        "JD Edwards consultant", "JDE EnterpriseOne implementation", "JD Edwards ERP upgrade",
        "JDE technical developer", "JD Edwards functional consultant", "JDE CNC administrator",
        "JD Edwards migration Oracle Cloud", "JDE system administrator",
        "JD Edwards 9.2 upgrade", "JDE upgrade project manager",
        # JDE World
        "JDE World administrator", "JD Edwards World developer", "JDE World upgrade",
        # Oracle Cloud ERP / Fusion
        "Oracle Cloud ERP consultant", "Oracle Fusion ERP implementation",
        "Oracle Financials Cloud", "Oracle ERP Cloud migration",
        "Oracle Fusion Cloud implementation manager",
        # Oracle EBS
        "Oracle E-Business Suite consultant", "Oracle EBS implementation",
        "Oracle EBS R12 upgrade", "Oracle EBS functional consultant",
        "Oracle Apps DBA", "Oracle EBS migration cloud",
        # PeopleSoft
        "Oracle PeopleSoft consultant", "PeopleSoft HCM implementation",
        "PeopleSoft Financials consultant", "PeopleSoft upgrade consultant",
        "PeopleSoft to Oracle Cloud migration",
        # NetSuite
        "NetSuite implementation consultant", "Oracle NetSuite ERP",
        "NetSuite administrator", "NetSuite project manager",
        # Oracle HCM Cloud
        "Oracle HCM Cloud consultant", "Oracle Fusion HCM implementation",
        "Oracle Global HR Cloud", "Oracle HCM Cloud project manager",
        "Oracle Payroll Cloud consultant",
        # Oracle SCM Cloud
        "Oracle SCM Cloud consultant", "Oracle Supply Chain Cloud implementation",
        "Oracle Procurement Cloud consultant", "Oracle Manufacturing Cloud consultant",
    ],
    "target_websites": [
        "oracle.com", "community.oracle.com", "linkedin.com",
        "indeed.com", "glassdoor.com",
    ],
    "competitor_domains": ["sap.com", "workday.com"],
    "partner_domains":    [],
    "manufacturer_domain": "oracle.com",
    "oracle_products": [
        "JD Edwards", "JD Edwards World",
        "Oracle Cloud ERP", "Oracle E-Business Suite", "Oracle PeopleSoft",
        "Oracle NetSuite", "Oracle HCM Cloud", "Oracle SCM Cloud",
    ],
}

# ── Full product taxonomy — 8 products ───────────────────────────────────────
# Three alias tiers per product drive confidence scoring in phase_classifier:
#   Tier 1 (role-specific)  — titles only an end-user company posts.
#                              1 match already = strong signal.
#   Tier 2 (module / version) — module names and version strings confirm
#                              active usage. Good corroboration.
#   Tier 3 (product name)   — broad product name variants. Useful for
#                              initial detection; needs corroboration.
#
# confidence_weight is a per-product multiplier applied on top of the
# keyword-match score in phase_classifier. Higher = classifier trusts
# this product's signal more.

_ORACLE_TAXONOMY_FULL = [

    # ── 1. JD Edwards ────────────────────────────────────────────────────────
    {
        "canonical_name": "JD Edwards",
        "category": "ERP",
        "confidence_weight": 1.0,
        "aliases": [
            # Tier 1 — role-specific (only end-users post these)
            "jde cnc administrator", "jde cnc admin", "enterpriseone cnc",
            "jde basis administrator", "e1 tools administrator",
            "jde orchestrator developer", "jde system administrator",
            "jde security administrator", "jde technical developer",
            "jde functional consultant", "jde finance consultant",
            "jde manufacturing consultant", "jde distribution consultant",
            "jde hr consultant", "jde payroll consultant",
            "jde support analyst", "jde report developer",
            "jde data migration", "jde business analyst",
            "jde solution architect", "jde project manager",
            "e1 developer", "e1 consultant", "jde architect",
            "jde integration developer", "jde analytics developer",
            # Tier 2 — version strings (definitive end-user signals)
            "jde 9.2", "e1 9.2", "jde 9.1", "jde e900", "jde e812",
            "tools release 9.2", "jde 9.2 upgrade", "enterpriseone 9.2",
            # Tier 2 — module names
            "jde distribution", "jde manufacturing", "jde finance",
            "jde payroll", "jde procurement", "jde sales order management",
            "jde service management", "jde shop floor", "jde work orders",
            "jde bill of materials", "jde mrp", "jde demand planning",
            "jde land development", "jde job costing", "jde project costing",
            "jde orchestrator",
            # Tier 3 — product name variants
            "jd edwards enterpriseone", "jde enterpriseone", "jde e1",
            "jd edwards oneworld", "jde oneworld", "jdedwards",
            "jd edwards erp", "jd edwards",
        ],
    },

    # ── 2. JD Edwards World ───────────────────────────────────────────────────
    {
        "canonical_name": "JD Edwards World",
        "category": "ERP",
        "confidence_weight": 1.0,
        "aliases": [
            # Tier 1 — role-specific
            "jde world administrator", "jde world developer",
            "jde world dba", "jde world cnc",
            "jd edwards world developer", "jde world systems analyst",
            # Tier 2 — platform and migration
            "jde as400", "jd edwards as400", "jd edwards as/400", "jde as/400",
            "jde world upgrade", "world to enterpriseone", "jde world to e1",
            "world software jde",
            # Tier 3
            "jde world", "jd edwards world",
        ],
    },

    # ── 3. Oracle Cloud ERP (Fusion) ─────────────────────────────────────────
    {
        "canonical_name": "Oracle Cloud ERP",
        "category": "ERP",
        "confidence_weight": 1.0,
        "aliases": [
            # Tier 1 — role-specific
            "oracle fusion financials consultant", "oracle cloud erp project manager",
            "oracle fusion erp implementation lead", "oracle cloud erp consultant",
            "oracle fusion cloud implementation manager",
            # Tier 2 — module names
            "oracle financials cloud", "oracle general ledger cloud",
            "oracle accounts payable cloud", "oracle accounts receivable cloud",
            "oracle procurement cloud", "oracle fixed assets cloud",
            "oracle project costing cloud", "oracle revenue management cloud",
            "oracle fusion general ledger", "oracle fusion financials",
            "oracle fusion procurement",
            # Tier 3 — product name variants
            "oracle cloud erp", "oracle fusion erp", "oracle erp cloud",
            "fusion erp", "oracle fusion cloud",
        ],
    },

    # ── 4. Oracle E-Business Suite ────────────────────────────────────────────
    {
        "canonical_name": "Oracle E-Business Suite",
        "category": "ERP",
        "confidence_weight": 0.9,
        "aliases": [
            # Tier 1 — role-specific
            "oracle apps dba", "oracle applications dba",
            "oracle ebs system administrator", "oracle ebs technical developer",
            "oracle apps technical developer", "oracle hrms functional consultant",
            "oracle ebs functional consultant", "oracle apps functional consultant",
            # Tier 2 — version strings
            "ebs r12", "oracle apps r12", "oracle ebs r12",
            "oracle 11i", "oracle 11.5.10", "oracle ebs 12.2", "oracle apps 12.2",
            # Tier 2 — module names
            "oracle receivables", "oracle payables",
            "oracle iproc", "oracle iprocurement",
            "oracle ascp", "oracle hrms",
            "oracle advanced supply chain planning",
            "oracle order management ebs", "oracle inventory ebs",
            # Tier 3
            "oracle e-business suite", "oracle ebs", "oracle apps",
            "oracle applications",
        ],
    },

    # ── 5. Oracle PeopleSoft ──────────────────────────────────────────────────
    {
        "canonical_name": "Oracle PeopleSoft",
        "category": "ERP",
        "confidence_weight": 0.9,
        "aliases": [
            # Tier 1 — role-specific
            "peoplesoft dba", "peoplesoft application developer",
            "peoplesoft hrms administrator", "peoplesoft campus solutions administrator",
            "peopletools developer", "peoplesoft technical developer",
            "peoplesoft functional consultant", "peoplesoft systems analyst",
            "peoplesoft security administrator",
            # Tier 2 — module names
            "peoplesoft hcm", "peoplesoft fscm",
            "peoplesoft campus solutions", "peoplesoft financials",
            "peoplesoft payroll", "peoplesoft student records",
            "peoplesoft time and labor", "peoplesoft benefits",
            "peoplesoft absence management",
            # Tier 2 — version / migration
            "peoplesoft 9.2 upgrade", "peoplesoft upgrade",
            "peoplesoft to oracle cloud",
            # Tier 3
            "peoplesoft", "oracle peoplesoft", "ps hcm", "ps fscm",
            "peopletools",
        ],
    },

    # ── 6. Oracle NetSuite ────────────────────────────────────────────────────
    {
        "canonical_name": "Oracle NetSuite",
        "category": "ERP",
        "confidence_weight": 0.8,
        "aliases": [
            # Tier 1 — role-specific
            "netsuite administrator", "netsuite developer",
            "netsuite suitescript developer", "netsuite implementation consultant",
            "netsuite project manager", "netsuite systems administrator",
            "netsuite functional consultant", "netsuite erp consultant",
            # Tier 2 — module names
            "netsuite erp", "netsuite suitecommerce", "netsuite openair",
            "netsuite oneworld", "netsuite advanced revenue management",
            "netsuite arm", "netsuite wms",
            # Tier 3
            "netsuite", "oracle netsuite",
        ],
    },

    # ── 7. Oracle HCM Cloud ───────────────────────────────────────────────────
    {
        "canonical_name": "Oracle HCM Cloud",
        "category": "HCM",
        "confidence_weight": 0.9,
        "aliases": [
            # Tier 1 — role-specific
            "oracle hcm cloud consultant", "oracle fusion hcm implementation",
            "oracle core hr administrator", "oracle hcm cloud project manager",
            "oracle hcm functional consultant",
            # Tier 2 — module names
            "oracle global hr", "oracle payroll cloud",
            "oracle talent management", "oracle workforce compensation",
            "oracle recruiting cloud", "oracle orc",
            "oracle learning cloud", "oracle absence management cloud",
            "oracle benefits cloud", "oracle performance management cloud",
            "oracle succession planning cloud", "oracle time and labor cloud",
            # Tier 3
            "oracle hcm", "oracle hcm cloud", "oracle fusion hcm",
            "oracle human capital management", "fusion hcm",
        ],
    },

    # ── 8. Oracle SCM Cloud ───────────────────────────────────────────────────
    {
        "canonical_name": "Oracle SCM Cloud",
        "category": "SCM",
        "confidence_weight": 0.85,
        "aliases": [
            # Tier 1 — role-specific
            "oracle scm cloud consultant", "oracle supply chain implementation",
            "oracle fusion scm consultant", "oracle scm cloud project manager",
            "oracle supply chain cloud project manager",
            # Tier 2 — module names
            "oracle inventory cloud", "oracle order management cloud",
            "oracle manufacturing cloud", "oracle warehouse management cloud",
            "oracle logistics cloud", "oracle planning cloud scm",
            "oracle transportation management", "oracle otm",
            "oracle quality management cloud",
            # Tier 3
            "oracle scm", "oracle scm cloud", "oracle supply chain cloud",
            "oracle fusion scm", "oracle supply chain management",
        ],
    },
]


def seed_default_profile() -> None:
    """Insert the Oracle/JDE profile and full taxonomy if no profiles exist yet."""
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM technology_profiles")
        if cur.fetchone()["n"] > 0:
            return

    profile = create_profile(**_ORACLE_SEED)
    for t in _ORACLE_TAXONOMY_FULL:
        create_taxonomy(profile["id"], **t)


def reset_taxonomy(profile_id: int = None) -> dict:
    """
    Replace the taxonomy for the given profile (or the first active profile
    if none specified) with the full _ORACLE_TAXONOMY_FULL set.

    Deletes rows whose canonical_name is no longer in the full set, then
    upserts all current rows.  Returns {updated, deleted, profile_id}.
    """
    with db.db_cursor(commit=False) as cur:
        if profile_id:
            cur.execute("SELECT id FROM technology_profiles WHERE id = %s", (profile_id,))
        else:
            cur.execute("SELECT id FROM technology_profiles WHERE is_active = TRUE ORDER BY id LIMIT 1")
        row = cur.fetchone()
    if not row:
        raise ValueError("No active technology profile found")
    pid = row["id"]

    keep_names = {t["canonical_name"] for t in _ORACLE_TAXONOMY_FULL}

    with db.db_cursor() as cur:
        cur.execute(
            "DELETE FROM product_taxonomy WHERE technology_profile_id = %s AND canonical_name <> ALL(%s)",
            (pid, list(keep_names)),
        )
        deleted = cur.rowcount

    updated = 0
    for t in _ORACLE_TAXONOMY_FULL:
        create_taxonomy(pid, **t)
        updated += 1

    return {"updated": updated, "deleted": deleted, "profile_id": pid}


# ── Technology Profile CRUD ───────────────────────────────────────────────────

def list_profiles(active_only: bool = False) -> list:
    where = "WHERE is_active = TRUE" if active_only else ""
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            f"""SELECT tp.*,
                       (SELECT COUNT(*) FROM product_taxonomy pt
                        WHERE pt.technology_profile_id = tp.id AND pt.is_active) AS product_count
                FROM technology_profiles tp
                {where}
                ORDER BY tp.name""",
        )
        return [dict(r) for r in cur.fetchall()]


def get_profile(profile_id: int) -> Optional[dict]:
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM technology_profiles WHERE id = %s", (profile_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def create_profile(
    name: str,
    description: str = "",
    keywords: list = None,
    target_websites: list = None,
    competitor_domains: list = None,
    partner_domains: list = None,
    manufacturer_domain: str = "",
    oracle_products: list = None,
) -> dict:
    with db.db_cursor() as cur:
        cur.execute(
            """INSERT INTO technology_profiles
                   (name, description, keywords, target_websites,
                    competitor_domains, partner_domains, manufacturer_domain, oracle_products)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING *""",
            (
                name, description,
                keywords or [],
                target_websites or [],
                competitor_domains or [],
                partner_domains or [],
                manufacturer_domain,
                oracle_products or [],
            ),
        )
        return dict(cur.fetchone())


def update_profile(profile_id: int, updates: dict) -> dict:
    allowed = {
        "name", "description", "keywords", "target_websites",
        "competitor_domains", "partner_domains", "manufacturer_domain",
        "oracle_products", "is_active",
    }
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        return get_profile(profile_id) or {}
    cols = ", ".join(f"{k} = %({k})s" for k in safe)
    safe["id"] = profile_id
    with db.db_cursor() as cur:
        cur.execute(
            f"UPDATE technology_profiles SET {cols}, updated_at = NOW() WHERE id = %(id)s RETURNING *",
            safe,
        )
        row = cur.fetchone()
    return dict(row) if row else {}


def delete_profile(profile_id: int) -> bool:
    with db.db_cursor() as cur:
        cur.execute("DELETE FROM technology_profiles WHERE id = %s RETURNING id", (profile_id,))
        return cur.fetchone() is not None


# ── Product Taxonomy CRUD ─────────────────────────────────────────────────────

def list_taxonomy(profile_id: int) -> list:
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT * FROM product_taxonomy WHERE technology_profile_id = %s ORDER BY canonical_name",
            (profile_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def create_taxonomy(
    profile_id: int,
    canonical_name: str,
    aliases: list = None,
    category: str = "",
    confidence_weight: float = 1.0,
) -> dict:
    with db.db_cursor() as cur:
        cur.execute(
            """INSERT INTO product_taxonomy
                   (technology_profile_id, canonical_name, aliases, category, confidence_weight)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (technology_profile_id, canonical_name) DO UPDATE SET
                   aliases = EXCLUDED.aliases,
                   category = EXCLUDED.category,
                   confidence_weight = EXCLUDED.confidence_weight,
                   updated_at = NOW()
               RETURNING *""",
            (profile_id, canonical_name, aliases or [], category, confidence_weight),
        )
        return dict(cur.fetchone())


def update_taxonomy(taxonomy_id: int, updates: dict) -> dict:
    allowed = {"canonical_name", "aliases", "category", "confidence_weight", "is_active"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        return {}
    cols = ", ".join(f"{k} = %({k})s" for k in safe)
    safe["id"] = taxonomy_id
    with db.db_cursor() as cur:
        cur.execute(
            f"UPDATE product_taxonomy SET {cols}, updated_at = NOW() WHERE id = %(id)s RETURNING *",
            safe,
        )
        row = cur.fetchone()
    return dict(row) if row else {}


def delete_taxonomy(taxonomy_id: int) -> bool:
    with db.db_cursor() as cur:
        cur.execute("DELETE FROM product_taxonomy WHERE id = %s RETURNING id", (taxonomy_id,))
        return cur.fetchone() is not None


def get_active_keywords() -> list[str]:
    """
    Return all keywords from all active technology profiles.
    Used by scrapers instead of hardcoded keyword lists.
    """
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT DISTINCT unnest(keywords) AS kw FROM technology_profiles WHERE is_active = TRUE"
        )
        return [r["kw"] for r in cur.fetchall()]


def get_active_products() -> list[dict]:
    """
    Return all active products (canonical + aliases) across all active profiles.
    Used by phase_classifier.py and lead_scorer.py.
    Returns: [{ canonical_name, aliases, category, confidence_weight, profile_name }]
    """
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT pt.*, tp.name AS profile_name
               FROM product_taxonomy pt
               JOIN technology_profiles tp ON tp.id = pt.technology_profile_id
               WHERE pt.is_active = TRUE AND tp.is_active = TRUE
               ORDER BY pt.confidence_weight DESC""",
        )
        return [dict(r) for r in cur.fetchall()]


def get_active_search_queries() -> list[str]:
    """
    Returns job-board search queries for all active taxonomy products.

    For each active product:
      - If it has an entry in config.QUERIES_BY_PRODUCT → use those proven queries.
      - If it is a new product not yet in that dict → auto-generate queries from
        its canonical name + aliases using config.generate_queries_for_product().

    Falls back to all QUERIES_BY_PRODUCT entries if the taxonomy is empty or
    the DB is unreachable, so a scan never silently runs with zero queries.
    """
    import logging
    from src import config

    logger = logging.getLogger(__name__)
    products = get_active_products()

    if not products:
        logger.warning("[tech_profiles] taxonomy empty or inactive — falling back to all QUERIES_BY_PRODUCT")
        fallback: list[str] = []
        for qs in config.QUERIES_BY_PRODUCT.values():
            fallback.extend(qs)
        return fallback

    queries: list[str] = []
    seen: set[str] = set()

    for product in products:
        name = product["canonical_name"]
        aliases = product.get("aliases") or []

        if name in config.QUERIES_BY_PRODUCT:
            product_queries = config.QUERIES_BY_PRODUCT[name]
        else:
            product_queries = config.generate_queries_for_product(name, aliases)

        for q in product_queries:
            if q not in seen:
                seen.add(q)
                queries.append(q)

    return queries
