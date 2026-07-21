"""
events.py
=========
CRUD for Events Intelligence — event registry and attendee tagging.
"""

from typing import Optional
import intent_engine.src.database as db


def list_events(profile_id: int = None, limit: int = 100) -> list:
    clauses, params = [], []
    if profile_id:
        clauses.append("e.technology_profile_id = %s")
        params.append(profile_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(min(limit, 500))
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            f"""SELECT e.*,
                       tp.name AS profile_name,
                       COUNT(ea.id) AS attendee_count_actual
                FROM events e
                LEFT JOIN technology_profiles tp ON tp.id = e.technology_profile_id
                LEFT JOIN event_attendees ea ON ea.event_id = e.id
                {where}
                GROUP BY e.id, tp.name
                ORDER BY e.event_date DESC NULLS LAST
                LIMIT %s""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def get_event(event_id: int) -> Optional[dict]:
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def create_event(
    name: str,
    event_type: str = "conference",
    technology_profile_id: int = None,
    location: str = "",
    event_date: str = None,
    description: str = "",
    attendee_count: int = 0,
) -> dict:
    with db.db_cursor() as cur:
        cur.execute(
            """INSERT INTO events
                   (name, event_type, technology_profile_id, location,
                    event_date, description, attendee_count)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               RETURNING *""",
            (name, event_type, technology_profile_id, location,
             event_date or None, description, attendee_count),
        )
        return dict(cur.fetchone())


def update_event(event_id: int, updates: dict) -> dict:
    allowed = {"name", "event_type", "technology_profile_id", "location",
               "event_date", "description", "attendee_count"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        return get_event(event_id) or {}
    cols = ", ".join(f"{k} = %({k})s" for k in safe)
    safe["id"] = event_id
    with db.db_cursor() as cur:
        cur.execute(
            f"UPDATE events SET {cols}, updated_at = NOW() WHERE id = %(id)s RETURNING *", safe
        )
        row = cur.fetchone()
    return dict(row) if row else {}


def delete_event(event_id: int) -> bool:
    with db.db_cursor() as cur:
        cur.execute("DELETE FROM events WHERE id = %s RETURNING id", (event_id,))
        return cur.fetchone() is not None


def list_attendees(event_id: int) -> list:
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT ea.*, cc.first_name, cc.last_name, cc.title,
                       cc.email, c.name AS company_name
                FROM event_attendees ea
                JOIN company_contacts cc ON cc.id = ea.contact_id
                JOIN companies c ON c.id = cc.company_id
                WHERE ea.event_id = %s
                ORDER BY cc.last_name""",
            (event_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def add_attendee(event_id: int, contact_id: int, role: str = "attendee") -> dict:
    with db.db_cursor() as cur:
        cur.execute(
            """INSERT INTO event_attendees (event_id, contact_id, role)
               VALUES (%s,%s,%s)
               ON CONFLICT (event_id, contact_id) DO UPDATE SET role = EXCLUDED.role
               RETURNING *""",
            (event_id, contact_id, role),
        )
        return dict(cur.fetchone())


def remove_attendee(event_id: int, contact_id: int) -> bool:
    with db.db_cursor() as cur:
        cur.execute(
            "DELETE FROM event_attendees WHERE event_id = %s AND contact_id = %s RETURNING id",
            (event_id, contact_id),
        )
        return cur.fetchone() is not None


def get_contact_events(contact_id: int) -> list:
    """All events a contact has attended — used to boost lead score."""
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT e.*, ea.role
               FROM event_attendees ea
               JOIN events e ON e.id = ea.event_id
               WHERE ea.contact_id = %s
               ORDER BY e.event_date DESC""",
            (contact_id,),
        )
        return [dict(r) for r in cur.fetchall()]
