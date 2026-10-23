"use client";

import Link from "next/link";
import { useState } from "react";

import { MoneyInput } from "@/components/money-input";
import { ProjectionChart } from "@/components/projection-chart";
import {
  Alert,
  Badge,
  Button,
  Card,
  Field,
  Input,
  LoadingBlock,
  PageHeader,
  Select,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useUser } from "@/lib/auth";
import { formatDate, todayIso } from "@/lib/labels";
import { formatMoney, parseToMinor } from "@/lib/money";
import {
  hasScenario,
  scenarioRequest,
  verdict,
  type Projection,
  type ScenarioInput,
} from "@/lib/projection";
import { useResource } from "@/lib/use-resource";

const HORIZONS = [3, 6, 12, 24].map((m) => ({ value: String(m), label: `${m} months` }));
const DELAYS = [
  { value: "0", label: "Salary arrives on time" },
  ...[1, 2, 3, 6].map((m) => ({
    value: String(m),
    label: `Next ${m} month${m > 1 ? "s" : ""} affected`,
  })),
];

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className="text-xs font-medium text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tracking-tight tabular ${tone ?? ""}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

function Onboarding({
  counts,
}: {
  counts: { accounts: number; incomes: number; obligations: number; items: number };
}) {
  const steps = [
    {
      done: counts.accounts > 0,
      label: "Add an account with your current balance",
      href: "/money",
    },
    { done: counts.incomes > 0, label: "Add your salary or other income", href: "/money" },
    { done: counts.obligations > 0, label: "Add rent and essential bills", href: "/money" },
    { done: counts.items > 0, label: "Add needs, wants and desires", href: "/plan" },
  ];
  if (steps.every((s) => s.done)) return null;
  return (
    <Card title="Get started" description="Four steps and SpendWise can protect your plans.">
      <ol className="grid gap-2 sm:grid-cols-2">
        {steps.map((s, i) => (
          <li key={s.label}>
            <Link
              href={s.href}
              className="flex items-center gap-3 rounded-lg border border-border px-3 py-2.5 text-sm hover:bg-surface-muted"
            >
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                  s.done ? "bg-success-soft text-success" : "bg-surface-muted text-muted"
                }`}
                aria-hidden="true"
              >
                {s.done ? "✓" : i + 1}
              </span>
              <span className={s.done ? "text-muted line-through" : ""}>{s.label}</span>
              <span className="sr-only">{s.done ? "(done)" : "(to do)"}</span>
            </Link>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function VerdictBanner({
  p,
  currency,
  scenario,
}: {
  p: Projection;
  currency: string;
  scenario: boolean;
}) {
  const v = verdict(p);
  const subject = scenario ? "In this scenario" : "With your current plan";
  if (v === "safe") {
    return (
      <Alert tone="success" title={`${subject}, you stay above your reserve.`}>
        Lowest balance {formatMoney(p.min_balance_minor, currency)} on{" "}
        {formatDate(p.min_balance_on)}.
      </Alert>
    );
  }
  if (v === "reserve") {
    return (
      <Alert
        tone="warning"
        title={`${subject}, you dip into your emergency reserve on ${formatDate(p.first_reserve_breach_on)}.`}
      >
        Lowest balance {formatMoney(p.min_balance_minor, currency)} on{" "}
        {formatDate(p.min_balance_on)} — below the {formatMoney(p.reserve_required_minor, currency)}{" "}
        reserve. Consider postponing a want or desire.
      </Alert>
    );
  }
  return (
    <Alert
      tone="danger"
      title={`${subject}, you run out of money on ${formatDate(p.first_negative_on)}.`}
    >
      Lowest balance {formatMoney(p.min_balance_minor, currency)} on {formatDate(p.min_balance_on)}.
      Postpone non-essential purchases or reduce spending before then.
    </Alert>
  );
}

export default function DashboardPage() {
  const user = useUser();
  const cur = user.base_currency;
  const [horizon, setHorizon] = useState(6);
  const [draft, setDraft] = useState<ScenarioInput>({
    horizonMonths: 6,
    delayMonths: 0,
    mode: "delayed",
    emergencyMinor: null,
    emergencyOn: null,
  });
  const [applied, setApplied] = useState<ScenarioInput | null>(null);
  const [emergencyText, setEmergencyText] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const counts = useResource("onboarding", async (signal) => {
    const [a, i, o, it] = await Promise.all(
      ["accounts", "incomes", "obligations", "items"].map((e) =>
        api<{ total: number }>(`/${e}`, { query: { limit: 1 }, signal }),
      ),
    );
    return { accounts: a.total, incomes: i.total, obligations: o.total, items: it.total };
  });

  const baseline = useResource<Projection>(`baseline:${horizon}`, (signal) =>
    api<Projection>("/projection", { method: "POST", body: { horizon_months: horizon }, signal }),
  );

  const scenarioKey =
    applied && hasScenario(applied) ? `scenario:${JSON.stringify({ ...applied, horizon })}` : null;
  const scenario = useResource<Projection>(scenarioKey, (signal) =>
    api<Projection>("/projection", {
      method: "POST",
      body: scenarioRequest({ ...applied!, horizonMonths: horizon }),
      signal,
    }),
  );

  function runScenario(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const emergency = emergencyText.trim() ? parseToMinor(emergencyText, cur) : null;
    if (emergencyText.trim() && emergency === null) {
      setFormError("Enter a valid emergency amount.");
      return;
    }
    setFormError(null);
    setApplied({ ...draft, emergencyMinor: emergency });
  }

  function reset() {
    setApplied(null);
    setEmergencyText("");
    setDraft({ ...draft, delayMonths: 0, emergencyMinor: null, emergencyOn: null });
  }

  const base = baseline.data;
  const shown = scenarioKey ? scenario.data : base;
  const scenarioError =
    scenario.error instanceof ApiError ? scenario.error.message : scenario.error?.message;

  return (
    <>
      <PageHeader
        title={`Hello, ${user.display_name.split(" ")[0]}`}
        description="Where your money is heading, and what happens if things go wrong."
        actions={
          <Select
            aria-label="Projection horizon"
            value={String(horizon)}
            onChange={(e) => setHorizon(Number(e.target.value))}
            options={HORIZONS}
            className="w-36"
          />
        }
      />

      <div className="flex flex-col gap-6">
        {counts.data && <Onboarding counts={counts.data} />}

        {baseline.loading && !base ? (
          <LoadingBlock label="Projecting your cash flow…" />
        ) : baseline.error ? (
          <Alert title="Could not load your projection">{baseline.error.message}</Alert>
        ) : base ? (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat
                label="Available now"
                value={formatMoney(base.opening_balance_minor, cur)}
                hint="Accounts used for planning"
              />
              <Stat
                label="Essentials per month"
                value={formatMoney(base.monthly_essentials_minor, cur)}
                hint="Rent, bills and other essentials"
              />
              <Stat
                label="Emergency reserve"
                value={formatMoney(base.reserve_required_minor, cur)}
                hint={`${user.reserve_months} month${user.reserve_months === 1 ? "" : "s"} of essentials`}
              />
              <Stat
                label="Runway"
                value={base.runway_months != null ? `${base.runway_months} months` : "—"}
                hint={
                  base.runway_months != null
                    ? "Essentials covered with no income"
                    : "Add essential expenses"
                }
                tone={
                  base.runway_months != null && Number(base.runway_months) < user.reserve_months
                    ? "text-warning"
                    : undefined
                }
              />
            </div>

            <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
              <Card
                title="What if…"
                description="Test a salary delay or an emergency before it happens."
              >
                <form onSubmit={runScenario} className="flex flex-col gap-4" noValidate>
                  {formError && <Alert>{formError}</Alert>}
                  <Field label="Salary">
                    {(p) => (
                      <Select
                        {...p}
                        value={String(draft.delayMonths)}
                        onChange={(e) =>
                          setDraft({ ...draft, delayMonths: Number(e.target.value) })
                        }
                        options={DELAYS}
                      />
                    )}
                  </Field>
                  {draft.delayMonths > 0 && (
                    <Field label="What happens to that pay">
                      {(p) => (
                        <Select
                          {...p}
                          value={draft.mode}
                          onChange={(e) =>
                            setDraft({ ...draft, mode: e.target.value as ScenarioInput["mode"] })
                          }
                          options={[
                            { value: "delayed", label: "Arrives late (paid later as arrears)" },
                            { value: "lost", label: "Never arrives (e.g. job loss)" },
                          ]}
                        />
                      )}
                    </Field>
                  )}
                  <Field label="Unexpected expense" hint="e.g. a medical bill or urgent repair">
                    {(p) => (
                      <MoneyInput
                        {...p}
                        currency={cur}
                        value={emergencyText}
                        onChange={(e) => setEmergencyText(e.target.value)}
                      />
                    )}
                  </Field>
                  {emergencyText.trim() && (
                    <Field label="When">
                      {(p) => (
                        <Input
                          {...p}
                          type="date"
                          min={todayIso()}
                          value={draft.emergencyOn ?? ""}
                          onChange={(e) =>
                            setDraft({ ...draft, emergencyOn: e.target.value || null })
                          }
                        />
                      )}
                    </Field>
                  )}
                  <div className="flex gap-2">
                    <Button type="submit" className="flex-1" loading={scenario.loading}>
                      Run scenario
                    </Button>
                    {applied && (
                      <Button type="button" variant="secondary" onClick={reset}>
                        Reset
                      </Button>
                    )}
                  </div>
                </form>
              </Card>

              <Card
                title="Projected balance"
                actions={scenarioKey ? <Badge tone="warning">Scenario applied</Badge> : undefined}
              >
                <div className="flex flex-col gap-4">
                  {scenarioError && <Alert>{scenarioError}</Alert>}
                  {shown && (
                    <VerdictBanner p={shown} currency={cur} scenario={Boolean(scenarioKey)} />
                  )}
                  <ProjectionChart baseline={base} scenario={scenarioKey ? scenario.data : null} />
                </div>
              </Card>
            </div>

            {shown && shown.planned_checks.length > 0 && (
              <Card
                title="Planned purchases in this period"
                description="Each purchase is checked against your reserve on the day you would pay."
              >
                <ul className="divide-y divide-border">
                  {shown.planned_checks.map((c) => (
                    <li
                      key={`${c.item_id}-${c.on}`}
                      className="flex flex-wrap items-center gap-3 py-3"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">{c.name}</p>
                        <p className="text-xs text-muted">
                          Pay by {formatDate(c.on)} · balance after{" "}
                          {formatMoney(c.balance_after_minor, cur)}
                        </p>
                      </div>
                      <p className="font-semibold tabular">{formatMoney(c.amount_minor, cur)}</p>
                      {!c.stays_solvent ? (
                        <Badge tone="danger">✕ Not affordable</Badge>
                      ) : !c.keeps_reserve ? (
                        <Badge tone="warning">! Uses reserve</Badge>
                      ) : (
                        <Badge tone="success">✓ Safe</Badge>
                      )}
                    </li>
                  ))}
                </ul>
              </Card>
            )}

            {shown && shown.warnings.length > 0 && (
              <Alert tone="brand" title="Not included in this projection">
                <ul className="list-disc pl-5">
                  {shown.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </Alert>
            )}
          </>
        ) : null}
      </div>
    </>
  );
}
