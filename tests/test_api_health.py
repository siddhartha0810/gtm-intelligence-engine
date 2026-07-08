"""
test_api_health.py
==================
Smoke tests — verify the server starts, core routes respond,
and no endpoint leaks credentials or internal errors by default.
"""

import pytest


class TestServerHealth:
    def test_root_returns_html(self, client):
        """Root path should return the React SPA or fallback HTML."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_docs_available(self, client):
        """FastAPI auto-docs should be reachable."""
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_schema(self, client):
        """OpenAPI JSON schema should be valid."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema
        assert "info" in schema


class TestConfigEndpoint:
    def test_config_authenticated(self, client, auth_headers):
        resp = client.get("/config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "apollo_key" in data
        assert "zb_key" in data

    def test_config_unauthenticated(self, client):
        resp = client.get("/config")
        assert resp.status_code == 401

    def test_config_does_not_expose_keys(self, client, auth_headers):
        """Config endpoint must return booleans, not actual key values."""
        resp = client.get("/config", headers=auth_headers)
        data = resp.json()
        # Values should be booleans not actual key strings
        assert isinstance(data.get("apollo_key"), bool)
        assert isinstance(data.get("zb_key"), bool)


class TestScanEndpoints:
    def test_scan_status(self, client, auth_headers):
        resp = client.get("/scan/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("idle", "running")

    def test_scan_log(self, client, auth_headers):
        resp = client.get("/scan/log", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_scan_start_unauthenticated(self, client):
        resp = client.post("/scan/start")
        assert resp.status_code == 401


class TestDashboard:
    def test_dashboard_authenticated(self, client, auth_headers):
        resp = client.get("/api/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "companies_tracked" in data
        assert "contacts_enriched" in data
        assert "intent_signals" in data
        assert "pushed_to_hubspot" in data

    def test_dashboard_unauthenticated(self, client):
        resp = client.get("/api/dashboard")
        assert resp.status_code == 401


class TestAuditLogs:
    def test_audit_logs_accessible(self, client, auth_headers):
        resp = client.get("/api/audit-logs", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_audit_logs_unauthenticated(self, client):
        resp = client.get("/api/audit-logs")
        assert resp.status_code == 401


class TestDataQualityEngine:
    def test_dqe_requires_auth(self, client):
        resp = client.post("/api/dqe/check/company", json={"name": "X"})
        assert resp.status_code == 401

    def test_dqe_company_check(self, client, auth_headers):
        resp = client.post("/api/dqe/check/company", json={
            "name": "Test Company Ltd",
            "domain": "testcompany.com",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "issues" in data
        assert "has_critical" in data

    def test_dqe_contact_check(self, client, auth_headers):
        resp = client.post("/api/dqe/check/contact", json={
            "first_name": "John",
            "last_name": "Smith",
            "email": "john.smith@testcompany.com",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "issues" in data

    def test_dqe_empty_company_name(self, client, auth_headers):
        resp = client.post("/api/dqe/check/company", json={"name": ""}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Empty name should flag a critical issue
        assert data["has_critical"] is True
