"""
conftest.py
===========
Shared pytest fixtures for the Oracle Intelligence Platform test suite.
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── Path setup (mirrors unified_app.py) ──────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
ORACLE_DIR = BASE_DIR / "oracle_intent_engine"

if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

# Point to a test DB or the real DB — tests use read-only queries where possible
os.environ.setdefault("DB_HOST",     "localhost")
os.environ.setdefault("DB_PORT",     "5432")
os.environ.setdefault("DB_NAME",     "oracle_intent")
os.environ.setdefault("DB_USER",     "postgres")
os.environ.setdefault("DB_PASSWORD", "Inoapps123")
os.environ.setdefault("JWT_SECRET",  "test-secret-key-not-for-production-use-only")

# Suppress subprocess workers during tests
os.environ.setdefault("APOLLO_API_KEY",     "")
os.environ.setdefault("ZEROBOUNCE_API_KEY", "")
os.environ.setdefault("HUBSPOT_API_KEY",    "")


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient — session-scoped so DB init runs once."""
    from unified_app import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def auth_token(client):
    """Register (or login) a test owner and return a valid JWT token."""
    # Try login first (user may already exist from a previous run)
    resp = client.post("/api/auth/login", json={
        "email":    "test-owner@inoapps.com",
        "password": "TestPass123!",
    })
    if resp.status_code == 200:
        return resp.json()["token"]

    # First run — register
    resp = client.post("/api/auth/register", json={
        "email":    "test-owner@inoapps.com",
        "name":     "Test Owner",
        "password": "TestPass123!",
        "role":     "owner",
    })
    assert resp.status_code == 200, f"Registration failed: {resp.text}"
    return resp.json()["token"]


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    """Authorization headers for authenticated requests."""
    return {"Authorization": f"Bearer {auth_token}"}
