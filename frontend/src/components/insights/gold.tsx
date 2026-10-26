"use client";

import { useState } from "react";

import { MoneyInput } from "@/components/money-input";
import { Alert, Button, Card, Field, Input, LoadingBlock, Select } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { timeAgo } from "@/lib/market";
import { formatMoney, minorToInput, parseToMinor } from "@/lib/money";
import { useResource } from "@/lib/use-resource";

type Gold = Schemas["GoldOut"];
type Bill = Schemas["JewelleryOut"];

const PURITIES = ["22K", "24K", "18K", "14K"].map((p) => ({ value: p, label: p }));

export function GoldCard({ currency }: { currency: string }) {
  const gold = useResource<Gold>("gold", (signal) => api<Gold>("/gold", { signal }));
  const [refreshing, setRefreshing] = useState(false);
  const [rate, setRate] = useState("");
  const [weight, setWeight] = useState("10");
  const [purity, setPurity] = useState("22K");
  const [making, setMaking] = useState("12");
  const [gst, setGst] = useState("3");
  const [bill, setBill] = useState<Bill | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setRefreshing(true);
    setError(null);
    try {
      await api("/gold/refresh", { method: "POST" });
      await gold.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not refresh the gold price.");
    } finally {
      setRefreshing(false);
    }
  }

  async function estimate(e: React.FormEvent) {
    e.preventDefault();
    const perGram = parseToMinor(rate, currency);
    if (!perGram) {
      setError("Enter the 24K rate per gram you were quoted.");
      return;
    }
    setError(null);
    try {
      setBill(
        await api<Bill>("/gold/jewellery", {
          method: "POST",
          body: {
            rate_24k_per_gram_minor: perGram,
            weight_grams: weight,
            purity,
            making_percent: making,
            gst_percent: gst,
          },
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not estimate the bill.");
    }
  }

  const g = gold.data;
  return (
    <Card
      title="Gold"
      description="A reference price and a jewellery bill estimate, with every charge shown separately."
      actions={
        <Button size="sm" variant="secondary" loading={refreshing} onClick={() => void refresh()}>
          Refresh price
        </Button>
      }
    >
      {error && (
        <div className="mb-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {gold.loading && !g ? (
        <LoadingBlock />
      ) : g?.available && g.per_gram_24k_minor != null ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-6">
            <div>
              <p className="text-xs text-muted">24K reference, per gram</p>
              <p className="text-2xl font-semibold tabular">
                {formatMoney(g.per_gram_24k_minor, g.currency)}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted">22K equivalent, per gram</p>
              <p className="text-2xl font-semibold tabular">
                {formatMoney(g.per_gram_22k_minor ?? 0, g.currency)}
              </p>
            </div>
          </div>
          <p className="text-xs text-muted">
            {g.usd_per_ounce} per troy ounce · {g.source}
            {g.observed_at ? ` · ${timeAgo(g.observed_at)}` : ""}
          </p>
          <Alert tone="warning">{g.caveat}</Alert>
          {g.per_gram_24k_minor && !rate && (
            <div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setRate(minorToInput(g.per_gram_24k_minor ?? 0, currency))}
              >
                Use this as the rate below (then adjust to your jeweller&apos;s quote)
              </Button>
            </div>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted">
          {g?.fx_note ?? "No gold price yet. Refresh to load one."}
        </p>
      )}

      <form onSubmit={estimate} className="mt-5 flex flex-col gap-4" noValidate>
        <p className="text-sm font-semibold">Jewellery bill estimate</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="24K rate per gram" hint="Your jeweller's quote">
            {(p) => (
              <MoneyInput
                {...p}
                currency={currency}
                value={rate}
                onChange={(e) => setRate(e.target.value)}
              />
            )}
          </Field>
          <Field label="Weight (grams)">
            {(p) => (
              <Input
                {...p}
                inputMode="decimal"
                value={weight}
                onChange={(e) => setWeight(e.target.value)}
              />
            )}
          </Field>
          <Field label="Purity">
            {(p) => (
              <Select
                {...p}
                value={purity}
                onChange={(e) => setPurity(e.target.value)}
                options={PURITIES}
              />
            )}
          </Field>
          <Field label="Making charges (%)">
            {(p) => (
              <Input
                {...p}
                inputMode="decimal"
                value={making}
                onChange={(e) => setMaking(e.target.value)}
              />
            )}
          </Field>
          <Field label="GST (%)" hint="3% on gold plus making in India">
            {(p) => (
              <Input
                {...p}
                inputMode="decimal"
                value={gst}
                onChange={(e) => setGst(e.target.value)}
              />
            )}
          </Field>
        </div>
        <div>
          <Button type="submit" variant="secondary">
            Estimate bill
          </Button>
        </div>
      </form>
      {bill && (
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:max-w-md">
          <dt className="text-muted">Gold value</dt>
          <dd className="text-right tabular">
            {formatMoney(bill.gold_value_minor, bill.currency)}
          </dd>
          <dt className="text-muted">Making charges</dt>
          <dd className="text-right tabular">
            {formatMoney(bill.making_charges_minor, bill.currency)}
          </dd>
          <dt className="text-muted">GST</dt>
          <dd className="text-right tabular">{formatMoney(bill.gst_minor, bill.currency)}</dd>
          <dt className="font-semibold">Total</dt>
          <dd className="text-right font-semibold tabular">
            {formatMoney(bill.total_minor, bill.currency)}
          </dd>
          <dt className="text-muted">Effective per gram</dt>
          <dd className="text-right tabular">
            {formatMoney(bill.effective_per_gram_minor, bill.currency)}
          </dd>
        </dl>
      )}
    </Card>
  );
}
