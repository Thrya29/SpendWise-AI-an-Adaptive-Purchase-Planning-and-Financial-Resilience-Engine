/**
 * Browser API client.
 *
 * - Access token lives in memory only (never localStorage), so XSS cannot read a stored token.
 * - The refresh token is an httpOnly, SameSite=Strict cookie scoped to /api/v1/auth.
 * - On a 401 the client refreshes once (shared across concurrent requests) and retries.
 */

import type { components } from "./schema";

export type Schemas = components["schemas"];

export const API_BASE = "/api/v1";

export interface FieldError {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fieldErrors: FieldError[];
  readonly currentVersion?: number;
  readonly requestId?: string;

  constructor(status: number, body: Record<string, unknown> | null) {
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${status})`;
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = typeof body?.type === "string" ? body.type.split("/").pop()! : "unknown";
    this.fieldErrors = Array.isArray(body?.errors) ? (body.errors as FieldError[]) : [];
    this.currentVersion =
      typeof body?.current_version === "number" ? body.current_version : undefined;
    this.requestId = typeof body?.request_id === "string" ? body.request_id : undefined;
  }

  /** Map validation errors to { fieldName: message } for form display. */
  fieldMessages(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const err of this.fieldErrors) {
      const field = err.loc.filter((p) => p !== "body").join(".");
      if (field && !out[field]) out[field] = err.msg.replace(/^Value error, /, "");
    }
    return out;
  }
}

let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;
let onSessionExpired: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

export function setSessionExpiredHandler(handler: (() => void) | null): void {
  onSessionExpired = handler;
}

async function parseBody(res: Response): Promise<Record<string, unknown> | null> {
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    return { detail: text.slice(0, 200) };
  }
}

/** Exchange the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "same-origin",
      });
      if (!res.ok) {
        accessToken = null;
        return false;
      }
      const body = (await res.json()) as Schemas["TokenResponse"];
      accessToken = body.access_token;
      return true;
    } catch {
      accessToken = null;
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ""}`;
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const send = () => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    return fetch(buildUrl(path, opts.query), {
      method: opts.method ?? "GET",
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      credentials: "same-origin",
      signal: opts.signal,
    });
  };

  let res = await send();
  if (res.status === 401 && !path.startsWith("/auth/")) {
    if (await refreshSession()) {
      res = await send();
    } else {
      onSessionExpired?.();
    }
  }
  const body = await parseBody(res);
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}
