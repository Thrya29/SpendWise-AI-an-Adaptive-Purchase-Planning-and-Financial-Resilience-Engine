import type { Schemas } from "@/lib/api/client";
import { formatDate } from "@/lib/labels";
import { formatMoney } from "@/lib/money";

export type Plan = Schemas["PlanOut"];
export type Decision = Schemas["DecisionOut"];
export type Action = Decision["action"];

export const ACTION_GROUPS: { action: Action; title: string; hint: string }[] = [
  { action: "use_reserve", title: "Needs your approval", hint: "Only possible on time by using part of your emergency reserve" },
  { action: "buy_now", title: "Buy now", hint: "Safe today in every protected scenario" },
  { action: "schedule", title: "Scheduled", hint: "Buy on the date shown to stay safe" },
  { action: "postpone", title: "Postponed", hint: "Not safe within this horizon — re-planned automatically" },
  { action: "wait_price", title: "Waiting for a better price", hint: "Current price is above your limit" },
]; // prettier-ignore

/** One plain-language sentence explaining a decision. All numbers come from the engine. */
export function explain(d: Decision, currency: string, locale?: string): string {
  const date = (iso: string) => formatDate(iso, locale);
  const money = (minor: number) => formatMoney(minor, currency, { locale });
  const pay = d.pay_on ? date(d.pay_on) : "";
  switch (d.action) {
    case "buy_now":
      return "Safe to buy today.";
    case "schedule":
      if (d.late) return `Earliest safe date is ${pay}, after your target date.`;
      return d.current_target_date
        ? `Pay on ${pay} to have it by your target date.`
        : `Safe from ${pay}.`;
    case "use_reserve": {
      const alt = d.alternative_pay_on
        ? ` Or wait until ${date(d.alternative_pay_on)} to keep the reserve intact.`
        : " There is no later date within this horizon that keeps the reserve intact.";
      return `Paying on ${pay} meets the deadline but dips into your reserve.${alt}`;
    }
    case "postpone": {
      const gap = money(d.shortfall_minor ?? 0);
      const when = d.shortfall_on ? ` by ${date(d.shortfall_on)}` : "";
      const scenario = d.shortfall_scenario ? ` (${d.shortfall_scenario})` : "";
      return d.reason === "outranked"
        ? `Higher-priority items use the available money first. Needs ${gap} more headroom${when}${scenario}.`
        : `Needs ${gap} more than you can safely spend${when}${scenario}.`;
    }
    case "wait_price":
      return d.max_price_minor != null
        ? `Price ${money(d.unit_price_minor)} is above your limit of ${money(d.max_price_minor)}.`
        : "Waiting for a lower price.";
  }
}

export function hasChanges(d: Decision): boolean {
  return Boolean(d.changes.target_date || d.changes.status);
}

/** Human-readable preview of what applying will change, e.g. ["Target date: 15 Dec 2026 → 2 Jan 2027"]. */
export function describeChanges(d: Decision, useAlternative = false, locale?: string): string[] {
  const changes = useAlternative && d.alternative_changes ? d.alternative_changes : d.changes;
  const out: string[] = [];
  if (changes.target_date) {
    const from = changes.target_date.from ? formatDate(changes.target_date.from, locale) : "none";
    out.push(`Target date: ${from} → ${formatDate(changes.target_date.to, locale)}`);
  }
  if (changes.status) out.push(`Status: ${changes.status.from} → ${changes.status.to}`);
  return out;
}

export const PROTECT_OPTIONS = [
  { id: "delay1", label: "Salary 1 month late", shock: { months: 1, mode: "delayed" as const } },
  { id: "delay2", label: "Salary 2 months late", shock: { months: 2, mode: "delayed" as const } },
  { id: "lost1", label: "No salary for 1 month", shock: { months: 1, mode: "lost" as const } },
];
