from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import httpx
import pytest

from app import worker
from app.core import mailer
from app.core.config import get_settings

API = "/api/v1"
# 09:30 in Asia/Kolkata (the test user's time zone) on 3 Nov 2026.
NOW = datetime(2026, 11, 3, 4, 0, tzinfo=UTC)


async def _household(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    for path, body in (
        ("accounts", {"name": "Bank", "currency": "INR", "opening_balance_minor": 1_000_000}),
        ("incomes", {"name": "Salary", "amount_minor": 5_000_000, "currency": "INR",
                     "anchor_date": "2026-10-02"}),  # due yesterday, 2 Nov
        ("obligations", {"name": "Rent", "amount_minor": 2_500_000, "currency": "INR",
                         "anchor_date": "2026-10-05"}),  # due 5 Nov
        ("obligations", {"name": "Streaming", "amount_minor": 64_900, "currency": "INR",
                         "anchor_date": "2026-10-04", "essential": False}),
        ("items", {"name": "Shoes", "tier": "want", "estimated_price_minor": 200_000,
                   "currency": "INR", "target_date": "2026-11-03"}),
    ):  # fmt: skip
        r = await client.post(f"{API}/{path}", json=body, headers=auth)
        assert r.status_code == 201, r.text


async def _alerts(client: httpx.AsyncClient, auth: dict[str, str]) -> list[dict]:
    return (await client.get(f"{API}/alerts", headers=auth)).json()


async def test_daily_money_reminders_are_created_once(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _household(client, auth)
    assert await worker.notify_users(NOW - timedelta(hours=3)) == (0, 0)  # 06:30 local: too early

    created, sent = await worker.notify_users(NOW)
    assert (created, sent) == (3, 0)  # email is off by default
    by_kind = {a["kind"]: a for a in await _alerts(client, auth)}
    # 10,000 - 2,000 (shoes today) - 649 (streaming) - 25,000 (rent) = -17,649 on 5 Nov.
    assert by_kind["bill_shortfall"]["title"] == "₹17,649 short for Rent on 5 Nov"
    assert by_kind["buy_day"]["title"] == "Today is the planned day to buy Shoes"
    assert by_kind["buy_day"]["item_id"] is not None
    assert by_kind["salary_check"]["title"] == "Did your Salary arrive?"
    assert "2 Nov" in by_kind["salary_check"]["body"]

    assert await worker.notify_users(NOW + timedelta(hours=2)) == (0, 0)  # same local day
    # Next day: rent is still short, but that reminder already exists.
    assert await worker.notify_users(NOW + timedelta(days=1)) == (0, 0)
    assert len(await _alerts(client, auth)) == 3


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    monkeypatch.setenv("SPENDWISE_SMTP_HOST", "smtp.example")
    get_settings.cache_clear()
    sent: list[EmailMessage] = []
    monkeypatch.setattr(mailer, "_send_sync", sent.append)
    yield sent
    get_settings.cache_clear()


async def test_email_digest_is_opt_in_and_daily(
    client: httpx.AsyncClient, auth: dict[str, str], smtp: list[EmailMessage]
) -> None:
    me = (await client.get(f"{API}/me", headers=auth)).json()
    assert me["email_available"] is True and me["email_notifications"] is False
    await _household(client, auth)
    r = await client.patch(f"{API}/me", json={"email_notifications": True}, headers=auth)
    assert r.status_code == 200 and r.json()["email_notifications"] is True

    assert await worker.notify_users(NOW) == (3, 1)
    msg = smtp[0]
    assert msg["To"] == "asha@example.com" and msg["Subject"] == "SpendWise: 3 things need a look"
    text = msg.get_content()
    assert "₹17,649 short for Rent" in text and "/alerts" in text and "Settings" in text

    assert await worker.notify_users(NOW + timedelta(days=1)) == (0, 0)  # nothing new to send
    assert len(smtp) == 1


async def test_failed_email_is_retried_after_an_hour(
    client: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    smtp: list[EmailMessage],
) -> None:  # fmt: skip
    await _household(client, auth)
    await client.patch(f"{API}/me", json={"email_notifications": True}, headers=auth)

    def down(_msg: EmailMessage) -> None:
        raise mailer.MailError("Could not send email: ConnectionRefusedError")

    monkeypatch.setattr(mailer, "_send_sync", down)
    assert await worker.notify_users(NOW) == (3, 0)
    monkeypatch.setattr(mailer, "_send_sync", smtp.append)
    assert await worker.notify_users(NOW + timedelta(minutes=30)) == (0, 0)
    assert await worker.notify_users(NOW + timedelta(minutes=61)) == (0, 1)
    assert "3 things" in smtp[0]["Subject"]


async def test_email_cannot_be_null(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await client.patch(f"{API}/me", json={"email_notifications": None}, headers=auth)
    assert r.status_code == 422
