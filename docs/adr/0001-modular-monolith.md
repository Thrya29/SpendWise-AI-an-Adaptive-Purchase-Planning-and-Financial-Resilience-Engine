# ADR 0001: Modular monolith

**Status:** Accepted · 2026-10-23

## Context
SpendWise has several concerns (ledger, planning, market data, insights, AI orchestration) but one
small team and one deployment target (Docker Compose). Microservices would add network failure
modes, distributed transactions and operational overhead without a scaling need to justify them.

## Decision
One FastAPI service with strict internal module boundaries:
`domain/` (pure logic, no I/O) ← `services/` (persistence, orchestration) ← `api/` (HTTP).
Background work (price polling, forecasting) will run as a separate *worker process* built from
the same codebase, not as a separate service.

## Consequences
* One deployable, one database, ACID transactions across modules.
* `domain/` has no framework imports, so it is unit- and property-testable in milliseconds.
* If a module later needs independent scaling (e.g. scraping workers), its boundary already exists.
