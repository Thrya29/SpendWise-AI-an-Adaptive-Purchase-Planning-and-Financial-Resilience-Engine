import { describe, expect, it } from "vitest";

import {
  ageInDays,
  buildApplyBody,
  defaultPicks,
  key,
  type Preview,
  type Recurring,
} from "./imports";

function rec(overrides: Partial<Recurring>): Recurring {
  return {
    key: "acme technologies salary",
    direction: "income",
    name: "Salary",
    amount_minor: 8_500_000,
    frequency: "monthly",
    last_on: "2026-09-01",
    next_on: "2026-10-01",
    occurrences: 4,
    amount_varies: false,
    confidence: "high",
    category: "income",
    essential: false,
    examples: [],
    already_set_up: false,
    ...overrides,
  };
}

const salary = rec({});
const rent = rec({ key: "rajesh kumar rent", direction: "expense", name: "Rent",
  amount_minor: 2_500_000, category: "housing", essential: true }); // prettier-ignore
const power = rec({ key: "billpay bescom", direction: "expense", name: "Electricity",
  amount_minor: 181_036, confidence: "medium", amount_varies: true, category: "utilities",
  essential: true }); // prettier-ignore
const netflix = rec({ key: "netflix com", direction: "expense", name: "Subscription",
  already_set_up: true }); // prettier-ignore

const preview = {
  currency: "INR",
  closing_balance_minor: 11_264_293,
  recurring: [salary, rent, power, netflix],
} as Preview;

describe("statement import", () => {
  it("ticks confident, new suggestions only", () => {
    const picks = defaultPicks(preview.recurring);
    expect(picks[key(salary)].include).toBe(true);
    expect(picks[key(rent)].include).toBe(true);
    expect(picks[key(power)].include).toBe(false); // irregular amount: the user decides
    expect(picks[key(netflix)].include).toBe(false); // already set up
  });

  it("builds the apply request from the user's choices", () => {
    const picks = defaultPicks(preview.recurring);
    picks[key(rent)] = { include: true, name: "  House rent ", essential: true };
    const body = buildApplyBody(preview, picks, { newName: "SBI savings" }, true);
    expect(body.new_account).toEqual({ name: "SBI savings", kind: "bank" });
    expect(body.account_id).toBeNull();
    expect(body.closing_balance_minor).toBe(11_264_293);
    expect(body.incomes).toEqual([
      { name: "Salary", amount_minor: 8_500_000, currency: "INR", frequency: "monthly",
        anchor_date: "2026-09-01", subject_to_shocks: true },
    ]); // prettier-ignore
    expect(body.obligations).toHaveLength(1);
    expect(body.obligations?.[0]).toMatchObject({ name: "House rent", category: "housing" });

    const noBalance = buildApplyBody(preview, picks, { id: "a1" }, false);
    expect(noBalance.account_id).toBe("a1");
    expect(noBalance.closing_balance_minor).toBeNull();
    expect(buildApplyBody(preview, picks, null, true).closing_balance_minor).toBeNull();
  });

  it("measures how old the statement is", () => {
    expect(ageInDays("2026-09-30", new Date(2026, 9, 26))).toBe(26);
    expect(ageInDays("2026-10-26", new Date(2026, 9, 26))).toBe(0);
  });
});
