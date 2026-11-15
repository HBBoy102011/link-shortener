"""Shared helpers for ORM models: UTC timestamps and safe comparisons."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def ensure_aware(value: datetime | None) -> datetime | None:
    """Attach UTC to naive datetimes (SQLite drops the timezone)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
