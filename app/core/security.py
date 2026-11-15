"""Password hashing, JWT tokens and privacy-preserving request fingerprints."""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models.user import User

#: ``auto_error=False`` lets us return our own unified 401 payload.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

#: Hash used to keep login timing similar for unknown e-mails.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt()).decode("ascii")


def hash_password(password: str) -> str:
    """Hash a password with bcrypt.

    The password is first reduced to a 44-byte SHA-256 digest so that bcrypt's
    72-byte input limit never silently truncates long passphrases.
    """
    digest = base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())
    return bcrypt.hashpw(digest, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Return whether ``password`` matches ``password_hash``."""
    if not password_hash:
        return False
    digest = base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())
    try:
        return bcrypt.checkpw(digest, password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def burn_password_check(password: str) -> None:
    """Run a hash comparison against a dummy value to level login timing."""
    verify_password(password, _DUMMY_HASH)


def create_access_token(subject: int | str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT for a user identifier."""
    now = datetime.now(UTC)
    expires = now + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT, raising :class:`AppError` on failure."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppError(
            401,
            "token_expired",
            "Your session has expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.PyJWTError as exc:
        raise AppError(
            401,
            "invalid_token",
            "The access token is invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if payload.get("type") != "access":
        raise AppError(401, "invalid_token", "The access token is invalid.")
    return payload


def _unauthorized(message: str = "Authentication required.") -> AppError:
    """Build a standard 401 error."""
    return AppError(401, "unauthorized", message, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the ``Authorization`` header."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized()
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _unauthorized("The access token is invalid.") from exc
    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized("The account no longer exists.")
    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """Resolve the user when a valid token is present, otherwise ``None``."""
    if credentials is None or not credentials.credentials:
        return None
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    return db.get(User, user_id)


def client_ip(request: Request) -> str:
    """Return the visitor IP, honouring ``X-Forwarded-For`` only when trusted."""
    if settings.trusted_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def hash_ip(ip: str) -> str:
    """Hash a visitor IP with a secret pepper (privacy-friendly analytics)."""
    return hmac.new(
        settings.ip_hash_pepper.encode("utf-8"),
        ip.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
