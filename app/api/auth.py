"""Registration, login and the current-user endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.errors import AppError
from app.core.rate_limit import enforce_auth_limit
from app.core.security import (
    burn_password_check,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from app.schemas.common import ErrorEnvelope

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

ERRORS = {
    401: {"model": ErrorEnvelope, "description": "Invalid credentials or token."},
    409: {"model": ErrorEnvelope, "description": "E-mail is already registered."},
    429: {"model": ErrorEnvelope, "description": "Too many authentication attempts."},
}


def _auth_payload(user: User) -> dict:
    """Build the token response for a freshly authenticated user."""
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_minutes * 60,
        "user": user,
    }


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses=ERRORS,
)
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Register a new account and return an access token."""
    enforce_auth_limit(request)
    email = str(payload.email).strip().lower()

    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise AppError(
            409,
            "email_taken",
            "An account with this e-mail already exists.",
            details={"email": email},
        )

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "email_taken", "This e-mail is already registered.") from exc
    db.refresh(user)
    return _auth_payload(user)


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Sign in and receive a JWT",
    responses=ERRORS,
)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Verify credentials and issue a bearer token."""
    enforce_auth_limit(request)
    email = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        burn_password_check(payload.password)
        raise AppError(401, "invalid_credentials", "E-mail or password is incorrect.")
    if not verify_password(payload.password, user.password_hash):
        raise AppError(401, "invalid_credentials", "E-mail or password is incorrect.")
    return _auth_payload(user)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Return the authenticated account",
    responses={401: {"model": ErrorEnvelope, "description": "Missing or invalid token."}},
)
def me(user: User = Depends(get_current_user)) -> User:
    """Return the account behind the bearer token."""
    return user
