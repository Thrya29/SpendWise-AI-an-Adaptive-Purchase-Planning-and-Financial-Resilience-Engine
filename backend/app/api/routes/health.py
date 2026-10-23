from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.db import get_engine

router = APIRouter(tags=["health"])


@router.get("/healthz", include_in_schema=False)
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readiness() -> JSONResponse:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
    return JSONResponse({"status": "ok", "database": "up"})
