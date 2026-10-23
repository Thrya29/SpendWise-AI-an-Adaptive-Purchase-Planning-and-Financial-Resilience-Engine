import { describe, expect, it } from "vitest";

import { describeChanges, explain, hasChanges, type Decision } from "./planner";

function decision(overrides: Partial<Decision>): Decision {
  return {
    item_id: "i1",
    item_version: 1,
    name: "Laptop",
    tier: "need",
    kind: "product",
    priority: 5,
    quantity: 1,
    unit_price_minor: 3_000_000,
    cost_minor: 3_000_000,
    current_target_date: "2026-11-20",
    deadline_type: "soft",
    action: "schedule",
    reason: "on_target",
    period_label: "2026-11",
    pay_on: "2026-11-20",
    late: false,
    shortfall_minor: null,
    shortfall_scenario: null,
    shortfall_on: null,
    alternative_pay_on: null,
    max_price_minor: null,
    requires_reserve_approval: false,
    changes: { target_date: null, status: null },
    alternative_changes: null,
    ...overrides,
  };
}

describe("explain", () => {
  it("covers every action with engine numbers only", () => {
    expect(explain(decision({ action: "buy_now" }), "INR")).toBe("Safe to buy today.");
    expect(explain(decision({}), "INR")).toBe("Pay on 20 Nov 2026 to have it by your target date.");
    expect(explain(decision({ late: true, pay_on: "2027-01-02" }), "INR")).toMatch(
      /Earliest safe date is 2 Jan 2027, after your target date/,
    );
    expect(explain(decision({ current_target_date: null }), "INR")).toBe("Safe from 20 Nov 2026.");
    expect(
      explain(decision({ action: "use_reserve", alternative_pay_on: "2026-11-02" }), "INR"),
    ).toMatch(/dips into your reserve\. Or wait until 2 Nov 2026/);
    expect(explain(decision({ action: "use_reserve" }), "INR")).toMatch(/no later date/);
    const postponed = decision({
      action: "postpone",
      reason: "not_affordable",
      shortfall_minor: 48_000_000,
      shortfall_on: "2026-11-01",
      shortfall_scenario: "As expected",
    });
    expect(explain(postponed, "INR")).toMatch(
      /Needs ₹4,80,000\.00 more .* by 1 Nov 2026 \(As expected\)/,
    );
    expect(explain({ ...postponed, reason: "outranked" }, "INR")).toMatch(/Higher-priority items/);
    expect(explain(decision({ action: "wait_price", max_price_minor: 2_000_000 }), "INR")).toMatch(
      /above your limit of ₹20,000\.00/,
    );
    expect(explain(decision({ action: "wait_price" }), "INR")).toBe("Waiting for a lower price.");
  });
});

describe("changes", () => {
  it("previews primary and alternative changes", () => {
    const d = decision({
      changes: {
        target_date: { from: null, to: "2026-11-20" },
        status: { from: "postponed", to: "planned" },
      },
      alternative_changes: { target_date: { from: null, to: "2026-12-02" }, status: null },
    });
    expect(hasChanges(d)).toBe(true);
    expect(describeChanges(d)).toEqual([
      "Target date: none → 20 Nov 2026",
      "Status: postponed → planned",
    ]);
    expect(describeChanges(d, true)).toEqual(["Target date: none → 2 Dec 2026"]);
    expect(hasChanges(decision({}))).toBe(false);
  });
});
