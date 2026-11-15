"""Short link creation, validation, redirects and ownership tests."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.base import utcnow
from app.models.link import Link


def test_anonymous_link_creation(client: TestClient) -> None:
    """Visitors without an account can shorten a URL."""
    response = client.post("/api/links", json={"url": "https://example.com/hello"})
    assert response.status_code == 201
    data = response.json()
    assert len(data["code"]) == settings.short_code_length
    assert data["short_url"] == f"http://testserver/{data['code']}"
    assert data["clicks"] == 0
    assert data["is_active"] is True
    assert data["has_password"] is False
    assert data["qr_url"].endswith(f"/api/links/{data['id']}/qr")


def test_custom_alias(client: TestClient, auth: dict) -> None:
    """A free custom alias is preserved verbatim."""
    response = client.post(
        "/api/links",
        json={"url": "https://example.com/cv", "custom_code": "my-resume"},
        headers=auth,
    )
    assert response.status_code == 201
    assert response.json()["code"] == "my-resume"
    assert response.json()["short_url"] == "http://testserver/my-resume"


def test_duplicate_alias_conflicts(client: TestClient, auth: dict) -> None:
    """Taking an alias twice returns 409 with the alias in details."""
    payload = {"url": "https://example.com/a", "custom_code": "same-code"}
    assert client.post("/api/links", json=payload, headers=auth).status_code == 201

    duplicate = client.post(
        "/api/links",
        json={"url": "https://example.com/b", "custom_code": "same-code"},
        headers=auth,
    )
    assert duplicate.status_code == 409
    body = duplicate.json()["error"]
    assert body["code"] == "code_taken"
    assert body["details"]["custom_code"] == "same-code"


def test_reserved_alias_is_rejected(client: TestClient, auth: dict) -> None:
    """Aliases that would shadow service routes are refused."""
    response = client.post(
        "/api/links",
        json={"url": "https://example.com/a", "custom_code": "docs"},
        headers=auth,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "reserved_code"


def test_self_reference_is_rejected(client: TestClient) -> None:
    """Links pointing back at the shortener would create a loop."""
    response = client.post("/api/links", json={"url": "http://testserver/abc123"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "self_reference"


def test_invalid_urls_fail_validation(client: TestClient) -> None:
    """Only absolute http(s) URLs are accepted."""
    for url in ("ftp://example.com/file", "not-a-url", ""):
        response = client.post("/api/links", json={"url": url})
        assert response.status_code == 422, url
        assert response.json()["error"]["code"] == "validation_error"


def test_expiry_must_be_in_the_future(client: TestClient) -> None:
    """A past expiry timestamp is a validation error."""
    response = client.post(
        "/api/links",
        json={"url": "https://example.com/a", "expires_at": "2001-01-01T00:00:00Z"},
    )
    assert response.status_code == 422
    assert "expires_at" in response.json()["error"]["details"][0]["field"]


def test_redirect_records_location(client: TestClient) -> None:
    """Following a code redirects with 302 to the original URL."""
    created = client.post("/api/links", json={"url": "https://example.com/target"}).json()
    response = client.get(f"/{created['code']}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/target"
    assert response.headers["cache-control"] == "no-store"


def test_unknown_code_is_404(client: TestClient) -> None:
    """Unknown codes and unsupported methods use the unified error shape."""
    response = client.get("/missing-code")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]

    method = client.post("/missing-code")
    assert method.status_code == 405
    assert method.json()["error"]["code"] == "method_not_allowed"


def test_expired_link_returns_410(client: TestClient, auth: dict, session: Session) -> None:
    """Expired links stay in the database but answer with 410 Gone."""
    created = client.post(
        "/api/links",
        json={"url": "https://example.com/old", "custom_code": "old-link"},
        headers=auth,
    ).json()

    session.execute(
        update(Link).where(Link.code == "old-link").values(expires_at=utcnow() - timedelta(days=1))
    )
    session.commit()

    response = client.get(f"/{created['code']}")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "link_expired"


def test_password_protected_link(client: TestClient) -> None:
    """Protected links require the correct password before redirecting."""
    created = client.post(
        "/api/links",
        json={"url": "https://example.com/secret", "password": "forest"},
    ).json()
    assert created["has_password"] is True

    missing = client.get(f"/{created['code']}", follow_redirects=False)
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "password_required"

    wrong = client.get(f"/{created['code']}", params={"password": "meadow"}, follow_redirects=False)
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_password"

    correct = client.get(
        f"/{created['code']}", params={"password": "forest"}, follow_redirects=False
    )
    assert correct.status_code == 302
    assert correct.headers["location"] == "https://example.com/secret"


def test_list_requires_authentication(client: TestClient) -> None:
    """The personal cabinet is private."""
    response = client.get("/api/links")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_list_shows_own_links_with_counts(client: TestClient, auth: dict, make_link) -> None:
    """The list contains the caller's links and their click counters."""
    created = make_link(headers=auth).json()
    client.get(f"/{created['code']}", follow_redirects=False)
    client.get(f"/{created['code']}", follow_redirects=False)

    response = client.get("/api/links", headers=auth)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["items"][0]["clicks"] == 2


def test_pagination(client: TestClient, auth: dict, make_link) -> None:
    """Links are paginated with a stable page size."""
    for index in range(3):
        make_link(headers=auth, custom_code=f"page-{index}")

    first = client.get("/api/links", params={"page": 1, "page_size": 2}, headers=auth)
    assert len(first.json()["items"]) == 2
    assert first.json()["total"] == 3

    second = client.get("/api/links", params={"page": 2, "page_size": 2}, headers=auth)
    assert len(second.json()["items"]) == 1


def test_other_users_links_are_invisible(
    client: TestClient, auth: dict, other_auth: dict, make_link
) -> None:
    """Another account cannot read or delete someone else's link."""
    created = make_link(headers=auth).json()

    assert client.get(f"/api/links/{created['id']}", headers=other_auth).status_code == 404
    assert client.get(f"/api/links/{created['id']}/stats", headers=other_auth).status_code == 404
    assert client.delete(f"/api/links/{created['id']}", headers=other_auth).status_code == 404

    owned = client.get(f"/api/links/{created['id']}", headers=auth)
    assert owned.status_code == 200
    assert owned.json()["code"] == created["code"]


def test_delete_removes_link_and_cache(client: TestClient, auth: dict, make_link) -> None:
    """Deletion answers 204 and invalidates the cached redirect."""
    created = make_link(headers=auth).json()
    assert client.get(f"/{created['code']}", follow_redirects=False).status_code == 302

    deleted = client.delete(f"/api/links/{created['id']}", headers=auth)
    assert deleted.status_code == 204

    assert client.get(f"/{created['code']}").status_code == 404
    assert client.get(f"/api/links/{created['id']}", headers=auth).status_code == 404


def test_create_rate_limit(client: TestClient, monkeypatch) -> None:
    """Link creation is limited per visitor."""
    monkeypatch.setattr(settings, "rate_limit_create_per_minute", 2)
    payload = {"url": "https://example.com/limited"}

    assert client.post("/api/links", json=payload).status_code == 201
    assert client.post("/api/links", json=payload).status_code == 201

    blocked = client.post("/api/links", json=payload)
    assert blocked.status_code == 429
    body = blocked.json()["error"]
    assert body["code"] == "rate_limited"
    assert body["details"]["retry_after"] >= 1
    assert blocked.headers["X-RateLimit-Limit"] == "2"
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
