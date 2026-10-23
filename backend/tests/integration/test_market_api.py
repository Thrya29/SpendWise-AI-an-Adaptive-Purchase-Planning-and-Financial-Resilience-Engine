"""Market data API against a simulated internet (no real network calls)."""

import json
from collections.abc import AsyncIterator, Callable
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from app.api.routes.market import get_fetcher, get_fx_client
from app.market.fetcher import SafeFetcher

API = "/api/v1"


def product_page(price: str, currency: str = "INR", availability: str = "InStock") -> str:
    ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Acme Laptop 14",
        "offers": {"@type": "Offer", "price": price, "priceCurrency": currency,
                   "availability": f"https://schema.org/{availability}"},
    }  # fmt: skip
    script = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    return f"<html><title>Acme</title>{script}</html>"


class Shop:
    """A fake website whose page content the test can change between checks."""

    def __init__(self) -> None:
        self.page = product_page("74999.00")
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        if self.status != 200:
            return httpx.Response(self.status)
        return httpx.Response(200, html=self.page)


async def _public_dns(host: str) -> list[str]:
    if host.endswith(".example"):
        return ["93.184.215.14"]
    raise OSError("NXDOMAIN")


@pytest.fixture
def shop(client: httpx.AsyncClient) -> Shop:
    shop = Shop()

    async def fetcher() -> AsyncIterator[SafeFetcher]:
        http = httpx.AsyncClient(transport=httpx.MockTransport(shop.handler))
        yield SafeFetcher(http, _public_dns)
        await http.aclose()

    client.app.dependency_overrides[get_fetcher] = fetcher  # type: ignore[attr-defined]
    return shop


