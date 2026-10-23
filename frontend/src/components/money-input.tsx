"use client";

import { forwardRef } from "react";

import { Input } from "@/components/ui";
import { minorExponent } from "@/lib/money";

/** Text input for major-unit amounts; parse with parseToMinor() on submit. */
export const MoneyInput = forwardRef<
  HTMLInputElement,
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> & { currency: string }
>(function MoneyInput({ currency, ...props }, ref) {
  const exp = minorExponent(currency);
  return (
    <div className="relative">
      <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-xs font-medium text-muted">
        {currency}
      </span>
      <Input
        ref={ref}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        placeholder={exp === 0 ? "0" : `0.${"0".repeat(exp)}`}
        className="pl-12 tabular"
        {...props}
      />
    </div>
  );
});
