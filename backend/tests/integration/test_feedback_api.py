from datetime import date, timedelta

import httpx
from sqlalchemy import select, update

from app.core.db import get_sessionmaker, utcnow
from app.models.entities import UsageEvent, User
from app.services import usage
from app.services.pilot_report import build_report
from tests.conftest import signup

API = "/api/v1"


async def _age_account(days: int) -> None:
    async with get_sessionmaker()() as s:
        await s.execute(update(User).values(created_at=utcnow() - timedelta(days=days)))
        await s.commit()


async def _events() -> list[UsageEvent]:
    async with get_sessionmaker()() as s:
        return list(await s.scalars(select(UsageEvent)))


async def test_comments_are_saved_validated_and_exported(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    body = {"message": "The import found my rent!", "rating": 5, "page": "/import"}
    r = await client.post(f"{API}/feedback", json=body, headers=auth)
    assert r.status_code == 201 and r.json()["kind"] == "comment"
    bad = await client.post(f"{API}/feedback", json={"message": "x", "rating": 9}, headers=auth)
    assert bad.status_code == 422
    export = (await client.get(f"{API}/me/export", headers=auth)).json()
    assert export["feedback"][0]["message"] == "The import found my rent!"


async def test_monthly_checkin_is_asked_once_after_a_few_weeks(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    fresh = (await client.get(f"{API}/feedback/checkin", headers=auth)).json()
    assert fresh["due"] is False  # a brand-new account has no month to look back on
    await _age_account(60)
    due = (await client.get(f"{API}/feedback/checkin", headers=auth)).json()
    assert due["due"] is True
    last_month = date.today().replace(day=1) - timedelta(days=1)
    assert due["month"] == f"{last_month.year:04d}-{last_month.month:02d}"

    answers = {"month": due["month"], "bills_short": True, "missed_need_deadline": False,
               "followed_plan": "partly", "comment": "Salary came late"}  # fmt: skip
    r = await client.post(f"{API}/feedback/checkin", json=answers, headers=auth)
    assert r.status_code == 201, r.text
    assert r.json()["answers"] == {"bills_short": True, "missed_need_deadline": False,
                                   "followed_plan": "partly"}  # fmt: skip
    assert (await client.get(f"{API}/feedback/checkin", headers=auth)).json()["due"] is False
    again = await client.post(f"{API}/feedback/checkin", json=answers, headers=auth)
    assert again.status_code == 409
    future = {**answers, "month": f"{date.today().year + 1}-01"}
    assert (
        await client.post(f"{API}/feedback/checkin", json=future, headers=auth)
    ).status_code == 422


async def test_usage_is_recorded_only_with_consent_and_erased_on_opt_out(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await client.get(f"{API}/me", headers=auth)
    await client.post(f"{API}/planner/plans", json={}, headers=auth)
    assert await _events() == []  # off by default

    me = (await client.patch(f"{API}/me", json={"share_usage": True}, headers=auth)).json()
    assert me["share_usage"] is True
    await client.get(f"{API}/me", headers=auth)
    await client.get(f"{API}/me", headers=auth)  # same day: still one "active"
    await client.post(f"{API}/planner/plans", json={}, headers=auth)
    events = await _events()
    assert sorted(e.event for e in events) == ["active", "plan_created"]
    user_id = me["id"]
    assert all(e.subject == usage.subject(user_id) and user_id not in e.subject for e in events)
    assert all(e.day == date.today() or abs((e.day - date.today()).days) <= 1 for e in events)

    await client.patch(f"{API}/me", json={"share_usage": False}, headers=auth)
    assert await _events() == []  # turning it off erases what was shared


async def test_deleting_the_account_erases_usage_events(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await client.patch(f"{API}/me", json={"share_usage": True}, headers=auth)
    await client.get(f"{API}/me", headers=auth)
    assert len(await _events()) == 1
    r = await client.post(
        f"{API}/me/delete", json={"password": "correct-horse-battery"}, headers=auth
    )
    assert r.status_code == 204
    assert await _events() == []


async def test_pilot_report_aggregates_without_identities(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await client.patch(f"{API}/me", json={"share_usage": True}, headers=auth)
    await client.post(f"{API}/incomes", json={"name": "Salary", "amount_minor": 5_000_000,
                      "currency": "INR", "anchor_date": "2026-10-01"}, headers=auth)  # fmt: skip
    other = await signup(client, email="ravi@example.com")
    await client.post(f"{API}/feedback", json={"message": "Too many steps"}, headers=other)
    await _age_account(60)
    month = (await client.get(f"{API}/feedback/checkin", headers=auth)).json()["month"]
    await client.post(f"{API}/feedback/checkin", headers=auth, json={
        "month": month, "bills_short": False, "missed_need_deadline": False,
        "followed_plan": "mostly"})  # fmt: skip

    async with get_sessionmaker()() as s:
        text = await build_report(s, date.today())
    assert "Accounts: 2; sharing usage statistics: 1" in text
    assert "| Added income | 100% (1/1) |" in text
    assert f"| {month} | 1 | 0% (0/1) | 0% (0/1) | 1 / 0 / 0 / 0 |" in text
    assert "Too many steps" in text
    assert "asha@example.com" not in text and "ravi@example.com" not in text
