"use client";

import { useState } from "react";

import { MoneyInput } from "@/components/money-input";
import { Alert, Badge, Field, LoadingBlock, Select } from "@/components/ui";
import { api, type Schemas } from "@/lib/api/client";
import { formatDate } from "@/lib/labels";
import { formatMoney, minorToInput, parseToMinor } from "@/lib/money";
import { useResource } from "@/lib/use-resource";

type Item = Schemas["PlannedItemRead"];
type ForecastOut = Schemas["ForecastOut"];

const HORIZONS = [7, 14, 30, 60, 90].map((d) => ({ value: String(d), label: `${d} days` }));
const TONE = { high: "success", medium: "brand", low: "warning" } as const;

/** "What is the chance it gets cheap enough in time?" from this item's own price history. */
export function PriceOutlook({ item }: { item: Item }) {
  const [horizon, setHorizon] = useState<number | null>(null);
  const [targetText, setTargetText] = useState("");
  const target = targetText.trim() ? parseToMinor(targetText, item.currency) : null;
  const key = `forecast:${item.id}:${target ?? "default"}:${horizon ?? "default"}`;
  const forecast = useResource<ForecastOut>(key, (signal) =>
    api<ForecastOut>(`/items/${item.id}/forecast`, {
      query: { target_minor: target ?? undefined, horizon_days: horizon ?? undefined },
      signal,
    }),
  );
  const f = forecast.data;

  return (
    <section className="rounded-lg border border-border p-4" aria-labelledby="outlook-title">
      <h3 id="outlook-title" className="text-sm font-semibold">
        Price outlook
      </h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field
          label="Target price"
          hint={
            f
              ? `Default: ${f.target_minor === item.max_price_minor ? "your maximum" : "10% off"}`
              : undefined
          }
        >
          {(p) => (
            <MoneyInput
              {...p}
              currency={item.currency}
              value={targetText}
              placeholder={f ? minorToInput(f.target_minor, item.currency) : undefined}
              onChange={(e) => setTargetText(e.target.value)}
            />
          )}
        </Field>
        <Field label="Within">
          {(p) => (
            <Select
              {...p}
              value={horizon ? String(horizon) : ""}
              onChange={(e) => setHorizon(e.target.value ? Number(e.target.value) : null)}
              options={[{ value: "", label: "Until you need it" }, ...HORIZONS]}
            />
          )}
        </Field>
      </div>

      <div className="mt-4" aria-live="polite">
        {forecast.loading && !f ? (
          <LoadingBlock label="Estimating…" />
        ) : forecast.error ? (
          <Alert>{forecast.error.message}</Alert>
        ) : !f ? null : !f.available ? (
          <p className="text-sm text-muted">{f.reason}</p>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <p className="text-3xl font-semibold tracking-tight tabular">
                {Math.round((f.probability ?? 0) * 100)}%
              </p>
              <p className="text-sm">
                chance of {formatMoney(f.target_minor, f.currency)} or less by{" "}
                {formatDate(f.by_date)}
              </p>
              {f.confidence && <Badge tone={TONE[f.confidence]}>{f.confidence} confidence</Badge>}
            </div>
            <p className="text-xs text-muted">{f.basis}</p>
            {f.recent_low_minor != null && f.recent_high_minor != null && (
              <p className="text-xs text-muted">
                Recent range (last 90 days): usually {formatMoney(f.recent_low_minor, f.currency)} –{" "}
                {formatMoney(f.recent_high_minor, f.currency)}, typically{" "}
                {formatMoney(f.recent_median_minor ?? 0, f.currency)}.
              </p>
            )}
          </div>
        )}
      </div>
      <p className="mt-3 text-xs text-muted">
        An estimate from this item’s own price history, not a guarantee. Shops can change prices at
        any time.
      </p>
    </section>
  );
}
