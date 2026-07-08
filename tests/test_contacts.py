"""
test_contacts.py
================
Tests for contact and enrichment endpoints.

/api/contacts returns a pagination envelope: { total, offset, limit, rows }.
"""

import pytest


def _rows(resp):
    """Unwrap the pagination envelope."""
    data = resp.json()
    assert isinstance(data, dict)
    for key in ("total", "offset", "limit", "rows"):
        assert key in data, f"pagination envelope missing '{key}'"
    assert isinstance(data["rows"], list)
    return data["rows"]


class TestContactsEndpoint:
    def test_get_all_contacts(self, client, auth_headers):
        resp = client.get("/api/contacts", headers=auth_headers)
        assert resp.status_code == 200
        _rows(resp)

    def test_get_contacts_unauthenticated(self, client):
        resp = client.get("/api/contacts")
        assert resp.status_code == 401

    def test_get_contacts_by_company_filter(self, client, auth_headers):
        resp = client.get("/api/contacts?company=example", headers=auth_headers)
        assert resp.status_code == 200
        _rows(resp)

    def test_contact_fields_present(self, client, auth_headers):
        resp = client.get("/api/contacts", headers=auth_headers)
        rows = _rows(resp)
        if not rows:
            pytest.skip("No contacts in database")
        contact = rows[0]
        for field in ["first_name", "last_name", "email", "company_name"]:
            assert field in contact, f"Missing field: {field}"
        # Password hash must never appear in contact response
        assert "password_hash" not in contact


class TestEnrichmentStatus:
    def test_enrich_status_endpoint(self, client, auth_headers):
        resp = client.get("/api/enrich/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    def test_enrich_stats_endpoint(self, client, auth_headers):
        resp = client.get("/api/enrich/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "apollo_configured" in data
        assert "zerobounce_configured" in data

    def test_enrich_preflight(self, client, auth_headers):
        resp = client.get("/api/enrich/preflight", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "from_contacts_master" in data
        assert "need_apollo" in data


class TestSignalContext:
    """The Contacts -> Campaign Builder handoff enrichment."""

    def test_signal_context_requires_auth(self, client):
        resp = client.post("/api/contacts/signal-context", json={"companies": ["Acme"]})
        assert resp.status_code == 401

    def test_signal_context_empty_list(self, client, auth_headers):
        resp = client.post("/api/contacts/signal-context", json={"companies": []},
                           headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"signals": {}}

    def test_signal_context_unknown_company(self, client, auth_headers):
        resp = client.post("/api/contacts/signal-context",
                           json={"companies": ["zz-no-such-company-zz"]},
                           headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["signals"] == {}


class TestImportFields:
    def test_company_import_fields(self, client, auth_headers):
        resp = client.get("/api/import/fields/company", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "fields" in data
        field_keys = [f["value"] for f in data["fields"]]
        assert "name" in field_keys
        assert "domain" in field_keys

    def test_contact_import_fields(self, client, auth_headers):
        resp = client.get("/api/import/fields/contact", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "fields" in data
        field_keys = [f["value"] for f in data["fields"]]
        assert "first_name" in field_keys
        assert "last_name" in field_keys
        assert "email" in field_keys

    def test_import_fields_unauthenticated(self, client):
        resp = client.get("/api/import/fields/company")
        assert resp.status_code == 401
