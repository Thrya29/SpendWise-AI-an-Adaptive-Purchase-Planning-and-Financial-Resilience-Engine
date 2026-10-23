"use client";

import { useState } from "react";

import { MoneyInput } from "@/components/money-input";
import { Alert, Button, Field, Input, Select, Textarea } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { DEADLINES, ITEM_KINDS, ITEM_STATUSES, TIERS, type Tier } from "@/lib/labels";
import { CURRENCIES, minorToInput, parseToMinor } from "@/lib/money";

type Item = Schemas["PlannedItemRead"];

const PRIORITIES = [
  { value: "5", label: "5 — Critical" },
  { value: "4", label: "4 — High" },
  { value: "3", label: "3 — Medium" },
  { value: "2", label: "2 — Low" },
  { value: "1", label: "1 — Nice to have" },
];

export function ItemForm({
  item,
  defaultTier,
  baseCurrency,
  onSaved,
  onCancel,
}: {
  item?: Item;
  defaultTier?: Tier;
  baseCurrency: string;
  onSaved: (item: Item) => void;
  onCancel: () => void;
}) {
  const [currency, setCurrency] = useState(item?.currency ?? baseCurrency);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const str = (k: string) => String(f.get(k) ?? "").trim();
    const price = parseToMinor(str("price"), currency);
    const maxPrice = str("max_price") ? parseToMinor(str("max_price"), currency) : null;
    const local: Record<string, string> = {};
    if (price === null) local.estimated_price_minor = "Enter a valid amount, e.g. 1499.50";
    if (str("max_price") && maxPrice === null) local.max_price_minor = "Enter a valid amount";
    if (Object.keys(local).length) {
      setErrors(local);
      return;
    }

    const body = {
      name: str("name"),
      tier: str("tier") as Tier,
      kind: str("kind") as Item["kind"],
      priority: Number(str("priority")),
      estimated_price_minor: price!,
      quantity: Number(str("quantity") || "1"),
      target_date: str("target_date") || null,
      deadline_type: str("deadline_type") as Item["deadline_type"],
      lead_time_days: Number(str("lead_time_days") || "0"),
      max_price_minor: maxPrice,
      url: str("url") || null,
      location: str("location") || null,
      notes: str("notes") || null,
    };

    setBusy(true);
    setErrors({});
    setFormError(null);
    try {
      const saved = item
        ? await api<Item>(`/items/${item.id}`, {
            method: "PATCH",
            body: { ...body, status: str("status") as Item["status"], version: item.version },
          })
        : await api<Item>("/items", { method: "POST", body: { ...body, currency } });
      onSaved(saved);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldMessages());
        setFormError(
          err.status === 409
            ? "This item was changed in another tab. Close and reopen it to get the latest version."
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

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      {formError && <Alert>{formError}</Alert>}
      <Field
        label="What is it?"
        error={errors.name}
        hint="A product, a service like a salon visit, a trip…"
      >
        {(p) => (
          <Input {...p} name="name" defaultValue={item?.name} required maxLength={200} autoFocus />
        )}
      </Field>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Category" error={errors.tier}>
          {(p) => (
            <Select
              {...p}
              name="tier"
              defaultValue={item?.tier ?? defaultTier ?? "want"}
              options={TIERS.map((t) => ({ value: t.value, label: t.label.replace(/s$/, "") }))}
            />
          )}
        </Field>
        <Field label="Type" error={errors.kind}>
          {(p) => (
            <Select
              {...p}
              name="kind"
              defaultValue={item?.kind ?? "product"}
              options={ITEM_KINDS}
            />
          )}
        </Field>
        <Field label="Priority" error={errors.priority}>
          {(p) => (
            <Select
              {...p}
              name="priority"
              defaultValue={String(item?.priority ?? 3)}
              options={PRIORITIES}
            />
          )}
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-[1fr_8rem_6rem]">
        <Field label="Estimated price (each)" error={errors.estimated_price_minor}>
          {(p) => (
            <MoneyInput
              {...p}
              name="price"
              currency={currency}
              defaultValue={item ? minorToInput(item.estimated_price_minor, item.currency) : ""}
              required
            />
          )}
        </Field>
        <Field label="Currency" error={errors.currency}>
          {(p) => (
            <Select
              {...p}
              value={currency}
              disabled={Boolean(item)}
              onChange={(e) => setCurrency(e.target.value)}
              options={CURRENCIES.map((c) => ({ value: c, label: c }))}
            />
          )}
        </Field>
        <Field label="Qty" error={errors.quantity}>
          {(p) => (
            <Input
              {...p}
              name="quantity"
              type="number"
              min={1}
              max={1000}
              defaultValue={item?.quantity ?? 1}
            />
          )}
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Target date" error={errors.target_date} hint="When you aim to have it">
          {(p) => (
            <Input {...p} name="target_date" type="date" defaultValue={item?.target_date ?? ""} />
          )}
        </Field>
        <Field label="Deadline" error={errors.deadline_type}>
          {(p) => (
            <Select
              {...p}
              name="deadline_type"
              defaultValue={item?.deadline_type ?? "soft"}
              options={DEADLINES.map((d) => ({ value: d.value, label: `${d.label} — ${d.hint}` }))}
            />
          )}
        </Field>
        <Field
          label="Lead time (days)"
          error={errors.lead_time_days}
          hint="Delivery or booking time"
        >
          {(p) => (
            <Input
              {...p}
              name="lead_time_days"
              type="number"
              min={0}
              max={365}
              defaultValue={item?.lead_time_days ?? 0}
            />
          )}
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Product or booking link" error={errors.url} hint="Optional">
          {(p) => (
            <Input
              {...p}
              name="url"
              type="url"
              inputMode="url"
              placeholder="https://"
              defaultValue={item?.url ?? ""}
            />
          )}
        </Field>
        <Field
          label="Maximum you would pay"
          error={errors.max_price_minor}
          hint="Optional price ceiling"
        >
          {(p) => (
            <MoneyInput
              {...p}
              name="max_price"
              currency={currency}
              defaultValue={
                item?.max_price_minor != null
                  ? minorToInput(item.max_price_minor, item.currency)
                  : ""
              }
            />
          )}
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Location or provider"
          error={errors.location}
          hint="e.g. a local salon, a city"
        >
          {(p) => (
            <Input {...p} name="location" maxLength={200} defaultValue={item?.location ?? ""} />
          )}
        </Field>
        {item && (
          <Field label="Status" error={errors.status}>
            {(p) => (
              <Select {...p} name="status" defaultValue={item.status} options={ITEM_STATUSES} />
            )}
          </Field>
        )}
      </div>

      <Field label="Notes" error={errors.notes}>
        {(p) => <Textarea {...p} name="notes" maxLength={5000} defaultValue={item?.notes ?? ""} />}
      </Field>

      <div className="mt-2 flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" loading={busy}>
          {item ? "Save changes" : "Add item"}
        </Button>
      </div>
    </form>
  );
}
