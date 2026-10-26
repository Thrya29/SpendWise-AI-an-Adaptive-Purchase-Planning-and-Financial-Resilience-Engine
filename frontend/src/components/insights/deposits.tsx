"use client";

import { useState } from "react";

import { MoneyInput } from "@/components/money-input";
import { Alert, Button, Card, Checkbox, Field, Input, LoadingBlock, Select } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { formatMoney, minorToInput, parseToMinor } from "@/lib/money";
import { useResource } from "@/lib/use-resource";

type Safe = Schemas["SafeToLockOut"];
type Deposit = Schemas["DepositOut"];

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg bg-surface-muted p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular">{value}</p>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function SafeToLockCard({
  onUse,
}: {
  onUse: (amountMinor: number, months: number) => void;
}) {
  const [months, setMonths] = useState(12);
  const [delay, setDelay] = useState(1);
  const safe = useResource<Safe>(`safe:${months}:${delay}`, (signal) =>
    api<Safe>("/insights/safe-to-lock", {
      query: { months, protect_delay_months: delay },
      signal,
    }),
  );
  const s = safe.data;
  return (
    <Card
      title="Money you could set aside"
      description="How much could sit in a deposit without putting any plan or your emergency reserve at risk."
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="For">
          {(p) => (
            <Select
              {...p}
              value={String(months)}
              onChange={(e) => setMonths(Number(e.target.value))}
              options={[3, 6, 12, 24, 36].map((m) => ({ value: String(m), label: `${m} months` }))}
            />
          )}
        </Field>
        <Field label="Stay safe even if">
          {(p) => (
            <Select
              {...p}
              value={String(delay)}
              onChange={(e) => setDelay(Number(e.target.value))}
              options={[
                { value: "0", label: "Salary arrives on time" },
                { value: "1", label: "Salary is 1 month late" },
                { value: "2", label: "Salary is 2 months late" },
              ]}
            />
          )}
        </Field>
      </div>
      <div className="mt-4" aria-live="polite">
        {safe.loading && !s ? (
          <LoadingBlock />
        ) : safe.error ? (
          <Alert>{safe.error.message}</Alert>
        ) : s ? (
          <div className="flex flex-col gap-3">
            <p className="text-3xl font-semibold tracking-tight tabular">
              {formatMoney(s.amount_minor, s.currency)}
            </p>
            <p className="text-sm text-muted">{s.explanation}</p>
            <div className="grid gap-3 sm:grid-cols-3">
              <Tile label="Available now" value={formatMoney(s.available_now_minor, s.currency)} />
              <Tile label="Emergency reserve" value={formatMoney(s.reserve_minor, s.currency)} />
              <Tile
                label="Runway"
                value={s.runway_months ? `${s.runway_months} months` : "—"}
                hint="Essentials covered with no income"
              />
            </div>
            {s.amount_minor > 0 && (
              <div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => onUse(s.amount_minor, s.months)}
                >
                  Compare an FD for this amount
                </Button>
              </div>
            )}
            {s.warnings.length > 0 && (
              <ul className="list-disc pl-5 text-xs text-muted">
                {s.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

export function DepositCard({
  currency,
  preset,
}: {
  currency: string;
  preset: { amountMinor: number; months: number } | null;
}) {
  const [amount, setAmount] = useState("");
  const [months, setMonths] = useState("12");
  const [fdRate, setFdRate] = useState("");
  const [savingsRate, setSavingsRate] = useState("2.70");
  const [early, setEarly] = useState(false);
  const [heldMonths, setHeldMonths] = useState("6");
  const [penalty, setPenalty] = useState("1.0");
  const [result, setResult] = useState<Deposit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [appliedPreset, setAppliedPreset] = useState<typeof preset>(null);

  if (preset && preset !== appliedPreset) {
    setAppliedPreset(preset);
    setAmount(minorToInput(preset.amountMinor, currency));
    setMonths(String(preset.months));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const principal = parseToMinor(amount, currency);
    if (!principal || !fdRate.trim()) {
      setError("Enter an amount and your bank's FD rate.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api<Deposit>("/insights/deposit", {
          method: "POST",
          body: {
            principal_minor: principal,
            fd_rate_percent: fdRate,
            months: Number(months),
            savings_rate_percent: savingsRate,
            premature: early ? { held_months: Number(heldMonths), penalty_percent: penalty } : null,
          },
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not calculate.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Fixed deposit or savings account?"
      description="Enter your bank's actual rates. Nothing here is a recommendation."
    >
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        {error && <Alert>{error}</Alert>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Amount">
            {(p) => (
              <MoneyInput
                {...p}
                currency={currency}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            )}
          </Field>
          <Field label="Months">
            {(p) => (
              <Input
                {...p}
                type="number"
                min={1}
                max={120}
                value={months}
                onChange={(e) => setMonths(e.target.value)}
              />
            )}
          </Field>
          <Field label="FD rate (% a year)">
            {(p) => (
              <Input
                {...p}
                inputMode="decimal"
                placeholder="e.g. 7.0"
                value={fdRate}
                onChange={(e) => setFdRate(e.target.value)}
              />
            )}
          </Field>
          <Field label="Savings account rate (% a year)">
            {(p) => (
              <Input
                {...p}
                inputMode="decimal"
                value={savingsRate}
                onChange={(e) => setSavingsRate(e.target.value)}
              />
            )}
          </Field>
        </div>
        <Checkbox
          label="What if I need the money early?"
          checked={early}
          onChange={(e) => setEarly(e.target.checked)}
        />
        {early && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Break after (months)">
              {(p) => (
                <Input
                  {...p}
                  type="number"
                  min={0}
                  value={heldMonths}
                  onChange={(e) => setHeldMonths(e.target.value)}
                />
              )}
            </Field>
            <Field label="Penalty (% points)" hint="Often 0.5–1">
              {(p) => (
                <Input
                  {...p}
                  inputMode="decimal"
                  value={penalty}
                  onChange={(e) => setPenalty(e.target.value)}
                />
              )}
            </Field>
          </div>
        )}
        <div>
          <Button type="submit" loading={busy}>
            Compare
          </Button>
        </div>
      </form>
      {result && (
        <div className="mt-5 flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <Tile
              label="FD at maturity"
              value={formatMoney(result.fd_maturity_minor, result.currency)}
              hint={`Interest ${formatMoney(result.fd_interest_minor, result.currency)}`}
            />
            <Tile
              label="Savings account"
              value={formatMoney(result.savings_balance_minor, result.currency)}
              hint={`Interest ${formatMoney(result.savings_interest_minor, result.currency)}`}
            />
            <Tile
              label="FD earns more by"
              value={formatMoney(result.fd_advantage_minor, result.currency)}
            />
          </div>
          {result.premature_payout_minor != null && (
            <Alert tone="warning">
              Breaking it early pays {formatMoney(result.premature_payout_minor, result.currency)} (
              {result.premature_effective_rate_percent}% effective), about{" "}
              {formatMoney(result.premature_interest_lost_minor ?? 0, result.currency)} less
              interest than holding to maturity.
            </Alert>
          )}
          <ul className="list-disc pl-5 text-xs text-muted">
            {result.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          <p className="text-xs text-muted">{result.disclaimer}</p>
        </div>
      )}
    </Card>
  );
}
