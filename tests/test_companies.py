"""
test_companies.py
=================
Tests for company-related API endpoints.
"""

import pytest


class TestCompaniesEndpoint:
    def test_get_companies_authenticated(self, client, auth_headers):
        resp = client.get("/api/companies", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_companies_unauthenticated(self, client):
        resp = client.get("/api/companies")
        assert resp.status_code == 401

    def test_get_companies_returns_expected_fields(self, client, auth_headers):
        resp = client.get("/api/companies", headers=auth_headers)
        assert resp.status_code == 200
        companies = resp.json()
        if companies:
            company = companies[0]
            assert "name" in company
            assert "domain" in company

    def test_get_companies_phase_filter(self, client, auth_headers):
        resp = client.get("/api/companies?phase=hiring", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_companies_product_filter(self, client, auth_headers):
        resp = client.get("/api/companies?product=JD+Edwards", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestCompanyContacts:
    def test_get_contacts_for_valid_company(self, client, auth_headers):
        # Get the first company ID
        companies = client.get("/api/companies", headers=auth_headers).json()
        if not companies:
            pytest.skip("No companies in database")
        company_id = companies[0]["id"]
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
        companies = client.get("/api/companies", headers=auth_headers).json()
        if not companies:
            pytest.skip("No companies in database")
        company_id = companies[0]["id"]
        for status in ["staged", "pending_review", "approved"]:
            resp = client.patch(
                f"/api/companies/{company_id}/status",
                json={"status": status},
                headers=auth_headers,
            )
            assert resp.status_code == 200, f"Failed for status: {status}"

    def test_invalid_status_rejected(self, client, auth_headers):
        companies = client.get("/api/companies", headers=auth_headers).json()
        if not companies:
            pytest.skip("No companies in database")
        company_id = companies[0]["id"]
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
