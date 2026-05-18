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

# ── Default seed profile — mirrors current hardcoded Oracle/JDE config ────────
_ORACLE_SEED = {
    "name": "Oracle / JDE",
    "description": "Oracle ERP, JD Edwards, Oracle Cloud, Oracle HCM, Oracle SCM",
    "keywords": [
        "JD Edwards", "JDE", "JDE EnterpriseOne", "Oracle ERP", "Oracle Cloud",
        "Oracle Fusion", "Oracle EBS", "Oracle HCM", "Oracle SCM", "Oracle EPM",
        "Oracle NetSuite", "Oracle E-Business Suite", "Oracle Financials",
        "ERP implementation", "ERP upgrade", "ERP consultant",
    ],
    "target_websites": [
        "oracle.com", "community.oracle.com", "linkedin.com",
        "indeed.com", "glassdoor.com",
    ],
    "competitor_domains": ["sap.com", "workday.com", "netsuite.com"],
    "partner_domains":    ["inoapps.com"],
    "manufacturer_domain": "oracle.com",
    "oracle_products": [
        "Oracle ERP", "JD Edwards", "Oracle Cloud", "Oracle HCM",
        "Oracle SCM", "Oracle EPM", "Oracle EBS", "Oracle NetSuite",
        "Oracle Fusion", "Oracle E-Business Suite",
    ],
}

_ORACLE_TAXONOMY = [
    {"canonical_name": "JD Edwards EnterpriseOne", "aliases": ["JDE", "JDE E1", "EnterpriseOne", "JD Edwards"],           "category": "ERP",     "confidence_weight": 1.0},
    {"canonical_name": "Oracle Cloud ERP",          "aliases": ["Oracle Cloud", "Oracle Fusion ERP", "Fusion ERP"],         "category": "ERP",     "confidence_weight": 1.0},
    {"canonical_name": "Oracle E-Business Suite",   "aliases": ["Oracle EBS", "EBS", "Oracle Financials"],                  "category": "ERP",     "confidence_weight": 0.9},
    {"canonical_name": "Oracle HCM Cloud",          "aliases": ["Oracle HCM", "HCM Cloud", "Oracle HR"],                    "category": "HCM",     "confidence_weight": 0.9},
    {"canonical_name": "Oracle SCM Cloud",          "aliases": ["Oracle SCM", "SCM Cloud", "Oracle Supply Chain"],           "category": "SCM",     "confidence_weight": 0.85},
    {"canonical_name": "Oracle EPM Cloud",          "aliases": ["Oracle EPM", "EPM Cloud", "Oracle Planning"],               "category": "EPM",     "confidence_weight": 0.85},
    {"canonical_name": "Oracle NetSuite",           "aliases": ["NetSuite", "Oracle Netsuite", "Netsuite ERP"],              "category": "ERP",     "confidence_weight": 0.8},
    {"canonical_name": "Oracle Database",           "aliases": ["Oracle DB", "Oracle RDBMS", "Oracle 19c", "Oracle 21c"],   "category": "DB",      "confidence_weight": 0.7},
]


def seed_default_profile() -> None:
    """Insert the Oracle/JDE profile if no profiles exist yet."""
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM technology_profiles")
        if cur.fetchone()["n"] > 0:
            return

    profile = create_profile(**_ORACLE_SEED)
    for t in _ORACLE_TAXONOMY:
        create_taxonomy(profile["id"], **t)


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
