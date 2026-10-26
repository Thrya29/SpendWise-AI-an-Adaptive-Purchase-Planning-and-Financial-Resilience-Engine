"""Savings and investment education endpoints, with all external sources mocked."""

import json
from collections.abc import AsyncIterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from app import worker
from app.api.routes.insights import get_data_client
from app.api.routes.market import get_fx_client
from app.services import insights_data
from tests.integration.test_market_api import ecb, fx_override

API = "/api/v1"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "navall_sample.txt"
CODE = 135762  # Axis Children's Fund - Direct Plan - Growth Option


def amfi_text() -> str:
    """The real AMFI sample, re-dated so 'active' checks never depend on the calendar."""
    today = date.today().strftime("%d-%b-%Y")
    return FIXTURE.read_text(encoding="utf-8").replace("22-Oct-2026", today)


def history_json(days: int = 800, growth: float = 0.0004) -> dict[str, Any]:
    start = date.today() - timedelta(days=days)
    data = [
        {
            "date": (start + timedelta(days=d)).strftime("%d-%m-%Y"),
            "nav": f"{20 * (1 + growth) ** d * (1 + 0.01 * ((d % 7) - 3)):.4f}",
        }
        for d in range(days + 1)
    ]
    return {"meta": {"scheme_code": CODE}, "data": list(reversed(data)), "status": "SUCCESS"}


