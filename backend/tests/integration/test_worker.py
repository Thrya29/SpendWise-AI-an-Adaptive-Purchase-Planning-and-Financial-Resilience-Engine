from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import httpx

from app import worker
from app.market.fetcher import SafeFetcher
from tests.integration.test_market_api import Shop, _public_dns, ecb

API = "/api/v1"


def shop_fetcher(shop: Shop) -> SafeFetcher:
    return SafeFetcher(httpx.AsyncClient(transport=httpx.MockTransport(shop.handler)), _public_dns)


async def _tracked(client: httpx.AsyncClient, auth: dict[str, str], url: str, **kw: Any) -> str:
    body = {"name": url.rsplit("/", 1)[-1], "tier": "want", "estimated_price_minor": 9_000_000,
            "currency": "INR", "url": url, "track_price": True, **kw}  # fmt: skip
    r = await client.post(f"{API}/items", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_worker_checks_due_items_politely(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    a = await _tracked(client, auth, "https://shop.example/a")
    b = await _tracked(client, auth, "https://shop.example/b")
    c = await _tracked(client, auth, "https://other.example/c")
    await _tracked(client, auth, "https://shop.example/off", track_price=False)
    done = await _tracked(client, auth, "https://shop.example/done")
    r = await client.patch(f"{API}/items/{done}", json={"version": 1, "status": "purchased"},
                           headers=auth)  # fmt: skip
    assert r.status_code == 200

    due = {str(item) for item, _ in await worker.due_items()}
    assert due == {a, b, c}

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    found = await worker.check_due_prices(shop_fetcher(Shop()), sleep=fake_sleep)
    assert found == 3  # untracked and purchased items are skipped
    assert len(sleeps) >= 1 and all(0 < s <= worker.SAME_SITE_SPACING_S for s in sleeps)

    item = (await client.get(f"{API}/items/{a}", headers=auth)).json()
    assert item["estimated_price_minor"] == 7_499_900 and item["price_source"] == "link"
    assert await worker.due_items() == []  # nothing due again until the next interval


async def test_worker_survives_failures_and_conflicts(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _tracked(client, auth, "https://shop.example/a")
    broken = Shop()
    broken.status = 500

    async def no_sleep(_s: float) -> None:
        return None

    assert await worker.check_due_prices(shop_fetcher(broken), sleep=no_sleep) == 0
    assert await worker.check_one(uuid4(), uuid4(), shop_fetcher(broken)) is False


async def test_fx_refresh_cadence(client: httpx.AsyncClient) -> None:
    def fx_client(handler: Any) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    assert await worker.refresh_fx_if_due(fx_client(ecb(date.today()))) is True
    assert await worker.refresh_fx_if_due(fx_client(ecb(date.today()))) is False  # fresh enough
    assert await worker.refresh_fx_if_due(fx_client(lambda _r: httpx.Response(503))) is False

    def fx_only(request: httpx.Request) -> httpx.Response:
        # Rates are served; every other reference source is down. A cycle must still finish.
        if request.url.host == "api.frankfurter.dev":
            return ecb(date.today() - timedelta(days=1))(request)
        return httpx.Response(404)

    await worker.run_once(fx_client(fx_only), shop_fetcher(Shop()))
