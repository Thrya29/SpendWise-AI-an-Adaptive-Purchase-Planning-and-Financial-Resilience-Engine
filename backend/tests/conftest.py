from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

# Configure before any app import. CI can override SPENDWISE_DATABASE_URL to run on PostgreSQL.
os.environ.setdefault("SPENDWISE_ENVIRONMENT", "test")
os.environ.setdefault("SPENDWISE_LOG_LEVEL", "WARNING")
os.environ["SPENDWISE_LOGIN_RATE_LIMIT_PER_MINUTE"] = "1000"

import httpx

from app.core import db as db_module
from app.core.config import get_settings
from app.core.db import Base
from app.core.ratelimit import reset_rate_limiter
from app.models import entities as _entities  # noqa: F401  (register tables)


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    if "SPENDWISE_DATABASE_URL" not in os.environ or os.environ.get("_SW_SQLITE"):
        os.environ["_SW_SQLITE"] = "1"
        os.environ["SPENDWISE_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    get_settings.cache_clear()
    reset_rate_limiter()
    await db_module.dispose_engine()
    engine = db_module.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    from app.main import create_app  # noqa: PLC0415 - must import after env is configured

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
    await db_module.dispose_engine()


REGISTER: dict[str, Any] = {
    "email": "asha@example.com",
    "password": "correct-horse-battery",
    "display_name": "Asha",
    "country": "in",
    "base_currency": "INR",
    "city": "Bengaluru",
    "timezone": "Asia/Kolkata",
}


async def signup(client: httpx.AsyncClient, **overrides: Any) -> dict[str, str]:
    body = {**REGISTER, **overrides}
    r = await client.post("/api/v1/auth/register", json=body)
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/auth/login", json={"email": body["email"], "password": body["password"]}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def auth(client: httpx.AsyncClient) -> dict[str, str]:
    return await signup(client)
