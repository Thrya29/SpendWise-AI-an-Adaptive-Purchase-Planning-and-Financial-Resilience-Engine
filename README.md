# SpendWise AI

**An adaptive purchase-planning and financial-resilience engine.**

Most expense trackers tell you what you already spent. SpendWise plans what you *will* spend. You
list your **needs, wants and desires** (a work laptop, a salon visit, a trip) and SpendWise checks
each one against your real cash flow. It tells you whether you can buy it without breaking your
emergency reserve, and what happens if your **salary is delayed** or an **emergency** hits.

> SpendWise provides planning tools and educational information, not regulated financial advice.

---

## What works today

| Area | Capability |
|---|---|
| **Needs, wants & desires** | Add, edit, delete and filter planned spending: products, services, travel, experiences, subscriptions. Each item has a priority (1–5), target date, hard/soft/flexible deadline, lead time, price ceiling, link and location. Items can be marked purchased, postponed, or moved back to planned. |
| **Money** | Accounts with live balances, recurring income (weekly/monthly/quarterly/yearly/one-off), recurring expenses flagged as essential or discretionary, and one-off transactions. |
| **Emergency reserve** | A configurable reserve (N months of essentials + a buffer) that plans must never spend. |
| **What-if simulator** | Projects the balance day by day for 3–24 months. You can apply a **salary delay** (paid late as arrears) or **salary loss** for N months, plus an **unexpected expense**. You see when you'd dip into the reserve or run out, and which planned purchases stay safe. |
| **Purchase planner** | Chooses the best month and day to buy each item, or postpones it, so your balance never drops below your reserve, **even if salary is late or lost** (you choose which shocks to guard against). It is an exact constraint solver (OR-Tools CP-SAT), not a heuristic. Every decision has a reason: postponed items show the exact extra money needed and by when. Nothing changes until you approve, and using the reserve always needs explicit consent. |
| **"Describe it" entry** | Type *"work laptop for 75k by 15 Dec, must have"* and the assistant fills in the form for you to review. |
| **AI assistant mode** | Each user chooses the built-in assistant (offline, no API key) or **their own Claude API key**, which is stored encrypted and never shown again. AI only reads text and writes summaries. It never does the math: a summary containing any number the engine didn't produce is rejected. Any AI failure falls back to the built-in assistant. |
| **Account & privacy** | Sign-up with country, city, address and timezone; password change; full JSON data export; permanent account deletion. |

### Worked example (it's a regression test)

Savings ₹60,000 · essentials ₹20,000/month · salary ₹45,000 delayed two months · ₹10,000 emergency ·
2-month reserve (₹40,000). SpendWise reports that the reserve is breached on the first rent day, the
low point is ₹10,000, and both delayed salaries arrive together later. See
[`test_reference_scenario_salary_delayed_two_months_with_emergency`](backend/tests/unit/test_cashflow.py).

## Architecture at a glance

```
Browser ──► Next.js (UI + same-origin /api proxy) ──► FastAPI ──► PostgreSQL
                                                         └──────► Redis (rate limits)
```

* **Deterministic core.** Balances, projections and reserve checks are pure Python with integer
  minor-unit money. The LLM never does arithmetic.
* **Modular monolith.** Clean module boundaries (ledger, planning, auth) without the operational
  cost of microservices at this scale.
* **Typed contract.** The frontend's TypeScript types are generated from the API's OpenAPI schema,
  and CI fails if they drift.

Full design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Planner: [ADR 0005](docs/adr/0005-robust-purchase-scheduling.md) · Decisions: [docs/adr/](docs/adr/) ·
Security: [docs/SECURITY.md](docs/SECURITY.md)

## Run it

Requires Docker with Compose v2.

```bash
python scripts/generate_env.py      # creates .env with fresh random secrets (never committed)
docker compose up --build -d
# open http://localhost:3000
```

Only the web app is published, and only on `127.0.0.1`. The API, database and Redis stay on
private Docker networks. Migrations run automatically when the API starts.

Local development without Docker: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Quality gates

Every push runs in CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

| Backend | Frontend |
|---|---|
| ruff lint + format · mypy `--strict` | ESLint (0 warnings) · Prettier · `tsc` |
| pytest on **SQLite and PostgreSQL 16** | Vitest unit tests |
| Property-based tests (Hypothesis): money invariants, and *no plan ever breaks the reserve* | Production `next build` |
| Coverage gate ≥ 85% (currently ~97%) | Generated API types must match the schema |
| Migration ↔ model drift check + up/down round-trip | `npm audit` on production deps |
| `pip-audit` on the locked runtime deps | Docker images must build |

Warnings are treated as errors in the backend test suite.

## Tech stack

**Backend:** Python 3.12 · FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · OR-Tools CP-SAT ·
Anthropic SDK (optional, user's own key) · Argon2 · PyJWT ·
PostgreSQL 16 · Redis 7  
**Frontend:** Next.js 16 (App Router, standalone output) · React 19 · TypeScript (strict) ·
Tailwind CSS 4 · Recharts  
**Ops:** Docker Compose · GitHub Actions

## Roadmap

Built in phases. Each phase ships tested and documented before the next begins.

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation: repo, CI, Docker, auth, security baseline | ✅ Done |
| 1 | Ledger, needs/wants/desires CRUD, cash-flow projection, salary-delay & emergency scenarios | ✅ Done |
| 2 | Purchase **scheduling optimizer** (CP-SAT): buy now / schedule / postpone / wait for price / use reserve with consent; replanning; AI item entry and summaries (built-in or Claude) | ✅ Done |
| 3 | Market intelligence: link ingestion with source provenance, price history, FX, alerts | ⏳ Next |
| 4 | Price forecasting with calibrated uncertainty; alternative-product discovery | Planned |
| 5 | Savings & investment education: runway, FD vs. liquid, mutual-fund NAVs, gold (all sourced and timestamped) | Planned |
| 6 | Research benchmark: planner vs. baseline budgeting rules under simulated shocks | Planned |
| 7 | Production hardening: observability, load tests, deployment guide | Planned |

## Honest limits

* Planning currently covers amounts in your **main currency**. Other-currency accounts and items
  are listed as excluded, never silently converted. FX conversion arrives in Phase 3.
* Prices are your own estimates until market data (Phase 3) is added. Every price will always show
  its source and age, and nothing stale is ever labelled "live".

## License

Copyright © 2026 Thrya29. All rights reserved.
