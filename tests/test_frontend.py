"""Health, documentation and static dashboard tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    """The probe reports the database and active backends."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert data["cache"] == "memory"
    assert data["rate_limit"] == "memory"
    assert data["version"]


def test_openapi_and_docs(client: TestClient) -> None:
    """Swagger and the OpenAPI document are served."""
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger" in docs.text.lower()

    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    for path in ("/api/auth/register", "/api/links", "/{code}", "/api/links/{link_id}/stats"):
        assert path in paths


def test_dashboard_is_served(client: TestClient) -> None:
    """The root page and its assets are available."""
    page = client.get("/")
    assert page.status_code == 200
    assert "Link Shortener" in page.text
    assert "text/html" in page.headers["content-type"]

    styles = client.get("/static/styles.css")
    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]


def test_favicon_returns_no_content(client: TestClient) -> None:
    """Browsers get a quiet 204 for the favicon."""
    assert client.get("/favicon.ico").status_code == 204


def test_unknown_api_path_uses_error_envelope(client: TestClient) -> None:
    """Framework 404s are normalised like every other error."""
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "not_found"


def test_invalid_path_parameter(client: TestClient, auth: dict) -> None:
    """Non-numeric link ids produce validation details."""
    response = client.get("/api/links/not-a-number", headers=auth)
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["field"] == "link_id"
