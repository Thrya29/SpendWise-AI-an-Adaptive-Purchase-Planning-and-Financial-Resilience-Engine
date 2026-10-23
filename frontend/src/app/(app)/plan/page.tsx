"use client";

import { useState } from "react";

import { ItemForm } from "@/components/item-form";
import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  cx,
  Dialog,
  EmptyState,
  LoadingBlock,
  PageHeader,
  Select,
} from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { useUser } from "@/lib/auth";
import {
  DEADLINES,
  formatDate,
  ITEM_KINDS,
  ITEM_STATUSES,
  labelOf,
  TIERS,
  type ItemStatus,
  type Tier,
} from "@/lib/labels";
import { formatMoney } from "@/lib/money";
import { useResource } from "@/lib/use-resource";

type Item = Schemas["PlannedItemRead"];
type Page = Schemas["Page_PlannedItemRead_"];

const STATUS_TONE: Record<ItemStatus, "brand" | "success" | "warning" | "neutral"> = {
  planned: "brand",
  purchased: "success",
  postponed: "warning",
  dropped: "neutral",
};

export default function PlanPage() {
  const user = useUser();
  const [tier, setTier] = useState<Tier | "all">("all");
  const [status, setStatus] = useState<ItemStatus | "">("planned");
  const [editing, setEditing] = useState<Item | "new" | null>(null);
  const [deleting, setDeleting] = useState<Item | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const query = {
    tier: tier === "all" ? undefined : tier,
    status: status || undefined,
    limit: 200,
  };
  const items = useResource<Page>(`items:${tier}:${status}`, (signal) =>
    api<Page>("/items", { query, signal }),
  );

  async function quickUpdate(item: Item, changes: Partial<Schemas["PlannedItemUpdate"]>) {
    setBusyId(item.id);
    setActionError(null);
    try {
      await api<Item>(`/items/${item.id}`, {
        method: "PATCH",
        body: { ...changes, version: item.version },
      });
      await items.reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Update failed");
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    setBusyId(deleting.id);
    try {
      await api<null>(`/items/${deleting.id}`, { method: "DELETE" });
      setDeleting(null);
      await items.reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Delete failed");
      setDeleting(null);
    } finally {
      setBusyId(null);
    }
  }

  const list = items.data?.items ?? [];
  const totals = new Map<string, number>();
  for (const it of list) {
    totals.set(
      it.currency,
      (totals.get(it.currency) ?? 0) + it.estimated_price_minor * it.quantity,
    );
  }

  return (
    <>
      <PageHeader
        title="Needs, wants & desires"
        description="Everything you plan to spend on — products, services, travel or experiences."
        actions={<Button onClick={() => setEditing("new")}>Add item</Button>}
      />

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div
          role="tablist"
          aria-label="Category"
          className="flex gap-1 rounded-lg bg-surface-muted p-1"
        >
          {[{ value: "all" as const, label: "All" }, ...TIERS].map((t) => (
            <button
              key={t.value}
              role="tab"
              aria-selected={tier === t.value}
              onClick={() => setTier(t.value)}
              className={cx(
                "rounded-md px-3 py-1.5 text-sm font-medium",
                tier === t.value ? "bg-surface text-text shadow-sm" : "text-muted hover:text-text",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3">
          {[...totals].map(([cur, total]) => (
            <span key={cur} className="text-sm text-muted tabular">
              Total {formatMoney(total, cur)}
            </span>
          ))}
          <Select
            aria-label="Status filter"
            value={status}
            onChange={(e) => setStatus(e.target.value as ItemStatus | "")}
            className="w-40"
            options={[{ value: "", label: "Any status" }, ...ITEM_STATUSES]}
          />
        </div>
      </div>

      {actionError && (
        <div className="mb-4">
          <Alert>{actionError}</Alert>
        </div>
      )}

      {items.loading && !items.data ? (
        <LoadingBlock />
      ) : items.error ? (
        <Alert title="Could not load your items">{items.error.message}</Alert>
      ) : list.length === 0 ? (
        <EmptyState
          title="Nothing here yet"
          description="Add a laptop you need for work, a salon visit, a trip — anything you plan to spend on. SpendWise will check it against your cash flow."
          action={<Button onClick={() => setEditing("new")}>Add your first item</Button>}
        />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {list.map((item) => (
            <li
              key={item.id}
              className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={item.tier}>{labelOf(TIERS, item.tier).replace(/s$/, "")}</Badge>
                    <Badge tone={STATUS_TONE[item.status]}>
                      {labelOf(ITEM_STATUSES, item.status)}
                    </Badge>
                    <span className="text-xs text-muted">
                      {labelOf(ITEM_KINDS, item.kind).split(" (")[0]}
                    </span>
                  </div>
                  <h3 className="mt-1.5 truncate font-semibold" title={item.name}>
                    {item.name}
                  </h3>
                </div>
                <div className="text-right">
                  <p className="font-semibold tabular">
                    {formatMoney(item.estimated_price_minor * item.quantity, item.currency)}
                  </p>
                  {item.quantity > 1 && (
                    <p className="text-xs text-muted tabular">
                      {item.quantity} × {formatMoney(item.estimated_price_minor, item.currency)}
                    </p>
                  )}
                  <p className="text-xs text-muted">
                    {item.price_source === "user" ? "Your estimate" : item.price_source}
                  </p>
                </div>
              </div>

              <dl className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <dt className="text-muted">Target</dt>
                  <dd className="font-medium">{formatDate(item.target_date)}</dd>
                </div>
                <div>
                  <dt className="text-muted">Deadline</dt>
                  <dd className="font-medium">{labelOf(DEADLINES, item.deadline_type)}</dd>
                </div>
                <div>
                  <dt className="text-muted">Priority</dt>
                  <dd className="font-medium" aria-label={`Priority ${item.priority} of 5`}>
                    {"●".repeat(item.priority)}
                    <span className="text-border">{"●".repeat(5 - item.priority)}</span>
                  </dd>
                </div>
              </dl>

              {(item.url || item.location) && (
                <p className="truncate text-xs text-muted">
                  {item.location}
                  {item.url && item.location && " · "}
                  {item.url && (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      className="text-brand hover:underline"
                    >
                      {new URL(item.url).hostname}
                    </a>
                  )}
                </p>
              )}

              <div className="mt-auto flex flex-wrap gap-2 border-t border-border pt-3">
                <Button size="sm" variant="secondary" onClick={() => setEditing(item)}>
                  Edit
                </Button>
                {item.status === "planned" && (
                  <>
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={busyId === item.id}
                      onClick={() => void quickUpdate(item, { status: "purchased" })}
                    >
                      Mark purchased
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busyId === item.id}
                      onClick={() => void quickUpdate(item, { status: "postponed" })}
                    >
                      Postpone
                    </Button>
                  </>
                )}
                {item.status !== "planned" && (
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={busyId === item.id}
                    onClick={() => void quickUpdate(item, { status: "planned" })}
                  >
                    Move back to planned
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto text-danger"
                  onClick={() => setDeleting(item)}
                >
                  Delete
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "Add a need, want or desire" : "Edit item"}
        wide
      >
        {editing !== null && (
          <ItemForm
            item={editing === "new" ? undefined : editing}
            defaultTier={tier === "all" ? undefined : tier}
            baseCurrency={user.base_currency}
            onCancel={() => setEditing(null)}
            onSaved={() => {
              setEditing(null);
              void items.reload();
            }}
          />
        )}
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        title="Delete item?"
        message={
          <>
            <strong className="text-text">{deleting?.name}</strong> will be removed permanently. To
            keep it for later, postpone it instead.
          </>
        }
        busy={busyId === deleting?.id}
        onConfirm={() => void confirmDelete()}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
