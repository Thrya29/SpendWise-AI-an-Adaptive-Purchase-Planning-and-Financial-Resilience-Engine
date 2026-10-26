"""Production hardening: body limits, readiness, worker heartbeat and notify pacing."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app import worker
from app.core import ratelimit
from app.core.config import get_settings
from app.core.middleware import MAX_BODY_BYTES

API = "/api/v1"


async def test_oversized_bodies_are_rejected_with_413(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    big = {"message": "x" * (MAX_BODY_BYTES + 10)}
    r = await client.post(f"{API}/feedback", json=big, headers=auth)
    assert r.status_code == 413 and r.json()["title"] == "Payload too large"

    async def chunks():  # no Content-Length: the stream is counted as it arrives
        for _ in range(12):
            yield b"x" * 100_000

    r = await client.post(
        f"{API}/feedback", content=chunks(),
        headers={**auth, "content-type": "application/json"},
    )  # fmt: skip
    assert r.status_code == 413
    # Statement uploads have a larger allowance.
    row = "01/10/2026,UPI-" + "COFFEE SHOP " * 6 + ",-1\n"  # ~90 bytes
    text = "Date,Description,Amount\n" + row * 15_000  # ~1.4 MB, under the row limit
    r = await client.post(f"{API}/imports/statement/preview", json={"text": text}, headers=auth)
    assert r.status_code == 200, r.text[:200]


async def test_readiness_reports_redis(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = (await client.get("/readyz")).json()
    assert ready == {"status": "ok", "database": "up", "redis": "not_configured"}

    async def down() -> bool:
        return False

    monkeypatch.setattr(ratelimit, "ping", down)
    r = await client.get("/readyz")
    assert r.status_code == 503 and r.json()["redis"] == "down"


async def test_slow_requests_are_logged_as_warnings(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.core import middleware  # noqa: PLC0415

    monkeypatch.setattr(middleware, "SLOW_REQUEST_MS", 0)
    with caplog.at_level(logging.INFO, logger="spendwise.http"):
        await client.get("/healthz")
    assert any(r.message == "slow_request" and r.levelno == logging.WARNING for r in caplog.records)


async def test_heartbeat_and_notify_pacing(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beat = tmp_path / "beat"
    monkeypatch.setenv("SPENDWISE_WORKER_HEARTBEAT_PATH", str(beat))
    get_settings.cache_clear()
    worker.heartbeat()
    assert datetime.fromisoformat(beat.read_text()).tzinfo is not None

    monkeypatch.setattr(worker, "_last_notify", None)
    assert await worker.notify_if_due() == (0, 0)  # no users yet, but it ran
    assert await worker.notify_if_due() is None  # paced: not again within 5 minutes
    get_settings.cache_clear()


async def test_only_users_with_something_due_are_processed(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    from app.core.db import get_sessionmaker  # noqa: PLC0415
    from app.models.entities import User  # noqa: PLC0415

    morning = datetime(2026, 11, 3, 4, 0, tzinfo=UTC)  # 09:30 in Asia/Kolkata
    async with get_sessionmaker()() as s:
        user = (await s.scalars(__import__("sqlalchemy").select(User))).one()
        assert worker._needs_attention(user, morning - timedelta(hours=3)) is False  # too early
        assert worker._needs_attention(user, morning) is True
        user.money_checked_on = morning.date()
        assert worker._needs_attention(user, morning) is False  # done today, email off
