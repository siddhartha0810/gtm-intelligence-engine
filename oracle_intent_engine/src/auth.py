"""
auth.py
=======
JWT-based authentication and RBAC for the unified platform.

Roles (lowest → highest privilege):
  viewer      — read-only across all modules
  analyst     — all data modules, no admin functions
  recruitment — recruitment module only (sensitive, gated)
  admin       — full access including user management
  owner       — full access + cannot be demoted by other admins

Flow:
  POST /api/auth/login  → returns { token, user }
  All other /api/* endpoints require  Authorization: Bearer <token>
  FastAPI dependency  require_user()  / require_role("admin")  used per route.

First-time setup:
  If the users table is empty, the first POST /api/auth/register creates
  an owner account (bootstraps the system).
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

import oracle_intent_engine.src.database as db

# ── Configuration ─────────────────────────────────────────────────────────────
_JWT_SECRET = os.environ.get("JWT_SECRET", "")
if not _JWT_SECRET:
    import secrets as _sec
    _JWT_SECRET = _sec.token_hex(32)  # random per-process secret (dev fallback only)
_JWT_ALG     = "HS256"
_TOKEN_HOURS = 12

ROLE_HIERARCHY = {
    "viewer":      0,
    "recruitment": 1,
    "analyst":     2,
    "admin":       3,
    "owner":       4,
}

_bearer = HTTPBearer(auto_error=False)


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── Token helpers ─────────────────────────────────────────────────────────────

def create_token(user_id: int, email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=_TOKEN_HOURS)
    payload = {
        "sub":   str(user_id),
        "email": email,
        "role":  role,
        "exp":   expire,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALG])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
        )


# ── FastAPI dependencies ──────────────────────────────────────────────────────

def _get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Decode JWT and return { id, email, role }.  Raises 401 if missing/invalid."""
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
        )
    payload = decode_token(creds.credentials)
    return {
        "id":    int(payload["sub"]),
        "email": payload["email"],
        "role":  payload["role"],
    }


def require_user(current_user: dict = Depends(_get_current_user)) -> dict:
    """Any authenticated user."""
    return current_user


def require_analyst(current_user: dict = Depends(_get_current_user)) -> dict:
    """analyst, admin, or owner."""
    if ROLE_HIERARCHY.get(current_user["role"], 0) < ROLE_HIERARCHY["analyst"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Analyst role required")
    return current_user


def require_admin(current_user: dict = Depends(_get_current_user)) -> dict:
    """admin or owner only."""
    if ROLE_HIERARCHY.get(current_user["role"], 0) < ROLE_HIERARCHY["admin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return current_user


def require_owner(current_user: dict = Depends(_get_current_user)) -> dict:
    """owner only."""
    if current_user["role"] != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return current_user


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> Optional[dict]:
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM users WHERE email = %s AND is_active = TRUE", (email.lower(),))
        row = cur.fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def create_user(email: str, name: str, password: str, role: str = "analyst") -> dict:
    """Create a new user. First user ever created is always 'owner'."""
    with db.db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM users")
        count = cur.fetchone()["n"]

    effective_role = "owner" if count == 0 else role
    pw_hash = hash_password(password)

    with db.db_cursor() as cur:
        cur.execute(
            """INSERT INTO users (email, name, password_hash, role)
               VALUES (%s, %s, %s, %s)
               RETURNING id, email, name, role, is_active, created_at""",
            (email.lower(), name, pw_hash, effective_role),
        )
        row = cur.fetchone()
    return dict(row)


def update_last_login(user_id: int) -> None:
    with db.db_cursor() as cur:
        cur.execute(
            "UPDATE users SET last_login = NOW() WHERE id = %s", (user_id,)
        )


def list_users() -> list:
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT id, email, name, role, is_active, last_login, created_at
               FROM users ORDER BY created_at""",
        )
        return [dict(r) for r in cur.fetchall()]


def update_user(user_id: int, updates: dict) -> dict:
    allowed = {"name", "role", "is_active"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        raise ValueError("No valid fields to update")
    cols = ", ".join(f"{k} = %({k})s" for k in safe)
    safe["user_id"] = user_id
    safe["updated_at"] = datetime.now(timezone.utc)
    with db.db_cursor() as cur:
        cur.execute(
            f"UPDATE users SET {cols}, updated_at = %(updated_at)s WHERE id = %(user_id)s "
            "RETURNING id, email, name, role, is_active",
            safe,
        )
        row = cur.fetchone()
    return dict(row) if row else {}


def change_password(user_id: int, new_password: str) -> None:
    pw_hash = hash_password(new_password)
    with db.db_cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s, updated_at = NOW() WHERE id = %s",
            (pw_hash, user_id),
        )
