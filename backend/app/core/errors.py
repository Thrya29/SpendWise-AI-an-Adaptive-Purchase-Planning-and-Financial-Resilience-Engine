"""RFC 9457 (problem+json) error responses."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("spendwise.errors")

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class DomainValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_error"


def _problem(
    request: Request, status_code: int, code: str, detail: str, **extra: Any
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://spendwise.dev/problems/{code}",
        "title": code.replace("_", " ").capitalize(),
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
        **extra,
    }
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(body, status_code=status_code, media_type=PROBLEM_JSON, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return _problem(request, exc.status_code, exc.code, exc.detail, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return _problem(
            request, 422, "validation_error", "Request validation failed", errors=errors
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem(request, exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"path": request.url.path})
        return _problem(request, 500, "internal_error", "An unexpected error occurred")
