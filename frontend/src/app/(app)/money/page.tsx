"use client";

import { useState } from "react";

import {
  AccountForm,
  IncomeForm,
  ObligationForm,
  TransactionForm,
  type Account,
  type Income,
  type Obligation,
  type Transaction,
} from "@/components/money-forms";
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Dialog,
  EmptyState,
  LoadingBlock,
  PageHeader,
} from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { useUser } from "@/lib/auth";
import { ACCOUNT_KINDS, formatDate, FREQUENCIES, labelOf } from "@/lib/labels";
import { approxConvert } from "@/lib/market";
import { formatMoney, minorExponent } from "@/lib/money";
import { useResource, type Resource } from "@/lib/use-resource";

type Entity = "accounts" | "incomes" | "obligations" | "transactions";
type Editing =
  | { entity: "accounts"; row?: Account }
  | { entity: "incomes"; row?: Income }
  | { entity: "obligations"; row?: Obligation }
  | { entity: "transactions"; row?: Transaction };

const TITLES: Record<Entity, string> = {
  accounts: "account",
  incomes: "income",
  obligations: "recurring expense",
  transactions: "transaction",
};

function useList<T>(entity: Entity) {
  return useResource<{ items: T[]; total: number }>(entity, (signal) =>
    api(`/${entity}`, { query: { limit: 200 }, signal }),
  );
}

function RowActions({ onEdit, onDelete }: { onEdit: () => void; onDelete: () => void }) {
  return (
    <div className="flex shrink-0 gap-1">
      <Button size="sm" variant="ghost" onClick={onEdit}>
        Edit
      </Button>
      <Button size="sm" variant="ghost" className="text-danger" onClick={onDelete}>
        Delete
      </Button>
    </div>
  );
}

function ListBody<T>({
  res,
  empty,
  render,
}: {
  res: Resource<{ items: T[]; total: number }>;
  empty: string;
  render: (row: T) => React.ReactNode;
}) {
  if (res.loading && !res.data) return <LoadingBlock />;
  if (res.error) return <Alert>{res.error.message}</Alert>;
  const rows = res.data?.items ?? [];
  if (!rows.length) return <EmptyState title={empty} />;
  return <ul className="divide-y divide-border">{rows.map(render)}</ul>;
}

