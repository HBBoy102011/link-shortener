"""Database engine, declarative base and request-scoped sessions."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def build_engine(url: str) -> Engine:
    """Create an engine that works with PostgreSQL and SQLite alike."""
    options: dict[str, Any] = {
        "echo": settings.database_echo,
        "pool_pre_ping": True,
        "future": True,
    }
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **options)


engine: Engine = build_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def get_db() -> Iterator[Session]:
    """Yield a database session and always close it afterwards."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
