import type { Schemas } from "@/lib/api/client";

type Item = Schemas["PlannedItemRead"];

export const STALE_AFTER_HOURS = 24;

/** "just now", "5 min ago", "3 h ago", "2 days ago" — relative to `now`. */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function isStale(iso: string | null | undefined, now: Date = new Date()): boolean {
  if (!iso) return false;
  return now.getTime() - new Date(iso).getTime() > STALE_AFTER_HOURS * 3_600_000;
}

/** Where the item's current price comes from, in plain words. */
export function priceProvenance(
  item: Item,
  now: Date = new Date(),
): { label: string; stale: boolean } {
  switch (item.price_source) {
    case "link":
      if (!item.price_observed_at) return { label: "From the product page", stale: false };
      return {
        label: `From the product page · ${timeAgo(item.price_observed_at, now)}`,
        stale: isStale(item.price_observed_at, now),
      };
    case "quote":
      return {
        label: item.price_observed_at ? `Quote · ${timeAgo(item.price_observed_at, now)}` : "Quote",
        stale: false,
      };
    case "estimate":
      return { label: "Estimate", stale: false };
    default:
      return { label: "Your estimate", stale: false };
  }
}

export function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/**
 * Display-only conversion (the server does exact conversion for planning).
 * `rate` = units of `to` per one unit of `from`, as a decimal string.
 */
export function approxConvert(minor: number, fromExp: number, toExp: number, rate: string): number {
  return Math.round((minor / 10 ** fromExp) * Number(rate) * 10 ** toExp);
}
