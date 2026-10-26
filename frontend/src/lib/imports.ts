import type { Schemas } from "@/lib/api/client";

export type Preview = Schemas["StatementPreviewOut"];
export type Recurring = Schemas["RecurringOut"];
export type ApplyBody = Schemas["StatementApplyIn"];

export const MAX_STATEMENT_BYTES = 3_000_000;

/** The user's edits to one suggested pattern. */
export interface Pick {
  include: boolean;
  name: string;
  essential: boolean;
}

/** Suggestions start ticked unless they already exist or the amount is irregular. */
export function defaultPicks(recurring: Recurring[]): Record<string, Pick> {
  return Object.fromEntries(
    recurring.map((r) => [
      key(r),
      {
        include: !r.already_set_up && r.confidence === "high",
        name: r.name,
        essential: r.essential,
      },
    ]),
  );
}

export function key(r: Recurring): string {
  return `${r.direction}:${r.key}`;
}

/** Days between the statement's last date and today; old statements give stale balances. */
export function ageInDays(end: string, today: Date = new Date()): number {
  const [y, m, d] = end.split("-").map(Number);
  const endUtc = Date.UTC(y, m - 1, d);
  const todayUtc = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((todayUtc - endUtc) / 86_400_000);
}

export function buildApplyBody(
  preview: Preview,
  picks: Record<string, Pick>,
  account: { id: string } | { newName: string } | null,
  setBalance: boolean,
): ApplyBody {
  const chosen = preview.recurring.filter((r) => picks[key(r)]?.include);
  const base = (r: Recurring) => ({
    name: picks[key(r)].name.trim() || r.name,
    amount_minor: r.amount_minor,
    currency: preview.currency,
    frequency: r.frequency,
    anchor_date: r.last_on,
  });
  return {
    currency: preview.currency,
    account_id: account && "id" in account ? account.id : null,
    new_account:
      account && "newName" in account ? { name: account.newName.trim(), kind: "bank" } : null,
    closing_balance_minor:
      setBalance && account && preview.closing_balance_minor != null
        ? preview.closing_balance_minor
        : null,
    incomes: chosen
      .filter((r) => r.direction === "income")
      .map((r) => ({ ...base(r), subject_to_shocks: true })),
    obligations: chosen
      .filter((r) => r.direction === "expense")
      .map((r) => ({ ...base(r), category: r.category, essential: picks[key(r)].essential })),
  };
}
