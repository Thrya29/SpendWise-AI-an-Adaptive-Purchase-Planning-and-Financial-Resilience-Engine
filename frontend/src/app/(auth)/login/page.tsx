"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert, Button, Field, Input } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await login(String(form.get("email")), String(form.get("password")));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in. Please try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      <h1 className="text-xl font-semibold">Sign in</h1>
      {error && <Alert>{error}</Alert>}
      <Field label="Email">
        {(p) => <Input {...p} name="email" type="email" autoComplete="email" required />}
      </Field>
      <Field label="Password">
        {(p) => (
          <Input {...p} name="password" type="password" autoComplete="current-password" required />
        )}
      </Field>
      <Button type="submit" loading={busy} className="mt-2 w-full">
        Sign in
      </Button>
      <p className="text-center text-sm text-muted">
        New here?{" "}
        <Link href="/register" className="font-medium text-brand hover:underline">
          Create an account
        </Link>
      </p>
    </form>
  );
}
