import { describe, expect, it } from "vitest";

import { countryOptions, formatDate, labelOf, TIERS, timezoneOptions, todayIso } from "./labels";

describe("labels", () => {
  it("resolves labels and falls back to the raw value", () => {
    expect(labelOf(TIERS, "need")).toBe("Needs");
    expect(labelOf(TIERS, "unknown" as never)).toBe("unknown");
  });

  it("formats ISO dates without timezone drift", () => {
    expect(formatDate("2026-01-31", "en-GB")).toBe("31 Jan 2026");
    expect(formatDate(null)).toBe("—");
  });

  it("lists countries with localised names and timezones", () => {
    const countries = countryOptions("en");
    expect(countries.find((c) => c.value === "IN")?.label).toBe("India");
    expect(countries.map((c) => c.label)).toEqual(
      [...countries.map((c) => c.label)].sort((a, b) => a.localeCompare(b)),
    );
    // ICU may list India as Asia/Calcutta; a saved Asia/Kolkata must still be selectable.
    const zones = timezoneOptions("Asia/Kolkata");
    expect(zones).toContain("Asia/Kolkata");
    expect(zones).toContain("UTC");
    expect(new Set(zones).size).toBe(zones.length);
    expect(todayIso()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
