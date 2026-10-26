from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core import ratelimit
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
        database = "up"
    except Exception:
        database = "down"
    redis_ok = await ratelimit.ping()
    redis = "not_configured" if redis_ok is None else "up" if redis_ok else "down"
    ok = database == "up" and redis != "down"
    return JSONResponse(
        {"status": "ok" if ok else "unavailable", "database": database, "redis": redis},
        status_code=200 if ok else 503,
    )
