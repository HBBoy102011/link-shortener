"""Unified error model and FastAPI exception handlers.

Every failure leaves the API as::

    {"error": {"code": "not_found", "message": "...", "details": ...}}

so clients can branch on a stable machine-readable ``code``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")

#: Mapping of bare HTTP status codes to stable error codes.
STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


class AppError(Exception):
    """An expected application failure with a public error payload."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Store everything needed to render the error response."""
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = str(code)
        self.message = str(message)
        self.details = details
        self.headers = dict(headers or {})

    def payload(self) -> dict[str, Any]:
        """Return the JSON-serialisable error body."""
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return {"error": body}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a JSON error response without raising an exception."""
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse({"error": body}, status_code=status_code, headers=headers)


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Flatten Pydantic validation errors into a compact list."""
    location_markers = {"body", "path", "query", "header", "cookie"}
    details: list[dict[str, Any]] = []
    for item in exc.errors():
        location = [str(part) for part in item.get("loc", ()) if part not in location_markers]
        details.append(
            {
                "field": ".".join(location) or "body",
                "message": str(item.get("msg", "Invalid value")),
                "type": str(item.get("type", "value_error")),
            }
        )
    return details


def register_error_handlers(app: FastAPI) -> None:
    """Attach the unified error handlers to an application."""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        """Render expected application errors."""
        return JSONResponse(exc.payload(), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        """Render request validation failures as ``validation_error``."""
        return error_response(
            422,
            "validation_error",
            "The request contains invalid fields.",
            _validation_details(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Render framework HTTP errors (404, 405 and friends)."""
        code = STATUS_CODES.get(exc.status_code, "http_error")
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(exc.status_code, code, detail, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Log unexpected failures and hide internals from clients."""
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        message = "Something went wrong. Please try again."
        details = None
        if app.debug:
            details = {"type": type(exc).__name__, "message": str(exc)}
        return error_response(500, "internal_error", message, details)
