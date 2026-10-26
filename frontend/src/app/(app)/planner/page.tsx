"use client";

import Link from "next/link";
import { useState } from "react";

import { MoneyInput } from "@/components/money-input";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  Field,
  PageHeader,
  Select,
} from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { useUser } from "@/lib/auth";
import { formatDate, labelOf, TIERS } from "@/lib/labels";
import { formatMoney, parseToMinor } from "@/lib/money";
import {
  ACTION_GROUPS,
  describeChanges,
  explain,
  hasChanges,
  onTimeRisk,
  PROTECT_OPTIONS,
  type Choice,
  type Decision,
  type Plan,
} from "@/lib/planner";

type ApplyResult = Schemas["ApplyResponse"];

const HORIZONS = [3, 6, 12, 24].map((m) => ({ value: String(m), label: `${m} months` }));

function DecisionRow({
  d,
  currency,
  nameOf,
  selectable,
  selected,
  onToggle,
  choice,
  onTime,
  onToggleOnTime,
}: {
  d: Decision;
  currency: string;
  nameOf: (id: string) => string | undefined;
  selectable: boolean;
  selected: boolean;
  onToggle: () => void;
  choice: Choice;
  onTime: boolean;
  onToggleOnTime: () => void;
}) {
  const changes = describeChanges(d, choice);
  const risk = onTimeRisk(d, currency);
  return (
    <li className="flex gap-3 py-3">
      <div className="pt-0.5">
        {selectable ? (
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            aria-label={`Apply changes for ${d.name}`}
            className="h-4 w-4 accent-[var(--brand)]"
          />
        ) : (
          <span className="block h-4 w-4" aria-hidden="true" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium">{d.name}</p>
          <Badge tone={d.tier}>{labelOf(TIERS, d.tier).replace(/s$/, "")}</Badge>
          {d.late && <Badge tone="warning">Late</Badge>}
        </div>
        <p className="mt-0.5 text-sm text-muted">{explain(d, currency, undefined, nameOf)}</p>
        {d.group_note && <p className="mt-1 text-sm text-warning">{d.group_note}</p>}
        {risk && (
          <div className="mt-2 rounded-lg bg-warning-soft p-3 text-sm">
            <p className="text-warning">{risk}</p>
            {selectable && (
              <div className="mt-2">
                <Checkbox
                  label="Pay on time anyway"
                  hint="I accept this risk for this deadline"
                  checked={onTime}
                  onChange={onToggleOnTime}
                />
              </div>
            )}
          </div>
        )}
        {changes.length > 0 && (
          <p className="mt-1 text-xs text-muted">
            <span className="font-medium text-text">If applied:</span> {changes.join(" · ")}
          </p>
        )}
      </div>
      <div className="text-right">
        <p className="font-semibold tabular">{formatMoney(d.cost_minor, currency)}</p>
        {d.original_currency !== currency && (
          <p className="text-xs text-muted tabular">
            from {formatMoney(d.original_unit_price_minor * d.quantity, d.original_currency)}
          </p>
        )}
        {d.pay_on && <p className="text-xs text-muted">{formatDate(d.pay_on)}</p>}
      </div>
    </li>
  );
}

export default function PlannerPage() {
  const user = useUser();
  const cur = user.base_currency;
  const [horizon, setHorizon] = useState(6);
  const [protect, setProtect] = useState<string[]>(["delay1"]);
  const [includePostponed, setIncludePostponed] = useState(true);
  const [emergency, setEmergency] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [allowReserve, setAllowReserve] = useState(false);
  const [onTime, setOnTime] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState<ApplyResult | null>(null);

  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    const emergencyMinor = emergency.trim() ? parseToMinor(emergency, cur) : null;
    if (emergency.trim() && !emergencyMinor) {
      setError("Enter a valid emergency amount.");
      return;
    }
    setRunning(true);
    setError(null);
    setApplied(null);
    try {
      const result = await api<Plan>("/planner/plans", {
        method: "POST",
        body: {
          horizon_months: horizon,
          include_postponed: includePostponed,
          protect: PROTECT_OPTIONS.filter((o) => protect.includes(o.id)).map((o) => o.shock),
          emergencies: emergencyMinor ? [{ name: "Emergency", amount_minor: emergencyMinor }] : [],
        },
      });
      setPlan(result);
      setSelected(
        new Set(
          result.decisions
            .filter((d) => hasChanges(d) || d.alternative_changes)
            .map((d) => d.item_id),
        ),
      );
      setAllowReserve(false);
      setOnTime(new Set());
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "The planner could not run. Please try again.",
      );
    } finally {
      setRunning(false);
    }
  }

  async function apply() {
    if (!plan) return;
    setApplying(true);
    setError(null);
    try {
      const res = await api<ApplyResult>(`/planner/plans/${plan.id}/apply`, {
        method: "POST",
        body: {
          item_ids: [...selected],
          allow_reserve: allowReserve,
          on_time_item_ids: [...onTime],
        },
      });
      setApplied(res);
      setPlan({ ...plan, status: res.status });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(`${err.message}`);
        setPlan({ ...plan, stale: true });
      } else {
        setError(err instanceof ApiError ? err.message : "Could not apply the plan.");
      }
    } finally {
      setApplying(false);
    }
  }

  function flip(set: Set<string>, id: string): Set<string> {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  }
  const toggle = (id: string) => setSelected((prev) => flip(prev, id));
  const toggleOnTime = (id: string) => setOnTime((prev) => flip(prev, id));
  const changeCount = new Set([...selected, ...onTime]).size;

  const nameOf = (id: string) => plan?.decisions.find((x) => x.item_id === id)?.name;
  const selectable = plan?.status === "draft" && !plan.stale;
  const reserveSelected = plan?.decisions.some(
    (d) => d.action === "use_reserve" && selected.has(d.item_id),
  );

  return (
    <>
      <PageHeader
        title="Planner"
        description="Finds the best time to buy each item while protecting your reserve — even if things go wrong."
      />

      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <Card title="Plan settings">
          <form onSubmit={run} className="flex flex-col gap-4" noValidate>
            <Field label="Look ahead">
              {(p) => (
                <Select
                  {...p}
                  value={String(horizon)}
                  onChange={(e) => setHorizon(Number(e.target.value))}
                  options={HORIZONS}
                />
              )}
            </Field>
            <fieldset className="flex flex-col gap-2.5">
              <legend className="mb-1 text-sm font-medium">Stay safe even if…</legend>
              {PROTECT_OPTIONS.map((o) => (
                <Checkbox
                  key={o.id}
                  label={o.label}
                  checked={protect.includes(o.id)}
                  onChange={() =>
                    setProtect((p) =>
                      p.includes(o.id) ? p.filter((x) => x !== o.id) : [...p, o.id],
                    )
                  }
                />
              ))}
            </fieldset>
            <Field
              label="Expected emergency (optional)"
              hint="Applied to every scenario from today"
            >
              {(p) => (
                <MoneyInput
                  {...p}
                  currency={cur}
                  value={emergency}
                  onChange={(e) => setEmergency(e.target.value)}
                />
              )}
            </Field>
            <Checkbox
              label="Re-plan postponed items"
              hint="Postponed items get another chance when money allows"
              checked={includePostponed}
              onChange={(e) => setIncludePostponed(e.target.checked)}
            />
            <Button type="submit" loading={running}>
              {plan ? "Run again" : "Run planner"}
            </Button>
          </form>
        </Card>

        <div className="flex flex-col gap-6">
          {error && <Alert>{error}</Alert>}

          {!plan ? (
            <EmptyState
              title="No plan yet"
              description="Choose what to protect against and run the planner. It proposes changes — nothing is saved until you approve."
              action={
                <Button onClick={() => void run()} loading={running}>
                  Run planner
                </Button>
              }
            />
          ) : (
            <>
              {plan.stale && plan.status === "draft" && (
                <Alert tone="warning" title="This plan is out of date">
                  Your money or items changed since it was made. Run the planner again.
                </Alert>
              )}
              {applied && (
                <Alert tone="success" title={`Applied ${applied.applied.length} change(s).`}>
                  {applied.skipped.length > 0 && (
                    <ul className="list-disc pl-5">
                      {applied.skipped.map((s) => (
                        <li key={s.item_id}>
                          {plan.decisions.find((d) => d.item_id === s.item_id)?.name ?? "Item"}:{" "}
                          {s.reason}
                        </li>
                      ))}
                    </ul>
                  )}
                  <Link href="/plan" className="mt-1 inline-block font-medium underline">
                    View your items
                  </Link>
                </Alert>
              )}

              <Card
                title="Summary"
                actions={
                  <Badge tone={plan.summary_source === "anthropic" ? "brand" : "neutral"}>
                    {plan.summary_source === "anthropic"
                      ? "Written by Claude"
                      : "Built-in assistant"}
                  </Badge>
                }
              >
                <p className="text-sm leading-relaxed">{plan.summary}</p>
                {plan.summary_notice && (
                  <p className="mt-2 text-xs text-muted">{plan.summary_notice}</p>
                )}
                <dl className="mt-4 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-lg bg-surface-muted p-3">
                    <dt className="text-xs text-muted">Planned spending</dt>
                    <dd className="font-semibold tabular">
                      {formatMoney(plan.planned_spend_minor, cur)}
                    </dd>
                  </div>
                  <div className="rounded-lg bg-surface-muted p-3">
                    <dt className="text-xs text-muted">Reserve protected</dt>
                    <dd className="font-semibold tabular">
                      {formatMoney(plan.reserve_required_minor, cur)}
                    </dd>
                  </div>
                  <div className="rounded-lg bg-surface-muted p-3">
                    <dt className="text-xs text-muted">Solver</dt>
                    <dd className="font-semibold">
                      {plan.solver.status === "optimal" ? "Optimal" : "Best found"} ·{" "}
                      {plan.solver.solve_ms} ms
                    </dd>
                  </div>
                </dl>
                <ul className="mt-4 divide-y divide-border text-sm">
                  {plan.scenarios.map((s) => {
                    const safe = !s.first_reserve_breach_on && !s.first_negative_on;
                    return (
                      <li key={s.name} className="flex flex-wrap items-center gap-2 py-2">
                        <span className="font-medium">{s.name}</span>
                        <span className="text-muted">
                          lowest {formatMoney(s.min_balance_minor, cur)} on{" "}
                          {formatDate(s.min_balance_on)}
                        </span>
                        <span className="ml-auto">
                          {safe ? (
                            <Badge tone="success">✓ Reserve intact</Badge>
                          ) : s.first_negative_on ? (
                            <Badge tone="danger">
                              ✕ Runs out {formatDate(s.first_negative_on)}
                            </Badge>
                          ) : (
                            <Badge tone="warning">
                              ! Reserve used {formatDate(s.first_reserve_breach_on)}
                            </Badge>
                          )}
                        </span>
                      </li>
                    );
                  })}
                </ul>
                {plan.warnings.length > 0 && (
                  <ul className="mt-3 list-disc pl-5 text-xs text-muted">
                    {plan.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                )}
              </Card>

              {plan.decisions.length === 0 ? (
                <EmptyState
                  title="Nothing to plan"
                  description="Add needs, wants or desires and the planner will schedule them."
                  action={
                    <Link href="/plan" className="text-sm font-medium text-brand hover:underline">
                      Add items
                    </Link>
                  }
                />
              ) : (
                ACTION_GROUPS.map((group) => {
                  const rows = plan.decisions.filter((d) => d.action === group.action);
                  if (!rows.length) return null;
                  return (
                    <Card
                      key={group.action}
                      title={`${group.title} (${rows.length})`}
                      description={group.hint}
                    >
                      <ul className="divide-y divide-border">
                        {rows.map((d) => (
                          <DecisionRow
                            key={d.item_id}
                            d={d}
                            currency={cur}
                            nameOf={nameOf}
                            selectable={
                              selectable && (hasChanges(d) || Boolean(d.alternative_changes))
                            }
                            selected={selected.has(d.item_id)}
                            onToggle={() => toggle(d.item_id)}
                            choice={
                              onTime.has(d.item_id)
                                ? "on_time"
                                : d.action === "use_reserve" && !allowReserve
                                  ? "alternative"
                                  : "plan"
                            }
                            onTime={onTime.has(d.item_id)}
                            onToggleOnTime={() => toggleOnTime(d.item_id)}
                          />
                        ))}
                      </ul>
                    </Card>
                  );
                })
              )}

              {selectable && plan.decisions.length > 0 && (
                <div className="sticky bottom-4 flex flex-col gap-3 rounded-xl border border-border bg-surface p-4 shadow-lg sm:flex-row sm:items-center">
                  {reserveSelected && (
                    <Checkbox
                      label="Allow using my emergency reserve for the items above"
                      hint="Untick to schedule them on the later, reserve-safe date instead"
                      checked={allowReserve}
                      onChange={(e) => setAllowReserve(e.target.checked)}
                    />
                  )}
                  <Button
                    className="sm:ml-auto"
                    onClick={() => void apply()}
                    loading={applying}
                    disabled={changeCount === 0}
                  >
                    Apply {changeCount} selected change{changeCount === 1 ? "" : "s"}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
