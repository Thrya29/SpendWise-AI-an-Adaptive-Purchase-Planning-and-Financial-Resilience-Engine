"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { AlertsBell } from "@/components/alerts-bell";
import { Button, cx, LoadingBlock } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/plan", label: "Needs, wants & desires" },
  { href: "/planner", label: "Planner" },
  { href: "/money", label: "Money" },
  { href: "/settings", label: "Settings" },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { status, user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);

  if (status !== "authenticated" || !user) {
    return <LoadingBlock label="Checking your session…" />;
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-border bg-surface/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
          <Link href="/dashboard" className="shrink-0 text-lg font-semibold tracking-tight">
            Spend<span className="text-brand">Wise</span>
          </Link>
          <nav aria-label="Main" className="-mx-2 flex flex-1 gap-1 overflow-x-auto">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    active
                      ? "bg-brand-soft text-brand"
                      : "text-muted hover:bg-surface-muted hover:text-text",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <AlertsBell />
          <div className="hidden items-center gap-3 sm:flex">
            <span className="max-w-40 truncate text-sm text-muted" title={user.email}>
              {user.display_name}
            </span>
            <Button variant="ghost" size="sm" onClick={() => void logout()}>
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
      <footer className="mx-auto max-w-6xl px-4 pb-10 text-xs text-muted">
        SpendWise provides planning tools and educational information, not regulated financial
        advice. Projections are estimates based on the data you enter.
        <button type="button" onClick={() => void logout()} className="ml-3 underline sm:hidden">
          Sign out
        </button>
      </footer>
    </div>
  );
}
