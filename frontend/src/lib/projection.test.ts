import { describe, expect, it } from "vitest";

import { hasScenario, mergeSeries, scenarioRequest, verdict, type Projection } from "./projection";

function proj(overrides: Partial<Projection>): Projection {
  return {
    currency: "INR",
    start: "2026-11-01",
    end: "2027-01-01",
    opening_balance_minor: 1000,
    closing_balance_minor: 1000,
    monthly_essentials_minor: 0,
    reserve_required_minor: 0,
    min_balance_minor: 1000,
    min_balance_on: "2026-11-01",
    first_reserve_breach_on: null,
    first_negative_on: null,
    runway_months: null,
    is_safe: true,
    months: [],
    events: [],
    planned_checks: [],
    warnings: [],
    ...overrides,
  };
}

const ev = (on: string, balance: number) => ({
  on,
  kind: "obligation" as const,
  label: "x",
  amount_minor: 0,
  balance_after_minor: balance,
  ref: null,
});

describe("mergeSeries", () => {
  it("builds a step series from opening balance through each event to the end", () => {
    const base = proj({
      events: [ev("2026-11-05", 800), ev("2026-12-05", 600)],
      closing_balance_minor: 600,
    });
    expect(mergeSeries(base)).toEqual([
      { date: "2026-11-01", baseline: 1000 },
      { date: "2026-11-05", baseline: 800 },
      { date: "2026-12-05", baseline: 600 },
      { date: "2027-01-01", baseline: 600 },
    ]);
  });

  it("uses the last event of a day and carries each series forward independently", () => {
    const base = proj({
      events: [ev("2026-11-05", 900), ev("2026-11-05", 700)],
      closing_balance_minor: 700,
    });
    const shock = proj({ events: [ev("2026-11-20", 400)], closing_balance_minor: 400 });
    expect(mergeSeries(base, shock)).toEqual([
      { date: "2026-11-01", baseline: 1000, scenario: 1000 },
      { date: "2026-11-05", baseline: 700, scenario: 1000 },
      { date: "2026-11-20", baseline: 700, scenario: 400 },
      { date: "2027-01-01", baseline: 700, scenario: 400 },
    ]);
  });
});

describe("scenario helpers", () => {
  it("classifies verdicts by severity", () => {
    expect(verdict(proj({}))).toBe("safe");
    expect(verdict(proj({ first_reserve_breach_on: "2026-11-05" }))).toBe("reserve");
    expect(
      verdict(proj({ first_reserve_breach_on: "2026-11-05", first_negative_on: "2026-12-01" })),
    ).toBe("negative");
  });

  it("builds requests only with the parts the user set", () => {
    const none = {
      horizonMonths: 6,
      delayMonths: 0,
      mode: "delayed" as const,
      emergencyMinor: null,
      emergencyOn: null,
    };
    expect(hasScenario(none)).toBe(false);
    expect(scenarioRequest(none)).toEqual({
      horizon_months: 6,
      include_planned: true,
      shock: null,
      emergencies: [],
    });

    const full = {
      ...none,
      delayMonths: 2,
      mode: "lost" as const,
      emergencyMinor: 500,
      emergencyOn: "2026-11-10",
    };
    expect(hasScenario(full)).toBe(true);
    expect(scenarioRequest(full)).toEqual({
      horizon_months: 6,
      include_planned: true,
      shock: { months: 2, mode: "lost" },
      emergencies: [{ name: "Emergency", amount_minor: 500, on: "2026-11-10" }],
    });
  });
});
