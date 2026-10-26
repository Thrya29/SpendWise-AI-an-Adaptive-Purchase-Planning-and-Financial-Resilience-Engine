# ADR 0010: Bank statement import without storing statements

**Status:** Accepted · 2026-10-26

## Context
Typing in every account, salary and bill is where most budgeting tools lose people. Indian banks
let customers download statements as CSV or Excel from net banking. Live linking through the
RBI's Account Aggregator framework would be smoother, but it needs a licensed partner,
a business agreement and consent flows, which are out of scope for now.

## Decision
* **CSV/TXT only.** Excel files can be saved as CSV. PDF statements are not parsed: layouts vary
  by bank and month, and a wrong amount here would be wrong everywhere.
* **Layout detection, not per-bank code.** Columns are matched by name patterns, and the date
  format is chosen by what parses. The running balance is the check: if rows don't add up, the
  preview says so before anything is saved.
* **Suggestions, not automation.** Recurring payments are proposed with their typical amount,
  rhythm and an example narration. Only high-confidence ones start ticked. The user renames them,
  chooses which bills are essential (these size the reserve), and confirms.
* **Nothing from the statement is stored.** Not the file, not the transactions, not the narrations.
  Only the confirmed income streams, bills and (optionally) the account balance are saved.

## Consequences
* Setup goes from typing a dozen records to reviewing a list.
* Individual past transactions are not imported, so spending history is not available for
  analysis. Importing them would need deduplication across overlapping statements and is a
  separate decision.
* Parser tests use synthetic statements in four layouts modelled on common exports; each new
  layout reported by users should become a fixture.