export default function MoneyPage() {
  const user = useUser();
  const accounts = useList<Account>("accounts");
  const fx = useResource<Schemas["FxOut"]>("fx", (signal) => api("/fx/latest", { signal }));
  const [refreshingFx, setRefreshingFx] = useState(false);

  async function refreshFx() {
    setRefreshingFx(true);
    setError(null);
    try {
      await api("/fx/refresh", { method: "POST" });
      await fx.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not refresh exchange rates.");
    } finally {
      setRefreshingFx(false);
    }
  }

  function inBase(minor: number, currency: string): string | null {
    const rate = fx.data?.available ? fx.data.rates?.[currency] : undefined;
    if (currency === user.base_currency || rate === undefined) return null;
    const value = approxConvert(
      minor,
      minorExponent(currency),
      minorExponent(user.base_currency),
      String(rate),
    );
    return `≈ ${formatMoney(value, user.base_currency)}`;
  }
  const incomes = useList<Income>("incomes");
  const obligations = useList<Obligation>("obligations");
  const transactions = useList<Transaction>("transactions");
  const [editing, setEditing] = useState<Editing | null>(null);
  const [deleting, setDeleting] = useState<{ entity: Entity; id: string; name: string } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resources: Record<Entity, Resource<unknown>> = {
    accounts,
    incomes,
    obligations,
    transactions,
  };
  const reload = (entity: Entity) => {
    void resources[entity].reload();
    if (entity === "transactions") void accounts.reload(); // balances change
  };

  async function confirmDelete() {
    if (!deleting) return;
    setBusy(true);
    try {
      await api<null>(`/${deleting.entity}/${deleting.id}`, { method: "DELETE" });
      reload(deleting.entity);
      if (deleting.entity === "accounts") void transactions.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    } finally {
      setBusy(false);
      setDeleting(null);
    }
  }

  const accountList = accounts.data?.items ?? [];
  const accountName = new Map(accountList.map((a) => [a.id, a.name]));
  const close = () => setEditing(null);
  const saved = () => {
    if (editing) reload(editing.entity);
    setEditing(null);
  };

  return (
    <>
      <PageHeader
        title="Money"
        description="Your balances, income and recurring commitments. Planning uses this to keep you safe."
      />
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      <div className="mb-6 flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-sm">
        <span className="font-medium">Exchange rates</span>
        <span className="text-muted">
          {fx.data?.available && fx.data.as_of
            ? `${fx.data.source} · ${formatDate(fx.data.as_of)}. Other currencies are converted to ${user.base_currency} for planning.`
            : `No recent rates. Amounts in other currencies are left out of planning until rates are available.`}
        </span>
        <Button
          size="sm"
          variant="secondary"
          className="ml-auto"
          loading={refreshingFx}
          onClick={() => void refreshFx()}
        >
          Refresh rates
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card
          title="Accounts"
          description="Where your money is kept"
          actions={
            <Button size="sm" onClick={() => setEditing({ entity: "accounts" })}>
              Add account
            </Button>
          }
        >
          <ListBody<Account>
            res={accounts}
            empty="Add your bank account, savings or cash."
            render={(a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="truncate font-medium">{a.name}</p>
                  <p className="text-xs text-muted">
                    {labelOf(ACCOUNT_KINDS, a.kind)}
                    {!a.include_in_planning && " · excluded from planning"}
                  </p>
                </div>
                <div className="ml-auto text-right">
                  <p className="font-semibold tabular">
                    {formatMoney(a.balance_minor ?? 0, a.currency)}
                  </p>
                  {inBase(a.balance_minor ?? 0, a.currency) && (
                    <p className="text-xs text-muted tabular">
                      {inBase(a.balance_minor ?? 0, a.currency)}
                    </p>
                  )}
                </div>
                <RowActions
                  onEdit={() => setEditing({ entity: "accounts", row: a })}
                  onDelete={() => setDeleting({ entity: "accounts", id: a.id, name: a.name })}
                />
              </li>
            )}
          />
        </Card>

        <Card
          title="Income"
          description="Salary and other money coming in"
          actions={
            <Button size="sm" onClick={() => setEditing({ entity: "incomes" })}>
              Add income
            </Button>
          }
        >
          <ListBody<Income>
            res={incomes}
            empty="Add your salary so SpendWise can plan around pay day."
            render={(i) => (
              <li key={i.id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="truncate font-medium">{i.name}</p>
                  <p className="text-xs text-muted">
                    {labelOf(FREQUENCIES, i.frequency)} from {formatDate(i.anchor_date)}
                    {i.subject_to_shocks && " · can be delayed"}
                  </p>
                </div>
                <p className="ml-auto font-semibold text-success tabular">
                  {formatMoney(i.amount_minor, i.currency)}
                </p>
                <RowActions
                  onEdit={() => setEditing({ entity: "incomes", row: i })}
                  onDelete={() => setDeleting({ entity: "incomes", id: i.id, name: i.name })}
                />
              </li>
            )}
          />
        </Card>

        <Card
          title="Recurring expenses"
          description="Rent, bills, EMIs, subscriptions"
          actions={
            <Button size="sm" onClick={() => setEditing({ entity: "obligations" })}>
              Add expense
            </Button>
          }
        >
          <ListBody<Obligation>
            res={obligations}
            empty="Add rent and bills — essentials define your emergency reserve."
            render={(o) => (
              <li key={o.id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="flex items-center gap-2 truncate font-medium">
                    {o.name} {o.essential && <Badge tone="brand">Essential</Badge>}
                  </p>
                  <p className="text-xs text-muted">
                    {labelOf(FREQUENCIES, o.frequency)} · {o.category}
                  </p>
                </div>
                <p className="ml-auto font-semibold tabular">
                  {formatMoney(o.amount_minor, o.currency)}
                </p>
                <RowActions
                  onEdit={() => setEditing({ entity: "obligations", row: o })}
                  onDelete={() => setDeleting({ entity: "obligations", id: o.id, name: o.name })}
                />
              </li>
            )}
          />
        </Card>

        <Card
          title="Recent transactions"
          description="One-off money in and out"
          actions={
            <Button
              size="sm"
              disabled={!accountList.length}
              title={accountList.length ? undefined : "Add an account first"}
              onClick={() => setEditing({ entity: "transactions" })}
            >
              Add transaction
            </Button>
          }
        >
          <ListBody<Transaction>
            res={transactions}
            empty="Record one-off spending or income here."
            render={(t) => (
              <li key={t.id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="truncate font-medium">{t.description || t.category}</p>
                  <p className="text-xs text-muted">
                    {formatDate(t.occurred_on)} · {accountName.get(t.account_id) ?? "Account"}
                  </p>
                </div>
                <p
                  className={`ml-auto font-semibold tabular ${t.kind === "income" ? "text-success" : ""}`}
                >
                  {t.kind === "income" ? "+" : "−"}
                  {formatMoney(t.amount_minor, t.currency)}
                </p>
                <RowActions
                  onEdit={() => setEditing({ entity: "transactions", row: t })}
                  onDelete={() =>
                    setDeleting({
                      entity: "transactions",
                      id: t.id,
                      name: t.description || t.category,
                    })
                  }
                />
              </li>
            )}
          />
        </Card>
      </div>

      <Dialog
        open={editing !== null}
        onClose={close}
        title={editing ? `${editing.row ? "Edit" : "Add"} ${TITLES[editing.entity]}` : ""}
      >
        {editing?.entity === "accounts" && (
          <AccountForm
            existing={editing.row}
            baseCurrency={user.base_currency}
            onSaved={saved}
            onCancel={close}
          />
        )}
        {editing?.entity === "incomes" && (
          <IncomeForm
            existing={editing.row}
            baseCurrency={user.base_currency}
            onSaved={saved}
            onCancel={close}
          />
        )}
        {editing?.entity === "obligations" && (
          <ObligationForm
            existing={editing.row}
            baseCurrency={user.base_currency}
            onSaved={saved}
            onCancel={close}
          />
        )}
        {editing?.entity === "transactions" && (
          <TransactionForm
            existing={editing.row}
            accounts={accountList}
            onSaved={saved}
            onCancel={close}
          />
        )}
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting ? TITLES[deleting.entity] : ""}?`}
        message={
          <>
            <strong className="text-text">{deleting?.name}</strong> will be removed permanently.
            {deleting?.entity === "accounts" &&
              " All transactions in this account are deleted too."}
          </>
        }
        busy={busy}
        onConfirm={() => void confirmDelete()}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
