# ADR 0002: Money as integer minor units

**Status:** Accepted · 2026-10-23

## Context
Binary floating point cannot represent most decimal fractions (`0.1 + 0.2 != 0.3`). Rounding
errors in a financial planner erode trust and can flip an "affordable" verdict.

## Decision
* Store and transmit every amount as an integer in the currency's ISO 4217 minor unit (`BIGINT` in
  PostgreSQL, `*_minor: int` in the API), with an explicit `currency` code.
* The domain `Money` type refuses floats and cross-currency arithmetic.
* Conversion to and from major units uses `Decimal` with banker's rounding on the server and
  string → `BigInt` parsing in the browser.
* Exponents follow ISO 4217 (JPY 0, INR 2, KWD 3), mirrored in `money.py` and `money.ts`.

## Consequences
* Exact, reproducible results, verified by property-based tests.
* Every display layer must format amounts, which the shared helpers already do.
* Multi-currency planning needs explicit FX conversion with a recorded rate and timestamp
  (Phase 3). It is never implicit.