def fx_override(
    client: httpx.AsyncClient, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    async def fx_client() -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c

    client.app.dependency_overrides[get_fx_client] = fx_client  # type: ignore[attr-defined]


def ecb(day: date) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.frankfurter.dev"
        return httpx.Response(200, json={
            "amount": 1.0, "base": "EUR", "date": day.isoformat(),
            "rates": {"INR": 106.249, "USD": 1.1205, "JPY": 175.97, "XAU": 0.0004},
        })  # fmt: skip

    return handler


async def _item(client: httpx.AsyncClient, auth: dict[str, str], **extra: Any) -> dict[str, Any]:
    body = {"name": "Laptop", "tier": "need", "estimated_price_minor": 8_000_000,
            "currency": "INR", "url": "https://shop.example/laptop", **extra}  # fmt: skip
    r = await client.post(f"{API}/items", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


async def test_preview_reads_published_price(
    client: httpx.AsyncClient, auth: dict[str, str], shop: Shop
) -> None:
    r = await client.post(f"{API}/market/preview", json={"url": "https://www.shop.example/laptop"},
                          headers=auth)  # fmt: skip
    p = r.json()
    assert r.status_code == 200 and p["found"] is True
    assert (p["price_minor"], p["currency"], p["method"], p["confidence"]) == (
        7_499_900, "INR", "json_ld", "high")  # fmt: skip
    assert p["source_name"] == "shop.example" and p["title"] == "Acme Laptop 14"
    assert p["availability"] == "in_stock"

    shop.page = "<html><title>Shop</title><p>Price: ₹999</p></html>"
    none = (await client.post(f"{API}/market/preview", json={"url": "https://shop.example/x"},
                              headers=auth)).json()  # fmt: skip
    assert none["found"] is False and "machine-readable" in none["message"]

    blocked = (await client.post(f"{API}/market/preview", json={"url": "https://shop.example/private/p"},
                                 headers=auth)).json()  # fmt: skip
    assert blocked["found"] is False and "does not allow" in blocked["message"]

    internal = (await client.post(f"{API}/market/preview", json={"url": "http://169.254.169.254/x"},
                                  headers=auth)).json()  # fmt: skip
    assert internal["found"] is False and "not a public website" in internal["message"]


async def test_check_history_quote_and_consent_to_apply(
    client: httpx.AsyncClient, auth: dict[str, str], shop: Shop
) -> None:
    item = await _item(client, auth)
    r = (await client.post(f"{API}/items/{item['id']}/price-check", headers=auth)).json()
    assert r["found"] is True and r["applied_to_item"] is False  # tracking is off: no change
    obs = r["observation"]
    assert obs["amount_minor"] == 7_499_900 and obs["url"] == "https://shop.example/laptop"
    current = (await client.get(f"{API}/items/{item['id']}", headers=auth)).json()
    assert current["estimated_price_minor"] == 8_000_000 and current["last_checked_at"]

    quote = await client.post(
        f"{API}/items/{item['id']}/prices",
        json={"amount_minor": 7_200_000, "source_name": "Croma, FC Road", "note": "in-store offer"},
        headers=auth,
    )  # fmt: skip
    assert quote.status_code == 201 and quote.json()["method"] == "manual"
    history = (await client.get(f"{API}/items/{item['id']}/prices", headers=auth)).json()
    assert [h["source_name"] for h in history] == ["Croma, FC Road", "shop.example"]

    applied = await client.post(
        f"{API}/items/{item['id']}/prices/{quote.json()['id']}/apply",
        json={"version": current["version"]}, headers=auth,
    )  # fmt: skip
    assert applied.status_code == 200
    updated = applied.json()
    assert updated["estimated_price_minor"] == 7_200_000 and updated["price_source"] == "quote"
    stale = await client.post(
        f"{API}/items/{item['id']}/prices/{obs['id']}/apply", json={"version": 1}, headers=auth
    )
    assert stale.status_code == 409


async def test_tracking_updates_price_and_raises_alerts(
    client: httpx.AsyncClient, auth: dict[str, str], shop: Shop
) -> None:
    item = await _item(client, auth, track_price=True, max_price_minor=7_000_000)
    first = (await client.post(f"{API}/items/{item['id']}/price-check", headers=auth)).json()
    assert first["applied_to_item"] is True
    tracked = (await client.get(f"{API}/items/{item['id']}", headers=auth)).json()
    assert tracked["estimated_price_minor"] == 7_499_900 and tracked["price_source"] == "link"
    assert tracked["price_observed_at"] is not None
    assert (await client.get(f"{API}/alerts/unread-count", headers=auth)).json() == {"unread": 0}

    shop.page = product_page("69999.00")  # 6.7% drop and below the 70,000 limit
    await client.post(f"{API}/items/{item['id']}/price-check", headers=auth)
    alerts = (await client.get(f"{API}/alerts", headers=auth)).json()
    assert {a["kind"] for a in alerts} == {"price_target", "price_drop"}
    assert any("₹69,999" in a["body"] for a in alerts)

    shop.page = product_page("69999.00", availability="OutOfStock")
    await client.post(f"{API}/items/{item['id']}/price-check", headers=auth)
    shop.page = product_page("69999.00")
    await client.post(f"{API}/items/{item['id']}/price-check", headers=auth)
    kinds = [a["kind"] for a in (await client.get(f"{API}/alerts", headers=auth)).json()]
    assert kinds.count("back_in_stock") == 1 and kinds.count("price_target") == 1

    assert (await client.post(f"{API}/alerts/read-all", headers=auth)).status_code == 204
    assert (await client.get(f"{API}/alerts?unread=true", headers=auth)).json() == []

    shop.page = product_page("899.00", currency="USD")
    r = (await client.post(f"{API}/items/{item['id']}/price-check", headers=auth)).json()
    assert r["applied_to_item"] is False and "priced in INR" in r["message"]


async def test_failed_checks_are_recorded_and_alerted(
    client: httpx.AsyncClient, auth: dict[str, str], shop: Shop
) -> None:
    item = await _item(client, auth, track_price=True)
    shop.status = 403
    for _ in range(3):
        r = (await client.post(f"{API}/items/{item['id']}/price-check", headers=auth)).json()
        assert r["found"] is False and "blocks automated" in r["message"]
    current = (await client.get(f"{API}/items/{item['id']}", headers=auth)).json()
    assert "blocks automated" in current["last_check_error"]
    alerts = (await client.get(f"{API}/alerts", headers=auth)).json()
    assert [a["kind"] for a in alerts] == ["check_failing"]
    one = alerts[0]["id"]
    assert (await client.post(f"{API}/alerts/{one}/read", headers=auth)).status_code == 204

    no_link = await _item(client, auth, url=None)
    r = await client.post(f"{API}/items/{no_link['id']}/price-check", headers=auth)
    assert r.status_code == 422


async def test_fx_refresh_and_conversion_in_projection(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    assert (await client.get(f"{API}/fx/latest", headers=auth)).json()["available"] is False
    fx_override(client, ecb(date.today() - timedelta(days=1)))
    fx = (await client.post(f"{API}/fx/refresh", headers=auth)).json()
    assert fx["available"] is True and fx["base"] == "INR"
    assert fx["rates"]["EUR"] == "106.249" and "XAU" not in fx["rates"]
    assert fx["rates"]["USD"].startswith("94.822846")

    for name, cur, amount in (("INR", "INR", 100_000), ("USD wallet", "USD", 10_000),
                              ("AED card", "AED", 10_000)):  # fmt: skip
        body = {"name": name, "currency": cur, "opening_balance_minor": amount}
        await client.post(f"{API}/accounts", json=body, headers=auth)
    p = (await client.post(f"{API}/projection", json={"horizon_months": 1}, headers=auth)).json()
    assert p["opening_balance_minor"] == 100_000 + 948_228  # $100 -> ₹9,482.28
    assert "Account 'USD wallet' converted from USD at 1 USD = 94.8228 INR (" in " ".join(
        p["warnings"]
    )
    assert any("AED card" in w and "no reference rate" in w for w in p["warnings"])

    usd_item = {
        "name": "Kindle",
        "tier": "want",
        "estimated_price_minor": 10_000,
        "currency": "USD",
    }
    await client.post(f"{API}/items", json=usd_item, headers=auth)
    plan = (
        await client.post(f"{API}/planner/plans", json={"horizon_months": 1}, headers=auth)
    ).json()
    (d,) = plan["decisions"]
    assert (d["original_currency"], d["original_unit_price_minor"], d["unit_price_minor"]) == (
        "USD", 10_000, 948_228)  # fmt: skip


async def test_stale_or_failing_fx_is_not_used(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    fx_override(client, ecb(date.today() - timedelta(days=30)))
    stale = (await client.post(f"{API}/fx/refresh", headers=auth)).json()
    assert stale["available"] is False  # stored, but too old to convert with

    fx_override(client, lambda _r: httpx.Response(503))
    r = await client.post(f"{API}/fx/refresh", headers=auth)
    assert r.status_code == 422 and "unavailable" in r.json()["detail"]


async def test_market_endpoints_are_private(
    client: httpx.AsyncClient, auth: dict[str, str], shop: Shop
) -> None:
    from tests.conftest import signup  # noqa: PLC0415

    item = await _item(client, auth)
    other = await signup(client, email="ravi@example.com")
    for method, path in (
        ("post", f"/items/{item['id']}/price-check"),
        ("get", f"/items/{item['id']}/prices"),
    ):
        assert (await getattr(client, method)(f"{API}{path}", headers=other)).status_code == 404
    assert (await client.get(f"{API}/alerts", headers=other)).json() == []
