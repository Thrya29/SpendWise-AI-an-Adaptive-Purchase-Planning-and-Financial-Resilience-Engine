from typing import Any

import httpx

from tests.conftest import REGISTER, signup

API = "/api/v1"

ITEM: dict[str, Any] = {
    "name": "Work laptop",
    "tier": "need",
    "kind": "product",
    "priority": 5,
    "estimated_price_minor": 7_500_000,
    "currency": "INR",
    "target_date": "2027-01-15",
    "deadline_type": "hard",
    "lead_time_days": 7,
    "url": "https://example.com/laptop",
}


async def test_item_crud_lifecycle(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await client.post(f"{API}/items", json=ITEM, headers=auth)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["status"] == "planned" and item["version"] == 1 and item["price_source"] == "user"

    r = await client.patch(
        f"{API}/items/{item['id']}", json={"version": 1, "priority": 4}, headers=auth
    )
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["priority"] == 4

    # Stale version -> 409 with the current version reported
    stale = await client.patch(
        f"{API}/items/{item['id']}", json={"version": 1, "priority": 3}, headers=auth
    )
    assert stale.status_code == 409 and stale.json()["current_version"] == 2

    done = await client.patch(
        f"{API}/items/{item['id']}", json={"version": 2, "status": "purchased"}, headers=auth
    )
    assert done.json()["purchased_on"] is not None

    assert (await client.delete(f"{API}/items/{item['id']}", headers=auth)).status_code == 204
    assert (await client.get(f"{API}/items/{item['id']}", headers=auth)).status_code == 404


async def test_item_validation_rules(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    no_date = {**ITEM, "target_date": None}
    assert (await client.post(f"{API}/items", json=no_date, headers=auth)).status_code == 422
    bad_url = {**ITEM, "url": "javascript:alert(1)"}
    assert (await client.post(f"{API}/items", json=bad_url, headers=auth)).status_code == 422
    neg = {**ITEM, "estimated_price_minor": -1}
    assert (await client.post(f"{API}/items", json=neg, headers=auth)).status_code == 422

    soft = (
        await client.post(f"{API}/items", json={**ITEM, "deadline_type": "soft"}, headers=auth)
    ).json()
    r = await client.patch(
        f"{API}/items/{soft['id']}",
        json={"version": 1, "deadline_type": "hard", "target_date": None},
        headers=auth,
    )
    assert r.status_code == 422
    r = await client.patch(
        f"{API}/items/{soft['id']}", json={"version": 1, "name": None}, headers=auth
    )
    assert r.status_code == 422


async def test_item_filters_and_pagination(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    for i, tier in enumerate(["need", "want", "desire", "want"]):
        body = {**ITEM, "name": f"Item {i} 100%", "tier": tier, "deadline_type": "soft"}
        assert (await client.post(f"{API}/items", json=body, headers=auth)).status_code == 201
    wants = (await client.get(f"{API}/items?tier=want", headers=auth)).json()
    assert wants["total"] == 2 and {i["tier"] for i in wants["items"]} == {"want"}
    page = (await client.get(f"{API}/items?limit=3&offset=0", headers=auth)).json()
    assert page["total"] == 4 and len(page["items"]) == 3
    search = (await client.get(f"{API}/items?q=2 100%", headers=auth)).json()
    assert search["total"] == 1
    assert (await client.get(f"{API}/items?limit=0", headers=auth)).status_code == 422


async def test_users_are_isolated(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    item = (await client.post(f"{API}/items", json=ITEM, headers=auth)).json()
    acc = (
        await client.post(f"{API}/accounts", json={"name": "Main", "currency": "INR"}, headers=auth)
    ).json()
    other = await signup(client, email="ravi@example.com")
    assert (await client.get(f"{API}/items/{item['id']}", headers=other)).status_code == 404
    patch = await client.patch(f"{API}/items/{item['id']}", json={"version": 1}, headers=other)
    assert patch.status_code == 404
    assert (await client.delete(f"{API}/items/{item['id']}", headers=other)).status_code == 404
    assert (await client.get(f"{API}/items", headers=other)).json()["total"] == 0
    txn = await client.post(
        f"{API}/transactions",
        json={
            "account_id": acc["id"],
            "kind": "expense",
            "amount_minor": 100,
            "occurred_on": "2026-01-01",
        },
        headers=other,
    )
    assert txn.status_code == 422


async def test_account_balance_reflects_transactions(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    acc = (
        await client.post(
            f"{API}/accounts",
            json={"name": "Savings", "currency": "INR", "opening_balance_minor": 6_000_000},
            headers=auth,
        )
    ).json()
    assert acc["balance_minor"] == 6_000_000
    for kind, amount in (("expense", 1_000_000), ("income", 250_000)):
        r = await client.post(
            f"{API}/transactions",
            json={
                "account_id": acc["id"],
                "kind": kind,
                "amount_minor": amount,
                "occurred_on": "2026-01-10",
                "category": "test",
            },
            headers=auth,
        )
        assert r.status_code == 201 and r.json()["currency"] == "INR"
    acc2 = (await client.get(f"{API}/accounts/{acc['id']}", headers=auth)).json()
    assert acc2["balance_minor"] == 5_250_000
    listed = (await client.get(f"{API}/transactions?account_id={acc['id']}", headers=auth)).json()
    assert listed["total"] == 2


async def test_income_and_obligation_validation(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    bad = {
        "name": "Pay",
        "amount_minor": 100,
        "currency": "INR",
        "anchor_date": "2026-05-01",
        "end_date": "2026-04-01",
    }
    assert (await client.post(f"{API}/incomes", json=bad, headers=auth)).status_code == 422
    ok = (
        await client.post(
            f"{API}/obligations",
            json={
                "name": "Rent",
                "amount_minor": 100,
                "currency": "INR",
                "anchor_date": "2026-05-01",
            },
            headers=auth,
        )
    ).json()
    r = await client.patch(
        f"{API}/obligations/{ok['id']}", json={"version": 1, "end_date": "2026-01-01"}, headers=auth
    )
    assert r.status_code == 422
    foreign = {
        "name": "Pay",
        "amount_minor": 100,
        "currency": "INR",
        "anchor_date": "2026-05-01",
        "account_id": "00000000-0000-0000-0000-000000000000",
    }
    assert (await client.post(f"{API}/incomes", json=foreign, headers=auth)).status_code == 422


async def test_profile_llm_settings_export_and_delete(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    r = await client.patch(f"{API}/me", json={"reserve_months": 3, "city": "Pune"}, headers=auth)
    assert r.json()["reserve_months"] == 3 and r.json()["city"] == "Pune"
    assert (
        await client.patch(f"{API}/me", json={"base_currency": None}, headers=auth)
    ).status_code == 422

    no_key = await client.put(f"{API}/me/llm", json={"mode": "anthropic"}, headers=auth)
    assert no_key.status_code == 422
    bad_key = await client.put(
        f"{API}/me/llm",
        json={"mode": "anthropic", "api_key": "not-an-anthropic-key-123"},
        headers=auth,
    )
    assert bad_key.status_code == 422
    ok = await client.put(
        f"{API}/me/llm",
        json={"mode": "anthropic", "api_key": "sk-ant-test-0000000000000000wxyz"},
        headers=auth,
    )
    assert ok.json()["llm_mode"] == "anthropic" and ok.json()["llm_api_key_hint"] == "wxyz"
    assert "sk-ant" not in ok.text
    cleared = await client.delete(f"{API}/me/llm/key", headers=auth)
    assert cleared.json()["llm_mode"] == "mock" and cleared.json()["llm_api_key_hint"] is None

    await client.post(f"{API}/items", json=ITEM, headers=auth)
    export = (await client.get(f"{API}/me/export", headers=auth)).json()
    assert export["profile"]["email"] == REGISTER["email"] and len(export["planned_items"]) == 1

    wrong = await client.post(f"{API}/me/delete", json={"password": "wrong"}, headers=auth)
    assert wrong.status_code == 401
    gone = await client.post(
        f"{API}/me/delete", json={"password": REGISTER["password"]}, headers=auth
    )
    assert gone.status_code == 204
    assert (await client.get(f"{API}/me", headers=auth)).status_code == 401
