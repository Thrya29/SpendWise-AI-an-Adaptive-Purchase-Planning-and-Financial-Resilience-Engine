import httpx
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.models.entities import ExtensionToken
from tests.conftest import signup

API = "/api/v1"
PAGE = "https://www.amazon.in/dp/B0EXAMPLE1"


async def _key(client: httpx.AsyncClient, auth: dict[str, str]) -> dict[str, str]:
    r = await client.post(f"{API}/me/extension-keys", json={"label": "Chrome"}, headers=auth)
    assert r.status_code == 201, r.text
    raw = r.json()["token"]
    assert raw.startswith("swx_") and r.json()["hint"] == raw[-4:]
    return {"Authorization": f"Bearer {raw}"}


async def test_capture_new_item_then_update_existing(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    ext = await _key(client, auth)
    body = {"url": PAGE, "page_title": "Noise-cancelling headphones", "price_minor": 2_499_900,
            "currency": "INR", "availability": "in_stock",
            "new_item": {"name": "Headphones", "tier": "want", "priority": 4}}  # fmt: skip
    r = await client.post(f"{API}/extension/capture", json=body, headers=ext)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["created_item"] is True and out["price_applied"] is True
    item = (await client.get(f"{API}/items/{out['item_id']}", headers=auth)).json()
    assert item["estimated_price_minor"] == 2_499_900 and item["url"] == PAGE
    assert item["price_source"] == "link"

    listed = (await client.get(f"{API}/extension/items", headers=ext)).json()
    assert [i["name"] for i in listed] == ["Headphones"]

    # A sale: 10% off. Saved to the same item, it becomes the planning price and alerts.
    sale = {**body, "price_minor": 2_249_900, "item_id": out["item_id"]}
    sale.pop("new_item")
    r = await client.post(f"{API}/extension/capture", json=sale, headers=ext)
    assert r.status_code == 201 and r.json()["price_applied"] is True
    assert any("Price drop" in a for a in r.json()["alerts"])
    history = (await client.get(f"{API}/items/{out['item_id']}/prices", headers=auth)).json()
    assert [h["method"] for h in history] == ["browser", "browser"]
    assert history[0]["source_name"] == "amazon.in"

    # Saved without changing the planning price.
    keep = {**sale, "price_minor": 2_399_900, "use_price": False}
    assert (await client.post(f"{API}/extension/capture", json=keep, headers=ext)).json()[
        "price_applied"
    ] is False
    item = (await client.get(f"{API}/items/{out['item_id']}", headers=auth)).json()
    assert item["estimated_price_minor"] == 2_249_900


async def test_requests_are_validated(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    ext = await _key(client, auth)
    base = {"url": PAGE, "price_minor": 100, "currency": "INR"}
    neither = await client.post(f"{API}/extension/capture", json=base, headers=ext)
    assert neither.status_code == 422
    bad_url = {**base, "url": "javascript:alert(1)", "new_item": {"name": "X"}}
    assert (
        await client.post(f"{API}/extension/capture", json=bad_url, headers=ext)
    ).status_code == 422
    item = (await client.post(f"{API}/extension/capture", headers=ext,
                              json={**base, "new_item": {"name": "Shoes"}})).json()  # fmt: skip
    usd = {**base, "currency": "USD", "item_id": item["item_id"]}
    r = await client.post(f"{API}/extension/capture", json=usd, headers=ext)
    assert r.status_code == 422 and "priced in INR" in r.text


async def test_keys_are_narrow_hashed_and_revocable(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    ext = await _key(client, auth)
    raw = ext["Authorization"].split()[1]
    async with get_sessionmaker()() as s:
        stored = (await s.scalars(select(ExtensionToken))).one()
        assert stored.token_hash != raw and raw not in stored.token_hash
    # The key works only on extension endpoints...
    assert (await client.get(f"{API}/accounts", headers=ext)).status_code == 401
    assert (await client.get(f"{API}/me/export", headers=ext)).status_code == 401
    # ...and a normal session token does not work on them.
    assert (await client.get(f"{API}/extension/items", headers=auth)).status_code == 401
    assert (await client.get(f"{API}/extension/items")).status_code == 401

    keys = (await client.get(f"{API}/me/extension-keys", headers=auth)).json()
    assert len(keys) == 1 and "token" not in keys[0]
    r = await client.delete(f"{API}/me/extension-keys/{keys[0]['id']}", headers=auth)
    assert r.status_code == 204
    assert (await client.get(f"{API}/extension/items", headers=ext)).status_code == 401


async def test_key_limits_and_other_users_items(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    for _ in range(5):
        await _key(client, auth)
    r = await client.post(f"{API}/me/extension-keys", json={}, headers=auth)
    assert r.status_code == 422 and "up to 5" in r.text

    mine_body = {"name": "Mine", "tier": "need", "estimated_price_minor": 100, "currency": "INR"}
    mine = await client.post(f"{API}/items", headers=auth, json=mine_body)
    other = await signup(client, email="ravi@example.com")
    theirs = await _key(client, other)
    steal = {"url": PAGE, "price_minor": 50, "currency": "INR", "item_id": mine.json()["id"]}
    r = await client.post(f"{API}/extension/capture", headers=theirs, json=steal)
    assert r.status_code == 422 and "not one of yours" in r.text