def data_handler(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "portal.amfiindia.com":
        return httpx.Response(200, text=amfi_text())
    if host == "api.mfapi.in" and path == f"/mf/{CODE}":
        return httpx.Response(200, json=history_json())
    if host == "api.gold-api.com":
        return httpx.Response(
            200,
            json={
                "currency": "USD",
                "price": 4030.600098,
                "symbol": "XAU",
                "updatedAt": "2026-10-23T12:06:13Z",
            },
        )
    if host == "api.frankfurter.dev":
        return ecb(date.today())(request)
    return httpx.Response(404)


@pytest.fixture
def sources(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    async def data_client() -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(data_handler)) as c:
            yield c

    client.app.dependency_overrides[get_data_client] = data_client  # type: ignore[attr-defined]
    fx_override(client, ecb(date.today()))
    monkeypatch.setattr(insights_data, "MIN_SCHEMES", 10)
    return httpx.AsyncClient(transport=httpx.MockTransport(data_handler))


def test_parser_handles_real_format_and_missing_navs() -> None:
    rows = insights_data.parse_amfi(amfi_text() + "\n999999;-;-;Old Fund;-;-;N.A.;01-Jan-2015\n")
    first = next(r for r in rows if r.scheme_code == CODE)
    assert first.name == "Axis Children's Fund - Direct Plan - Growth Option"
    assert first.fund_house == "Axis Mutual Fund" and first.isin == "INF846K01WO1"
    assert first.nav == "28.8435" and first.category
    old = next(r for r in rows if r.scheme_code == 999999)
    assert old.nav is None and old.nav_date == date(2015, 1, 1)


async def test_reference_data_refresh_search_watch_and_detail(
    client: httpx.AsyncClient, auth: dict[str, str], sources: httpx.AsyncClient
) -> None:
    done = await worker.refresh_reference_data_if_due(sources)
    assert {"amfi", "gold"} <= set(done)
    assert await worker.refresh_reference_data_if_due(sources) == []  # fresh: nothing to do

    found = (
        await client.get(f"{API}/funds/search", params={"q": "axis children direct"}, headers=auth)
    ).json()
    assert [f["scheme_code"] for f in found][:1] and all("Direct Plan" in f["name"] for f in found)
    stale = (
        await client.get(f"{API}/funds/search", params={"q": "franklin short-term"}, headers=auth)
    ).json()
    # Hidden by default: a wound-down plan (old NAV date) and a segregated portfolio whose
    # current NAV is published as 0.0000 (no valid price).
    assert stale == []
    with_old = (
        await client.get(
            f"{API}/funds/search",
            headers=auth,
            params={"q": "franklin short-term", "include_inactive": "true"},
        )
    ).json()
    assert with_old and with_old[0]["active"] is False
    assert (
        await client.get(f"{API}/funds/search", params={"q": "ab"}, headers=auth)
    ).status_code == 422

    assert (
        await client.post(f"{API}/funds/watchlist", json={"scheme_code": CODE}, headers=auth)
    ).status_code == 201
    await client.post(
        f"{API}/funds/watchlist", json={"scheme_code": CODE}, headers=auth
    )  # idempotent
    assert [
        f["scheme_code"] for f in (await client.get(f"{API}/funds/watchlist", headers=auth)).json()
    ] == [CODE]

    detail = (await client.get(f"{API}/funds/{CODE}", headers=auth)).json()
    assert detail["watched"] is True and detail["history_points"] == 801
    assert set(detail["cagr_percent"]) == {"1y"} and float(detail["cagr_percent"]["1y"]) > 10
    assert float(detail["volatility_percent"]) > 0 and float(detail["max_drawdown_percent"]) > 0
    assert (
        "community mirror" in detail["history_source"]
        and "not investment advice" in detail["disclaimer"]
    )

    assert (await client.delete(f"{API}/funds/watchlist/{CODE}", headers=auth)).status_code == 204
    assert (await client.get(f"{API}/funds/watchlist", headers=auth)).json() == []
    assert (await client.get(f"{API}/funds/1", headers=auth)).status_code == 404


async def test_incomplete_amfi_file_is_rejected(client: httpx.AsyncClient) -> None:
    from app.core.db import get_sessionmaker  # noqa: PLC0415

    mock = httpx.MockTransport(data_handler)
    async with httpx.AsyncClient(transport=mock) as c, get_sessionmaker()() as session:
        with pytest.raises(insights_data.SourceUnavailableError, match="incomplete"):
            await insights_data.refresh_schemes(session, c)


async def test_simulator_defaults_fund_history_and_fd_comparison(
    client: httpx.AsyncClient, auth: dict[str, str], sources: httpx.AsyncClient
) -> None:
    base = {"monthly_minor": 10_000_00, "months": 120}
    d = (await client.post(f"{API}/insights/simulate", json=base, headers=auth)).json()
    assert d["p10_minor"] < d["p50_minor"] < d["p90_minor"]
    assert (
        "Illustrative defaults" in d["assumptions_source"] and d["invested_minor"] == 1_200_000_00
    )

    mine = (
        await client.post(
            f"{API}/insights/simulate",
            headers=auth,
            json={
                **base,
                "annual_return_percent": "8",
                "annual_volatility_percent": "0",
                "compare_fd_rate_percent": "8",
            },
        )
    ).json()
    assert mine["p50_minor"] == pytest.approx(mine["fd_value_minor"], rel=1e-6)
    assert mine["probability_of_loss"] == 0

    await worker.refresh_reference_data_if_due(sources)
    from_fund = (
        await client.post(
            f"{API}/insights/simulate", json={**base, "scheme_code": CODE}, headers=auth
        )
    ).json()
    assert "This fund's last 1 year(s)" in from_fund["assumptions_source"]
    assert float(from_fund["annual_return_percent"]) > 10
    for bad in ({"months": 120}, {**base, "months": 0}, {**base, "annual_return_percent": "500"}):
        assert (
            await client.post(f"{API}/insights/simulate", json=bad, headers=auth)
        ).status_code == 422


async def test_deposit_comparison_and_premature_withdrawal(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    body = {
        "principal_minor": 1_00_000_00,
        "fd_rate_percent": "7",
        "months": 12,
        "savings_rate_percent": "3",
        "premature": {"held_months": 6, "penalty_percent": "1"},
    }
    r = (await client.post(f"{API}/insights/deposit", json=body, headers=auth)).json()
    assert r["fd_maturity_minor"] == 10_718_590 and r["savings_balance_minor"] == 10_303_391
    assert r["fd_advantage_minor"] == 10_718_590 - 10_303_391
    assert float(r["premature_effective_rate_percent"]) == 6.0
    assert r["premature_interest_lost_minor"] > 0
    bad = {**body, "premature": {"held_months": 13}}
    assert (await client.post(f"{API}/insights/deposit", json=bad, headers=auth)).status_code == 422


async def test_safe_to_lock_respects_plans_and_reserve(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    t = date.today()
    nxt = date(t.year + t.month // 12, t.month % 12 + 1, 1)
    for path, body in (
        ("accounts", {"name": "S", "currency": "INR", "opening_balance_minor": 2_00_000_00}),
        (
            "incomes",
            {
                "name": "Pay",
                "amount_minor": 45_000_00,
                "currency": "INR",
                "anchor_date": nxt.isoformat(),
            },
        ),
        (
            "obligations",
            {
                "name": "Rent",
                "amount_minor": 20_000_00,
                "currency": "INR",
                "anchor_date": (nxt + timedelta(days=4)).isoformat(),
            },
        ),
        (
            "items",
            {
                "name": "Laptop",
                "tier": "need",
                "estimated_price_minor": 50_000_00,
                "currency": "INR",
                "target_date": (nxt + timedelta(days=10)).isoformat(),
            },
        ),
    ):
        assert (await client.post(f"{API}/{path}", json=body, headers=auth)).status_code == 201
    r = (
        await client.get(
            f"{API}/insights/safe-to-lock",
            headers=auth,
            params={"months": 6, "protect_delay_months": 1},
        )
    ).json()
    # Delayed salary: 2L - 20k rent - 50k laptop = 1.3L low point; reserve 40k -> 90k lockable.
    assert r["amount_minor"] == 90_000_00 and r["reserve_minor"] == 40_000_00
    assert r["binding_scenario"] == "Salary delayed 1 month" and "₹90,000" in r["explanation"]
    relaxed = (
        await client.get(
            f"{API}/insights/safe-to-lock",
            headers=auth,
            params={"months": 6, "protect_delay_months": 0},
        )
    ).json()
    assert relaxed["amount_minor"] > r["amount_minor"]


async def test_nothing_to_lock_when_reserve_is_short(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await client.post(
        f"{API}/obligations",
        headers=auth,
        json={
            "name": "Rent",
            "amount_minor": 30_000_00,
            "currency": "INR",
            "anchor_date": date.today().isoformat(),
        },
    )
    r = (await client.get(f"{API}/insights/safe-to-lock", headers=auth)).json()
    assert r["amount_minor"] == 0 and r["explanation"].startswith("Nothing can be locked")


async def test_gold_reference_and_jewellery_bill(
    client: httpx.AsyncClient, auth: dict[str, str], sources: httpx.AsyncClient
) -> None:
    assert (await client.get(f"{API}/gold", headers=auth)).json()["available"] is False
    assert (await client.post(f"{API}/fx/refresh", headers=auth)).status_code == 200
    g = (await client.post(f"{API}/gold/refresh", headers=auth)).json()
    assert g["available"] is True and g["usd_per_ounce"] == "$4,030.60"
    # $4,030.60/oz / 31.1034768 g = $129.59/g; x 94.8228 INR/USD ~ ₹12,288/g
    assert 1_228_000 <= g["per_gram_24k_minor"] <= 1_229_500
    assert g["per_gram_22k_minor"] < g["per_gram_24k_minor"] and "import duty" in g["caveat"]
    assert "converted from USD" in g["fx_note"]

    bill = (
        await client.post(
            f"{API}/gold/jewellery",
            headers=auth,
            json={
                "rate_24k_per_gram_minor": 7_500_00,
                "weight_grams": "10",
                "purity": "22K",
                "making_percent": "12",
                "hallmark_fee_minor": 45_00,
            },
        )
    ).json()
    assert bill["total_minor"] == (
        bill["gold_value_minor"]
        + bill["making_charges_minor"]
        + bill["hallmark_fee_minor"]
        + bill["gst_minor"]
    )
    both = await client.post(
        f"{API}/gold/jewellery",
        headers=auth,
        json={
            "rate_24k_per_gram_minor": 1,
            "weight_grams": "1",
            "making_percent": "1",
            "making_per_gram_minor": 1,
        },
    )
    assert both.status_code == 422


async def test_gold_unavailable_without_exchange_rates(
    client: httpx.AsyncClient, auth: dict[str, str], sources: httpx.AsyncClient
) -> None:
    client.app.dependency_overrides.pop(get_fx_client, None)  # type: ignore[attr-defined]
    await client.post(f"{API}/gold/refresh", headers=auth)
    g = (await client.get(f"{API}/gold", headers=auth)).json()
    assert g["available"] is False and "no recent exchange rate" in g["fx_note"]
    json.dumps(g)
