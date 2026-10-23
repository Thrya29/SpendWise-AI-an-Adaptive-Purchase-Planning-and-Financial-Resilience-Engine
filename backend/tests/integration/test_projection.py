from datetime import date, timedelta

import httpx

API = "/api/v1"


async def _seed(client: httpx.AsyncClient, auth: dict[str, str], start: date) -> None:
    nxt = date(start.year + (start.month // 12), start.month % 12 + 1, 1)
    calls = [
        ("accounts", {"name": "Savings", "currency": "INR", "opening_balance_minor": 6_000_000}),
        ("accounts", {"name": "USD wallet", "currency": "USD", "opening_balance_minor": 10_000}),
        (
            "incomes",
            {
                "name": "Salary",
                "amount_minor": 4_500_000,
                "currency": "INR",
                "anchor_date": nxt.isoformat(),
            },
        ),
        (
            "obligations",
            {
                "name": "Rent & essentials",
                "amount_minor": 2_000_000,
                "currency": "INR",
                "anchor_date": (nxt + timedelta(days=4)).isoformat(),
            },
        ),
        (
            "items",
            {
                "name": "Laptop",
                "tier": "need",
                "estimated_price_minor": 3_000_000,
                "currency": "INR",
                "target_date": (nxt + timedelta(days=16)).isoformat(),
                "lead_time_days": 7,
            },
        ),
        (
            "items",
            {
                "name": "Trip",
                "tier": "desire",
                "estimated_price_minor": 2_500_000,
                "currency": "INR",
            },
        ),
    ]
    for path, body in calls:
        r = await client.post(f"{API}/{path}", json=body, headers=auth)
        assert r.status_code == 201, r.text


async def test_projection_with_salary_delay_and_emergency(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    me = (await client.get(f"{API}/me", headers=auth)).json()
    assert me["timezone"] == "Asia/Kolkata"
    start = date.today()
    await _seed(client, auth, start)

    base = (await client.post(f"{API}/projection", json={"horizon_months": 3}, headers=auth)).json()
    assert base["opening_balance_minor"] == 6_000_000
    assert base["monthly_essentials_minor"] == 2_000_000
    assert base["reserve_required_minor"] == 4_000_000
    assert any("USD wallet" in w for w in base["warnings"])
    assert any("no target date" in w for w in base["warnings"])
    (laptop,) = base["planned_checks"]
    assert laptop["name"] == "Laptop"

    shocked = (
        await client.post(
            f"{API}/projection",
            json={
                "horizon_months": 3,
                "shock": {"months": 2, "mode": "delayed"},
                "emergencies": [{"name": "Medical", "amount_minor": 1_000_000}],
            },
            headers=auth,
        )
    ).json()
    assert shocked["is_safe"] is False
    assert shocked["min_balance_minor"] < base["min_balance_minor"]
    assert shocked["first_reserve_breach_on"] is not None
    assert len(shocked["months"]) >= 3


async def test_projection_validation(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    far = (date.today() + timedelta(days=4000)).isoformat()
    r = await client.post(
        f"{API}/projection",
        json={"emergencies": [{"amount_minor": 100, "on": far}]},
        headers=auth,
    )
    assert r.status_code == 422
    assert (
        await client.post(f"{API}/projection", json={"horizon_months": 99}, headers=auth)
    ).status_code == 422
    empty = (await client.post(f"{API}/projection", json={}, headers=auth)).json()
    assert empty["is_safe"] is True and empty["runway_months"] is None
