"use client";

import { useState } from "react";

import { Alert, Button, Input } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";

type Draft = Schemas["ItemDraftOut"];

const EXAMPLES = [
  "Salon visit next month around 1500",
  "Work laptop for 75k by 15 Dec, must have",
  "Trip to Goa in March, budget 40000",
];

/** Free-text entry: the assistant drafts the item, the user reviews it in the normal form. */
export function QuickAdd({ onDraft }: { onDraft: (draft: Draft) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (text.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const draft = await api<Draft>("/assistant/parse-item", {
        method: "POST",
        body: { text: text.trim() },
      });
      onDraft(draft);
      setText("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not read that. Try the full form.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-xl border border-border bg-surface p-4"
      aria-label="Describe a purchase"
    >
      <label htmlFor="quick-add" className="text-sm font-medium">
        Describe it in your own words
      </label>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row">
        <Input
          id="quick-add"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={`e.g. "${EXAMPLES[0]}"`}
          maxLength={500}
          autoComplete="off"
        />
        <Button type="submit" loading={busy} disabled={text.trim().length < 2}>
          Fill in for me
        </Button>
      </div>
      <p className="mt-2 text-xs text-muted">
        You review everything before it is saved. Try:{" "}
        {EXAMPLES.map((ex, i) => (
          <button
            key={ex}
            type="button"
            className="text-brand hover:underline"
            onClick={() => setText(ex)}
          >
            {ex}
            {i < EXAMPLES.length - 1 ? " · " : ""}
          </button>
        ))}
      </p>
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
    </form>
  );
}

export function DraftBanner({ draft }: { draft: Draft }) {
  const source = draft.source === "anthropic" ? "Claude" : "the built-in assistant";
  return (
    <div className="mb-4 flex flex-col gap-2">
      <Alert tone="brand">
        Filled in by {source}. Check each field before saving
        {draft.missing.length > 0 && <> — please add the {draft.missing.join(" and ")}</>}.
      </Alert>
      {draft.notice && <Alert tone="warning">{draft.notice}</Alert>}
    </div>
  );
}
