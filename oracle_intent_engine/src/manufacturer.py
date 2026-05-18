"""
manufacturer.py
===============
CRUD for Manufacturer Intelligence — Oracle partner/SI contact tracking
and their links to prospect companies.
"""

from typing import Optional
import oracle_intent_engine.src.database as db


def list_manufacturer_contacts(profile_id: int = None, limit: int = 200) -> list:
    clauses, params = [], []
    if profile_id:
        clauses.append("mc.technology_profile_id = %s")
        params.append(profile_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(min(limit, 500))
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            f"""SELECT mc.*, tp.name AS profile_name,
                       COUNT(ml.id) AS linked_companies
                FROM manufacturer_contacts mc
                LEFT JOIN technology_profiles tp ON tp.id = mc.technology_profile_id
                LEFT JOIN manufacturer_links ml ON ml.manufacturer_contact_id = mc.id
                {where}
                GROUP BY mc.id, tp.name
                ORDER BY mc.company, mc.last_name
                LIMIT %s""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def get_manufacturer_contact(contact_id: int) -> Optional[dict]:
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM manufacturer_contacts WHERE id = %s", (contact_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def create_manufacturer_contact(data: dict) -> dict:
    fields = [
        "first_name", "last_name", "email", "phone", "company", "job_title",
        "technology_profile_id", "oracle_alignment", "oracle_department",
        "oracle_team", "linkedin_url", "source",
    ]
    safe = {f: data.get(f, "") for f in fields}
    safe["technology_profile_id"] = data.get("technology_profile_id") or None
    cols = ", ".join(safe.keys())
    vals = ", ".join(f"%({k})s" for k in safe)
    with db.db_cursor() as cur:
        cur.execute(
            f"INSERT INTO manufacturer_contacts ({cols}) VALUES ({vals}) RETURNING *", safe
        )
        return dict(cur.fetchone())


def update_manufacturer_contact(contact_id: int, updates: dict) -> dict:
    allowed = {
        "first_name", "last_name", "email", "phone", "company", "job_title",
        "technology_profile_id", "oracle_alignment", "oracle_department",
        "oracle_team", "linkedin_url",
    }
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        return get_manufacturer_contact(contact_id) or {}
    cols = ", ".join(f"{k} = %({k})s" for k in safe)
    safe["id"] = contact_id
    with db.db_cursor() as cur:
        cur.execute(
            f"UPDATE manufacturer_contacts SET {cols}, updated_at = NOW() WHERE id = %(id)s RETURNING *",
            safe,
        )
        row = cur.fetchone()
    return dict(row) if row else {}


def delete_manufacturer_contact(contact_id: int) -> bool:
    with db.db_cursor() as cur:
        cur.execute("DELETE FROM manufacturer_contacts WHERE id = %s RETURNING id", (contact_id,))
        return cur.fetchone() is not None


def link_to_company(manufacturer_contact_id: int, company_id: int, link_type: str = "partner") -> dict:
    with db.db_cursor() as cur:
        cur.execute(
            """INSERT INTO manufacturer_links (manufacturer_contact_id, company_id, link_type)
               VALUES (%s,%s,%s)
               ON CONFLICT (manufacturer_contact_id, company_id) DO UPDATE SET link_type = EXCLUDED.link_type
               RETURNING *""",
            (manufacturer_contact_id, company_id, link_type),
        )
        return dict(cur.fetchone())


def unlink_from_company(manufacturer_contact_id: int, company_id: int) -> bool:
    with db.db_cursor() as cur:
        cur.execute(
            "DELETE FROM manufacturer_links WHERE manufacturer_contact_id=%s AND company_id=%s RETURNING id",
            (manufacturer_contact_id, company_id),
        )
        return cur.fetchone() is not None


def get_company_manufacturer_contacts(company_id: int) -> list:
    """All manufacturer/partner contacts linked to a prospect company."""
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT mc.*, ml.link_type
               FROM manufacturer_links ml
               JOIN manufacturer_contacts mc ON mc.id = ml.manufacturer_contact_id
               WHERE ml.company_id = %s
               ORDER BY mc.company, mc.last_name""",
            (company_id,),
        )
        return [dict(r) for r in cur.fetchall()]
