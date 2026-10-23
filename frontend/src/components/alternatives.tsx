"use client";

import { useState } from "react";

import { Alert, Badge, Button, Select } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { formatMoney } from "@/lib/money";
import { useResource } from "@/lib/use-resource";

type Item = Schemas["PlannedItemRead"];
type Suggestion = Schemas["AlternativeSuggestion"];

/**
 * Manage an item's alternatives group (the planner buys at most one of a group), and look
 * up current alternatives on the web. Suggestions open the item form without a price.
 */
export function Alternatives({
  item,
  onChanged,
  onAddSuggestion,
}: {
  item: Item;
  onChanged: () => void;
  onAddSuggestion: (s: Suggestion) => void;
}) {
  const [linkTo, setLinkTo] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState<Schemas["AlternativesOut"] | null>(null);
  // Load every item (any tier or status), not just what the current page filter shows.
  const all = useResource<{ items: Item[] }>("alternatives:items", (signal) =>
    api("/items", { query: { limit: 200 }, signal }),
  );
  const [group, setGroup] = useState<string | null>(item.alternative_group ?? null);
  const allItems = all.data?.items ?? [];
  const members = group ? allItems.filter((i) => i.alternative_group === group) : [item];

  const suggestions = search?.suggestions ?? [];
  const inGroup = new Set(members.map((m) => m.id));
  const candidates = allItems.filter((i) => !inGroup.has(i.id));

  async function run(label: string, fn: () => Promise<void>) {
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

  const link = () =>
    run("link", async () => {
      const linked = await api<Item[]>(`/items/${item.id}/alternatives`, {
        method: "POST",
        body: { other_item_id: linkTo },
      });
      setGroup(linked[0]?.alternative_group ?? null);
      setLinkTo("");
      await all.reload();
      onChanged();
    });

  const unlink = () =>
    run("unlink", async () => {
      await api<null>(`/items/${item.id}/alternatives`, { method: "DELETE" });
      setGroup(null);
      await all.reload();
      onChanged();
    });

  const find = () =>
    run("search", async () => {
      setSearch(await api(`/items/${item.id}/alternatives/search`, { method: "POST" }));
    });

  return (
    <div className="flex flex-col gap-5">
      {error && <Alert>{error}</Alert>}

      <section>
        <h3 className="text-sm font-semibold">This item’s alternatives</h3>
        <p className="mt-0.5 text-xs text-muted">
          The planner buys at most one item from a group — the best fit for your priorities and cash
          flow.
        </p>
        {members.length > 1 ? (
          <ul className="mt-3 divide-y divide-border rounded-lg border border-border">
            {members.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                <span className="truncate">
                  {m.name} {m.id === item.id && <Badge>this item</Badge>}
                </span>
                <span className="tabular text-muted">
                  {formatMoney(m.estimated_price_minor * m.quantity, m.currency)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-muted">No alternatives linked yet.</p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <Select
            aria-label="Item to link as an alternative"
            className="w-auto min-w-48 flex-1"
            value={linkTo}
            onChange={(e) => setLinkTo(e.target.value)}
            options={[
              { value: "", label: candidates.length ? "Choose an item…" : "No other items" },
              ...candidates.map((c) => ({ value: c.id, label: c.name })),
            ]}
          />
          <Button
            variant="secondary"
            disabled={!linkTo}
            loading={busy === "link"}
            onClick={() => void link()}
          >
            Link as alternative
          </Button>
          {members.length > 1 && (
            <Button variant="ghost" loading={busy === "unlink"} onClick={() => void unlink()}>
              Remove this item from the group
            </Button>
          )}
        </div>
      </section>

      <section className="rounded-lg bg-surface-muted p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">Find current alternatives</h3>
            <p className="text-xs text-muted">
              Searches the web with your Claude API key. Only products found on real, cited pages
              are shown.
            </p>
          </div>
          <Button variant="secondary" loading={busy === "search"} onClick={() => void find()}>
            Search
          </Button>
        </div>
        {search && (
          <div className="mt-3 flex flex-col gap-3">
            <Alert tone={search.available ? "success" : "warning"}>{search.message}</Alert>
            {suggestions.length > 0 && (
              <ul className="flex flex-col gap-2">
                {suggestions.map((s) => (
                  <li key={s.url} className="rounded-lg border border-border bg-surface p-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="font-medium">{s.name}</p>
                        <p className="text-xs text-muted">{s.why}</p>
                        <p className="mt-1 text-xs">
                          <a
                            href={s.url}
                            target="_blank"
                            rel="noopener noreferrer nofollow"
                            className="text-brand hover:underline"
                          >
                            {s.source_name}
                          </a>
                          {s.price_text && (
                            <span className="text-muted">
                              {" "}
                              · listed as “{s.price_text}” (unverified)
                            </span>
                          )}
                        </p>
                      </div>
                      <Button size="sm" variant="secondary" onClick={() => onAddSuggestion(s)}>
                        Add as alternative
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
