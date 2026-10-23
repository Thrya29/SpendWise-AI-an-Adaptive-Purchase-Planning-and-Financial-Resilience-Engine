import type { Schemas } from "@/lib/api/client";

export type Tier = Schemas["PlannedItemRead"]["tier"];
export type ItemKind = Schemas["PlannedItemRead"]["kind"];
export type ItemStatus = Schemas["PlannedItemRead"]["status"];
export type DeadlineType = Schemas["PlannedItemRead"]["deadline_type"];
export type Frequency = Schemas["IncomeRead"]["frequency"];
export type AccountKind = Schemas["AccountRead"]["kind"];

export const TIERS: { value: Tier; label: string; hint: string }[] = [
  { value: "need", label: "Needs", hint: "Essential: work, health, home" },
  { value: "want", label: "Wants", hint: "Improves life, can be timed" },
  { value: "desire", label: "Desires", hint: "Aspirational, first to postpone" },
];

export const ITEM_KINDS: { value: ItemKind; label: string }[] = [
  { value: "product", label: "Product" },
  { value: "service", label: "Service (e.g. salon, repair)" },
  { value: "travel", label: "Travel" },
  { value: "experience", label: "Experience" },
  { value: "subscription", label: "Subscription" },
  { value: "other", label: "Other" },
];

export const ITEM_STATUSES: { value: ItemStatus; label: string }[] = [
  { value: "planned", label: "Planned" },
  { value: "postponed", label: "Postponed" },
  { value: "purchased", label: "Purchased" },
  { value: "dropped", label: "Dropped" },
];

export const DEADLINES: { value: DeadlineType; label: string; hint: string }[] = [
  { value: "hard", label: "Hard", hint: "Must have it by the target date" },
  { value: "soft", label: "Soft", hint: "Preferred date, can move" },
  { value: "none", label: "Flexible", hint: "Whenever it is affordable" },
];

export const FREQUENCIES: { value: Frequency; label: string }[] = [
  { value: "monthly", label: "Monthly" },
  { value: "weekly", label: "Weekly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "yearly", label: "Yearly" },
  { value: "once", label: "One-off" },
];

export const ACCOUNT_KINDS: { value: AccountKind; label: string }[] = [
  { value: "bank", label: "Bank account" },
  { value: "savings", label: "Savings" },
  { value: "cash", label: "Cash" },
  { value: "wallet", label: "Wallet / UPI" },
  { value: "other", label: "Other" },
];

export function labelOf<T extends string>(options: { value: T; label: string }[], value: T) {
  return options.find((o) => o.value === value)?.label ?? value;
}

const ISO_COUNTRIES =
  "AE AR AT AU BD BE BH BR CA CH CL CN CO CZ DE DK EG ES FI FR GB GH GR HK HU ID IE IL IN IT JP KE KR KW LK MA MX MY NG NL NO NP NZ OM PE PH PK PL PT QA RO SA SE SG TH TR TW UA US VN ZA".split(
    " ",
  );

export function countryOptions(locale?: string): { value: string; label: string }[] {
  let names: Intl.DisplayNames | null = null;
  try {
    names = new Intl.DisplayNames(locale ? [locale] : undefined, { type: "region" });
  } catch {
    names = null;
  }
  return ISO_COUNTRIES.map((code) => ({ value: code, label: names?.of(code) ?? code })).sort(
    (a, b) => a.label.localeCompare(b.label),
  );
}

/**
 * IANA timezones for a picker. ICU lists some zones under legacy names (e.g. Asia/Calcutta
 * rather than Asia/Kolkata), so the user's saved zone and the browser's own zone are always
 * included; otherwise a <select> would silently fall back to the first option and change it.
 */
export function timezoneOptions(...mustInclude: (string | null | undefined)[]): string[] {
  let zones: string[];
  try {
    zones = Intl.supportedValuesOf("timeZone");
  } catch {
    zones = ["UTC", "Asia/Kolkata", "Europe/London", "America/New_York"];
  }
  const extra = [...mustInclude, browserTimezone(), "UTC"].filter((z): z is string => Boolean(z));
  return [...new Set([...zones, ...extra])].sort();
}

export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function formatDate(iso: string | null | undefined, locale?: string): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function todayIso(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}
