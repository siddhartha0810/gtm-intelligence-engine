"""
test_contacts.py
================
Tests for contact and enrichment endpoints.
"""

import pytest


class TestContactsEndpoint:
    def test_get_all_contacts(self, client, auth_headers):
        resp = client.get("/api/contacts", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_contacts_unauthenticated(self, client):
        resp = client.get("/api/contacts")
        assert resp.status_code == 401

    def test_get_contacts_by_company_filter(self, client, auth_headers):
        resp = client.get("/api/contacts?company=example", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_contact_fields_present(self, client, auth_headers):
        resp = client.get("/api/contacts", headers=auth_headers)
        contacts = resp.json()
        if not contacts:
            pytest.skip("No contacts in database")
        contact = contacts[0]
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


class TestImportFields:
    def test_company_import_fields(self, client):
        resp = client.get("/api/import/fields/company")
        assert resp.status_code == 200
        data = resp.json()
        assert "fields" in data
        field_keys = [f["value"] for f in data["fields"]]
        assert "name" in field_keys
        assert "domain" in field_keys

    def test_contact_import_fields(self, client):
        resp = client.get("/api/import/fields/contact")
        assert resp.status_code == 200
        data = resp.json()
        assert "fields" in data
        field_keys = [f["value"] for f in data["fields"]]
        assert "first_name" in field_keys
        assert "last_name" in field_keys
        assert "email" in field_keys
