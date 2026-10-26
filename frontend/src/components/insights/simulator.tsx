"use client";

import { useState } from "react";

import { MoneyInput } from "@/components/money-input";
import { Alert, Button, Card, Field, Input, Select } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { formatMoney, parseToMinor } from "@/lib/money";

type Sim = Schemas["SimulateOut"];
type Fund = Schemas["FundOut"];

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg bg-surface-muted p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular">{value}</p>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function SimulatorCard({
  currency,
  funds,
  fundCode,
  onFundCode,
}: {
  currency: string;
  funds: Fund[];
  fundCode: number | null;
  onFundCode: (code: number | null) => void;
}) {
  const [lump, setLump] = useState("");
  const [monthly, setMonthly] = useState("");
  const [years, setYears] = useState("10");
  const [ret, setRet] = useState("");
  const [vol, setVol] = useState("");
  const [fdRate, setFdRate] = useState("");
  const [result, setResult] = useState<Sim | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    const initial = lump.trim() ? parseToMinor(lump, currency) : 0;
    const each = monthly.trim() ? parseToMinor(monthly, currency) : 0;
    if (initial === null || each === null || initial + each === 0) {
      setError("Enter a lump sum, a monthly amount, or both.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api<Sim>("/insights/simulate", {
          method: "POST",
          body: {
            initial_minor: initial,
            monthly_minor: each,
            months: Math.round(Number(years) * 12),
            annual_return_percent: ret.trim() || null,
            annual_volatility_percent: vol.trim() || null,
            scheme_code: fundCode,
            compare_fd_rate_percent: fdRate.trim() || null,
          },
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not run the simulation.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="What could an investment grow to?"
      description="Shows a range of possible outcomes, not a promise. Markets can and do fall."
    >
      <form onSubmit={run} className="flex flex-col gap-4" noValidate>
        {error && <Alert>{error}</Alert>}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Lump sum">
            {(p) => (
              <MoneyInput
                {...p}
                currency={currency}
                value={lump}
                onChange={(e) => setLump(e.target.value)}
              />
            )}
          </Field>
          <Field label="Every month (SIP)">
            {(p) => (
              <MoneyInput
                {...p}
                currency={currency}
                value={monthly}
                onChange={(e) => setMonthly(e.target.value)}
              />
            )}
          </Field>
          <Field label="Years">
            {(p) => (
              <Input
                {...p}
                type="number"
                min={1}
                max={40}
                value={years}
                onChange={(e) => setYears(e.target.value)}
              />
            )}
          </Field>
        </div>
        <Field label="Assumptions from" hint="A fund you watch, or your own numbers below">
          {(p) => (
            <Select
              {...p}
              value={fundCode ? String(fundCode) : ""}
              onChange={(e) => onFundCode(e.target.value ? Number(e.target.value) : null)}
              options={[
                { value: "", label: "My own assumptions" },
                ...funds.map((f) => ({ value: String(f.scheme_code), label: f.name })),
              ]}
            />
          )}
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field
            label="Expected return (% a year)"
            hint={fundCode ? "Blank: use the fund's history" : "Blank: 10%"}
          >
            {(p) => (
              <Input
                {...p}
                inputMode="decimal"
                value={ret}
                onChange={(e) => setRet(e.target.value)}
              />
            )}
          </Field>
          <Field
            label="Volatility (% a year)"
            hint={fundCode ? "Blank: use the fund's history" : "Blank: 15%"}
          >
            {(p) => (
              <Input
                {...p}
                inputMode="decimal"
                value={vol}
                onChange={(e) => setVol(e.target.value)}
              />
            )}
          </Field>
          <Field label="Compare with FD at (% a year)" hint="Optional">
            {(p) => (
              <Input
                {...p}
                inputMode="decimal"
                value={fdRate}
                onChange={(e) => setFdRate(e.target.value)}
              />
            )}
          </Field>
        </div>
        <div>
          <Button type="submit" loading={busy}>
            Show possible outcomes
          </Button>
        </div>
      </form>

      {result && (
        <div className="mt-5 flex flex-col gap-3" aria-live="polite">
          <p className="text-sm">
            You would put in{" "}
            <strong className="tabular">
              {formatMoney(result.invested_minor, result.currency)}
            </strong>{" "}
            over {Math.round(result.months / 12)} years. In {result.paths.toLocaleString()}{" "}
            simulated markets:
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat
              label="Weak markets (1 in 10 do worse)"
              value={formatMoney(result.p10_minor, result.currency)}
            />
            <Stat label="Middle outcome" value={formatMoney(result.p50_minor, result.currency)} />
            <Stat
              label="Strong markets (1 in 10 do better)"
              value={formatMoney(result.p90_minor, result.currency)}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat
              label="Chance of ending below what you put in"
              value={`${Math.round(result.probability_of_loss * 100)}%`}
            />
            <Stat
              label="Typical worst fall along the way"
              value={`${Math.round(result.median_max_drawdown * 100)}%`}
              hint="From a high point, before recovering"
            />
            {result.fd_value_minor != null && (
              <Stat
                label="Same money in an FD"
                value={formatMoney(result.fd_value_minor, result.currency)}
                hint="Fixed rate, no market risk"
              />
            )}
          </div>
          <p className="text-xs text-muted">
            Assumed {result.annual_return_percent}% return and {result.annual_volatility_percent}%
            volatility a year · {result.assumptions_source}.
          </p>
          <p className="text-xs text-muted">{result.disclaimer}</p>
        </div>
      )}
    </Card>
  );
}
