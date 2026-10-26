"use client";

import Link from "next/link";
import { useState } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Field,
  Input,
  PageHeader,
  Select,
} from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { useUser } from "@/lib/auth";
import {
  ageInDays,
  buildApplyBody,
  defaultPicks,
  key,
  MAX_STATEMENT_BYTES,
  type Pick,
  type Preview,
} from "@/lib/imports";
import { formatDate, FREQUENCIES, labelOf } from "@/lib/labels";
import { formatMoney } from "@/lib/money";
import { useResource } from "@/lib/use-resource";

type Account = Schemas["AccountRead"];
type ApplyOut = Schemas["StatementApplyOut"];

const NEW = "__new__";
const NONE = "__none__";

export default function ImportPage() {
  const user = useUser();
  const accounts = useResource<{ items: Account[] }>("accounts", (signal) =>
    api("/accounts", { query: { limit: 200 }, signal }),
  );
  const [file, setFile] = useState<File | null>(null);
  const [monthFirst, setMonthFirst] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [picks, setPicks] = useState<Record<string, Pick>>({});
  const [target, setTarget] = useState<string>(NEW);
  const [newName, setNewName] = useState("Bank account");
  const [setBalance, setSetBalance] = useState(true);
  const [busy, setBusy] = useState<"read" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<ApplyOut | null>(null);

  const cur = preview?.currency ?? user.base_currency;
  const money = (minor: number) => formatMoney(minor, cur);

  async function read(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return setError("Choose a statement file first.");
    if (file.size > MAX_STATEMENT_BYTES) {
      return setError("That file is larger than 3 MB. Export a shorter period and try again.");
    }
    setBusy("read");
    setError(null);
    setDone(null);
    try {
      const p = await api<Preview>("/imports/statement/preview", {
        method: "POST",
        body: { text: await file.text(), day_first: !monthFirst },
      });
      setPreview(p);
      setPicks(defaultPicks(p.recurring));
      const existing = (accounts.data?.items ?? []).filter((a) => a.currency === p.currency);
      setTarget(existing.length === 1 ? existing[0].id : NEW);
    } catch (err) {
      setPreview(null);
      setError(err instanceof ApiError ? err.message : "Could not read that statement.");
    } finally {
      setBusy(null);
    }
  }

  async function apply() {
    if (!preview) return;
    setBusy("apply");
    setError(null);
    try {
      const account = target === NONE ? null : target === NEW ? { newName } : { id: target };
      const res = await api<ApplyOut>("/imports/statement/apply", {
        method: "POST",
        body: buildApplyBody(preview, picks, account, setBalance),
      });
      setDone(res);
      setPreview(null);
      setFile(null);
      await accounts.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the import.");
    } finally {
      setBusy(null);
    }
  }

  function edit(k: string, change: Partial<Pick>) {
    setPicks((prev) => ({ ...prev, [k]: { ...prev[k], ...change } }));
  }

  const chosen = preview ? preview.recurring.filter((r) => picks[key(r)]?.include).length : 0;
  const age = preview ? ageInDays(preview.end) : 0;
  const accountOptions = [
    ...(accounts.data?.items ?? [])
      .filter((a) => !a.archived && a.currency === cur)
      .map((a) => ({ value: a.id, label: `${a.name} (${money(a.balance_minor)})` })),
    { value: NEW, label: "A new account" },
    { value: NONE, label: "Don't change any account" },
  ];

  return (
    <>
      <PageHeader
        title="Import a bank statement"
        description="Set up your salary and regular bills in a minute instead of typing them in."
      />
      <div className="flex flex-col gap-6">
        {error && <Alert>{error}</Alert>}
        {done && (
          <Alert tone="success" title="Imported">
            Added {done.incomes_created.length} income and {done.obligations_created.length} bill
            {done.obligations_created.length === 1 ? "" : "s"}
            {done.balance_minor != null ? `; balance set to ${money(done.balance_minor)}` : ""}.
            {done.skipped.length > 0 && ` Skipped: ${done.skipped.join("; ")}.`}{" "}
            <Link href="/money" className="font-medium underline">
              Review in Money
            </Link>{" "}
            or{" "}
            <Link href="/planner" className="font-medium underline">
              run the planner
            </Link>
            .
          </Alert>
        )}

        <Card
          title="1. Choose the file"
          description="Download a statement as CSV (or Excel saved as CSV) from your bank's net banking. 3–6 months works best."
        >
          <form onSubmit={read} className="flex flex-col gap-4" noValidate>
            <Field label="Statement file" hint="CSV or TXT, up to 3 MB">
              {(p) => (
                <input
                  {...p}
                  type="file"
                  accept=".csv,.txt,text/csv,text/plain"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-surface-muted file:px-3 file:py-2 file:text-sm file:font-medium"
                />
              )}
            </Field>
            <Checkbox
              label="Dates are month first (e.g. 10/05/2026 is 5 October)"
              hint="Leave unticked for Indian and most other banks"
              checked={monthFirst}
              onChange={(e) => setMonthFirst(e.target.checked)}
            />
            <p className="text-xs text-muted">
              The file is read on the server and thrown away. SpendWise keeps only what you confirm
              below — never the statement or its transactions.
            </p>
            <div>
              <Button type="submit" loading={busy === "read"} disabled={!file}>
                Read statement
              </Button>
            </div>
          </form>
        </Card>

        {preview && (
          <>
            <Card title="2. Check it was read correctly">
              <dl className="grid gap-3 sm:grid-cols-4">
                {[
                  ["Transactions", String(preview.rows)],
                  ["Period", `${formatDate(preview.start)} – ${formatDate(preview.end)}`],
                  ["Money in", money(preview.money_in_minor)],
                  ["Money out", money(preview.money_out_minor)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-lg bg-surface-muted p-3">
                    <dt className="text-xs text-muted">{label}</dt>
                    <dd className="font-semibold tabular">{value}</dd>
                  </div>
                ))}
              </dl>
              <div className="mt-3 flex flex-wrap gap-2 text-sm">
                {preview.balance_checked > 0 ? (
                  preview.balance_mismatches === 0 ? (
                    <Badge tone="success">
                      ✓ All {preview.balance_checked} rows match the running balance
                    </Badge>
                  ) : (
                    <Badge tone="warning">
                      ! {preview.balance_mismatches} of {preview.balance_checked} rows don&apos;t
                      match the balance
                    </Badge>
                  )
                ) : (
                  <Badge>No balance column to check against</Badge>
                )}
                {preview.skipped_rows > 0 && (
                  <Badge>{preview.skipped_rows} non-transaction lines ignored</Badge>
                )}
              </div>
              {preview.warnings.map((w) => (
                <div key={w} className="mt-3">
                  <Alert tone="warning">{w}</Alert>
                </div>
              ))}
              <details className="mt-3 text-sm">
                <summary className="cursor-pointer text-muted">Latest transactions</summary>
                <ul className="mt-2 divide-y divide-border">
                  {preview.recent.map((r, i) => (
                    <li key={i} className="flex gap-3 py-1.5">
                      <span className="w-24 shrink-0 text-muted">{formatDate(r.on)}</span>
                      <span className="min-w-0 flex-1 truncate" title={r.description}>
                        {r.description}
                      </span>
                      <span className={`tabular ${r.amount_minor > 0 ? "text-success" : ""}`}>
                        {r.amount_minor > 0 ? "+" : ""}
                        {money(r.amount_minor)}
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            </Card>

            <Card
              title="3. Choose what to set up"
              description="Payments that repeat weekly, monthly or quarterly. Rename them and mark which bills are essential — essentials size your emergency reserve."
            >
              {preview.recurring.length === 0 ? (
                <p className="text-sm text-muted">
                  No regular payments found. A longer statement (3 months or more) helps.
                </p>
              ) : (
                <ul className="divide-y divide-border">
                  {preview.recurring.map((r) => {
                    const k = key(r);
                    const pick = picks[k];
                    return (
                      <li key={k} className="flex flex-wrap items-start gap-3 py-3">
                        <input
                          type="checkbox"
                          checked={pick.include}
                          onChange={(e) => edit(k, { include: e.target.checked })}
                          aria-label={`Set up ${pick.name}`}
                          className="mt-2.5 h-4 w-4 accent-[var(--brand)]"
                        />
                        <div className="min-w-0 flex-1">
                          <Input
                            aria-label="Name"
                            value={pick.name}
                            onChange={(e) => edit(k, { name: e.target.value })}
                            className="max-w-xs"
                          />
                          <p className="mt-1 text-xs text-muted">
                            {labelOf(FREQUENCIES, r.frequency)} · seen {r.occurrences} times · next
                            about {formatDate(r.next_on)}
                            {r.examples[0] ? ` · “${r.examples[0]}”` : ""}
                          </p>
                          <div className="mt-1 flex flex-wrap gap-2">
                            {r.already_set_up && <Badge tone="brand">Already set up</Badge>}
                            {r.amount_varies && (
                              <Badge tone="warning">Amount varies — typical shown</Badge>
                            )}
                          </div>
                          {r.direction === "expense" && (
                            <div className="mt-2">
                              <Checkbox
                                label="Essential"
                                checked={pick.essential}
                                onChange={(e) => edit(k, { essential: e.target.checked })}
                              />
                            </div>
                          )}
                        </div>
                        <p
                          className={`pt-2 font-semibold tabular ${r.direction === "income" ? "text-success" : ""}`}
                        >
                          {r.direction === "income" ? "+" : "−"}
                          {money(r.amount_minor)}
                        </p>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>

            <Card title="4. Account balance">
              <div className="flex flex-col gap-4">
                <Field label="Statement account">
                  {(p) => (
                    <Select
                      {...p}
                      value={target}
                      onChange={(e) => setTarget(e.target.value)}
                      options={accountOptions}
                    />
                  )}
                </Field>
                {target === NEW && (
                  <Field label="New account name">
                    {(p) => (
                      <Input {...p} value={newName} onChange={(e) => setNewName(e.target.value)} />
                    )}
                  </Field>
                )}
                {target !== NONE && preview.closing_balance_minor != null && (
                  <Checkbox
                    label={`Set the balance to ${money(preview.closing_balance_minor)}`}
                    hint={`The closing balance on ${formatDate(preview.end)}${
                      age > 7 ? ` — ${age} days ago, so update it if it has changed since` : ""
                    }`}
                    checked={setBalance}
                    onChange={(e) => setSetBalance(e.target.checked)}
                  />
                )}
                <div>
                  <Button
                    onClick={() => void apply()}
                    loading={busy === "apply"}
                    disabled={chosen === 0 && (target === NONE || !setBalance)}
                  >
                    Import {chosen} item{chosen === 1 ? "" : "s"}
                  </Button>
                </div>
              </div>
            </Card>
          </>
        )}
      </div>
    </>
  );
}
