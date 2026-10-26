"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";

import { Alert, Button, Card, Checkbox, Dialog, Field, Select, Textarea } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { useResource } from "@/lib/use-resource";

type Due = Schemas["CheckinDue"];

const RATINGS = [
  { value: "", label: "No rating" },
  ...[5, 4, 3, 2, 1].map((r) => ({ value: String(r), label: `${r} / 5` })),
];

export function FeedbackButton() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [rating, setRating] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (message.trim().length < 2) return setError("Write a few words first.");
    setState("sending");
    setError(null);
    try {
      await api("/feedback", {
        method: "POST",
        body: { message, rating: rating ? Number(rating) : null, page: pathname },
      });
      setState("sent");
      setMessage("");
      setRating("");
    } catch (err) {
      setState("idle");
      setError(err instanceof ApiError ? err.message : "Could not send. Please try again.");
    }
  }

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          setOpen(true);
          setState("idle");
        }}
      >
        Feedback
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Tell us what's working">
        {state === "sent" ? (
          <div className="flex flex-col gap-4">
            <Alert tone="success">Thank you — every message is read.</Alert>
            <div className="flex justify-end">
              <Button onClick={() => setOpen(false)}>Close</Button>
            </div>
          </div>
        ) : (
          <form onSubmit={send} className="flex flex-col gap-4" noValidate>
            {error && <Alert>{error}</Alert>}
            <Field label="What's confusing, missing or wrong — or what helped?">
              {(p) => (
                <Textarea
                  {...p}
                  rows={5}
                  maxLength={2000}
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                />
              )}
            </Field>
            <Field label="How useful is SpendWise so far?">
              {(p) => (
                <Select
                  {...p}
                  value={rating}
                  onChange={(e) => setRating(e.target.value)}
                  options={RATINGS}
                />
              )}
            </Field>
            <p className="text-xs text-muted">
              Sent with the page you are on ({pathname}). Don&apos;t include passwords or account
              numbers.
            </p>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={state === "sending"}>
                Send
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}

const FOLLOWED = [
  { value: "mostly", label: "Mostly" },
  { value: "partly", label: "Partly" },
  { value: "no", label: "Not really" },
  { value: "no_plan", label: "I didn't make a plan" },
];

function monthName(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString(undefined, { month: "long" });
}

/** "How did last month go?" Three questions that show whether planning helps in real life. */
export function CheckinCard() {
  const due = useResource<Due>("checkin", (signal) => api<Due>("/feedback/checkin", { signal }));
  const [short, setShort] = useState(false);
  const [missed, setMissed] = useState(false);
  const [followed, setFollowed] = useState("mostly");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!due.data?.due && !done) return null;
  if (done) {
    return <Alert tone="success">Thanks for checking in. It helps make SpendWise better.</Alert>;
  }
  const month = due.data!.month;

  async function send(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/feedback/checkin", {
        method: "POST",
        body: {
          month,
          bills_short: short,
          missed_need_deadline: missed,
          followed_plan: followed,
          comment: comment.trim() || null,
        },
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title={`How did ${monthName(month)} go?`}
      description="Three quick questions, once a month. Your answers show whether planning is actually helping."
    >
      <form onSubmit={send} className="flex flex-col gap-3" noValidate>
        {error && <Alert>{error}</Alert>}
        <Checkbox
          label="I ran short of money for a bill"
          checked={short}
          onChange={(e) => setShort(e.target.checked)}
        />
        <Checkbox
          label="I missed a deadline for something I needed"
          checked={missed}
          onChange={(e) => setMissed(e.target.checked)}
        />
        <Field label="Did you follow your plan?">
          {(p) => (
            <Select
              {...p}
              value={followed}
              onChange={(e) => setFollowed(e.target.value)}
              options={FOLLOWED}
            />
          )}
        </Field>
        <Field label="Anything else? (optional)">
          {(p) => (
            <Textarea
              {...p}
              rows={2}
              maxLength={2000}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          )}
        </Field>
        <div>
          <Button type="submit" loading={busy}>
            Send
          </Button>
        </div>
      </form>
    </Card>
  );
}
