"use client";

import { useMemo, useState } from "react";

import { MoneyInput } from "@/components/money-input";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  Field,
  Input,
  PageHeader,
  Select,
} from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api/client";
import { useAuth, useUser, type User } from "@/lib/auth";
import { countryOptions, timezoneOptions } from "@/lib/labels";
import { CURRENCIES, minorToInput, parseToMinor } from "@/lib/money";

type Feedback = { tone: "success" | "danger"; text: string } | null;

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function ProfileCard({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const countries = useMemo(() => countryOptions(), []);
  const timezones = useMemo(
    () => timezoneOptions(user.timezone).map((t) => ({ value: t, label: t })),
    [user.timezone],
  );

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const s = (k: string) => String(f.get(k) ?? "").trim();
    setBusy(true);
    setFeedback(null);
    setErrors({});
    try {
      const updated = await api<User>("/me", {
        method: "PATCH",
        body: {
          display_name: s("display_name"),
          country: s("country"),
          city: s("city") || null,
          address: s("address") || null,
          timezone: s("timezone"),
          base_currency: s("base_currency"),
        } satisfies Schemas["ProfileUpdate"],
      });
      onSaved(updated);
      setFeedback({ tone: "success", text: "Profile saved." });
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fieldMessages());
      setFeedback({ tone: "danger", text: errorText(err, "Could not save your profile.") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Profile & location"
      description="Location and currency are used for local prices and planning."
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        {feedback && <Alert tone={feedback.tone}>{feedback.text}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" error={errors.display_name}>
            {(p) => (
              <Input
                {...p}
                name="display_name"
                defaultValue={user.display_name}
                required
                maxLength={100}
              />
            )}
          </Field>
          <Field label="Email">
            {(p) => <Input {...p} value={user.email} disabled readOnly />}
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Country" error={errors.country}>
            {(p) => (
              <Select {...p} name="country" defaultValue={user.country} options={countries} />
            )}
          </Field>
          <Field label="City" error={errors.city}>
            {(p) => <Input {...p} name="city" defaultValue={user.city ?? ""} maxLength={120} />}
          </Field>
          <Field
            label="Main currency"
            error={errors.base_currency}
            hint="Planning includes only amounts in this currency"
          >
            {(p) => (
              <Select
                {...p}
                name="base_currency"
                defaultValue={user.base_currency}
                options={CURRENCIES.map((c) => ({ value: c, label: c }))}
              />
            )}
          </Field>
        </div>
        <Field
          label="Address"
          error={errors.address}
          hint="Optional — for delivery estimates and local providers"
        >
          {(p) => <Input {...p} name="address" defaultValue={user.address ?? ""} maxLength={500} />}
        </Field>
        <Field label="Timezone" error={errors.timezone}>
          {(p) => (
            <Select {...p} name="timezone" defaultValue={user.timezone} options={timezones} />
          )}
        </Field>
        <div className="flex justify-end">
          <Button type="submit" loading={busy}>
            Save profile
          </Button>
        </div>
      </form>
    </Card>
  );
}

function ReserveCard({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const buffer = parseToMinor(String(f.get("buffer") || "0"), user.base_currency);
    if (buffer === null) {
      setFeedback({ tone: "danger", text: "Enter a valid buffer amount." });
      return;
    }
    setBusy(true);
    setFeedback(null);
    try {
      const updated = await api<User>("/me", {
        method: "PATCH",
        body: { reserve_months: Number(f.get("months")), reserve_buffer_minor: buffer },
      });
      onSaved(updated);
      setFeedback({ tone: "success", text: "Reserve policy saved." });
    } catch (err) {
      setFeedback({ tone: "danger", text: errorText(err, "Could not save.") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Emergency reserve"
      description="Money SpendWise will never plan to spend. It covers your essentials if salary is delayed."
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        {feedback && <Alert tone={feedback.tone}>{feedback.text}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Months of essential expenses" hint="Common guidance is 3 to 6 months">
            {(p) => (
              <Select
                {...p}
                name="months"
                defaultValue={String(user.reserve_months)}
                options={Array.from({ length: 13 }, (_, m) => ({
                  value: String(m),
                  label: m === 0 ? "No reserve" : `${m} month${m > 1 ? "s" : ""}`,
                }))}
              />
            )}
          </Field>
          <Field label="Extra safety buffer" hint="Added on top of the months above">
            {(p) => (
              <MoneyInput
                {...p}
                name="buffer"
                currency={user.base_currency}
                defaultValue={minorToInput(user.reserve_buffer_minor, user.base_currency)}
              />
            )}
          </Field>
        </div>
        <div className="flex justify-end">
          <Button type="submit" loading={busy}>
            Save reserve
          </Button>
        </div>
      </form>
    </Card>
  );
}

function NotificationsCard({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busy, setBusy] = useState(false);

  async function toggle(on: boolean) {
    setBusy(true);
    setFeedback(null);
    try {
      onSaved(await api<User>("/me", { method: "PATCH", body: { email_notifications: on } }));
      setFeedback({
        tone: "success",
        text: on ? "Email reminders are on." : "Email reminders are off.",
      });
    } catch (err) {
      setFeedback({ tone: "danger", text: errorText(err, "Could not save.") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Notifications"
      description="Each morning SpendWise checks for bills you can't cover in the next 3 days, purchases planned for today, and salary that was due yesterday. Reminders always appear under Alerts."
    >
      <div className="flex flex-col gap-3">
        {feedback && <Alert tone={feedback.tone}>{feedback.text}</Alert>}
        <Checkbox
          label="Also email me a daily digest"
          hint={
            user.email_available
              ? `At most once a day, to ${user.email}. Emails include amounts and item names.`
              : "Email isn't set up on this server yet, so reminders stay in the app."
          }
          checked={user.email_notifications ?? false}
          disabled={busy || (!user.email_available && !user.email_notifications)}
          onChange={(e) => void toggle(e.target.checked)}
        />
      </div>
    </Card>
  );
}

function ResearchCard({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busy, setBusy] = useState(false);

  async function toggle(on: boolean) {
    setBusy(true);
    setFeedback(null);
    try {
      onSaved(await api<User>("/me", { method: "PATCH", body: { share_usage: on } }));
      setFeedback({
        tone: "success",
        text: on ? "Thank you — sharing is on." : "Sharing is off and what was shared is deleted.",
      });
    } catch (err) {
      setFeedback({ tone: "danger", text: errorText(err, "Could not save.") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Help improve SpendWise"
      description="Share which steps you use (for example: imported a statement, ran the planner), so we can see where people get stuck."
    >
      <div className="flex flex-col gap-3">
        {feedback && <Alert tone={feedback.tone}>{feedback.text}</Alert>}
        <Checkbox
          label="Share usage statistics"
          hint="Off by default. Records the day and the step only, under a code that isn't your account ID. Never amounts, names or anything you type. Turning it off deletes what was shared."
          checked={user.share_usage ?? false}
          disabled={busy}
          onChange={(e) => void toggle(e.target.checked)}
        />
      </div>
    </Card>
  );
}

function AssistantCard({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const [mode, setMode] = useState(user.llm_mode);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const key = String(new FormData(form).get("api_key") ?? "").trim();
    setBusy(true);
    setFeedback(null);
    try {
      const updated = await api<User>("/me/llm", {
        method: "PUT",
        body: { mode, api_key: key || null } satisfies Schemas["LlmSettingsUpdate"],
      });
      onSaved(updated);
      form.reset();
      setFeedback({ tone: "success", text: "Assistant settings saved." });
    } catch (err) {
      setFeedback({ tone: "danger", text: errorText(err, "Could not save.") });
    } finally {
      setBusy(false);
    }
  }

  async function removeKey() {
    setBusy(true);
    try {
      const updated = await api<User>("/me/llm/key", { method: "DELETE" });
      onSaved(updated);
      setMode("mock");
      setFeedback({ tone: "success", text: "API key removed. Using the built-in assistant." });
    } catch (err) {
      setFeedback({ tone: "danger", text: errorText(err, "Could not remove the key.") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="AI assistant"
      description="AI only reads text and explains plans. All money calculations are done by exact, tested code."
      actions={
        <Badge tone={user.llm_mode === "anthropic" ? "brand" : "neutral"}>
          {user.llm_mode === "anthropic" ? "Using Claude" : "Built-in assistant"}
        </Badge>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        {feedback && <Alert tone={feedback.tone}>{feedback.text}</Alert>}
        <fieldset className="grid gap-3 sm:grid-cols-2">
          <legend className="sr-only">Assistant mode</legend>
          {(
            [
              {
                value: "mock",
                title: "Built-in assistant",
                text: "Works offline with no API key. Rule-based understanding and template explanations.",
              },
              {
                value: "anthropic",
                title: "Claude (your API key)",
                text: "Richer understanding of free text and explanations, billed to your Anthropic account.",
              },
            ] as const
          ).map((opt) => (
            <label
              key={opt.value}
              className={`cursor-pointer rounded-lg border p-4 ${mode === opt.value ? "border-brand bg-brand-soft" : "border-border"}`}
            >
              <input
                type="radio"
                name="mode"
                value={opt.value}
                checked={mode === opt.value}
                onChange={() => setMode(opt.value)}
                className="sr-only"
              />
              <span className="block text-sm font-semibold">{opt.title}</span>
              <span className="mt-1 block text-xs text-muted">{opt.text}</span>
            </label>
          ))}
        </fieldset>
        {mode === "anthropic" && (
          <Field
            label="Anthropic API key"
            hint={
              user.llm_api_key_hint
                ? `A key ending in …${user.llm_api_key_hint} is saved (encrypted). Leave blank to keep it.`
                : "Stored encrypted and never shown again. Starts with sk-ant-"
            }
          >
            {(p) => (
              <Input
                {...p}
                name="api_key"
                type="password"
                autoComplete="off"
                placeholder="sk-ant-…"
              />
            )}
          </Field>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          {user.llm_api_key_hint && (
            <Button
              type="button"
              variant="secondary"
              onClick={() => void removeKey()}
              disabled={busy}
            >
              Remove saved key
            </Button>
          )}
          <Button type="submit" loading={busy}>
            Save assistant settings
          </Button>
        </div>
      </form>
    </Card>
  );
}

function SecurityCard() {
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    if (f.get("new_password") !== f.get("confirm")) {
      setFeedback({ tone: "danger", text: "New passwords do not match." });
      return;
    }
    setBusy(true);
    setFeedback(null);
    try {
      await api<null>("/auth/password", {
        method: "POST",
        body: {
          current_password: String(f.get("current")),
          new_password: String(f.get("new_password")),
        },
      });
      form.reset();
      setFeedback({
        tone: "success",
        text: "Password changed. Other devices have been signed out.",
      });
    } catch (err) {
      const text =
        err instanceof ApiError && err.fieldErrors.length
          ? "New password must be 10–128 characters."
          : errorText(err, "Could not change password.");
      setFeedback({ tone: "danger", text });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Password">
      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        {feedback && <Alert tone={feedback.tone}>{feedback.text}</Alert>}
        <Field label="Current password">
          {(p) => (
            <Input {...p} name="current" type="password" autoComplete="current-password" required />
          )}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="New password" hint="At least 10 characters">
            {(p) => (
              <Input
                {...p}
                name="new_password"
                type="password"
                autoComplete="new-password"
                required
              />
            )}
          </Field>
          <Field label="Confirm new password">
            {(p) => (
              <Input {...p} name="confirm" type="password" autoComplete="new-password" required />
            )}
          </Field>
        </div>
        <div className="flex justify-end">
          <Button type="submit" loading={busy}>
            Change password
          </Button>
        </div>
      </form>
    </Card>
  );
}

function DataCard() {
  const { logout } = useAuth();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function exportData() {
    setBusy(true);
    setError(null);
    try {
      const data = await api<unknown>("/me/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `spendwise-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorText(err, "Export failed."));
    } finally {
      setBusy(false);
    }
  }

  async function deleteAccount(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api<null>("/me/delete", {
        method: "POST",
        body: { password: String(new FormData(e.currentTarget).get("password")) },
      });
      await logout().catch(() => undefined);
    } catch (err) {
      setError(errorText(err, "Could not delete the account."));
      setBusy(false);
    }
  }

  return (
    <Card
      title="Your data"
      description="Download everything SpendWise stores about you, or erase it permanently."
    >
      {error && !confirming && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => void exportData()} loading={busy && !confirming}>
          Download my data (JSON)
        </Button>
        <Button variant="danger" onClick={() => setConfirming(true)}>
          Delete my account
        </Button>
      </div>
      <Dialog open={confirming} onClose={() => setConfirming(false)} title="Delete your account?">
        <form onSubmit={deleteAccount} className="flex flex-col gap-4">
          <p className="text-sm text-muted">
            This permanently erases your profile, accounts, plans and history. It cannot be undone.
          </p>
          {error && <Alert>{error}</Alert>}
          <Field label="Confirm with your password">
            {(p) => (
              <Input
                {...p}
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            )}
          </Field>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setConfirming(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button type="submit" variant="danger" loading={busy}>
              Delete permanently
            </Button>
          </div>
        </form>
      </Dialog>
    </Card>
  );
}

export default function SettingsPage() {
  const user = useUser();
  const { setUser } = useAuth();
  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-6">
          <ProfileCard user={user} onSaved={setUser} />
          <SecurityCard />
        </div>
        <div className="flex flex-col gap-6">
          <ReserveCard user={user} onSaved={setUser} />
          <NotificationsCard user={user} onSaved={setUser} />
          <ResearchCard user={user} onSaved={setUser} />
          <AssistantCard user={user} onSaved={setUser} />
          <DataCard />
        </div>
      </div>
    </>
  );
}
