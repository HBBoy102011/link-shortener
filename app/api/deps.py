"""Shared FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

from app.core.database import get_db
from app.core.security import get_current_user, get_optional_user

__all__ = ["Pagination", "get_current_user", "get_db", "get_optional_user", "pagination"]


@dataclass(frozen=True)
class Pagination:
    """Validated page window for list endpoints."""

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        """Return the SQL offset."""
        return (self.page - 1) * self.page_size


def pagination(
    page: int = Query(default=1, ge=1, le=10_000, description="1-based page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
) -> Pagination:
    """Validate the pagination query parameters."""
    return Pagination(page=page, page_size=page_size)
