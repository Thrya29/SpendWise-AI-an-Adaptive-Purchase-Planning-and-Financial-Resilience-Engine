"""Load test a running SpendWise deployment through its public entry point.

Creates a few test users, gives each a salary, bills and a wish list, then has N virtual
users repeat what people do: open the dashboard (projection), list items, check alerts and,
now and then, run the planner. Prints latency percentiles per endpoint.

Usage:  python scripts/loadtest.py [--base http://localhost:3000] [--users 4]
                                   [--concurrency 8] [--seconds 60]
Only point it at a deployment you own: it creates accounts.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import secrets
import statistics
import time
import uuid
from collections import defaultdict
from datetime import date, timedelta

import httpx

PASSWORD = secrets.token_urlsafe(18)  # fresh per run; the accounts are throwaway
RNG = random.Random(7)  # noqa: S311 - reproducible test data, not security


async def make_user(client: httpx.AsyncClient, n: int) -> dict[str, str]:
    email = f"load-{uuid.uuid4().hex[:10]}-{n}@example.com"
    r = await client.post("/auth/register", json={
        "email": email, "password": PASSWORD, "display_name": f"Load {n}", "country": "IN",
        "base_currency": "INR", "timezone": "Asia/Kolkata",
    })  # fmt: skip
    r.raise_for_status()
    r = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    r.raise_for_status()
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    first = date.today().replace(day=1)
    seed = [
        ("accounts", {"name": "Bank", "currency": "INR", "opening_balance_minor": 20_000_000}),
        ("incomes", {"name": "Salary", "amount_minor": 9_000_000, "currency": "INR",
                     "anchor_date": first.isoformat()}),
        ("obligations", {"name": "Rent", "amount_minor": 3_000_000, "currency": "INR",
                         "anchor_date": (first + timedelta(days=4)).isoformat()}),
        ("obligations", {"name": "Groceries", "amount_minor": 300_000, "currency": "INR",
                         "frequency": "weekly", "anchor_date": first.isoformat()}),
    ]  # fmt: skip
    for i in range(12):
        target = date.today() + timedelta(days=15 * (i + 1))
        seed.append(("items", {
            "name": f"Item {i}", "tier": RNG.choice(["need", "want", "desire"]),
            "estimated_price_minor": RNG.randint(5_000, 120_000) * 100, "currency": "INR",
            "target_date": target.isoformat(), "priority": RNG.randint(1, 5),
        }))  # fmt: skip
    for path, body in seed:
        (await client.post(f"/{path}", json=body, headers=auth)).raise_for_status()
    return auth


async def virtual_user(
    client: httpx.AsyncClient, auth: dict[str, str], until: float,
    timings: dict[str, list[float]], statuses: dict[str, dict[int, int]],
) -> None:  # fmt: skip
    i = 0
    while time.perf_counter() < until:
        i += 1
        steps: list[tuple[str, str, str, dict | None]] = [
            ("projection", "POST", "/projection", {"horizon_months": 6}),
            ("items", "GET", "/items?limit=50", None),
            ("alerts", "GET", "/alerts/unread-count", None),
        ]
        if i % 5 == 0:
            steps.append(("planner", "POST", "/planner/plans", {"horizon_months": 6}))
        for name, method, path, body in steps:
            started = time.perf_counter()
            r = await client.request(method, path, json=body, headers=auth)
            timings[name].append((time.perf_counter() - started) * 1000)
            statuses[name][r.status_code] += 1


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


async def main_async(args: argparse.Namespace) -> int:
    limits = httpx.Limits(max_connections=args.concurrency * 2)
    async with httpx.AsyncClient(
        base_url=args.base.rstrip("/") + "/api/v1", timeout=60, limits=limits
    ) as client:
        users = [await make_user(client, n) for n in range(args.users)]
        timings: dict[str, list[float]] = defaultdict(list)
        statuses: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        started = time.perf_counter()
        until = started + args.seconds
        await asyncio.gather(*(
            virtual_user(client, users[v % len(users)], until, timings, statuses)
            for v in range(args.concurrency)
        ))  # fmt: skip
        elapsed = time.perf_counter() - started

    total = sum(len(v) for v in timings.values())
    print(f"{total} requests in {elapsed:.0f} s = {total / elapsed:.1f} req/s "
          f"({args.concurrency} virtual users over {args.users} accounts)\n")  # fmt: skip
    print(f"{'endpoint':<12}{'requests':>9}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}  statuses")
    failed = 0
    for name, values in timings.items():
        codes = dict(sorted(statuses[name].items()))
        failed += sum(n for code, n in codes.items() if code >= 500)
        print(f"{name:<12}{len(values):>9}{statistics.median(values):>9.0f}"
              f"{pct(values, 0.95):>9.0f}{pct(values, 0.99):>9.0f}  {codes}")  # fmt: skip
    print("\n429 = rate limited (expected for the planner under load); 5xx = failure.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://localhost:3000")
    parser.add_argument("--users", type=int, default=4)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--seconds", type=int, default=60)
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
