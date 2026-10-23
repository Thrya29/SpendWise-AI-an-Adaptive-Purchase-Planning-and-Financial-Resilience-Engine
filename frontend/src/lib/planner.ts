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
export function explain(d: Decision, currency: string): string {
  const pay = d.pay_on ? formatDate(d.pay_on) : "";
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
        ? ` Or wait until ${formatDate(d.alternative_pay_on)} to keep the reserve intact.`
        : " There is no later date within this horizon that keeps the reserve intact.";
      return `Paying on ${pay} meets the deadline but dips into your reserve.${alt}`;
    }
    case "postpone": {
      const gap = formatMoney(d.shortfall_minor ?? 0, currency);
      const when = d.shortfall_on ? ` by ${formatDate(d.shortfall_on)}` : "";
      const scenario = d.shortfall_scenario ? ` (${d.shortfall_scenario})` : "";
      return d.reason === "outranked"
        ? `Higher-priority items use the available money first. Needs ${gap} more headroom${when}${scenario}.`
        : `Needs ${gap} more than you can safely spend${when}${scenario}.`;
    }
    case "wait_price":
      return d.max_price_minor != null
        ? `Price ${formatMoney(d.unit_price_minor, currency)} is above your limit of ${formatMoney(d.max_price_minor, currency)}.`
        : "Waiting for a lower price.";
  }
}

export function hasChanges(d: Decision): boolean {
  return Boolean(d.changes.target_date || d.changes.status);
}

/** Human-readable preview of what applying will change, e.g. ["Target date: 15 Dec 2026 → 2 Jan 2027"]. */
export function describeChanges(d: Decision, useAlternative = false): string[] {
  const changes = useAlternative && d.alternative_changes ? d.alternative_changes : d.changes;
  const out: string[] = [];
  if (changes.target_date) {
    const from = changes.target_date.from ? formatDate(changes.target_date.from) : "none";
    out.push(`Target date: ${from} → ${formatDate(changes.target_date.to)}`);
  }
  if (changes.status) out.push(`Status: ${changes.status.from} → ${changes.status.to}`);
  return out;
}

export const PROTECT_OPTIONS = [
  { id: "delay1", label: "Salary 1 month late", shock: { months: 1, mode: "delayed" as const } },
  { id: "delay2", label: "Salary 2 months late", shock: { months: 2, mode: "delayed" as const } },
  { id: "lost1", label: "No salary for 1 month", shock: { months: 1, mode: "lost" as const } },
];
