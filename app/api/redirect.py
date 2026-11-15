"""Public redirect route: the heart of the service."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.errors import AppError
from app.core.security import verify_password
from app.schemas.common import ErrorEnvelope
from app.services import link_service

router = APIRouter(tags=["Redirect"])

#: Short codes never contain other characters, so anything else is a 404.
CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

RESPONSES = {
    302: {"description": "Redirect to the original URL."},
    401: {"model": ErrorEnvelope, "description": "The link is password-protected."},
    404: {"model": ErrorEnvelope, "description": "Unknown short code."},
    410: {"model": ErrorEnvelope, "description": "The link is inactive or expired."},
}


@router.get(
    "/{code}",
    summary="Follow a short link",
    response_class=RedirectResponse,
    status_code=302,
    responses=RESPONSES,
)
def follow_short_link(
    code: str,
    request: Request,
    password: str | None = Query(
        default=None,
        max_length=128,
        description="Password for protected links.",
    ),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Resolve a code, record the visit and redirect the visitor."""
    if not CODE_PATTERN.fullmatch(code):
        raise AppError(404, "not_found", "This short link does not exist.")

    payload = link_service.ensure_link_usable(link_service.resolve_link(db, code))

    if payload.get("password_hash"):
        if not password:
            raise AppError(
                401,
                "password_required",
                "This link is protected by a password.",
                details={"protected": True},
            )
        if not verify_password(password, str(payload["password_hash"])):
            raise AppError(
                401,
                "invalid_password",
                "Incorrect password.",
                details={"protected": True},
            )

    link_service.record_click(db, int(payload["id"]), request)
    return RedirectResponse(
        url=str(payload["original_url"]),
        status_code=302,
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"},
    )
