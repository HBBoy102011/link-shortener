"""FastAPI application factory and the ASGI entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api import auth, health, links, redirect
from app.core.config import settings
from app.core.database import Base, engine
from app.core.errors import register_error_handlers

logger = logging.getLogger("app")

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"

TAGS_METADATA = [
    {
        "name": "Authentication",
        "description": "Register, sign in and inspect the current account.",
    },
    {
        "name": "Links",
        "description": "Create, list, delete short links and read their analytics.",
    },
    {"name": "Redirect", "description": "Public short-link resolution."},
    {"name": "Service", "description": "Health and readiness probes."},
]

DESCRIPTION = """
A small but complete URL shortener: JWT accounts, custom aliases, expiring and
password-protected links, per-day click analytics, QR codes and a web dashboard.

**Try it**

1. `POST /api/auth/register` to get a token.
2. Press **Authorize** and paste the token.
3. `POST /api/links` with a long URL.
4. Open `/{code}` and inspect `GET /api/links/{id}/stats`.

Anonymous links are allowed: `POST /api/links` works without a token, but such
links cannot be listed or deleted later.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Prepare the process on startup and log the active configuration."""
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    if settings.auto_create_tables:  # pragma: no cover - development convenience
        Base.metadata.create_all(bind=engine)
        logger.info("Tables created from metadata (AUTO_CREATE_TABLES=true).")
    logger.info(
        "Starting %s %s in %s mode; cache=%s",
        settings.app_name,
        settings.app_version,
        settings.environment,
        "redis" if settings.redis_url else "memory",
    )
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    """Build the FastAPI application with routes, static files and handlers."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        contact={"name": "Link Shortener", "url": "https://github.com/"},
        license_info={"name": "MIT"},
    )

    register_error_handlers(app)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
        )

    app.include_router(auth.router)
    app.include_router(links.router)
    app.include_router(health.router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        """Serve the single-page dashboard."""
        return FileResponse(INDEX_FILE)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        """Answer the browser's favicon request without noise."""
        return Response(status_code=204)

    # The catch-all redirect route must be registered last.
    app.include_router(redirect.router)

    return app


app = create_app()
