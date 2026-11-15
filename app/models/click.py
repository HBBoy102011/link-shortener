"""Click event model used for analytics."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import utcnow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.link import Link


class Click(Base):
    """One recorded visit of a short link.

    Only a peppered hash of the visitor IP is stored, never the address
    itself, which keeps analytics useful while respecting privacy.
    """

    __tablename__ = "clicks"
    __table_args__ = (Index("ix_clicks_link_clicked", "link_id", "clicked_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    link_id: Mapped[int] = mapped_column(
        ForeignKey("links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    referer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    device_type: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    link: Mapped[Link] = relationship(back_populates="clicks")

    def __repr__(self) -> str:
        """Return a debug representation."""
        return f"<Click id={self.id} link_id={self.link_id} device={self.device_type!r}>"
