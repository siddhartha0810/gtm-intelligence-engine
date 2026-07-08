"""
test_companies.py
=================
Tests for company-related API endpoints.

/api/companies returns a pagination envelope: { total, offset, limit, rows }.
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


class TestCompaniesEndpoint:
    def test_get_companies_authenticated(self, client, auth_headers):
        resp = client.get("/api/companies", headers=auth_headers)
        assert resp.status_code == 200
        _rows(resp)

    def test_get_companies_unauthenticated(self, client):
        resp = client.get("/api/companies")
        assert resp.status_code == 401

    def test_get_companies_returns_expected_fields(self, client, auth_headers):
        resp = client.get("/api/companies", headers=auth_headers)
        assert resp.status_code == 200
        rows = _rows(resp)
        if rows:
            company = rows[0]
            assert "name" in company
            assert "domain" in company

    def test_get_companies_phase_filter(self, client, auth_headers):
        resp = client.get("/api/companies?phase=hiring", headers=auth_headers)
        assert resp.status_code == 200
        _rows(resp)

    def test_get_companies_product_filter(self, client, auth_headers):
        resp = client.get("/api/companies?product=JD+Edwards", headers=auth_headers)
        assert resp.status_code == 200
        _rows(resp)


class TestCompanyContacts:
    def test_get_contacts_for_valid_company(self, client, auth_headers):
        # Get the first company ID
        rows = _rows(client.get("/api/companies", headers=auth_headers))
        if not rows:
            pytest.skip("No companies in database")
        company_id = rows[0]["id"]
        resp = client.get(f"/api/company/{company_id}/contacts", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_contacts_invalid_company(self, client, auth_headers):
        resp = client.get("/api/company/999999999/contacts", headers=auth_headers)
        # Should return empty list or 404, not 500
        assert resp.status_code in (200, 404)

    def test_get_contacts_unauthenticated(self, client):
        resp = client.get("/api/company/1/contacts")
        assert resp.status_code == 401


class TestCompanyStatus:
    def test_valid_status_values(self, client, auth_headers):
        rows = _rows(client.get("/api/companies", headers=auth_headers))
        if not rows:
            pytest.skip("No companies in database")
        company_id = rows[0]["id"]
        for status in ["staged", "pending_review", "approved"]:
            resp = client.patch(
                f"/api/companies/{company_id}/status",
                json={"status": status},
                headers=auth_headers,
            )
            assert resp.status_code == 200, f"Failed for status: {status}"

    def test_invalid_status_rejected(self, client, auth_headers):
        rows = _rows(client.get("/api/companies", headers=auth_headers))
        if not rows:
            pytest.skip("No companies in database")
        company_id = rows[0]["id"]
        resp = client.patch(
            f"/api/companies/{company_id}/status",
            json={"status": "active"},  # 'active' is not a valid status
            headers=auth_headers,
        )
        assert resp.status_code == 400


class TestProductList:
    def test_products_endpoint(self, client, auth_headers):
        resp = client.get("/api/companies/products", headers=auth_headers)
        assert resp.status_code == 200
        products = resp.json()
        assert isinstance(products, list)
        assert "JD Edwards" in products
