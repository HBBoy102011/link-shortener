"""Short link model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import utcnow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.click import Click
    from app.models.user import User


class Link(Base):
    """A short code that redirects to an original URL."""

    __tablename__ = "links"
    __table_args__ = (Index("ix_links_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    owner: Mapped[User | None] = relationship(back_populates="links")
    clicks: Mapped[list[Click]] = relationship(
        back_populates="link",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def has_password(self) -> bool:
        """Return whether the link is protected by a password."""
        return bool(self.password_hash)

    def __repr__(self) -> str:
        """Return a debug representation."""
        return f"<Link id={self.id} code={self.code!r}>"
