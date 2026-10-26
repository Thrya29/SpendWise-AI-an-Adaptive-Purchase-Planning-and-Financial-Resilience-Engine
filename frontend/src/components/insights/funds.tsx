"use client";

import { useState } from "react";

import { Alert, Badge, Button, Card, EmptyState, Input, LoadingBlock } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { formatDate } from "@/lib/labels";
import { type Resource } from "@/lib/use-resource";

type Fund = Schemas["FundOut"];
type Detail = Schemas["FundDetailOut"];

function FundRow({ f, action }: { f: Fund; action: React.ReactNode }) {
  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium" title={f.name}>
          {f.name}
        </p>
        <p className="text-xs text-muted">
          {f.fund_house} · code {f.scheme_code}
          {f.isin ? ` · ${f.isin}` : ""}
          {!f.active && " · not currently priced"}
        </p>
      </div>
      <div className="text-right text-sm">
        <p className="font-semibold tabular">{f.nav ?? "—"}</p>
        <p className="text-xs text-muted">NAV {formatDate(f.nav_date)}</p>
      </div>
      {action}
    </li>
  );
}

export function FundsCard({
  watchlist,
  onSimulate,
}: {
  watchlist: Resource<Fund[]>;
  onSimulate: (code: number) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Fund[] | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  const search = (e: React.FormEvent) => {
    e.preventDefault();
    if (q.trim().length < 3) return;
    void act("search", async () =>
      setResults(await api<Fund[]>("/funds/search", { query: { q } })),
    );
  };
  const watch = (code: number) =>
    act(`w${code}`, async () => {
      await api("/funds/watchlist", { method: "POST", body: { scheme_code: code } });
      await watchlist.reload();
    });
  const unwatch = (code: number) =>
    act(`u${code}`, async () => {
      await api(`/funds/watchlist/${code}`, { method: "DELETE" });
      setDetail(null);
      await watchlist.reload();
    });
  const open = (code: number) =>
    act(`d${code}`, async () => setDetail(await api<Detail>(`/funds/${code}`)));

  const watched = new Set((watchlist.data ?? []).map((f) => f.scheme_code));

  return (
    <Card
      title="Mutual funds you are following"
      description="Official daily NAVs from AMFI. Facts about funds you choose — no fund is recommended."
    >
      {error && (
        <div className="mb-3">
          <Alert>{error}</Alert>
        </div>
      )}
      <form onSubmit={search} className="flex gap-2">
        <Input
          aria-label="Search funds"
          placeholder="Search by name, e.g. nifty 50 index direct growth"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Button type="submit" variant="secondary" loading={busy === "search"}>
          Search
        </Button>
      </form>
      {results && (
        <ul className="mt-2 max-h-72 divide-y divide-border overflow-y-auto">
          {results.length === 0 && (
            <li className="py-3 text-sm text-muted">No currently priced funds match.</li>
          )}
          {results.map((f) => (
            <FundRow
              key={f.scheme_code}
              f={f}
              action={
                watched.has(f.scheme_code) ? (
                  <Badge tone="brand">Following</Badge>
                ) : (
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy === `w${f.scheme_code}`}
                    onClick={() => void watch(f.scheme_code)}
                  >
                    Follow
                  </Button>
                )
              }
            />
          ))}
        </ul>
      )}

      <h3 className="mt-5 text-sm font-semibold">Following</h3>
      {watchlist.loading && !watchlist.data ? (
        <LoadingBlock />
      ) : (watchlist.data ?? []).length === 0 ? (
        <EmptyState
          title="Not following any funds"
          description="Search above to follow a fund and see how it has behaved."
        />
      ) : (
        <ul className="divide-y divide-border">
          {(watchlist.data ?? []).map((f) => (
            <FundRow
              key={f.scheme_code}
              f={f}
              action={
                <Button
                  size="sm"
                  variant="ghost"
                  loading={busy === `d${f.scheme_code}`}
                  onClick={() => void open(f.scheme_code)}
                >
                  Details
                </Button>
              }
            />
          ))}
        </ul>
      )}

      {detail && (
        <div className="mt-4 rounded-lg border border-border p-4">
          <p className="font-semibold">{detail.name}</p>
          <p className="text-xs text-muted">{detail.category}</p>
          {detail.history_points > 0 ? (
            <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              {(["1y", "3y", "5y"] as const).map((k) => (
                <div key={k}>
                  <dt className="text-xs text-muted">{k} return a year</dt>
                  <dd className="font-semibold tabular">
                    {detail.cagr_percent[k] != null ? `${detail.cagr_percent[k]}%` : "—"}
                  </dd>
                </div>
              ))}
              <div>
                <dt className="text-xs text-muted">Volatility (1y)</dt>
                <dd className="font-semibold tabular">
                  {detail.volatility_percent != null ? `${detail.volatility_percent}%` : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">
                  Worst fall since {formatDate(detail.history_from)}
                </dt>
                <dd className="font-semibold tabular">
                  {detail.max_drawdown_percent != null ? `−${detail.max_drawdown_percent}%` : "—"}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="mt-2 text-sm text-muted">Historical data is not available right now.</p>
          )}
          <p className="mt-3 text-xs text-muted">
            NAV: {detail.source}
            {detail.history_source ? ` · History: ${detail.history_source}` : ""}.{" "}
            {detail.disclaimer}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => onSimulate(detail.scheme_code)}>
              Use in the simulator
            </Button>
            <Button
              size="sm"
              variant="ghost"
              loading={busy === `u${detail.scheme_code}`}
              onClick={() => void unwatch(detail.scheme_code)}
            >
              Stop following
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
