# ADR 0003: Deterministic core, optional LLM

**Status:** Accepted · 2026-10-23

## Context
Users need to trust affordability verdicts. LLMs are good at language (turning "salon visit next
month around ₹1,500" into a structured item) and at explanation, but they are not reliable
calculators, and not every user has, or wants, an API key.

## Decision
* All balances, projections, schedules and reserve checks are plain, tested Python.
* LLM access goes through a provider interface with two implementations: a deterministic **mock**
  (rules and templates, the default, needs no network) and **Anthropic Claude** using the user's
  own key. *Status:* the per-user choice and encrypted key storage are implemented; the providers
  ship with the first AI features (natural-language item intake, plan explanations) in Phase 2.
* User API keys are encrypted at rest (Fernet, server-held key), shown only as the last four
  characters, and can be deleted at any time.
* LLM output is validated against typed schemas, never executes actions directly, and plan changes
  always require user approval. Fetched web content is treated as data, never as instructions.

## Consequences
* Every feature has a non-AI path, which also makes CI hermetic.
* Explanations from the mock provider are plainer than Claude's, which is an accepted trade-off.
