"""
audit.py
========
Immutable audit logging — every create / update / delete writes a row
to audit_logs.  Call log_audit() at the end of any mutation endpoint.

Usage:
    from src.audit import log_audit
    log_audit(user, "create", "company", str(company_id), new_value={"name": ...})
    log_audit(user, "delete", "contact", str(contact_id))
    log_audit(user, "push_hubspot", "company", str(company_id))
"""

import json
import traceback
from typing import Any, Optional

import intent_engine.src.database as db
from intent_engine.src.utils import get_logger

logger = get_logger(__name__)


def log_audit(
    user: Optional[dict],
    action: str,
    entity_type: str,
    entity_id: str = "",
    old_value: Any = None,
    new_value: Any = None,
    ip_address: str = "",
) -> None:
    """
    Write one immutable row to audit_logs.
    Never raises — errors are logged to the application logger only,
    so a failed audit write never breaks the primary request.
    """
    try:
        user_id    = user["id"]    if user else None
        user_email = user["email"] if user else "system"

        def _to_jsonb(v) -> Optional[str]:
            if v is None:
                return None
            if isinstance(v, str):
                return v
            return json.dumps(v, default=str)

        with db.db_cursor() as cur:
            cur.execute(
                """INSERT INTO audit_logs
                       (user_id, user_email, action, entity_type, entity_id,
                        old_value, new_value, ip_address)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    user_id,
                    user_email,
                    action,
                    entity_type,
                    entity_id,
                    _to_jsonb(old_value),
                    _to_jsonb(new_value),
                    ip_address,
                ),
            )
    except Exception:
        logger.warning("audit_log write failed:\n%s", traceback.format_exc())


def get_audit_logs(
    entity_type: str = "",
    entity_id: str = "",
    user_email: str = "",
    action: str = "",
    limit: int = 200,
    offset: int = 0,
) -> list:
    """Fetch audit log rows with optional filters."""
    clauses = []
    params: list = []

    if entity_type:
        clauses.append("entity_type = %s")
        params.append(entity_type)
    if entity_id:
        clauses.append("entity_id = %s")
        params.append(entity_id)
    if user_email:
        clauses.append("user_email ILIKE %s")
        params.append(f"%{user_email}%")
    if action:
        clauses.append("action ILIKE %s")
        params.append(f"%{action}%")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params += [min(limit, 500), max(offset, 0)]

    with db.db_cursor(commit=False) as cur:
        cur.execute(
            f"""SELECT id, user_id, user_email, action, entity_type, entity_id,
                       old_value, new_value, ip_address,
                       created_at::text AS created_at
                FROM audit_logs
                {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]
