"""Analytics response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DayClicks(BaseModel):
    """Clicks recorded on one calendar day."""

    date: str = Field(description="ISO date, e.g. 2026-05-01.")
    clicks: int = Field(ge=0)


class SourceClicks(BaseModel):
    """Clicks coming from one referer host."""

    source: str = Field(description="Referer host or 'direct'.")
    clicks: int = Field(ge=0)


class DeviceClicks(BaseModel):
    """Clicks from one device class parsed from the User-Agent."""

    device: str = Field(description="desktop, mobile, tablet, bot or other.")
    clicks: int = Field(ge=0)


class LinkStats(BaseModel):
    """Aggregated analytics for a single short link."""

    link_id: int
    code: str
    short_url: str
    original_url: str
    total_clicks: int = Field(ge=0)
    unique_visitors: int = Field(ge=0)
    first_click_at: datetime | None = None
    last_click_at: datetime | None = None
    created_at: datetime
    expires_at: datetime | None = None
    days: list[DayClicks] = Field(
        default_factory=list,
        description="Clicks per day for the last 30 days, oldest first.",
    )
    referers: list[SourceClicks] = Field(default_factory=list)
    devices: list[DeviceClicks] = Field(default_factory=list)
