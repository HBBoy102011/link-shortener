"""Business logic for short links: creation, resolution, caching and deletion."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.cache import link_cache
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.models.base import ensure_aware, utcnow
from app.models.click import Click
from app.models.link import Link
from app.models.user import User
from app.schemas.link import LinkCreateRequest
from app.services.request_info import describe_click

logger = logging.getLogger("app.links")

#: Alphabet without visually ambiguous characters (0/O, 1/l/I).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"

#: Codes that would shadow real routes.
RESERVED_CODES = frozenset(
    {
        "api",
        "docs",
        "redoc",
        "openapi.json",
        "health",
        "app",
        "static",
        "favicon.ico",
        "robots.txt",
        "sitemap.xml",
        "admin",
        "qr",
    }
)

#: How many random candidates to try before giving up.
CODE_ATTEMPTS = 12


# ----------------------------------------------------------------------
# Codes
# ----------------------------------------------------------------------
def generate_code(length: int | None = None) -> str:
    """Return a cryptographically random short code."""
    size = settings.short_code_length if length is None else int(length)
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(size))


def _allocate_code(db: Session) -> str:
    """Return a code that is not used yet."""
    for _ in range(CODE_ATTEMPTS):
        candidate = generate_code()
        exists = db.scalar(select(Link.id).where(Link.code == candidate))
        if exists is None:
            return candidate
    raise AppError(503, "code_exhausted", "Could not allocate a short code. Please retry.")


def _ensure_code_free(db: Session, code: str) -> None:
    """Raise a conflict when a user-supplied alias is taken."""
    if code.lower() in RESERVED_CODES:
        raise AppError(
            400,
            "reserved_code",
            "This short code is reserved by the service.",
            details={"custom_code": code},
        )
    exists = db.scalar(select(Link.id).where(Link.code == code))
    if exists is not None:
        raise AppError(
            409,
            "code_taken",
            "This short code is already in use.",
            details={"custom_code": code},
        )


# ----------------------------------------------------------------------
# URL checks
# ----------------------------------------------------------------------
def _hostname(url: str) -> str:
    """Return a lower-case hostname for a URL."""
    return (urlparse(url).hostname or "").lower()


def ensure_public_destination(url: str, request: Request) -> None:
    """Reject links that point back at the shortener itself."""
    target = _hostname(url)
    blocked = {_hostname(settings.base_url), (request.url.hostname or "").lower()}
    header_host = request.headers.get("host", "").split(":", 1)[0].lower()
    if header_host:
        blocked.add(header_host)
    if target and target in blocked:
        raise AppError(
            400,
            "self_reference",
            "Links to this service itself are not allowed.",
            details={"url": url},
        )


# ----------------------------------------------------------------------
# Creation and lookup
# ----------------------------------------------------------------------
def create_link(
    db: Session,
    request: Request,
    payload: LinkCreateRequest,
    user: User | None,
) -> Link:
    """Create and persist a short link for a user or an anonymous visitor."""
    original_url = str(payload.url)
    ensure_public_destination(original_url, request)

    if payload.custom_code:
        code = payload.custom_code
        _ensure_code_free(db, code)
    else:
        code = _allocate_code(db)

    link = Link(
        user_id=user.id if user is not None else None,
        code=code,
        original_url=original_url,
        expires_at=payload.expires_at,
        is_active=True,
        password_hash=hash_password(payload.password) if payload.password else None,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            409,
            "code_taken",
            "This short code is already in use.",
            details={"custom_code": code},
        ) from exc
    db.refresh(link)
    return link


def get_link(db: Session, link_id: int) -> Link | None:
    """Return a link by primary key."""
    return db.get(Link, link_id)


def get_user_link(db: Session, user: User, link_id: int) -> Link:
    """Return a link owned by ``user`` or raise a 404."""
    link = db.scalar(select(Link).where(Link.id == int(link_id), Link.user_id == user.id))
    if link is None:
        raise AppError(404, "not_found", "Link not found.")
    return link


def resolve_link(db: Session, code: str) -> dict[str, Any] | None:
    """Return a cached or database-backed payload for a code."""
    cached = link_cache.get(code)
    if cached is not None:
        return cached

    link = db.scalar(select(Link).where(Link.code == code))
    if link is None:
        return None

    expires_at = ensure_aware(link.expires_at)
    payload: dict[str, Any] = {
        "id": int(link.id),
        "code": str(link.code),
        "original_url": str(link.original_url),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "is_active": bool(link.is_active),
        "password_hash": link.password_hash,
    }
    ttl = settings.cache_ttl_seconds
    if expires_at is not None:
        remaining = (expires_at - utcnow()).total_seconds()
        if remaining <= 0:
            return payload
        ttl = min(ttl, int(remaining))
    link_cache.set(code, payload, ttl)
    return payload


def ensure_link_usable(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a resolved payload and raise 404/410 when it cannot be used."""
    if payload is None:
        raise AppError(404, "not_found", "This short link does not exist.")
    if not payload.get("is_active", True):
        raise AppError(410, "link_inactive", "This short link is no longer active.")
    expires_raw = payload.get("expires_at")
    if expires_raw:
        expires_at = datetime.fromisoformat(str(expires_raw))
        if ensure_aware(expires_at) <= utcnow():
            link_cache.delete(str(payload.get("code", "")))
            raise AppError(410, "link_expired", "This short link has expired.")
    return payload


