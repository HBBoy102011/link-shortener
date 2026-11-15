"""Authentication, JWT and account tests."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token


def test_register_returns_token_and_user(client: TestClient) -> None:
    """Registration creates an account and signs the user in."""
    response = client.post(
        "/api/auth/register",
        json={"email": "Mushroom@Example.com", "password": "quiet-forest-42"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == settings.jwt_expire_minutes * 60
    assert data["user"]["email"] == "mushroom@example.com"
    assert "password" not in data["user"]


def test_duplicate_email_is_rejected(client: TestClient, registered_user: dict) -> None:
    """E-mail uniqueness is enforced with a 409 and a stable code."""
    response = client.post(
        "/api/auth/register",
        json={"email": "user@example.com", "password": "another-password"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


def test_short_password_fails_validation(client: TestClient) -> None:
    """Passwords shorter than the configured minimum are rejected."""
    response = client.post(
        "/api/auth/register",
        json={"email": "user@example.com", "password": "short"},
    )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["field"] == "password"


def test_login_success_and_failure(client: TestClient, registered_user: dict) -> None:
    """Login accepts the right password and rejects the wrong one."""
    ok = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "quiet-forest-42"},
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    wrong = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_credentials"

    unknown = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password"},
    )
    assert unknown.status_code == 401
    assert unknown.json()["error"]["code"] == "invalid_credentials"


def test_me_requires_and_accepts_token(client: TestClient, auth: dict) -> None:
    """``/api/auth/me`` reflects the bearer token."""
    missing = client.get("/api/auth/me")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"

    response = client.get("/api/auth/me", headers=auth)
    assert response.status_code == 200
    assert response.json()["email"] == "user@example.com"


def test_garbage_and_expired_tokens_are_rejected(client: TestClient, registered_user: dict) -> None:
    """Invalid and expired JWTs produce distinct error codes."""
    garbage = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert garbage.status_code == 401
    assert garbage.json()["error"]["code"] == "invalid_token"

    expired_token = create_access_token(
        registered_user["user"]["id"], expires_delta=timedelta(seconds=-5)
    )
    expired = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "token_expired"


def test_auth_rate_limit(client: TestClient, monkeypatch) -> None:
    """Repeated login attempts from one visitor are throttled."""
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 2)
    payload = {"email": "nobody@example.com", "password": "wrong-password"}

    assert client.post("/api/auth/login", json=payload).status_code == 401
    assert client.post("/api/auth/login", json=payload).status_code == 401

    blocked = client.post("/api/auth/login", json=payload)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1
