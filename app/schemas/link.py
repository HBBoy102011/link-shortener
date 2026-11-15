"""Schemas for creating, listing and returning short links."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.core.config import settings

#: Allowed characters for user-supplied aliases.
CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class LinkCreateRequest(BaseModel):
    """Payload for creating a short link."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "url": "https://example.com/a/very/long/path?utm_source=newsletter",
                    "custom_code": "my-resume",
                    "expires_at": "2030-01-01T00:00:00Z",
                    "password": None,
                }
            ]
        }
    )

    url: HttpUrl = Field(description="Original absolute http(s) URL.")
    custom_code: str | None = Field(
        default=None,
        description=(
            f"Optional alias of {settings.min_custom_code_length}-"
            f"{settings.max_custom_code_length} characters (letters, digits, - and _)."
        ),
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiry moment; afterwards the link returns 410 Gone.",
    )
    password: str | None = Field(
        default=None,
        min_length=4,
        max_length=128,
        description="Optional password that visitors must provide.",
    )

    @field_validator("url")
    @classmethod
    def _limit_url_length(cls, value: HttpUrl) -> HttpUrl:
        """Reject very long URLs before they reach the database."""
        if len(str(value)) > settings.max_url_length:
            raise ValueError(f"URL must be at most {settings.max_url_length} characters.")
        return value

    @field_validator("custom_code")
    @classmethod
    def _validate_custom_code(cls, value: str | None) -> str | None:
        """Check alias characters and length."""
        if value is None:
            return None
        code = value.strip()
        if not CODE_PATTERN.fullmatch(code):
            raise ValueError("Code may contain only letters, digits, '-' and '_'.")
        if not settings.min_custom_code_length <= len(code) <= settings.max_custom_code_length:
            raise ValueError(
                f"Code length must be between {settings.min_custom_code_length} and "
                f"{settings.max_custom_code_length}."
            )
        return code

    @field_validator("expires_at")
    @classmethod
    def _validate_expiry(cls, value: datetime | None) -> datetime | None:
        """Require expiry to be in the future and timezone-aware."""
        if value is None:
            return None
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        moment = moment.astimezone(UTC)
        if moment <= datetime.now(UTC):
            raise ValueError("Expiry must be in the future.")
        return moment


class LinkResponse(BaseModel):
    """Public representation of a short link."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    short_url: str
    original_url: str
    created_at: datetime
    expires_at: datetime | None = None
    is_active: bool = True
    has_password: bool = False
    clicks: int = 0
    qr_url: str


class LinkListResponse(BaseModel):
    """Paginated list of the authenticated user's links."""

    items: list[LinkResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