# ----------------------------------------------------------------------
# Clicks
# ----------------------------------------------------------------------
def record_click(db: Session, link_id: int, request: Request) -> None:
    """Store one click without letting analytics break the redirect."""
    info = describe_click(request)
    click = Click(
        link_id=int(link_id),
        referer=info.referer,
        user_agent=info.user_agent,
        device_type=info.device_type,
        ip_hash=info.ip_hash,
    )
    db.add(click)
    try:
        db.commit()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive
        db.rollback()
        logger.warning("Could not record click for link %s: %s", link_id, exc)


# ----------------------------------------------------------------------
# Listing, counting and deletion
# ----------------------------------------------------------------------
def count_clicks(db: Session, link_id: int) -> int:
    """Return the total number of clicks for a link."""
    return int(db.scalar(select(func.count(Click.id)).where(Click.link_id == link_id)) or 0)


def list_user_links(
    db: Session,
    user: User,
    page: int,
    page_size: int,
) -> tuple[list[tuple[Link, int]], int]:
    """Return one page of a user's links together with click counts."""
    total = int(db.scalar(select(func.count(Link.id)).where(Link.user_id == user.id)) or 0)
    rows = db.execute(
        select(Link, func.count(Click.id))
        .outerjoin(Click, Click.link_id == Link.id)
        .where(Link.user_id == user.id)
        .group_by(Link.id)
        .order_by(Link.created_at.desc(), Link.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [(row[0], int(row[1])) for row in rows], total


def delete_link(db: Session, link: Link) -> None:
    """Delete a link, its clicks and its cache entry."""
    code = str(link.code)
    db.delete(link)
    db.commit()
    link_cache.delete(code)


# ----------------------------------------------------------------------
# Serialisation
# ----------------------------------------------------------------------
def to_response(link: Link, clicks: int = 0) -> dict[str, Any]:
    """Convert a link model into the public API shape."""
    return {
        "id": int(link.id),
        "code": str(link.code),
        "short_url": settings.short_url(str(link.code)),
        "original_url": str(link.original_url),
        "created_at": ensure_aware(link.created_at),
        "expires_at": ensure_aware(link.expires_at),
        "is_active": bool(link.is_active),
        "has_password": bool(link.password_hash),
        "clicks": int(clicks),
        "qr_url": f"{settings.base_url}/api/links/{int(link.id)}/qr",
    }
