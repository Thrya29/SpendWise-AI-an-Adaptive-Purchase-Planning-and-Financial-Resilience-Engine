import { describe, expect, it } from "vitest";

import type { Schemas } from "@/lib/api/client";

import { approxConvert, hostname, isStale, priceProvenance, timeAgo } from "./market";

const NOW = new Date("2026-10-23T12:00:00Z");
const ago = (ms: number) => new Date(NOW.getTime() - ms).toISOString();
const H = 3_600_000;

describe("timeAgo / isStale", () => {
  it("uses coarse, readable units", () => {
    expect(timeAgo(ago(10_000), NOW)).toBe("just now");
    expect(timeAgo(ago(5 * 60_000), NOW)).toBe("5 min ago");
    expect(timeAgo(ago(3 * H), NOW)).toBe("3 h ago");
    expect(timeAgo(ago(72 * H), NOW)).toBe("3 days ago");
    expect(timeAgo(ago(-H), NOW)).toBe("just now"); // clock skew never shows the future
  });

  it("flags prices older than a day", () => {
    expect(isStale(ago(23 * H), NOW)).toBe(false);
    expect(isStale(ago(25 * H), NOW)).toBe(true);
    expect(isStale(null, NOW)).toBe(false);
  });
});

describe("priceProvenance", () => {
  const item = (o: Partial<Schemas["PlannedItemRead"]>) => o as Schemas["PlannedItemRead"];

  it("describes every price source", () => {
    expect(priceProvenance(item({ price_source: "user" }), NOW)).toEqual({
      label: "Your estimate",
      stale: false,
    });
    expect(
      priceProvenance(item({ price_source: "link", price_observed_at: ago(2 * H) }), NOW),
    ).toEqual({
      label: "From the product page · 2 h ago",
      stale: false,
    });
    expect(
      priceProvenance(item({ price_source: "link", price_observed_at: ago(30 * H) }), NOW).stale,
    ).toBe(true);
    expect(
      priceProvenance(item({ price_source: "link", price_observed_at: null }), NOW).label,
    ).toBe("From the product page");
    expect(
      priceProvenance(item({ price_source: "quote", price_observed_at: ago(H) }), NOW).label,
    ).toBe("Quote · 1 h ago");
    expect(
      priceProvenance(item({ price_source: "quote", price_observed_at: null }), NOW).label,
    ).toBe("Quote");
    expect(priceProvenance(item({ price_source: "estimate" }), NOW).label).toBe("Estimate");
  });

  it("extracts hostnames safely", () => {
    expect(hostname("https://www.shop.example/p?q=1")).toBe("shop.example");
    expect(hostname("not a url")).toBe("not a url");
  });
});

describe("approxConvert", () => {
  it("converts between minor units with different exponents", () => {
    expect(approxConvert(10_000, 2, 2, "94.8228")).toBe(948_228); // $100 -> ₹9,482.28
    expect(approxConvert(10_000, 0, 2, "0.5390")).toBe(539_000); // ¥10,000 -> ₹5,390.00
    expect(approxConvert(0, 2, 2, "94.8")).toBe(0);
  });
});
