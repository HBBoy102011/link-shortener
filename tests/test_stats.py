"""Analytics aggregation and QR code tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
BOT_UA = "python-requests/2.31"


def test_stats_aggregate_clicks(client: TestClient, auth: dict, monkeypatch) -> None:
    """Totals, devices, referers and daily buckets are computed correctly."""
    monkeypatch.setattr(settings, "trusted_proxy", True)
    created = client.post(
        "/api/links",
        json={"url": "https://example.com/campaign"},
        headers=auth,
    ).json()
    code = created["code"]

    visits = [
        ({"user-agent": IPHONE_UA, "referer": "https://news.example/article"}, "203.0.113.9"),
        ({"user-agent": DESKTOP_UA, "referer": "https://www.blog.example/post"}, "198.51.100.7"),
        ({"user-agent": BOT_UA}, "203.0.113.9"),
    ]
    for headers, forwarded in visits:
        response = client.get(
            f"/{code}",
            headers={**headers, "x-forwarded-for": forwarded},
            follow_redirects=False,
        )
        assert response.status_code == 302

    response = client.get(f"/api/links/{created['id']}/stats", headers=auth)
    assert response.status_code == 200
    stats = response.json()

    assert stats["total_clicks"] == 3
    assert stats["unique_visitors"] == 2
    assert stats["first_click_at"] is not None
    assert stats["last_click_at"] is not None
    assert len(stats["days"]) == 30
    assert sum(day["clicks"] for day in stats["days"]) == 3

    devices = {row["device"]: row["clicks"] for row in stats["devices"]}
    assert devices == {"mobile": 1, "desktop": 1, "bot": 1}

    sources = {row["source"]: row["clicks"] for row in stats["referers"]}
    assert sources == {"news.example": 1, "blog.example": 1, "direct": 1}


def test_stats_empty_link(client: TestClient, auth: dict) -> None:
    """A fresh link reports zeros and a full 30-day window."""
    created = client.post(
        "/api/links", json={"url": "https://example.com/nothing"}, headers=auth
    ).json()
    stats = client.get(f"/api/links/{created['id']}/stats", headers=auth).json()

    assert stats["total_clicks"] == 0
    assert stats["unique_visitors"] == 0
    assert stats["first_click_at"] is None
    assert len(stats["days"]) == 30
    assert all(day["clicks"] == 0 for day in stats["days"])
    assert stats["referers"] == []
    assert stats["devices"] == []


def test_stats_require_owner(client: TestClient, make_link) -> None:
    """Analytics are private to the link owner."""
    created = make_link().json()
    response = client.get(f"/api/links/{created['id']}/stats")
    assert response.status_code == 401


def test_qr_code_png(client: TestClient, make_link) -> None:
    """The QR endpoint returns a real PNG image."""
    created = make_link().json()
    response = client.get(f"/api/links/{created['id']}/qr", params={"size": 6})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(response.content) > 200


def test_qr_unknown_link(client: TestClient) -> None:
    """A missing link produces the unified 404 payload."""
    response = client.get("/api/links/99999/qr")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
