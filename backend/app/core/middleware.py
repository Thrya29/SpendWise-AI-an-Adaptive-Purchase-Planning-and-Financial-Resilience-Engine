from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

logger = logging.getLogger("spendwise.http")
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
SLOW_REQUEST_MS = 1000

MAX_BODY_BYTES = 1_000_000
# Statement uploads carry a whole CSV export; everything else is small JSON.
LARGE_BODY_PATHS = {"/api/v1/imports/statement/preview": 3_500_000}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        logger.log(
            logging.WARNING if duration_ms >= SLOW_REQUEST_MS else logging.INFO,
            "slow_request" if duration_ms >= SLOW_REQUEST_MS else "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


class BodySizeLimitMiddleware:
    """Reject request bodies over the limit with 413, whether or not Content-Length is sent.

    The web proxy has the same limits; this keeps the API safe when reached directly. Bodies
    without a Content-Length are read (up to the limit) before the app sees them, so an
    oversized stream gets a clear 413 rather than a parse error.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = LARGE_BODY_PATHS.get(scope["path"], MAX_BODY_BYTES)
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            if declared.isdigit() and int(declared) > limit:
                await _too_large(scope, receive, send, limit)
                return
            await self.app(scope, receive, send)  # the server enforces the declared length
            return
        buffered: list[Message] = []
        size = 0
        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] != "http.request":
                break
            size += len(message.get("body", b""))
            if size > limit:
                await _too_large(scope, receive, send, limit)
                return
            if not message.get("more_body", False):
                break

        async def replay() -> Message:
            return buffered.pop(0) if buffered else await receive()

        await self.app(scope, replay, send)


async def _too_large(scope: Scope, receive: Receive, send: Send, limit: int) -> None:
    response = JSONResponse(
        {
            "type": "https://spendwise.dev/problems/payload_too_large",
            "title": "Payload too large",
            "status": 413,
            "detail": f"Request body exceeds {limit:,} bytes",
        },
        status_code=413,
        media_type="application/problem+json",
    )
    await response(scope, receive, send)
