/**
 * Exact money helpers. The API exchanges integer minor units (paise, cents, yen);
 * user input is parsed as a decimal string so no floating-point rounding can occur.
 */

const NON_DEFAULT_EXPONENTS: Record<string, number> = {
  BIF: 0, CLP: 0, DJF: 0, GNF: 0, ISK: 0, JPY: 0, KMF: 0, KRW: 0, PYG: 0, RWF: 0,
  UGX: 0, UYI: 0, VND: 0, VUV: 0, XAF: 0, XOF: 0, XPF: 0,
  BHD: 3, IQD: 3, JOD: 3, KWD: 3, LYD: 3, OMR: 3, TND: 3,
}; // prettier-ignore

/** Kept in sync with backend/app/domain/money.py SUPPORTED_CURRENCIES. */
export const CURRENCIES = [
  "INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD", "JPY", "CHF", "CNY", "HKD",
  "NZD", "SAR", "QAR", "KWD", "BHD", "OMR", "MYR", "THB", "IDR", "PHP", "LKR", "NPR",
  "BDT", "PKR", "ZAR", "SEK", "NOK", "DKK", "KRW", "BRL", "MXN",
] as const; // prettier-ignore

export type Currency = (typeof CURRENCIES)[number];

export function minorExponent(currency: string): number {
  return NON_DEFAULT_EXPONENTS[currency] ?? 2;
}

const MAX_MINOR = 10n ** 15n;

/**
 * Parse a user-entered major-unit amount ("1,499.50") into integer minor units.
 * Returns null for anything that is not a plain non-negative decimal, has more
 * decimal places than the currency allows, or exceeds the API's limit.
 */
export function parseToMinor(input: string, currency: string): number | null {
  const cleaned = input.trim().replace(/[,\s_]/g, "");
  if (!/^\d+(\.\d+)?$/.test(cleaned)) return null;
  const exp = minorExponent(currency);
  const [whole, frac = ""] = cleaned.split(".");
  if (frac.length > exp) return null;
  const minor = BigInt(whole) * 10n ** BigInt(exp) + BigInt(frac.padEnd(exp, "0") || "0");
  if (minor > MAX_MINOR) return null;
  return Number(minor);
}

/** Convert minor units to a plain decimal string for editable inputs ("1499.50"). */
export function minorToInput(minor: number, currency: string): string {
  const exp = minorExponent(currency);
  const negative = minor < 0;
  const digits = Math.abs(minor)
    .toString()
    .padStart(exp + 1, "0");
  const whole = exp === 0 ? digits : digits.slice(0, -exp);
  const frac = exp === 0 ? "" : `.${digits.slice(-exp)}`;
  return `${negative ? "-" : ""}${whole}${frac}`;
}

const formatters = new Map<string, Intl.NumberFormat>();

function formatter(currency: string, locale: string | undefined, compact: boolean) {
  const key = `${currency}|${locale ?? ""}|${compact}`;
  let f = formatters.get(key);
  if (!f) {
    const exp = minorExponent(currency);
    f = new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      notation: compact ? "compact" : "standard",
      minimumFractionDigits: compact ? 0 : exp,
      maximumFractionDigits: compact ? 1 : exp,
    });
    formatters.set(key, f);
  }
  return f;
}

/** Display minor units as localised currency, e.g. 149950 INR -> "₹1,499.50". */
export function formatMoney(
  minor: number,
  currency: string,
  opts: { locale?: string; compact?: boolean } = {},
): string {
  const exp = minorExponent(currency);
  // Divide via string to avoid float artefacts for large values.
  const value = Number(minorToInput(minor, currency));
  return formatter(currency, opts.locale, opts.compact ?? false).format(exp === 0 ? minor : value);
}
