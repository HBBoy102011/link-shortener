"""Health probe used by container orchestrators and uptime checks."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.cache import link_cache
from app.core.config import settings
from app.core.errors import AppError
from app.core.rate_limit import limiter
from app.schemas.common import HealthResponse

router = APIRouter(prefix="/api", tags=["Service"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness and dependency check",
    responses={503: {"description": "Database is unavailable."}},
)
def health(db: Session = Depends(get_db)) -> dict:
    """Report whether the service and its database are reachable."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise AppError(503, "database_unavailable", "Database is not reachable.") from exc
    return {
        "status": "ok",
        "database": "ok",
        "cache": link_cache.backend,
        "rate_limit": limiter.backend,
        "version": settings.app_version,
    }
