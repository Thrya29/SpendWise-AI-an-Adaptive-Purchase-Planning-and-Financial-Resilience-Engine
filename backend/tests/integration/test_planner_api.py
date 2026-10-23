from datetime import date, timedelta
from typing import Any

import httpx

from app.domain.recurrence import add_months
from tests.conftest import signup

API = "/api/v1"


def _next_month_first() -> date:
    t = date.today()
    return date(t.year + t.month // 12, t.month % 12 + 1, 1)


async def _seed(client: httpx.AsyncClient, auth: dict[str, str]) -> dict[str, str]:
    nxt = _next_month_first()
    for path, body in (
        ("accounts", {"name": "Savings", "currency": "INR", "opening_balance_minor": 6_000_000}),
        ("incomes", {"name": "Salary", "amount_minor": 4_500_000, "currency": "INR",
                     "anchor_date": nxt.isoformat()}),
        ("obligations", {"name": "Rent", "amount_minor": 2_000_000, "currency": "INR",
                         "anchor_date": (nxt + timedelta(days=4)).isoformat()}),
    ):  # fmt: skip
        assert (await client.post(f"{API}/{path}", json=body, headers=auth)).status_code == 201
    ids: dict[str, str] = {}
    for name, body in {
        "laptop": {"tier": "need", "priority": 5, "estimated_price_minor": 3_000_000},
        "trip": {"tier": "desire", "priority": 3, "estimated_price_minor": 9_000_000},
        "phone": {"tier": "want", "estimated_price_minor": 5_000_000, "max_price_minor": 4_000_000},
        "headphones": {"tier": "want", "estimated_price_minor": 500_000},
    }.items():
        r = await client.post(
            f"{API}/items", json={"name": name, "currency": "INR", **body}, headers=auth
        )
        assert r.status_code == 201, r.text
        ids[name] = r.json()["id"]
    return ids


def _by_name(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {d["name"]: d for d in plan["decisions"]}


async def test_plan_review_and_apply(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    ids = await _seed(client, auth)
    r = await client.post(f"{API}/planner/plans", json={"horizon_months": 3}, headers=auth)
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["status"] == "draft" and plan["solver"]["status"] == "optimal"
    assert plan["summary_source"] == "mock" and plan["summary"]
    d = _by_name(plan)
    assert d["phone"]["action"] == "wait_price" and d["phone"]["changes"] == {
        "target_date": None, "status": None}  # fmt: skip
    assert d["headphones"]["action"] == "buy_now"
    assert d["headphones"]["changes"]["target_date"]["to"] == date.today().isoformat()
    assert d["trip"]["action"] in ("schedule", "postpone")
    assert [s["name"] for s in plan["scenarios"]] == ["As expected"]
    assert plan["scenarios"][0]["first_reserve_breach_on"] is None
    periods = plan["periods"]
    assert periods[0]["start"] == date.today().isoformat()
    covered_until = date.fromisoformat(periods[-1]["end"]) - timedelta(days=1)
    assert covered_until >= add_months(date.today(), 3) - timedelta(days=1)  # same as dashboard

    fetched = (await client.get(f"{API}/planner/plans/{plan['id']}", headers=auth)).json()
    assert fetched["stale"] is False and fetched["decisions"] == plan["decisions"]

    applied = await client.post(
        f"{API}/planner/plans/{plan['id']}/apply", json={"item_ids": [ids["headphones"]]},
        headers=auth,
    )  # fmt: skip
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == [ids["headphones"]]
    item = (await client.get(f"{API}/items/{ids['headphones']}", headers=auth)).json()
    assert item["target_date"] == date.today().isoformat() and item["version"] == 2

    again = await client.post(f"{API}/planner/plans/{plan['id']}/apply", json={}, headers=auth)
    assert again.status_code == 409
    listed = (await client.get(f"{API}/planner/plans", headers=auth)).json()
    assert listed[0]["id"] == plan["id"] and listed[0]["status"] == "applied"


async def test_salary_delay_protection_postpones_and_marks_items(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    ids = await _seed(client, auth)
    body = {"horizon_months": 2, "protect": [{"months": 2, "mode": "delayed"}]}
    plan = (await client.post(f"{API}/planner/plans", json=body, headers=auth)).json()
    assert [s["name"] for s in plan["scenarios"]] == ["As expected", "Salary delayed 2 months"]
    trip = _by_name(plan)["trip"]
    assert trip["action"] == "postpone" and trip["shortfall_minor"] > 0
    assert trip["changes"]["status"] == {"from": "planned", "to": "postponed"}
    r = await client.post(f"{API}/planner/plans/{plan['id']}/apply", json={}, headers=auth)
    assert ids["trip"] in r.json()["applied"]
    trip_item = (await client.get(f"{API}/items/{ids['trip']}", headers=auth)).json()
    assert trip_item["status"] == "postponed"

    # Postponed items are re-planned by default (rolling replanning).
    replan = (
        await client.post(f"{API}/planner/plans", json={"horizon_months": 6}, headers=auth)
    ).json()
    assert "trip" in _by_name(replan)
    no_postponed = (
        await client.post(
            f"{API}/planner/plans", json={"horizon_months": 6, "include_postponed": False},
            headers=auth,
        )
    ).json()  # fmt: skip
    assert "trip" not in _by_name(no_postponed)


async def _surgery(client: httpx.AsyncClient, auth: dict[str, str], **extra: Any) -> str:
    soon = (date.today() + timedelta(days=1)).isoformat()
    body = {
        "name": "surgery",
        "tier": "need",
        "priority": 5,
        "estimated_price_minor": 3_500_000,
        "currency": "INR",
        "target_date": soon,
        "deadline_type": "hard",
        **extra,
    }
    r = await client.post(
        f"{API}/items",
        json=body,
        headers=auth,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_declining_reserve_use_applies_the_safe_later_date(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    ids = await _seed(client, auth)
    for other in ids.values():  # nothing competes with the surgery for headroom
        assert (await client.delete(f"{API}/items/{other}", headers=auth)).status_code == 204
    surgery = await _surgery(client, auth)
    plan = (
        await client.post(f"{API}/planner/plans", json={"horizon_months": 2}, headers=auth)
    ).json()
    d = _by_name(plan)["surgery"]
    assert d["action"] == "use_reserve" and d["requires_reserve_approval"] is True
    assert (
        d["alternative_pay_on"]
        and d["alternative_changes"]["target_date"]["to"] == d["alternative_pay_on"]
    )
    assert "approval" in plan["summary"]

    r = (await client.post(f"{API}/planner/plans/{plan['id']}/apply", json={}, headers=auth)).json()
    assert surgery in r["applied"]
    item = (await client.get(f"{API}/items/{surgery}", headers=auth)).json()
    assert item["target_date"] == d["alternative_pay_on"]


async def test_approving_reserve_use_keeps_the_on_time_date(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _seed(client, auth)
    surgery = await _surgery(client, auth)
    await client.patch(
        f"{API}/items/{surgery}", json={"version": 1, "status": "postponed"}, headers=auth
    )
    plan = (
        await client.post(f"{API}/planner/plans", json={"horizon_months": 2}, headers=auth)
    ).json()
    d = _by_name(plan)["surgery"]
    assert d["changes"]["status"] == {"from": "postponed", "to": "planned"}
    ok = await client.post(
        f"{API}/planner/plans/{plan['id']}/apply",
        json={"item_ids": [surgery], "allow_reserve": True}, headers=auth,
    )  # fmt: skip
    assert ok.json()["applied"] == [surgery]
    item = (await client.get(f"{API}/items/{surgery}", headers=auth)).json()
    assert item["status"] == "planned" and item["target_date"] == d["current_target_date"]


async def test_reserve_use_without_safe_alternative_is_skipped(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _seed(client, auth)
    surgery = await _surgery(client, auth)
    plan = (
        await client.post(f"{API}/planner/plans", json={"horizon_months": 1}, headers=auth)
    ).json()
    d = _by_name(plan)["surgery"]
    assert d["action"] == "use_reserve" and d["alternative_changes"] is None
    r = (await client.post(f"{API}/planner/plans/{plan['id']}/apply", json={}, headers=auth)).json()
    assert {"item_id": surgery, "reason": "Needs approval to use the reserve"} in r["skipped"]


async def test_stale_plans_are_refused(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    ids = await _seed(client, auth)
    plan = (await client.post(f"{API}/planner/plans", json={}, headers=auth)).json()
    await client.patch(
        f"{API}/items/{ids['trip']}", json={"version": 1, "priority": 4}, headers=auth
    )
    assert (await client.get(f"{API}/planner/plans/{plan['id']}", headers=auth)).json()["stale"]
    r = await client.post(f"{API}/planner/plans/{plan['id']}/apply", json={}, headers=auth)
    assert r.status_code == 409 and r.json()["stale"] is True

    fresh = (await client.post(f"{API}/planner/plans", json={}, headers=auth)).json()
    assert (
        await client.post(f"{API}/planner/plans/{fresh['id']}/discard", headers=auth)
    ).status_code == 204
    assert (
        await client.post(f"{API}/planner/plans/{fresh['id']}/discard", headers=auth)
    ).status_code == 409
    unknown = await client.post(
        f"{API}/planner/plans/{plan['id']}/apply",
        json={"item_ids": ["00000000-0000-0000-0000-000000000000"]}, headers=auth,
    )  # fmt: skip
    assert unknown.status_code == 409  # still stale


async def test_plans_are_private_and_validated(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _seed(client, auth)
    plan = (await client.post(f"{API}/planner/plans", json={}, headers=auth)).json()
    other = await signup(client, email="ravi@example.com")
    assert (await client.get(f"{API}/planner/plans/{plan['id']}", headers=other)).status_code == 404
    assert (await client.get(f"{API}/planner/plans", headers=other)).json() == []
    far = (date.today() + timedelta(days=4000)).isoformat()
    bad = await client.post(
        f"{API}/planner/plans", json={"emergencies": [{"amount_minor": 1, "on": far}]}, headers=auth
    )
    assert bad.status_code == 422
    assert (
        await client.post(f"{API}/planner/plans", json={"horizon_months": 0}, headers=auth)
    ).status_code == 422


async def test_empty_plan_and_emergency(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    empty = (await client.post(f"{API}/planner/plans", json={}, headers=auth)).json()
    assert empty["decisions"] == [] and "nothing to plan" in empty["summary"]
    await _seed(client, auth)
    plan = (
        await client.post(
            f"{API}/planner/plans",
            json={"emergencies": [{"name": "Repair", "amount_minor": 1_900_000}],
                  "protect": [{"months": 1, "mode": "lost"}, {"months": 1, "mode": "lost"}]},
            headers=auth,
        )
    ).json()  # fmt: skip
    assert [s["name"] for s in plan["scenarios"]] == ["As expected", "No salary for 1 month"]
    assert _by_name(plan)["headphones"]["action"] != "buy_now"  # emergency ate the headroom


async def test_parse_item_endpoint(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await client.post(
        f"{API}/assistant/parse-item", json={"text": "salon visit next month around ₹1,500"},
        headers=auth,
    )  # fmt: skip
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["name"], d["kind"], d["estimated_price_minor"], d["currency"], d["source"]) == (
        "Salon visit", "service", 150_000, "INR", "mock")  # fmt: skip
    assert d["deadline_type"] == "soft" and d["missing"] == []

    vague = (await client.post(f"{API}/assistant/parse-item", json={"text": "birthday gift"},
                               headers=auth)).json()  # fmt: skip
    assert vague["missing"] == ["price", "date"] and vague["deadline_type"] == "none"
    usd = (await client.post(f"{API}/assistant/parse-item", json={"text": "2 x mouse $19.99"},
                             headers=auth)).json()  # fmt: skip
    assert (usd["currency"], usd["estimated_price_minor"], usd["quantity"]) == ("USD", 1999, 2)
    assert (
        await client.post(f"{API}/assistant/parse-item", json={"text": "x"}, headers=auth)
    ).status_code == 422
