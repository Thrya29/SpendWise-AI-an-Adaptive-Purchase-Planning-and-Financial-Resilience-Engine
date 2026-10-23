"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { LoadingBlock } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") router.replace("/dashboard");
  }, [status, router]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <div className="mb-8 text-center">
        <p className="text-2xl font-semibold tracking-tight">
          Spend<span className="text-brand">Wise</span> AI
        </p>
        <p className="mt-1 text-sm text-muted">
          Adaptive purchase planning &amp; financial resilience
        </p>
      </div>
      <div className="w-full max-w-md rounded-xl border border-border bg-surface p-6 shadow-sm sm:p-8">
        {status === "anonymous" ? children : <LoadingBlock />}
      </div>
    </main>
  );
}
