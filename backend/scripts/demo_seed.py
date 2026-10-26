"""Demo data for the walkthrough video, GIF and user-manual screenshots.

Creates a made-up, lived-in account ("Asha Rao") on a local SpendWise. Run from backend/ with
SPENDWISE_DATABASE_URL pointing at a throwaway database (never a real one):

  python scripts/demo_seed.py reference   # ECB rates, AMFI funds, gold (needs internet)
  python scripts/demo_seed.py everyday    # the demo account (the API must be running)

Then record:  cd e2e && npx playwright test --config demo/playwright.demo.config.ts
"""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import worker
from app.core.db import get_sessionmaker
from app.models.entities import (
    Alert,
    AlertKind,
    Availability,
    ObservationMethod,
    PlannedItem,
    PriceObservation,
    User,
)
from app.services import notification_service

API = "http://127.0.0.1:8000/api/v1"
EMAIL = "asha.demo@example.com"
PASSWORD = "demo-password-123"  # noqa: S105 - a public demo account on a throwaway database

ACCOUNTS = [
    {"name": "HDFC Savings", "currency": "INR", "opening_balance_minor": 11_200_000},
    {"name": "Cash wallet", "kind": "cash", "currency": "INR", "opening_balance_minor": 350_000},
]
INCOMES = [
    {"name": "Salary", "amount_minor": 8_500_000, "anchor_date": "2026-10-01"},
    {"name": "Freelance design", "amount_minor": 1_200_000, "anchor_date": "2026-10-15",
     "subject_to_shocks": False},
]  # fmt: skip
BILLS = [  # name, amount, first date, frequency, category, essential
    ("Rent", 2_500_000, "2026-10-05", "monthly", "housing", True),
    ("Electricity", 180_000, "2026-10-12", "monthly", "utilities", True),
    ("Phone and internet", 99_900, "2026-10-08", "monthly", "utilities", True),
    ("Groceries", 250_000, "2026-10-03", "weekly", "food", True),
    ("Health insurance", 620_000, "2026-09-20", "quarterly", "insurance", True),
    ("SIP - index fund", 500_000, "2026-10-10", "monthly", "savings", False),
    ("Streaming", 64_900, "2026-10-18", "monthly", "subscriptions", False),
]
ITEMS: list[dict[str, Any]] = [
    {"name": "Laptop for work", "tier": "need", "estimated_price_minor": 7_800_000, "priority": 5,
     "target_date": "2026-12-15", "deadline_type": "hard", "notes": "Old one is 6 years old"},
    {"name": "School fees (term 2)", "tier": "need", "estimated_price_minor": 4_500_000,
     "priority": 5, "target_date": "2026-11-20", "deadline_type": "hard", "kind": "service"},
    {"name": "Washing machine", "tier": "need", "estimated_price_minor": 3_200_000,
     "priority": 3, "target_date": "2027-01-10", "deadline_type": "soft"},
    {"name": "Phone upgrade", "tier": "want", "estimated_price_minor": 5_499_900, "priority": 4,
     "max_price_minor": 4_900_000, "url": "https://shop.example/phones/pixel"},
    {"name": "Goa trip", "tier": "desire", "estimated_price_minor": 4_000_000, "priority": 3,
     "target_date": "2027-02-01", "deadline_type": "soft", "kind": "travel", "location": "Goa"},
    {"name": "Noise-cancelling headphones", "tier": "want", "estimated_price_minor": 2_499_900,
     "priority": 2},
    {"name": "Budget headphones", "tier": "want", "estimated_price_minor": 899_900, "priority": 3},
    {"name": "Gym membership", "tier": "desire", "estimated_price_minor": 1_200_000,
     "priority": 2, "kind": "subscription"},
]  # fmt: skip


async def reference() -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        print("fx", await worker.refresh_fx_if_due(client))
        print("reference", await worker.refresh_reference_data_if_due(client))


async def everyday() -> None:
    async with httpx.AsyncClient(base_url=API, timeout=60) as c:
        profile = {"email": EMAIL, "password": PASSWORD, "display_name": "Asha Rao",
                   "country": "IN", "base_currency": "INR", "city": "Bengaluru",
                   "timezone": "Asia/Kolkata"}  # fmt: skip
        (await c.post("/auth/register", json=profile)).raise_for_status()
        r = await c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

        async def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
            res = await c.post(path, json=body, headers=auth)
            if res.status_code >= 400:
                raise RuntimeError(f"{path}: {res.status_code} {res.text}")
            return res.json() if res.content else {}

        for account in ACCOUNTS:
            await post("/accounts", account)
        for income in INCOMES:
            await post("/incomes", {**income, "currency": "INR"})
        for name, amount, day, freq, category, essential in BILLS:
            await post("/obligations", {
                "name": name, "amount_minor": amount, "currency": "INR", "anchor_date": day,
                "frequency": freq, "category": category, "essential": essential,
            })  # fmt: skip
        created = {i["name"]: await post("/items", {**i, "currency": "INR"}) for i in ITEMS}
        await post(
            f"/items/{created['Noise-cancelling headphones']['id']}/alternatives",
            {"other_item_id": created["Budget headphones"]["id"]},
        )
        await post("/funds/watchlist", {"scheme_code": 120716})

    await backdate_phone_history(created["Phone upgrade"]["id"])
    await morning_reminders()


async def backdate_phone_history(item_id: str) -> None:
    """Two months of price checks with sales, so the chart and the outlook have history."""
    rng = random.Random(4)  # noqa: S311 - reproducible demo data
    now = datetime.now(UTC)
    async with get_sessionmaker()() as s:
        item = await s.get(PlannedItem, UUID(item_id))
        assert item is not None
        for days_ago in range(62, -1, -2):
            sale = days_ago in (50, 48, 30, 28, 26, 12, 10)
            s.add(PriceObservation(
                user_id=item.user_id, item_id=item.id,
                amount_minor=4_799_900 if sale else 5_499_900, currency="INR",
                method=ObservationMethod.JSON_LD, confidence="high",
                availability=Availability.IN_STOCK, source_name="shop.example", url=item.url,
                page_title="Pixel phone 256 GB",
                observed_at=now - timedelta(days=days_ago, hours=rng.randint(0, 6)),
            ))  # fmt: skip
        s.add(Alert(
            user_id=item.user_id, item_id=item.id, kind=AlertKind.PRICE_TARGET,
            title="Phone upgrade is within your limit",
            body="shop.example lists it at ₹47,999, at or below your maximum of ₹49,000.",
            created_at=now - timedelta(days=10),
        ))  # fmt: skip
        item.price_observed_at = now
        await s.commit()


async def morning_reminders() -> None:
    async with get_sessionmaker()() as s:
        user = (await s.scalars(select(User).where(User.email == EMAIL))).one()
        user.money_checked_on = None
        morning = datetime.now(UTC).replace(hour=4)  # 09:30 in India
        created = await notification_service.money_alerts(s, user, morning)
        await s.commit()
        print("reminders", [a.title for a in created])


if __name__ == "__main__":
    asyncio.run({"reference": reference, "everyday": everyday}[sys.argv[1]]())
