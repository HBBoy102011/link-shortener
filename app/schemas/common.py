"""Shared response schemas, including the unified error envelope."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Machine-readable and human-readable description of a failure."""

    code: str = Field(examples=["not_found"], description="Stable error code.")
    message: str = Field(examples=["This short link does not exist."])
    details: Any | None = Field(default=None, description="Optional structured context.")


class ErrorEnvelope(BaseModel):
    """The only error shape the API returns."""

    error: ErrorDetail


class MessageResponse(BaseModel):
    """Simple informational response."""

    message: str


class HealthResponse(BaseModel):
    """Service health probe."""

    status: str = Field(examples=["ok"])
    database: str = Field(examples=["ok"])
    cache: str = Field(examples=["memory"], description="Active cache backend.")
    rate_limit: str = Field(examples=["memory"], description="Active limiter backend.")
    version: str
