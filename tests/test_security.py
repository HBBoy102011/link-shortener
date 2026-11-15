"""Unit tests for password hashing, tokens and request fingerprints."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest
from starlette.requests import Request

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import (
    burn_password_check,
    client_ip,
    create_access_token,
    decode_access_token,
    hash_ip,
    hash_password,
    verify_password,
)
from app.services.request_info import describe_click, detect_device, extract_source


def make_request(headers: dict[str, str], client: tuple[str, int] = ("1.2.3.4", 5000)) -> Request:
    """Build a minimal Starlette request for unit tests."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "server": ("testserver", 80),
        "client": client,
    }
    return Request(scope)


def test_password_hashing_roundtrip() -> None:
    """Hashes are salted, verifiable and never store the plain password."""
    first = hash_password("quiet-forest-42")
    second = hash_password("quiet-forest-42")
    assert first != second
    assert "quiet-forest-42" not in first
    assert verify_password("quiet-forest-42", first)
    assert verify_password("quiet-forest-42", second)
    assert not verify_password("wrong-password", first)


def test_password_hash_edge_cases() -> None:
    """Missing or corrupt hashes are handled without raising."""
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-bcrypt-hash")
    burn_password_check("anything")  # must not raise


def test_long_passwords_are_supported() -> None:
    """The SHA-256 pre-hash sidesteps bcrypt's 72-byte limit."""
    password = "длинный-пароль-" * 40
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password(password[:-1], hashed)


def test_access_token_roundtrip() -> None:
    """A token created for a subject decodes back to it."""
    token = create_access_token(42)
    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["type"] == "access"


def test_garbage_token_raises_app_error() -> None:
    """Malformed tokens produce a 401 ``invalid_token`` error."""
    with pytest.raises(AppError) as info:
        decode_access_token("not-a-token")
    assert info.value.status_code == 401
    assert info.value.code == "invalid_token"


def test_expired_token_raises_app_error() -> None:
    """Expired tokens produce ``token_expired``."""
    token = create_access_token(7, expires_delta=timedelta(seconds=-1))
    with pytest.raises(AppError) as info:
        decode_access_token(token)
    assert info.value.code == "token_expired"


def test_wrong_token_type_is_rejected() -> None:
    """Refresh-style tokens cannot be used as access tokens."""
    token = jwt.encode(
        {"sub": "1", "type": "refresh", "exp": 9_999_999_999},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AppError) as info:
        decode_access_token(token)
    assert info.value.code == "invalid_token"


def test_hash_ip_is_stable_and_peppered() -> None:
    """IP fingerprints are deterministic, fixed length and distinct."""
    first = hash_ip("203.0.113.9")
    assert first == hash_ip("203.0.113.9")
    assert len(first) == 64
    assert first != hash_ip("198.51.100.7")


def test_client_ip_respects_trusted_proxy(monkeypatch) -> None:
    """Forwarded headers are used only when the proxy is trusted."""
    request = make_request({"x-forwarded-for": "203.0.113.9, 10.0.0.1"})

    monkeypatch.setattr(settings, "trusted_proxy", False)
    assert client_ip(request) == "1.2.3.4"

    monkeypatch.setattr(settings, "trusted_proxy", True)
    assert client_ip(request) == "203.0.113.9"


def test_detect_device() -> None:
    """User-Agent classification covers bots, phones, tablets and desktops."""
    assert detect_device(None) == "other"
    assert detect_device("python-requests/2.31") == "bot"
    assert detect_device("Mozilla/5.0 (compatible; Googlebot/2.1)") == "bot"
    assert detect_device("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)") == "tablet"
    assert detect_device("Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile") == "mobile"
    assert detect_device("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0") == "desktop"


def test_extract_source() -> None:
    """Referers are reduced to a host, with internal links labelled."""
    assert extract_source(None) is None
    assert extract_source("") is None
    assert extract_source("not a url") is None
    assert extract_source("https://www.news.example/article") == "news.example"
    assert extract_source("https://news.example:8443/a") == "news.example"
    assert extract_source("http://testserver/page") == "internal"


def test_describe_click() -> None:
    """The click description carries device, source and a hashed IP."""
    request = make_request(
        {
            "user-agent": "Mozilla/5.0 (iPhone) Mobile/15E148",
            "referer": "https://www.blog.example/post",
        },
        client=("198.51.100.7", 4000),
    )
    info = describe_click(request)
    assert info.device_type == "mobile"
    assert info.referer == "blog.example"
    assert info.ip_hash == hash_ip("198.51.100.7")
    assert info.user_agent is not None and "iPhone" in info.user_agent


def test_describe_click_truncates_long_agent() -> None:
    """Over-long headers are cut to the database column width."""
    request = make_request({"user-agent": "x" * 900})
    info = describe_click(request)
    assert info.user_agent is not None
    assert len(info.user_agent) == 400
