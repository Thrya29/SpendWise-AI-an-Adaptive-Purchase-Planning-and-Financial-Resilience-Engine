from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx

from app.core.db import get_sessionmaker
from app.models.entities import Availability, ObservationMethod, PriceObservation

API = "/api/v1"


async def _item(client: httpx.AsyncClient, auth: dict[str, str], **extra: Any) -> dict[str, Any]:
    body = {"name": "Phone", "tier": "want", "estimated_price_minor": 5_000_000,
            "currency": "INR", **extra}  # fmt: skip
    r = await client.post(f"{API}/items", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


async def _account(client: httpx.AsyncClient, auth: dict[str, str], amount: int) -> None:
    body = {"name": "Savings", "currency": "INR", "opening_balance_minor": amount}
    assert (await client.post(f"{API}/accounts", json=body, headers=auth)).status_code == 201


async def _history(
    client: httpx.AsyncClient, auth: dict[str, str], item: dict[str, Any], prices: list[int]
) -> None:
    """Backdated daily observations ending today (the API only records 'now')."""
    owner = UUID((await client.get(f"{API}/me", headers=auth)).json()["id"])
    start = datetime.now(UTC) - timedelta(days=len(prices) - 1)
    async with get_sessionmaker()() as session:
        for i, amount in enumerate(prices):
            session.add(
                PriceObservation(
                    user_id=owner, item_id=UUID(item["id"]), amount_minor=amount,
                    currency="INR", method=ObservationMethod.JSON_LD, confidence="high",
                    availability=Availability.IN_STOCK, source_name="shop.example",
                    url="https://shop.example/p", observed_at=start + timedelta(days=i),
                )
            )  # fmt: skip
        await session.commit()


SALES = [4_500_000 if (d % 15) in (5, 6) else 5_000_000 for d in range(60)]


async def test_forecast_needs_history_then_reports_probability(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    item = await _item(client, auth, max_price_minor=4_500_000)
    none = (await client.get(f"{API}/items/{item['id']}/forecast", headers=auth)).json()
    assert none["available"] is False and "Not enough price history" in none["reason"]
    assert none["target_minor"] == 4_500_000 and none["horizon_days"] == 30

    await _history(client, auth, item, SALES)
    f = (await client.get(f"{API}/items/{item['id']}/forecast", headers=auth)).json()
    assert f["available"] is True and 0.5 < f["probability"] < 0.99
    assert f["episodes"] == 4 and f["reference_minor"] == 5_000_000
    assert f["recent_low_minor"] <= f["recent_median_minor"] <= f["recent_high_minor"]
    assert "price checks over 59 days" in f["basis"]

    deep = (await client.get(f"{API}/items/{item['id']}/forecast",
                             params={"target_minor": 3_000_000, "horizon_days": 7},
                             headers=auth)).json()  # fmt: skip
    assert deep["probability"] < f["probability"] and deep["episodes"] == 0
    bad = await client.get(f"{API}/items/{item['id']}/forecast", params={"horizon_days": 0},
                           headers=auth)  # fmt: skip
    assert bad.status_code == 422


async def test_planner_explains_waiting_with_a_forecast(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _account(client, auth, 20_000_000)
    item = await _item(client, auth, max_price_minor=4_600_000)
    await _history(client, auth, item, SALES)
    plan = (
        await client.post(f"{API}/planner/plans", json={"horizon_months": 2}, headers=auth)
    ).json()
    (d,) = plan["decisions"]
    assert d["action"] == "wait_price" and d["forecast_probability"] is not None
    assert d["forecast_by"] and d["forecast_confidence"] in ("low", "medium", "high")
    pct = round(d["forecast_probability"] * 100)
    assert f"{pct}% chance of reaching your limit in time" in plan["summary"]

    fresh = await _item(client, auth, name="New TV", max_price_minor=1_000)
    plan = (await client.post(f"{API}/planner/plans", json={}, headers=auth)).json()
    tv = next(x for x in plan["decisions"] if x["item_id"] == fresh["id"])
    assert tv["forecast_probability"] is None and "Not enough price history" in tv["forecast_note"]


async def test_alternatives_link_merge_unlink_and_plan(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _account(client, auth, 1_000_000)
    a = await _item(
        client, auth, name="Pixel", tier="need", priority=5, estimated_price_minor=800_000
    )
    b = await _item(
        client, auth, name="Galaxy", tier="need", priority=3, estimated_price_minor=700_000
    )
    c = await _item(client, auth, name="iPhone", estimated_price_minor=900_000)
    d = await _item(client, auth, name="Moto", estimated_price_minor=300_000)

    group = (await client.post(f"{API}/items/{a['id']}/alternatives",
                               json={"other_item_id": b["id"]}, headers=auth)).json()  # fmt: skip
    assert {x["name"] for x in group} == {"Pixel", "Galaxy"}
    assert len({x["alternative_group"] for x in group}) == 1
    await client.post(f"{API}/items/{c['id']}/alternatives", json={"other_item_id": d["id"]},
                      headers=auth)  # fmt: skip
    merged = (await client.post(f"{API}/items/{b['id']}/alternatives",
                                json={"other_item_id": c["id"]}, headers=auth)).json()  # fmt: skip
    assert {x["name"] for x in merged} == {"Pixel", "Galaxy", "iPhone", "Moto"}

    plan = (
        await client.post(f"{API}/planner/plans", json={"horizon_months": 1}, headers=auth)
    ).json()
    by = {x["name"]: x for x in plan["decisions"]}
    buying = [n for n, x in by.items() if x["action"] in ("buy_now", "schedule", "use_reserve")]
    assert buying == ["Pixel"]
    assert by["Galaxy"]["action"] == "alternative"
    assert by["Galaxy"]["chosen_alternative_id"] == a["id"]
    assert by["Galaxy"]["changes"] == {"target_date": None, "status": None}

    for x in (b, c, d):
        assert (
            await client.delete(f"{API}/items/{x['id']}/alternatives", headers=auth)
        ).status_code == 204
    last = (await client.get(f"{API}/items/{a['id']}", headers=auth)).json()
    assert last["alternative_group"] is None  # a group of one is dissolved
    assert (
        await client.delete(f"{API}/items/{a['id']}/alternatives", headers=auth)
    ).status_code == 204
    self_link = await client.post(f"{API}/items/{a['id']}/alternatives",
                                  json={"other_item_id": a["id"]}, headers=auth)  # fmt: skip
    assert self_link.status_code == 422


async def test_alternative_search_needs_claude(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    item = await _item(client, auth)
    r = (await client.post(f"{API}/items/{item['id']}/alternatives/search", headers=auth)).json()
    assert r["available"] is False and "Claude API key" in r["message"] and r["suggestions"] == []


async def test_buying_a_fallback_states_the_waiting_preferred_alternative(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _account(client, auth, 20_000_000)
    preferred = await _item(client, auth, name="55-inch TV", priority=4, max_price_minor=4_600_000)
    fallback = await _item(
        client, auth, name="50-inch TV", priority=3, estimated_price_minor=4_000_000
    )
    await _history(client, auth, preferred, SALES)
    await client.post(f"{API}/items/{preferred['id']}/alternatives",
                      json={"other_item_id": fallback["id"]}, headers=auth)  # fmt: skip
    plan = (
        await client.post(f"{API}/planner/plans", json={"horizon_months": 2}, headers=auth)
    ).json()
    by = {d["name"]: d for d in plan["decisions"]}
    assert by["55-inch TV"]["action"] == "wait_price"
    assert by["50-inch TV"]["action"] == "buy_now"
    assert by["50-inch TV"]["group_note"].startswith("Your preferred 55-inch TV is waiting")
    assert "rules it out" in by["50-inch TV"]["group_note"]
