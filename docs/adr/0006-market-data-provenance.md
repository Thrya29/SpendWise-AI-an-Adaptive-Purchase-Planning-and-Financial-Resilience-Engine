# ADR 0006: Market data with provenance, not scraping

**Status:** Accepted · 2026-10-23

## Context
Users want current prices for the things they plan to buy, and amounts in several currencies.
Prices that are wrong, stale or invented would corrupt every plan built on them. Fetching
arbitrary user-supplied URLs from a server is also a classic attack vector (SSRF).

## Decision
**Prices only from data that sellers publish on purpose.** The extractor reads schema.org
JSON-LD (`Product` → `Offer`/`AggregateOffer`, including `@graph` and `priceSpecification`),
microdata (`itemprop="price"`) and OpenGraph/product meta tags. Visible page text is never
scraped. If a page publishes no structured price, the user is told so and can enter a price or
record a shop quote. Confidence: JSON-LD `high`, microdata/meta `medium`, and the low end of a
price range `low`.

**Every observation keeps its provenance:** amount and currency, method, confidence,
availability, source (domain or shop), URL, page title and observation time. Observations are
append-only. The item's planning price changes only when the user clicks *Use this price* or has
turned on *Track this price*. The UI always shows where a price came from and how old it is,
and flags it as possibly outdated after 24 hours.

**Fetching is defensive** (`app/market/fetcher.py`):
* http/https only, default ports only, no credentials in URLs;
* every resolved address must be public: loopback, private, link-local (including
  169.254.169.254), multicast, reserved and unspecified addresses are refused, as are IPv4-mapped
  IPv6 forms of them;
* redirects are followed manually (at most 3), with each hop re-validated;
* 2 MB and 15 s caps, HTML only, an identifying User-Agent, and robots.txt honoured;
* per-user rate limits on the API, and per-site spacing in the worker.

*Residual risk:* DNS rebinding between validation and connection. Mitigation: the API container's
only internal neighbours are the database and Redis, both blocked by address and name.

**Exchange rates:** ECB euro reference rates via Frankfurter (free, no key). They are stored
exactly, as decimal strings, one row per currency per day. Conversion is integer minor units ×
a Decimal cross rate with banker's rounding. Rates older than 10 days are not used. Every
converted amount in a projection or plan comes with a note giving the rate and its date.
Currencies the ECB does not publish (e.g. AED, SAR) are excluded with a warning, never estimated.

**Alerts:** the price is at or below your maximum (on crossing only), a drop of at least 5%,
the item is back in stock, or 3 consecutive failed checks on a tracked item.

## Consequences
* Major marketplaces that block bots or render prices with JavaScript return "no price found".
  This is intentional, and the honest outcome. Licensed retailer APIs (for example affiliate
  programmes) can be added later as additional sources with the same provenance model.
* A separate worker process (same image) refreshes rates every 6 hours and tracked prices every
  12 hours. Each job is its own transaction; conflicts with concurrent user edits are skipped
  and retried next cycle.
