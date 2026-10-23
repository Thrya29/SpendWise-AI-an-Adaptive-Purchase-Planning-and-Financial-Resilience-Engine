"use client";

import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

import { Button } from "@/components/ui";
import { formatDate } from "@/lib/labels";
import { formatMoney } from "@/lib/money";
import { mergeSeries, type Projection } from "@/lib/projection";

const SERIES = {
  baseline: { label: "As planned", color: "var(--series-1)", dash: undefined },
  scenario: { label: "Scenario", color: "var(--series-2)", dash: "6 4" },
} as const;

function shortDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

function Swatch({ color, dashed }: { color: string; dashed?: boolean }) {
  return (
    <svg width="18" height="8" aria-hidden="true" className="shrink-0">
      <line
        x1="1"
        y1="4"
        x2="17"
        y2="4"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={dashed ? "4 3" : undefined}
      />
    </svg>
  );
}

function ChartTooltip({
  active,
  payload,
  label,
  currency,
}: TooltipContentProps<number, string> & { currency: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-medium text-text">{formatDate(String(label))}</p>
      {payload.map((entry) => {
        const key = entry.dataKey as keyof typeof SERIES;
        return (
          <p key={key} className="flex items-center gap-2 text-muted">
            <Swatch color={SERIES[key].color} dashed={Boolean(SERIES[key].dash)} />
            <span>{SERIES[key].label}</span>
            <span className="ml-auto pl-4 font-semibold text-text tabular">
              {formatMoney(Number(entry.value), currency)}
            </span>
          </p>
        );
      })}
    </div>
  );
}

export function ProjectionChart({
  baseline,
  scenario,
}: {
  baseline: Projection;
  scenario?: Projection | null;
}) {
  const [showTable, setShowTable] = useState(false);
  const data = mergeSeries(baseline, scenario);
  const currency = baseline.currency;
  const reserve = baseline.reserve_required_minor;
  const values = data.flatMap((d) => [d.baseline, d.scenario ?? d.baseline]);
  const lo = Math.min(0, reserve, ...values);
  const hi = Math.max(reserve, ...values);
  const pad = Math.max((hi - lo) * 0.08, 1);
  const series = scenario ? (["baseline", "scenario"] as const) : (["baseline"] as const);

  return (
    <figure className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {series.length > 1 ? (
          <ul className="flex flex-wrap gap-4 text-xs text-muted" aria-label="Legend">
            {series.map((key) => (
              <li key={key} className="flex items-center gap-1.5">
                <Swatch color={SERIES[key].color} dashed={Boolean(SERIES[key].dash)} />
                {SERIES[key].label}
              </li>
            ))}
            <li className="flex items-center gap-1.5">
              <Swatch color="var(--text-muted)" dashed /> Reserve
            </li>
          </ul>
        ) : (
          <p className="text-xs text-muted">
            Projected balance, end of each day. Dashed line: reserve.
          </p>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setShowTable((v) => !v)}
          aria-pressed={showTable}
        >
          {showTable ? "Show chart" : "Show table"}
        </Button>
      </div>

      {showTable ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm tabular">
            <caption className="sr-only">Monthly cash-flow summary</caption>
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="py-2 pr-4 font-medium">Month</th>
                <th className="py-2 pr-4 text-right font-medium">In</th>
                <th className="py-2 pr-4 text-right font-medium">Essentials</th>
                <th className="py-2 pr-4 text-right font-medium">Planned buys</th>
                <th className="py-2 pr-4 text-right font-medium">Lowest</th>
                <th className="py-2 text-right font-medium">Closing</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {(scenario ?? baseline).months.map((m) => (
                <tr key={m.month}>
                  <td className="py-2 pr-4">{m.month}</td>
                  <td className="py-2 pr-4 text-right">{formatMoney(m.inflow_minor, currency)}</td>
                  <td className="py-2 pr-4 text-right">
                    {formatMoney(m.essential_outflow_minor, currency)}
                  </td>
                  <td className="py-2 pr-4 text-right">
                    {formatMoney(m.planned_outflow_minor, currency)}
                  </td>
                  <td
                    className={`py-2 pr-4 text-right ${m.min_balance_minor < reserve ? "text-danger" : ""}`}
                  >
                    {formatMoney(m.min_balance_minor, currency)}
                  </td>
                  <td className="py-2 text-right font-medium">
                    {formatMoney(m.closing_balance_minor, currency)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {scenario && <p className="mt-2 text-xs text-muted">Figures shown for the scenario.</p>}
        </div>
      ) : (
        <div className="h-72 w-full" role="img" aria-label="Projected balance over time">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="0" />
              <XAxis
                dataKey="date"
                tickFormatter={shortDate}
                tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                axisLine={{ stroke: "var(--border)" }}
                tickLine={false}
                minTickGap={28}
              />
              <YAxis
                domain={[lo - pad, hi + pad]}
                tickFormatter={(v: number) =>
                  formatMoney(Math.round(v), currency, { compact: true })
                }
                tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={64}
              />
              {lo < 0 && <ReferenceLine y={0} stroke="var(--danger)" strokeWidth={1} />}
              {reserve > 0 && (
                <ReferenceLine
                  y={reserve}
                  stroke="var(--text-muted)"
                  strokeDasharray="4 4"
                  strokeWidth={1}
                  label={{
                    value: "Reserve",
                    position: "insideTopRight",
                    fill: "var(--text-muted)",
                    fontSize: 11,
                  }}
                />
              )}
              <Tooltip
                content={(props) => (
                  <ChartTooltip
                    {...(props as TooltipContentProps<number, string>)}
                    currency={currency}
                  />
                )}
                cursor={{ stroke: "var(--text-muted)", strokeWidth: 1 }}
              />
              {series.map((key) => (
                <Line
                  key={key}
                  type="stepAfter"
                  dataKey={key}
                  stroke={SERIES[key].color}
                  strokeWidth={2}
                  strokeDasharray={SERIES[key].dash}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <figcaption className="sr-only">
        Balance starts at {formatMoney(baseline.opening_balance_minor, currency)} and reaches its
        lowest point of {formatMoney((scenario ?? baseline).min_balance_minor, currency)} on{" "}
        {formatDate((scenario ?? baseline).min_balance_on)}.
      </figcaption>
    </figure>
  );
}
