"""Unit tests for the in-memory cache and the rate limiter."""

from __future__ import annotations

import pytest

from app.core.cache import LinkCache
from app.core.rate_limit import RateLimiter


def test_cache_roundtrip() -> None:
    """Values survive a set/get cycle and disappear on delete."""
    cache = LinkCache()
    assert cache.backend == "memory"
    assert cache.get("abc") is None

    cache.set("abc", {"url": "https://example.com"}, ttl_seconds=30)
    assert cache.get("abc") == {"url": "https://example.com"}

    cache.delete("abc")
    assert cache.get("abc") is None


def test_cache_zero_ttl_is_not_stored() -> None:
    """A zero TTL disables caching for that entry."""
    cache = LinkCache()
    cache.set("abc", {"url": "https://example.com"}, ttl_seconds=0)
    assert cache.get("abc") is None


def test_cache_returns_copies() -> None:
    """Callers cannot mutate the cached payload by accident."""
    cache = LinkCache()
    cache.set("abc", {"count": 1}, ttl_seconds=30)
    payload = cache.get("abc")
    assert payload is not None
    payload["count"] = 2
    assert cache.get("abc") == {"count": 1}


def test_cache_clear() -> None:
    """``clear`` forgets every in-process entry."""
    cache = LinkCache()
    cache.set("a", {"x": 1}, ttl_seconds=30)
    cache.set("b", {"x": 2}, ttl_seconds=30)
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_rate_limiter_blocks_after_limit() -> None:
    """The sliding window allows exactly ``limit`` hits and reports retry."""
    limiter = RateLimiter()
    assert limiter.backend == "memory"

    first = limiter.hit("visitor", limit=2, window_seconds=60)
    second = limiter.hit("visitor", limit=2, window_seconds=60)
    third = limiter.hit("visitor", limit=2, window_seconds=60)

    assert first.allowed and first.remaining == 1
    assert second.allowed and second.remaining == 0
    assert not third.allowed
    assert third.retry_after >= 1
    assert third.headers()["Retry-After"] == str(third.retry_after)


def test_rate_limiter_reset() -> None:
    """Resetting clears every counter."""
    limiter = RateLimiter()
    assert limiter.hit("visitor", limit=1).allowed
    assert not limiter.hit("visitor", limit=1).allowed
    limiter.reset()
    assert limiter.hit("visitor", limit=1).allowed


def test_rate_limiter_isolates_visitors() -> None:
    """Different keys do not share a window."""
    limiter = RateLimiter()
    assert limiter.hit("one", limit=1).allowed
    assert limiter.hit("two", limit=1).allowed


def test_production_rejects_placeholder_secrets() -> None:
    """The service refuses to boot in production with example secrets."""
    from pydantic import ValidationError

    from app.core.config import INSECURE_PEPPER, INSECURE_SECRET, Settings

    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            base_url="https://links.example.com",
            secret_key=INSECURE_SECRET,
            ip_hash_pepper="real-pepper",
        )

    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            base_url="https://links.example.com",
            secret_key="real-secret-value",
            ip_hash_pepper=INSECURE_PEPPER,
        )

    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            base_url="http://links.example.com",
            secret_key="real-secret-value",
            ip_hash_pepper="real-pepper",
        )

    settings_ok = Settings(
        environment="production",
        base_url="https://links.example.com",
        secret_key="real-secret-value",
        ip_hash_pepper="real-pepper",
    )
    assert settings_ok.is_production
    assert settings_ok.short_url("abc") == "https://links.example.com/abc"


def test_database_url_is_pinned_to_psycopg3() -> None:
    """Platform-supplied PostgreSQL URLs keep working with psycopg 3 only."""
    from app.core.config import Settings

    for raw in (
        "postgres://user:secret@db:5432/links",
        "postgresql://user:secret@db:5432/links",
    ):
        settings = Settings(database_url=raw)
        assert settings.database_url == "postgresql+psycopg://user:secret@db:5432/links"

    explicit = Settings(database_url="postgresql+psycopg2://user:secret@db/links")
    assert explicit.database_url == "postgresql+psycopg2://user:secret@db/links"

    sqlite = Settings(database_url="sqlite:///./links.db")
    assert sqlite.database_url == "sqlite:///./links.db"
