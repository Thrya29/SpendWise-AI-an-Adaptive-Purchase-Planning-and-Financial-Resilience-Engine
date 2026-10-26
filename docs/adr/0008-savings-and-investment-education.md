# ADR 0008: Savings and investment education, not advice

**Status:** Accepted · 2026-10-23

## Context
After planning purchases, users ask what to do with money they don't need yet: an FD, a
savings account, mutual funds, gold. In India, giving personal advice on securities for
consideration requires SEBI registration as an investment adviser, including when AI is
involved. A useful tool must stay clearly on the side of education and calculation.

## Decision
**Scope.** SpendWise explains and simulates using the user's own numbers. It never ranks funds,
never says "buy" or "sell", and every result carries an "educational estimate, not investment
advice" note pointing to SEBI-registered advisers.

| Feature | How it stays honest |
|---|---|
| **Safe to set aside** | The lowest (balance − reserve) over the chosen horizon, across protected scenarios, with every scheduled purchase included. Locking money lowers every day's balance by the same amount until maturity, so this is exact. |
| **FD vs. savings** | The user enters their bank's actual rates. Quarterly compounding for tenures of 6 months or more, simple interest below that. Breaking early uses the rate for the period held minus a penalty, never below zero. Tax and TDS are mentioned, not computed. |
| **Simulator** | Seeded Monte Carlo of lognormal monthly returns: 10th, 50th and 90th percentile outcomes, the chance of ending below the amount invested, and the typical worst fall. Inputs are the user's own assumptions, illustrative defaults labelled as such, or a watched fund's own history, with the window and source named. |
| **Mutual funds** | AMFI's official daily NAV file (about 14k schemes), stored daily. History for watched funds comes from mfapi.in, labelled as a community mirror of AMFI data. Funds that are inactive or have no valid NAV (wound-down plans, segregated portfolios published at 0.0000) are hidden from search by default. Search ranks exact phrase matches first. |
| **Gold** | The international spot price (gold-api.com) converted at the ECB reference rate. It is explicitly labelled as excluding Indian import duty, GST and dealer margin, and users are pointed to their jeweller's quote. The jewellery bill splits gold value, making charges, hallmarking and GST (default 3% on gold plus making). |

**Freshness.** A worker refreshes AMFI daily, gold every 6 hours and watched funds' history
daily. Every figure shows its source and date.

## Consequences
* No feature recommends a security. Comparison is limited to facts about funds the user chose.
* The gold reference will read lower than Indian retail rates; the label says so on every view.
* Bank FD rates are not fetched: they vary by bank, tenure and customer, and stale published
  rates would mislead.
