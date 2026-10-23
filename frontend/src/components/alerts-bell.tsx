"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";

const POLL_MS = 60_000;

/** Header link to alerts with an unread badge; polls only while the tab is visible. */
export function AlertsBell() {
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const r = await api<Schemas["AlertCount"]>("/alerts/unread-count");
        if (!cancelled) setUnread(r.unread);
      } catch {
        // A failed poll is not worth interrupting the user for; the next one retries.
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    document.addEventListener("visibilitychange", load);
    window.addEventListener("spendwise:alerts-changed", load);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", load);
      window.removeEventListener("spendwise:alerts-changed", load);
    };
  }, []);

  const label = unread > 0 ? `Alerts, ${unread} unread` : "Alerts";
  return (
    <Link
      href="/alerts"
      aria-label={label}
      title={label}
      className="relative rounded-md p-1.5 text-muted hover:bg-surface-muted hover:text-text"
    >
      <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden="true">
        <path
          d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16Zm4 4a2 2 0 0 0 4 0"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
      {unread > 0 && (
        <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-semibold text-white">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  );
}
