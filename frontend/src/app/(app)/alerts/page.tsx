"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert, Badge, Button, EmptyState, LoadingBlock, PageHeader } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { timeAgo } from "@/lib/market";
import { useResource } from "@/lib/use-resource";

type AlertRow = Schemas["AlertOut"];

const KIND: Record<AlertRow["kind"], { label: string; tone: "success" | "brand" | "warning" }> = {
  price_target: { label: "Within your limit", tone: "success" },
  price_drop: { label: "Price drop", tone: "brand" },
  back_in_stock: { label: "Back in stock", tone: "brand" },
  check_failing: { label: "Check failing", tone: "warning" },
};

function notifyBell() {
  window.dispatchEvent(new Event("spendwise:alerts-changed"));
}

export default function AlertsPage() {
  const alerts = useResource<AlertRow[]>("alerts", (signal) =>
    api<AlertRow[]>("/alerts", { query: { limit: 100 }, signal }),
  );
  const [error, setError] = useState<string | null>(null);

  async function act(path: string) {
    setError(null);
    try {
      await api<null>(path, { method: "POST" });
      await alerts.reload();
      notifyBell();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  const rows = alerts.data ?? [];
  const unread = rows.filter((a) => !a.read_at).length;

  return (
    <>
      <PageHeader
        title="Alerts"
        description="Price drops, prices within your limit, and checks that need your attention."
        actions={
          unread > 0 ? (
            <Button variant="secondary" onClick={() => void act("/alerts/read-all")}>
              Mark all as read
            </Button>
          ) : undefined
        }
      />
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}
      {alerts.loading && !alerts.data ? (
        <LoadingBlock />
      ) : alerts.error ? (
        <Alert>{alerts.error.message}</Alert>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No alerts yet"
          description="Turn on “Track this price” for an item with a product link, and set the most you would pay. You will be alerted when it drops."
          action={
            <Link href="/plan" className="text-sm font-medium text-brand hover:underline">
              Go to your items
            </Link>
          }
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map((a) => (
            <li
              key={a.id}
              className={`rounded-xl border bg-surface p-4 ${a.read_at ? "border-border" : "border-brand"}`}
            >
              <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={KIND[a.kind].tone}>{KIND[a.kind].label}</Badge>
                    {!a.read_at && <span className="text-xs font-medium text-brand">New</span>}
                    <span className="text-xs text-muted">{timeAgo(a.created_at)}</span>
                  </div>
                  <p className="mt-1.5 font-medium">{a.title}</p>
                  <p className="text-sm text-muted">{a.body}</p>
                </div>
                {!a.read_at && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void act(`/alerts/${a.id}/read`)}
                  >
                    Mark as read
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
