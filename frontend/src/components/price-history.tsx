"use client";

import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

import { MoneyInput } from "@/components/money-input";
import { PriceOutlook } from "@/components/price-outlook";
import { Alert, Badge, Button, EmptyState, Field, Input, LoadingBlock } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { timeAgo } from "@/lib/market";
import { formatMoney, parseToMinor } from "@/lib/money";
import { useResource } from "@/lib/use-resource";

type Item = Schemas["PlannedItemRead"];
type Observation = Schemas["ObservationOut"];

const METHOD_LABEL: Record<Observation["method"], string> = {
  json_ld: "Product page data",
  microdata: "Product page data",
  opengraph: "Page summary tags",
  manual: "Quote you recorded",
  browser: "Saved from your browser",
};

function ChartTip({
  active,
  payload,
  currency,
}: TooltipContentProps<number, string> & { currency: string }) {
  if (!active || !payload?.length) return null;
  const o = payload[0].payload as Observation;
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-lg">
      <p className="font-semibold text-text tabular">{formatMoney(o.amount_minor, currency)}</p>
      <p className="text-muted">
        {o.source_name} · {new Date(o.observed_at).toLocaleString()}
      </p>
    </div>
  );
}

export function PriceHistory({ item, onChanged }: { item: Item; onChanged: () => void }) {
  const history = useResource<Observation[]>(`prices:${item.id}`, (signal) =>
    api<Observation[]>(`/items/${item.id}/prices`, { signal }),
  );
  const [version, setVersion] = useState(item.version);
  const [shop, setShop] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [showTable, setShowTable] = useState(false);

  const rows = history.data ?? [];
  const sameCurrency = rows.filter((r) => r.currency === item.currency);
  const chartData = [...sameCurrency].reverse();

  async function apply(obs: Observation) {
    setBusy(obs.id);
    setMessage(null);
    try {
      const updated = await api<Item>(`/items/${item.id}/prices/${obs.id}/apply`, {
        method: "POST",
        body: { version },
      });
      setVersion(updated.version);
      setMessage({
        tone: "success",
        text: `Price updated to ${formatMoney(obs.amount_minor, obs.currency)}.`,
      });
      onChanged();
    } catch (err) {
      setMessage({
        tone: "danger",
        text: err instanceof ApiError ? err.message : "Could not update.",
      });
    } finally {
      setBusy(null);
    }
  }

  async function addQuote(e: React.FormEvent) {
    e.preventDefault();
    const minor = parseToMinor(amount, item.currency);
    if (!minor || !shop.trim()) {
      setMessage({ tone: "danger", text: "Enter the shop and a valid amount." });
      return;
    }
    setBusy("quote");
    setMessage(null);
    try {
      await api(`/items/${item.id}/prices`, {
        method: "POST",
        body: { amount_minor: minor, source_name: shop.trim() },
      });
      setShop("");
      setAmount("");
      await history.reload();
    } catch (err) {
      setMessage({
        tone: "danger",
        text: err instanceof ApiError ? err.message : "Could not save the quote.",
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      {message && <Alert tone={message.tone}>{message.text}</Alert>}
      <PriceOutlook item={item} />

      {history.loading && !history.data ? (
        <LoadingBlock />
      ) : history.error ? (
        <Alert>{history.error.message}</Alert>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No prices recorded yet"
          description={
            item.url
              ? "Use “Check price” to read the product page, or record a quote below."
              : "Add a product link to check prices, or record a quote below."
          }
        />
      ) : (
        <>
          {chartData.length >= 2 && (
            <figure>
              <div className="mb-2 flex items-center justify-between">
                <figcaption className="text-xs text-muted">
                  Price over time ({item.currency})
                </figcaption>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-pressed={showTable}
                  onClick={() => setShowTable((v) => !v)}
                >
                  {showTable ? "Show chart" : "Show table"}
                </Button>
              </div>
              {!showTable && (
                <div className="h-40" role="img" aria-label="Price over time">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 6, right: 8, bottom: 0, left: 4 }}>
                      <CartesianGrid vertical={false} stroke="var(--border)" />
                      <XAxis
                        dataKey="observed_at"
                        tickFormatter={(v: string) =>
                          new Date(v).toLocaleDateString(undefined, {
                            day: "numeric",
                            month: "short",
                          })
                        }
                        tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                        axisLine={{ stroke: "var(--border)" }}
                        tickLine={false}
                        minTickGap={24}
                      />
                      <YAxis
                        dataKey="amount_minor"
                        domain={["auto", "auto"]}
                        tickFormatter={(v: number) =>
                          formatMoney(v, item.currency, { compact: true })
                        }
                        tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                        width={60}
                      />
                      <Tooltip
                        content={(p) => (
                          <ChartTip
                            {...(p as TooltipContentProps<number, string>)}
                            currency={item.currency}
                          />
                        )}
                        cursor={{ stroke: "var(--text-muted)", strokeWidth: 1 }}
                      />
                      <Line
                        type="linear"
                        dataKey="amount_minor"
                        stroke="var(--series-1)"
                        strokeWidth={2}
                        dot={{
                          r: 4,
                          strokeWidth: 2,
                          stroke: "var(--surface)",
                          fill: "var(--series-1)",
                        }}
                        activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--surface)" }}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </figure>
          )}

          <ul className="divide-y divide-border">
            {rows.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    <span className="tabular">{formatMoney(o.amount_minor, o.currency)}</span>
                    {o.availability === "out_of_stock" && (
                      <Badge tone="warning">Out of stock</Badge>
                    )}
                    {o.confidence === "low" && <Badge tone="neutral">Lowest in a range</Badge>}
                  </p>
                  <p className="text-xs text-muted">
                    {o.url ? (
                      <a
                        href={o.url}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                        className="text-brand hover:underline"
                      >
                        {o.source_name}
                      </a>
                    ) : (
                      o.source_name
                    )}{" "}
                    · {METHOD_LABEL[o.method]} · {timeAgo(o.observed_at)}
                    {o.note ? ` · ${o.note}` : ""}
                  </p>
                </div>
                {o.currency === item.currency ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy === o.id}
                    onClick={() => void apply(o)}
                  >
                    Use this price
                  </Button>
                ) : (
                  <span className="text-xs text-muted">Different currency</span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      <form onSubmit={addQuote} className="rounded-lg bg-surface-muted p-3" noValidate>
        <p className="mb-2 text-sm font-medium">Record a quote</p>
        <div className="grid gap-3 sm:grid-cols-[1fr_10rem_auto] sm:items-end">
          <Field label="Shop or source">
            {(p) => (
              <Input
                {...p}
                value={shop}
                onChange={(e) => setShop(e.target.value)}
                placeholder="e.g. local store"
                maxLength={200}
              />
            )}
          </Field>
          <Field label="Price">
            {(p) => (
              <MoneyInput
                {...p}
                currency={item.currency}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            )}
          </Field>
          <Button type="submit" loading={busy === "quote"}>
            Add
          </Button>
        </div>
      </form>
    </div>
  );
}
