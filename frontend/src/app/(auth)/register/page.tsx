"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Alert, Button, Field, Input, Select } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { browserTimezone, countryOptions, timezoneOptions } from "@/lib/labels";
import { CURRENCIES } from "@/lib/money";

export default function RegisterPage() {
  const { register } = useAuth();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const countries = useMemo(() => countryOptions(), []);
  const timezones = useMemo(() => timezoneOptions().map((t) => ({ value: t, label: t })), []);
  const defaultTz = useMemo(() => browserTimezone(), []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const password = String(form.get("password"));
    if (password !== String(form.get("confirm"))) {
      setErrors({ confirm: "Passwords do not match" });
      return;
    }
    setBusy(true);
    setErrors({});
    setFormError(null);
    try {
      await register({
        email: String(form.get("email")),
        password,
        display_name: String(form.get("display_name")),
        country: String(form.get("country")),
        base_currency: String(form.get("base_currency")),
        city: String(form.get("city") || "") || null,
        address: String(form.get("address") || "") || null,
        timezone: String(form.get("timezone")),
      });
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldMessages());
        setFormError(err.fieldErrors.length ? "Please fix the highlighted fields." : err.message);
      } else {
        setFormError("Could not create your account. Please try again.");
      }
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      <h1 className="text-xl font-semibold">Create your account</h1>
      {formError && <Alert>{formError}</Alert>}
      <Field label="Name" error={errors.display_name}>
        {(p) => <Input {...p} name="display_name" autoComplete="name" required maxLength={100} />}
      </Field>
      <Field label="Email" error={errors.email}>
        {(p) => <Input {...p} name="email" type="email" autoComplete="email" required />}
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Password" error={errors.password} hint="At least 10 characters">
          {(p) => (
            <Input
              {...p}
              name="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={10}
            />
          )}
        </Field>
        <Field label="Confirm password" error={errors.confirm}>
          {(p) => (
            <Input {...p} name="confirm" type="password" autoComplete="new-password" required />
          )}
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Country of residence" error={errors.country}>
          {(p) => <Select {...p} name="country" defaultValue="IN" options={countries} />}
        </Field>
        <Field label="Main currency" error={errors.base_currency}>
          {(p) => (
            <Select
              {...p}
              name="base_currency"
              defaultValue="INR"
              options={CURRENCIES.map((c) => ({ value: c, label: c }))}
            />
          )}
        </Field>
      </div>
      <Field label="City" error={errors.city} hint="Used for local price estimates">
        {(p) => <Input {...p} name="city" autoComplete="address-level2" maxLength={120} />}
      </Field>
      <Field
        label="Address (optional)"
        error={errors.address}
        hint="Used for delivery and local providers"
      >
        {(p) => <Input {...p} name="address" autoComplete="street-address" maxLength={500} />}
      </Field>
      <Field label="Timezone" error={errors.timezone}>
        {(p) => <Select {...p} name="timezone" defaultValue={defaultTz} options={timezones} />}
      </Field>
      <Button type="submit" loading={busy} className="mt-2 w-full">
        Create account
      </Button>
      <p className="text-center text-sm text-muted">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-brand hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
