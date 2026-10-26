"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { AlertsBell } from "@/components/alerts-bell";
import { FeedbackButton } from "@/components/feedback";
import { Button, cx, LoadingBlock } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/plan", label: "Needs, wants & desires" },
  { href: "/planner", label: "Planner" },
  { href: "/money", label: "Money" },
  { href: "/import", label: "Import" },
  { href: "/insights", label: "Savings & investing" },
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
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2 sm:h-14 sm:flex-nowrap sm:py-0">
          <Link
            href="/dashboard"
            className="mr-auto shrink-0 text-lg font-semibold tracking-tight sm:mr-0"
          >
            Spend<span className="text-brand">Wise</span>
          </Link>
          <nav
            aria-label="Main"
            className="order-last -mx-2 flex w-full gap-1 overflow-x-auto [mask-image:linear-gradient(to_right,black_85%,transparent)] sm:order-none sm:w-auto sm:flex-1 sm:[mask-image:none]"
          >
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
          <div className="hidden sm:block">
            <FeedbackButton />
          </div>
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
        <span className="mt-2 flex items-center gap-2 sm:hidden">
          <FeedbackButton />
          <button type="button" onClick={() => void logout()} className="underline">
            Sign out
          </button>
        </span>
      </footer>
    </div>
  );
}
