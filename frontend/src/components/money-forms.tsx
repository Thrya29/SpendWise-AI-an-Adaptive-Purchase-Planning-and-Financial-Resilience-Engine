"use client";

import { useState } from "react";

import { MoneyInput } from "@/components/money-input";
import { Alert, Button, Checkbox, Field, Input, Select } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { ACCOUNT_KINDS, FREQUENCIES, todayIso } from "@/lib/labels";
import { CURRENCIES, minorToInput, parseToMinor } from "@/lib/money";

export type Account = Schemas["AccountRead"];
export type Income = Schemas["IncomeRead"];
export type Obligation = Schemas["ObligationRead"];
export type Transaction = Schemas["TransactionRead"];

interface FormProps<T> {
  existing?: T;
  baseCurrency: string;
  onSaved: () => void;
  onCancel: () => void;
}

/** Shared submit/error plumbing for the small finance forms. */
function useSubmit(onSaved: () => void) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, local: Record<string, string> = {}) {
    if (Object.keys(local).length) {
      setErrors(local);
      return;
    }
    setBusy(true);
    setErrors({});
    setFormError(null);
    try {
      await fn();
      onSaved();
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldMessages());
        setFormError(
          err.status === 409
            ? "This record changed elsewhere. Close and reopen it to get the latest version."
            : err.fieldErrors.length
              ? "Please fix the highlighted fields."
              : err.message,
        );
      } else {
        setFormError("Could not save. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }
  return { errors, formError, busy, run };
}

function Actions({
  busy,
  onCancel,
  editing,
}: {
  busy: boolean;
  onCancel: () => void;
  editing: boolean;
}) {
  return (
    <div className="mt-2 flex justify-end gap-2">
      <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
        Cancel
      </Button>
      <Button type="submit" loading={busy}>
        {editing ? "Save changes" : "Add"}
      </Button>
    </div>
  );
}

function CurrencySelect({
  value,
  onChange,
  disabled,
  ...p
}: {
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  id: string;
}) {
  return (
    <Select
      {...p}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      options={CURRENCIES.map((c) => ({ value: c, label: c }))}
    />
  );
}

const fd = (f: FormData, k: string) => String(f.get(k) ?? "").trim();

export function AccountForm({ existing, baseCurrency, onSaved, onCancel }: FormProps<Account>) {
  const [currency, setCurrency] = useState(existing?.currency ?? baseCurrency);
  const { errors, formError, busy, run } = useSubmit(onSaved);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const raw = fd(f, "opening");
    const negative = raw.startsWith("-");
    const parsed = parseToMinor(raw.replace(/^-/, "") || "0", currency);
    const opening = parsed === null ? null : negative ? -parsed : parsed;
    const body = {
      name: fd(f, "name"),
      kind: fd(f, "kind") as Account["kind"],
      opening_balance_minor: opening ?? 0,
      include_in_planning: f.get("include_in_planning") === "on",
    };
    void run(
      () =>
        existing
          ? api(`/accounts/${existing.id}`, {
              method: "PATCH",
              body: { ...body, version: existing.version },
            })
          : api("/accounts", { method: "POST", body: { ...body, currency } }),
      opening === null ? { opening_balance_minor: "Enter a valid amount" } : {},
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      {formError && <Alert>{formError}</Alert>}
      <Field label="Account name" error={errors.name}>
        {(p) => (
          <Input
            {...p}
            name="name"
            defaultValue={existing?.name}
            required
            maxLength={100}
            autoFocus
          />
        )}
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Type" error={errors.kind}>
          {(p) => (
            <Select
              {...p}
              name="kind"
              defaultValue={existing?.kind ?? "bank"}
              options={ACCOUNT_KINDS}
            />
          )}
        </Field>
        <Field label="Currency" error={errors.currency}>
          {(p) => (
            <CurrencySelect
              {...p}
              value={currency}
              onChange={setCurrency}
              disabled={Boolean(existing)}
            />
          )}
        </Field>
      </div>
      <Field
        label="Balance when you started tracking"
        error={errors.opening_balance_minor}
        hint="Transactions you record are added to this. Prefix with - for an overdraft."
      >
        {(p) => (
          <MoneyInput
            {...p}
            name="opening"
            currency={currency}
            defaultValue={
              existing ? minorToInput(existing.opening_balance_minor, existing.currency) : ""
            }
          />
        )}
      </Field>
      <Checkbox
        name="include_in_planning"
        defaultChecked={existing?.include_in_planning ?? true}
        label="Use this money for planning"
        hint="Untick for money you never want plans to touch (e.g. a long-term deposit)."
      />
      <Actions busy={busy} onCancel={onCancel} editing={Boolean(existing)} />
    </form>
  );
}

function RecurrenceFields({
  errors,
  existing,
}: {
  errors: Record<string, string>;
  existing?: { frequency: Income["frequency"]; anchor_date: string; end_date: string | null };
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <Field label="How often" error={errors.frequency}>
        {(p) => (
          <Select
            {...p}
            name="frequency"
            defaultValue={existing?.frequency ?? "monthly"}
            options={FREQUENCIES}
          />
        )}
      </Field>
      <Field label="Next / first date" error={errors.anchor_date}>
        {(p) => (
          <Input
            {...p}
            name="anchor_date"
            type="date"
            required
            defaultValue={existing?.anchor_date ?? todayIso()}
          />
        )}
      </Field>
      <Field label="Ends (optional)" error={errors.end_date}>
        {(p) => (
          <Input {...p} name="end_date" type="date" defaultValue={existing?.end_date ?? ""} />
        )}
      </Field>
    </div>
  );
}

export function IncomeForm({ existing, baseCurrency, onSaved, onCancel }: FormProps<Income>) {
  const currency = existing?.currency ?? baseCurrency;
  const { errors, formError, busy, run } = useSubmit(onSaved);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const amount = parseToMinor(fd(f, "amount"), currency);
    const body = {
      name: fd(f, "name"),
      amount_minor: amount ?? 0,
      frequency: fd(f, "frequency") as Income["frequency"],
      anchor_date: fd(f, "anchor_date"),
      end_date: fd(f, "end_date") || null,
      subject_to_shocks: f.get("subject_to_shocks") === "on",
    };
    void run(
      () =>
        existing
          ? api(`/incomes/${existing.id}`, {
              method: "PATCH",
              body: { ...body, version: existing.version },
            })
          : api("/incomes", { method: "POST", body: { ...body, currency } }),
      !amount ? { amount_minor: "Enter an amount greater than zero" } : {},
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      {formError && <Alert>{formError}</Alert>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Source" error={errors.name}>
          {(p) => (
            <Input
              {...p}
              name="name"
              placeholder="Salary"
              defaultValue={existing?.name}
              required
              maxLength={100}
              autoFocus
            />
          )}
        </Field>
        <Field label={`Amount (${currency})`} error={errors.amount_minor}>
          {(p) => (
            <MoneyInput
              {...p}
              name="amount"
              currency={currency}
              defaultValue={existing ? minorToInput(existing.amount_minor, currency) : ""}
            />
          )}
        </Field>
      </div>
      <RecurrenceFields errors={errors} existing={existing} />
      <Checkbox
        name="subject_to_shocks"
        defaultChecked={existing?.subject_to_shocks ?? true}
        label="Could be delayed or stop"
        hint="Included in salary-delay and job-loss scenarios. Untick for very stable income like rent you receive."
      />
      <Actions busy={busy} onCancel={onCancel} editing={Boolean(existing)} />
    </form>
  );
}

export function ObligationForm({
  existing,
  baseCurrency,
  onSaved,
  onCancel,
}: FormProps<Obligation>) {
  const currency = existing?.currency ?? baseCurrency;
  const { errors, formError, busy, run } = useSubmit(onSaved);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const amount = parseToMinor(fd(f, "amount"), currency);
    const body = {
      name: fd(f, "name"),
      category: fd(f, "category") || "general",
      amount_minor: amount ?? 0,
      frequency: fd(f, "frequency") as Obligation["frequency"],
      anchor_date: fd(f, "anchor_date"),
      end_date: fd(f, "end_date") || null,
      essential: f.get("essential") === "on",
    };
    void run(
      () =>
        existing
          ? api(`/obligations/${existing.id}`, {
              method: "PATCH",
              body: { ...body, version: existing.version },
            })
          : api("/obligations", { method: "POST", body: { ...body, currency } }),
      !amount ? { amount_minor: "Enter an amount greater than zero" } : {},
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      {formError && <Alert>{formError}</Alert>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="What for" error={errors.name}>
          {(p) => (
            <Input
              {...p}
              name="name"
              placeholder="Rent"
              defaultValue={existing?.name}
              required
              maxLength={100}
              autoFocus
            />
          )}
        </Field>
        <Field label={`Amount (${currency})`} error={errors.amount_minor}>
          {(p) => (
            <MoneyInput
              {...p}
              name="amount"
              currency={currency}
              defaultValue={existing ? minorToInput(existing.amount_minor, currency) : ""}
            />
          )}
        </Field>
      </div>
      <Field
        label="Category"
        error={errors.category}
        hint="e.g. housing, utilities, loan, insurance"
      >
        {(p) => (
          <Input
            {...p}
            name="category"
            defaultValue={existing?.category ?? "general"}
            maxLength={50}
          />
        )}
      </Field>
      <RecurrenceFields errors={errors} existing={existing} />
      <Checkbox
        name="essential"
        defaultChecked={existing?.essential ?? true}
        label="Essential"
        hint="Essentials set the size of your emergency reserve and are always protected."
      />
      <Actions busy={busy} onCancel={onCancel} editing={Boolean(existing)} />
    </form>
  );
}

export function TransactionForm({
  existing,
  accounts,
  onSaved,
  onCancel,
}: Omit<FormProps<Transaction>, "baseCurrency"> & { accounts: Account[] }) {
  const [accountId, setAccountId] = useState(existing?.account_id ?? accounts[0]?.id ?? "");
  const currency = accounts.find((a) => a.id === accountId)?.currency ?? "INR";
  const { errors, formError, busy, run } = useSubmit(onSaved);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const amount = parseToMinor(fd(f, "amount"), currency);
    const body = {
      kind: fd(f, "kind") as Transaction["kind"],
      amount_minor: amount ?? 0,
      occurred_on: fd(f, "occurred_on"),
      category: fd(f, "category") || "general",
      description: fd(f, "description") || null,
    };
    void run(
      () =>
        existing
          ? api(`/transactions/${existing.id}`, {
              method: "PATCH",
              body: { ...body, version: existing.version },
            })
          : api("/transactions", { method: "POST", body: { ...body, account_id: accountId } }),
      !amount ? { amount_minor: "Enter an amount greater than zero" } : {},
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      {formError && <Alert>{formError}</Alert>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Account" error={errors.account_id}>
          {(p) => (
            <Select
              {...p}
              value={accountId}
              disabled={Boolean(existing)}
              onChange={(e) => setAccountId(e.target.value)}
              options={accounts.map((a) => ({ value: a.id, label: `${a.name} (${a.currency})` }))}
            />
          )}
        </Field>
        <Field label="Type" error={errors.kind}>
          {(p) => (
            <Select
              {...p}
              name="kind"
              defaultValue={existing?.kind ?? "expense"}
              options={[
                { value: "expense", label: "Money out" },
                { value: "income", label: "Money in" },
              ]}
            />
          )}
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Amount" error={errors.amount_minor}>
          {(p) => (
            <MoneyInput
              {...p}
              name="amount"
              currency={currency}
              defaultValue={existing ? minorToInput(existing.amount_minor, currency) : ""}
              autoFocus
            />
          )}
        </Field>
        <Field label="Date" error={errors.occurred_on}>
          {(p) => (
            <Input
              {...p}
              name="occurred_on"
              type="date"
              required
              defaultValue={existing?.occurred_on ?? todayIso()}
            />
          )}
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Category" error={errors.category}>
          {(p) => (
            <Input
              {...p}
              name="category"
              defaultValue={existing?.category ?? "general"}
              maxLength={50}
            />
          )}
        </Field>
        <Field label="Description" error={errors.description}>
          {(p) => (
            <Input
              {...p}
              name="description"
              defaultValue={existing?.description ?? ""}
              maxLength={500}
            />
          )}
        </Field>
      </div>
      <Actions busy={busy} onCancel={onCancel} editing={Boolean(existing)} />
    </form>
  );
}
