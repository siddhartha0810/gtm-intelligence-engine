"""
test_auth.py
============
Tests for authentication and RBAC endpoints.
"""

import pytest


class TestAuthLogin:
    def test_login_success(self, client, auth_token):
        """Valid credentials return token and user object."""
        assert auth_token
        assert len(auth_token) > 20

    def test_login_wrong_password(self, client):
        resp = client.post("/api/auth/login", json={
            "email":    "test-owner@example.com",
            "password": "WrongPassword!",
        })
        assert resp.status_code == 401

    def test_login_unknown_email(self, client):
        resp = client.post("/api/auth/login", json={
            "email":    "nobody@nowhere.com",
            "password": "anything",
        })
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        resp = client.post("/api/auth/login", json={"email": "test@test.com"})
        assert resp.status_code in (400, 401, 422)


class TestAuthMe:
    def test_me_authenticated(self, client, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "email" in data
        assert "password_hash" not in data  # never expose password hash

    def test_me_unauthenticated(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_bad_token(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401


class TestUserManagement:
    def test_list_users_as_admin(self, client, auth_headers):
        resp = client.get("/api/users", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) >= 1

    def test_list_users_unauthenticated(self, client):
        resp = client.get("/api/users")
        assert resp.status_code == 401
