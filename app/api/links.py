"""Short link management and analytics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_current_user, get_db, get_optional_user, pagination
from app.core.config import settings
from app.core.errors import AppError
from app.core.rate_limit import enforce_create_limit
from app.models.user import User
from app.schemas.common import ErrorEnvelope
from app.schemas.link import LinkCreateRequest, LinkListResponse, LinkResponse
from app.schemas.stats import LinkStats
from app.services import link_service, qr_service, stats_service

router = APIRouter(prefix="/api/links", tags=["Links"])

ERRORS = {
    400: {"model": ErrorEnvelope, "description": "Reserved alias or self-referencing URL."},
    401: {"model": ErrorEnvelope, "description": "Authentication required."},
    404: {"model": ErrorEnvelope, "description": "Link not found."},
    409: {"model": ErrorEnvelope, "description": "Alias already taken."},
    422: {"model": ErrorEnvelope, "description": "Invalid URL or alias."},
    429: {"model": ErrorEnvelope, "description": "Creation rate limit exceeded."},
}


@router.post(
    "",
    response_model=LinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a short link",
    responses=ERRORS,
)
def create_link(
    payload: LinkCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> dict:
    """Shorten a URL.

    Authentication is optional: anonymous links are allowed and simply have no
    owner.  Signed-in users see their links in the dashboard.
    """
    enforce_create_limit(request)
    link = link_service.create_link(db, request, payload, user)
    return link_service.to_response(link)


@router.get(
    "",
    response_model=LinkListResponse,
    summary="List the authenticated user's links",
    responses={401: {"model": ErrorEnvelope, "description": "Authentication required."}},
)
def list_links(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: Pagination = Depends(pagination),
) -> dict:
    """Return a page of the caller's links with click counters."""
    rows, total = link_service.list_user_links(db, user, page.page, page.page_size)
    return {
        "items": [link_service.to_response(link, clicks) for link, clicks in rows],
        "total": total,
        "page": page.page,
        "page_size": page.page_size,
    }


@router.get(
    "/{link_id}",
    response_model=LinkResponse,
    summary="Get one of the user's links",
    responses=ERRORS,
)
def get_link(
    link_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Return a single link owned by the caller."""
    link = link_service.get_user_link(db, user, link_id)
    return link_service.to_response(link, link_service.count_clicks(db, link.id))


@router.delete(
    "/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one of the user's links",
    responses=ERRORS,
)
def delete_link(
    link_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Delete a link together with its analytics."""
    link = link_service.get_user_link(db, user, link_id)
    link_service.delete_link(db, link)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{link_id}/stats",
    response_model=LinkStats,
    summary="Analytics for one of the user's links",
    responses=ERRORS,
)
def link_stats(
    link_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Return totals, daily clicks, top referers and device split."""
    link = link_service.get_user_link(db, user, link_id)
    return stats_service.collect_stats(db, link)


@router.get(
    "/{link_id}/qr",
    summary="QR code for a link",
    response_class=Response,
    responses={
        200: {"content": {"image/png": {}}, "description": "PNG QR code."},
        404: {"model": ErrorEnvelope, "description": "Link not found."},
    },
)
def link_qr(
    link_id: int,
    db: Session = Depends(get_db),
    size: int = Query(default=10, ge=2, le=40, description="Pixels per QR module."),
) -> Response:
    """Render the short URL as a PNG QR code."""
    link = link_service.get_link(db, link_id)
    if link is None:
        raise AppError(404, "not_found", "Link not found.")
    data = qr_service.make_qr_png(settings.short_url(link.code), box_size=size)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )
