import { describe, expect, it } from "vitest";

import { formatMoney, minorExponent, minorToInput, parseToMinor } from "./money";

describe("parseToMinor", () => {
  it("parses decimals exactly into minor units", () => {
    expect(parseToMinor("1499.50", "INR")).toBe(149950);
    expect(parseToMinor("1,49,999", "INR")).toBe(14999900);
    expect(parseToMinor("0.1", "USD")).toBe(10);
    expect(parseToMinor("0.29", "USD")).toBe(29); // 0.29 * 100 is 28.999... in floats
    expect(parseToMinor("1499", "JPY")).toBe(1499);
    expect(parseToMinor("1.234", "KWD")).toBe(1234);
  });

  it("rejects malformed, negative, over-precise or oversized input", () => {
    for (const bad of ["", "abc", "-5", "1.2.3", "1e5", "0x10", "Infinity"]) {
      expect(parseToMinor(bad, "INR")).toBeNull();
    }
    expect(parseToMinor("1.999", "INR")).toBeNull();
    expect(parseToMinor("1.5", "JPY")).toBeNull();
    expect(parseToMinor("99999999999999999", "INR")).toBeNull();
  });
});

describe("minorToInput", () => {
  it("round-trips with parseToMinor", () => {
    for (const [minor, cur] of [
      [149950, "INR"],
      [5, "USD"],
      [0, "EUR"],
      [1499, "JPY"],
      [1234, "KWD"],
    ] as const) {
      expect(parseToMinor(minorToInput(minor, cur), cur)).toBe(minor);
    }
    expect(minorToInput(5, "USD")).toBe("0.05");
    expect(minorToInput(-150, "USD")).toBe("-1.50");
  });
});

describe("formatMoney", () => {
  it("formats with the currency's precision", () => {
    expect(formatMoney(149950, "INR", { locale: "en-IN" })).toBe("₹1,499.50");
    expect(formatMoney(1499, "JPY", { locale: "en-US" })).toBe("¥1,499");
    expect(formatMoney(-2500, "USD", { locale: "en-US" })).toBe("-$25.00");
    expect(formatMoney(150000000, "INR", { locale: "en-IN", compact: true })).toMatch(/₹15/);
  });

  it("knows non-default exponents", () => {
    expect(minorExponent("INR")).toBe(2);
    expect(minorExponent("JPY")).toBe(0);
    expect(minorExponent("BHD")).toBe(3);
  });
});
