from pathlib import Path

import httpx

from tests.conftest import signup

API = "/api/v1"
SBI = (Path(__file__).resolve().parents[1] / "fixtures" / "statements" / "sbi_style.txt").read_text(
    encoding="utf-8"
)


async def _preview(client: httpx.AsyncClient, auth: dict[str, str]) -> dict:
    r = await client.post(f"{API}/imports/statement/preview", json={"text": SBI}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


async def test_preview_reads_the_statement_and_saves_nothing(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    p = await _preview(client, auth)
    assert (p["rows"], p["start"], p["end"], p["currency"]) == (
        80,
        "2026-06-01",
        "2026-09-30",
        "INR",
    )
    assert p["balance_checked"] == 79 and p["balance_mismatches"] == 0
    assert p["closing_balance_minor"] == 112_642_93 and p["warnings"] == []
    assert p["recent"][0]["on"] == "2026-09-30" and len(p["recent"]) == 8
    names = [r["name"] for r in p["recurring"]]
    assert names[0] == "Salary" and "Rent" in names
    assert not any(r["already_set_up"] for r in p["recurring"])
    for path in ("incomes", "obligations", "accounts"):
        assert (await client.get(f"{API}/{path}", headers=auth)).json()["items"] == []


async def test_apply_creates_confirmed_streams_and_sets_the_balance(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    p = await _preview(client, auth)
    rec = {r["name"]: r for r in p["recurring"]}
    salary, rent = rec["Salary"], rec["Rent"]
    body = {
        "new_account": {"name": "SBI savings"},
        "closing_balance_minor": p["closing_balance_minor"],
        "incomes": [{"name": "Salary", "amount_minor": salary["amount_minor"], "currency": "INR",
                     "frequency": "monthly", "anchor_date": salary["last_on"]}],
        "obligations": [{"name": "Rent", "amount_minor": rent["amount_minor"], "currency": "INR",
                         "frequency": "monthly", "anchor_date": rent["last_on"],
                         "category": "housing", "essential": True}],
    }  # fmt: skip
    r = await client.post(f"{API}/imports/statement/apply", json=body, headers=auth)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["balance_minor"] == 112_642_93 and len(out["incomes_created"]) == 1
    accounts = (await client.get(f"{API}/accounts", headers=auth)).json()["items"]
    assert accounts[0]["balance_minor"] == 112_642_93 and accounts[0]["id"] == out["account_id"]
    incomes = (await client.get(f"{API}/incomes", headers=auth)).json()["items"]
    assert incomes[0]["account_id"] == out["account_id"]

    # A second preview knows these are set up; applying them again is skipped, not duplicated.
    again = {r["name"]: r for r in (await _preview(client, auth))["recurring"]}
    assert again["Salary"]["already_set_up"] and again["Rent"]["already_set_up"]
    body.pop("new_account")
    body["account_id"] = out["account_id"]
    body["closing_balance_minor"] = 100_000_00  # balance moved since: the account follows
    r2 = (await client.post(f"{API}/imports/statement/apply", json=body, headers=auth)).json()
    assert r2["incomes_created"] == [] and len(r2["skipped"]) == 2
    accounts = (await client.get(f"{API}/accounts", headers=auth)).json()["items"]
    assert accounts[0]["balance_minor"] == 100_000_00
    assert len((await client.get(f"{API}/obligations", headers=auth)).json()["items"]) == 1


async def test_bad_input_is_explained(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await client.post(
        f"{API}/imports/statement/preview", json={"text": "hello,world\n"}, headers=auth
    )
    assert r.status_code == 422 and "transaction table" in r.text
    both = {"account_id": "00000000-0000-0000-0000-000000000001", "new_account": {"name": "X"}}
    r = await client.post(f"{API}/imports/statement/apply", json=both, headers=auth)
    assert r.status_code == 422 and "not both" in r.text


async def test_accounts_of_other_users_cannot_be_targeted(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    acc = await client.post(
        f"{API}/accounts", json={"name": "Mine", "currency": "INR"}, headers=auth
    )
    other = await signup(client, email="other@example.com")
    r = await client.post(
        f"{API}/imports/statement/apply",
        json={"account_id": acc.json()["id"], "closing_balance_minor": 1}, headers=other,
    )  # fmt: skip
    assert r.status_code == 422 and "your accounts" in r.text
    assert (
        await client.post(f"{API}/imports/statement/preview", json={"text": SBI})
    ).status_code == 401
