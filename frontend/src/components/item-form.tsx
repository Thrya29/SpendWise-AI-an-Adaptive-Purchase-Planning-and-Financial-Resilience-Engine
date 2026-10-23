"use client";

import { useRef, useState } from "react";

import { MoneyInput } from "@/components/money-input";
import { Alert, Button, Checkbox, Field, Input, Select, Textarea } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { DEADLINES, ITEM_KINDS, ITEM_STATUSES, TIERS, type Tier } from "@/lib/labels";
import { CURRENCIES, minorToInput, parseToMinor } from "@/lib/money";

type Item = Schemas["PlannedItemRead"];
type Draft = Schemas["ItemDraftOut"];

/** Initial field values, from a saved item or an assistant draft. */
export type ItemPrefill = Partial<
  Pick<
    Item,
    | "name" | "tier" | "kind" | "priority" | "estimated_price_minor" | "currency" | "quantity"
    | "target_date" | "deadline_type" | "lead_time_days" | "max_price_minor" | "url" | "location"
    | "notes"
    | "track_price"
  >
>; // prettier-ignore

function fromDraft(d: Draft): ItemPrefill {
  return {
    name: d.name,
    tier: d.tier,
    kind: d.kind,
    priority: d.priority,
    estimated_price_minor: d.estimated_price_minor ?? undefined,
    currency: d.currency,
    quantity: d.quantity,
    target_date: d.target_date,
    deadline_type: d.deadline_type,
    lead_time_days: d.lead_time_days,
    location: d.location,
  };
}

const PRIORITIES = [
  { value: "5", label: "5 — Critical" },
  { value: "4", label: "4 — High" },
  { value: "3", label: "3 — Medium" },
  { value: "2", label: "2 — Low" },
  { value: "1", label: "1 — Nice to have" },
];

export function ItemForm({
  item,
  draft,
  prefill,
  defaultTier,
  baseCurrency,
  onSaved,
  onCancel,
}: {
  item?: Item;
  draft?: Draft;
  prefill?: ItemPrefill;
  defaultTier?: Tier;
  baseCurrency: string;
  onSaved: (item: Item) => void;
  onCancel: () => void;
}) {
  const init: ItemPrefill | undefined = item ?? prefill ?? (draft ? fromDraft(draft) : undefined);
  const [currency, setCurrency] = useState(init?.currency ?? baseCurrency);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const priceRef = useRef<HTMLInputElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const [lookup, setLookup] = useState<{ tone: "success" | "warning"; text: string } | null>(null);
  const [looking, setLooking] = useState(false);

  async function priceFromLink() {
    const url = urlRef.current?.value.trim();
    if (!url) {
      setLookup({ tone: "warning", text: "Paste a product link first." });
      return;
    }
    setLooking(true);
    setLookup(null);
    try {
      const preview = await api<Schemas["PreviewOut"]>("/market/preview", {
        method: "POST",
        body: { url },
      });
      if (!preview.found || preview.price_minor == null || !preview.currency) {
        setLookup({ tone: "warning", text: preview.message });
        return;
      }
      if (preview.currency !== currency && item) {
        setLookup({
          tone: "warning",
          text: `The page lists the price in ${preview.currency}, but this item is in ${currency}.`,
        });
        return;
      }
      if (preview.currency !== currency) setCurrency(preview.currency);
      if (priceRef.current)
        priceRef.current.value = minorToInput(preview.price_minor, preview.currency);
      if (nameRef.current && !nameRef.current.value.trim() && preview.title) {
        nameRef.current.value = preview.title.slice(0, 200);
      }
      const stock =
        preview.availability === "out_of_stock"
          ? " Currently out of stock."
          : preview.availability === "in_stock"
            ? " In stock."
            : "";
      setLookup({ tone: "success", text: `${preview.message}${stock} Check it before saving.` });
    } catch (err) {
      setLookup({
        tone: "warning",
        text: err instanceof ApiError ? err.message : "Could not read that link.",
      });
    } finally {
      setLooking(false);
    }
  }

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
      track_price: f.get("track_price") === "on",
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
          <Input
            {...p}
            ref={nameRef}
            name="name"
            defaultValue={init?.name}
            required
            maxLength={200}
            autoFocus
          />
        )}
      </Field>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Category" error={errors.tier}>
          {(p) => (
            <Select
              {...p}
              name="tier"
              defaultValue={init?.tier ?? defaultTier ?? "want"}
              options={TIERS.map((t) => ({ value: t.value, label: t.label.replace(/s$/, "") }))}
            />
          )}
        </Field>
        <Field label="Type" error={errors.kind}>
          {(p) => (
            <Select
              {...p}
              name="kind"
              defaultValue={init?.kind ?? "product"}
              options={ITEM_KINDS}
            />
          )}
        </Field>
        <Field label="Priority" error={errors.priority}>
          {(p) => (
            <Select
              {...p}
              name="priority"
              defaultValue={String(init?.priority ?? 3)}
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
              ref={priceRef}
              name="price"
              currency={currency}
              defaultValue={
                init?.estimated_price_minor != null
                  ? minorToInput(init.estimated_price_minor, currency)
                  : ""
              }
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
              defaultValue={init?.quantity ?? 1}
            />
          )}
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Target date" error={errors.target_date} hint="When you aim to have it">
          {(p) => (
            <Input {...p} name="target_date" type="date" defaultValue={init?.target_date ?? ""} />
          )}
        </Field>
        <Field label="Deadline" error={errors.deadline_type}>
          {(p) => (
            <Select
              {...p}
              name="deadline_type"
              defaultValue={init?.deadline_type ?? "soft"}
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
              defaultValue={init?.lead_time_days ?? 0}
            />
          )}
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Product or booking link" error={errors.url} hint="Optional">
          {(p) => (
            <Input
              {...p}
              ref={urlRef}
              name="url"
              type="url"
              inputMode="url"
              placeholder="https://"
              defaultValue={init?.url ?? ""}
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
                init?.max_price_minor != null ? minorToInput(init.max_price_minor, currency) : ""
              }
            />
          )}
        </Field>
      </div>

      <div className="flex flex-col gap-3 rounded-lg bg-surface-muted p-3">
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => void priceFromLink()}
            loading={looking}
          >
            Get price from link
          </Button>
          <Checkbox
            name="track_price"
            defaultChecked={init?.track_price ?? false}
            label="Track this price"
            hint="Re-check the link twice a day, update the price and alert you to drops"
          />
        </div>
        {lookup && <Alert tone={lookup.tone}>{lookup.text}</Alert>}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Location or provider"
          error={errors.location}
          hint="e.g. a local salon, a city"
        >
          {(p) => (
            <Input {...p} name="location" maxLength={200} defaultValue={init?.location ?? ""} />
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
        {(p) => <Textarea {...p} name="notes" maxLength={5000} defaultValue={init?.notes ?? ""} />}
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
