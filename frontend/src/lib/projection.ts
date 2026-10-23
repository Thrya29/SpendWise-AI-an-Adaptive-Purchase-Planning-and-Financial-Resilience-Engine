import type { Schemas } from "@/lib/api/client";

export type Projection = Schemas["ProjectionResponse"];

export interface BalancePoint {
  date: string; // ISO yyyy-mm-dd
  baseline: number; // minor units, end-of-day balance
  scenario?: number;
}

/** End-of-day balances keyed by date, starting from the opening balance. */
function endOfDay(p: Projection): Map<string, number> {
  const out = new Map<string, number>([[p.start, p.opening_balance_minor]]);
  for (const e of p.events) out.set(e.on, e.balance_after_minor);
  if (!out.has(p.end)) out.set(p.end, p.closing_balance_minor);
  return out;
}

/**
 * Merge a baseline projection and an optional scenario into one step series.
 * Each date appears once; a series without an event on that date carries its
 * previous balance forward, which is exactly how cash behaves between events.
 */
export function mergeSeries(baseline: Projection, scenario?: Projection | null): BalancePoint[] {
  const a = endOfDay(baseline);
  const b = scenario ? endOfDay(scenario) : null;
  const dates = [...new Set([...a.keys(), ...(b?.keys() ?? [])])].sort();
  let lastA = baseline.opening_balance_minor;
  let lastB = scenario?.opening_balance_minor ?? 0;
  return dates.map((date) => {
    lastA = a.get(date) ?? lastA;
    const point: BalancePoint = { date, baseline: lastA };
    if (b) {
      lastB = b.get(date) ?? lastB;
      point.scenario = lastB;
    }
    return point;
  });
}

export type Verdict = "safe" | "reserve" | "negative";

export function verdict(p: Projection): Verdict {
  if (p.first_negative_on) return "negative";
  if (p.first_reserve_breach_on) return "reserve";
  return "safe";
}

export interface ScenarioInput {
  horizonMonths: number;
  delayMonths: number;
  mode: "delayed" | "lost";
  emergencyMinor: number | null;
  emergencyOn: string | null;
}

export function scenarioRequest(s: ScenarioInput): Schemas["ProjectionRequest"] {
  return {
    horizon_months: s.horizonMonths,
    include_planned: true,
    shock: s.delayMonths > 0 ? { months: s.delayMonths, mode: s.mode } : null,
    emergencies:
      s.emergencyMinor && s.emergencyMinor > 0
        ? [{ name: "Emergency", amount_minor: s.emergencyMinor, on: s.emergencyOn || null }]
        : [],
  };
}

export function hasScenario(s: ScenarioInput): boolean {
  return s.delayMonths > 0 || Boolean(s.emergencyMinor && s.emergencyMinor > 0);
}
