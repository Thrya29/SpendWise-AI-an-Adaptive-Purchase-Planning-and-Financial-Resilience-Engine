# Architecture

## 1. Goals and non-goals

**Goals**

1. Tell a user, for any planned purchase, whether it is affordable **without breaching a protected
   emergency reserve**, both now and under adverse scenarios (salary delay or loss, emergencies).
2. Keep every money figure **exact and reproducible**: the same inputs always give the same answer.
3. Work fully **without any LLM**. AI is an optional layer for language, never for arithmetic.
4. Be operable by one engineer: one `docker compose up`, automatic migrations, health checks.

**Non-goals (for now)**

* Bank-account aggregation (requires regulated data-access agreements).
* Personalised securities recommendations (regulated investment advice).
* Guaranteed coverage of every retailer's live prices.

## 2. System context

```
                 ┌───────────────────────── private network: frontend ─────────────────────┐
 Browser ──HTTPS─► web (Next.js standalone)                                                │
   │             │  • static UI shells                                                     │
   │             │  • /api/v1/* route handler = same-origin proxy (header allowlist)       │
   │             └──────────────┬───────────────────────────────────────────────────────────┘
   │                            │ HTTP (internal)
   │             ┌──────────────▼──────────── private network: backend ───────────────────┐
   │             │ api (FastAPI, uvicorn)                                                  │
   │             │  api/      routers, dependencies, problem+json errors                   │
   │             │  services/ auth, owner-scoped repository, ledger assembly               │
   │             │  domain/   money, recurrence, cash-flow projection  (pure, no I/O)      │
   │             │  models/   SQLAlchemy entities          core/  config, db, security     │
   │             └──────┬───────────────────────────┬──────────────────────────────────────┘
   │                    │                           │
   │              PostgreSQL 16                 Redis 7 (rate-limit counters)
```

Only `web` is published to the host, on `127.0.0.1`. `api`, `db` and `redis` are reachable solely
on internal Docker networks. Containers run as non-root with read-only root filesystems and
`no-new-privileges`.

## 3. Key design decisions

| Decision | Why | ADR |
|---|---|---|
| Modular monolith, not microservices | One team, one deployable; module boundaries keep a later split cheap | [0001](adr/0001-modular-monolith.md) |
| Integer minor-unit money | Floats cannot represent 0.1; financial results must be exact | [0002](adr/0002-integer-money.md) |
| Deterministic engine, optional LLM | Users must trust the numbers; the app must work offline | [0003](adr/0003-deterministic-core-optional-llm.md) |
| Same-origin proxy + in-memory access token | Strict cookies and no token in localStorage | [0004](adr/0004-auth-and-session-model.md) |

## 4. Domain model

```
User 1─* Account 1─* Transaction
  │1─* IncomeStream        (amount, frequency, anchor, end, subject_to_shocks)
  │1─* Obligation          (amount, frequency, anchor, end, essential)
  │1─* PlannedItem         (tier: need|want|desire, kind, priority 1-5, price, qty,
  │                         target_date, deadline: hard|soft|none, lead_time, status)
  │1─* RefreshToken        (sha256 hash, family_id for reuse detection)
  └1─* AuditEvent          (entity, action, field-level diff)
```

* Every user-owned table carries `user_id` with `ON DELETE CASCADE`. Every query goes through
  `OwnedRepository`, which always filters by owner, so another user's row returns **404, not 403**
  and IDs cannot be probed.
* Mutable rows carry a `version` column (SQLAlchemy `version_id_col`). Updates must send the
  version they read, and stale writes return **409** with the current version.
* Every create, update and delete writes an `AuditEvent` with a field-level diff.

## 5. The cash-flow engine (`backend/app/domain/cashflow.py`)

Pure function: `project(opening_balance, start, end, incomes, obligations, planned, scenario,
reserve) -> Projection`.

1. **Expand recurrences** (`recurrence.py`). Monthly schedules clamp to month end (31 Jan →
   28/29 Feb) while keeping the anchor day for later months.
2. **Apply shocks** to income streams marked `subject_to_shocks`:
   * *Delayed N months*: payments due in `[shock_start, shock_start + N months)` arrive N months
     later. The engine looks back 24 months so arrears from before the horizon are included.
   * *Lost*: those payments never arrive.
3. **Order events** by date, applying **outflows before inflows on the same day** (conservative).
4. **Walk the ledger**, recording each balance, the low point, the first reserve breach and the
   first negative day, plus a check for every planned purchase (keeps reserve? stays solvent?).
5. **Reserve** = monthly-equivalent essentials × reserve months + buffer. The weekly → monthly
   conversion is ×52/12 with banker's rounding.

Planned items are paid on `max(today, target_date − lead_time_days)`, the latest date that still
gets the item there in time.

**Invariants verified by property-based tests** (`tests/property/`):

* Conservation: closing = opening + Σ events, and each event's running balance is exact.
* A salary shock never raises the balance at any month end, the low point or the closing balance.
* Adding spending never improves the low point and never delays the first reserve breach.

## 6. API conventions

* Base path `/api/v1`, OpenAPI at `/api/v1/openapi.json`.
* Money is always `*_minor: int` plus an ISO 4217 `currency` (the Stripe convention).
* Errors use RFC 9457 `application/problem+json` with a `request_id` for support. Validation
  errors include per-field `errors[]`.
* Lists are paginated (`limit` ≤ 200, `offset`) and return `{items, total, limit, offset}`.
* `PATCH` is partial, but `version` is required. Fields that cannot be null are rejected explicitly
  instead of being written as null.

## 7. Frontend

* **Next.js 16** with `cacheComponents`. Pages are prerendered static shells, and data loads on the
  client with the user's access token. The only dynamic route is the `/api/v1/[...path]` proxy.
* The proxy reads `API_INTERNAL_URL` at request time, so one image serves every environment. It
  forwards an allowlist of headers in each direction, rejects path traversal, caps bodies at 1 MB,
  times out after 30 s, and turns upstream failures into a problem+json 502.
* `src/lib/api/schema.d.ts` is generated from the backend's OpenAPI. CI regenerates it and fails
  on any diff.
* User-entered amounts are parsed as **strings into BigInt minor units**, so `0.29` is exactly
  29 cents.

## 8. Operations

* `/healthz` (liveness) and `/readyz` (checks the database) power the Docker health checks.
  Compose starts `api` only after `db` and `redis` are healthy, and `web` only after `api`.
* Structured JSON logs carry a `request_id` that is propagated end to end (`X-Request-ID`).
* The API refuses to start in production with default secrets, short JWT secrets or insecure
  cookies.

## 9. What comes next

The **Phase 2 planner** turns the projection into decisions. Each planned item gets a buy-in-period
variable `x[i,t]`, solved with OR-Tools CP-SAT to maximise priority-weighted value minus cost and
risk. It is subject to the projection's cash-flow constraints in every protected scenario, the
reserve, deadlines (with lead time), and replacement or alternative links. The output is a diff of
**buy now / wait / postpone** that the user approves before anything changes.
