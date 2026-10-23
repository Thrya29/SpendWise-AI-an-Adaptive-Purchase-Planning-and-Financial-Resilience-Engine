import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, refreshSession, setAccessToken, setSessionExpiredHandler } from "./client";

function json(status: number, body: unknown): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  setAccessToken(null);
  setSessionExpiredHandler(null);
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

function authHeader(call: number): string | undefined {
  const init = fetchMock.mock.calls[call][1] as RequestInit;
  return (init.headers as Record<string, string>).Authorization;
}

describe("api", () => {
  it("sends bearer token, JSON body and query string", async () => {
    setAccessToken("tok");
    fetchMock.mockResolvedValueOnce(json(200, { ok: true }));
    await api("/items", { method: "POST", body: { a: 1 }, query: { tier: "need", q: "" } });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/items?tier=need");
    expect(init.body).toBe('{"a":1}');
    expect(authHeader(0)).toBe("Bearer tok");
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    setAccessToken("old");
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: "expired" }))
      .mockResolvedValueOnce(
        json(200, { access_token: "new", token_type: "bearer", expires_in: 900 }),
      )
      .mockResolvedValueOnce(json(200, { id: 1 }));
    await expect(api("/me")).resolves.toEqual({ id: 1 });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/auth/refresh");
    expect(authHeader(2)).toBe("Bearer new");
  });

  it("calls the session-expired handler when refresh fails", async () => {
    const expired = vi.fn();
    setSessionExpiredHandler(expired);
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: "expired" }))
      .mockResolvedValueOnce(json(401, { detail: "no session" }));
    await expect(api("/me")).rejects.toBeInstanceOf(ApiError);
    expect(expired).toHaveBeenCalledOnce();
  });

  it("does not try to refresh for auth endpoints", async () => {
    fetchMock.mockResolvedValueOnce(json(401, { detail: "Invalid email or password" }));
    await expect(api("/auth/login", { method: "POST", body: {} })).rejects.toThrow(
      "Invalid email or password",
    );
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("parses problem+json into a typed error", async () => {
    fetchMock.mockResolvedValueOnce(
      json(422, {
        type: "https://spendwise.dev/problems/validation_error",
        detail: "Request validation failed",
        request_id: "r1",
        errors: [{ loc: ["body", "name"], msg: "Value error, too short", type: "value_error" }],
      }),
    );
    const err = (await api("/items").catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(422);
    expect(err.code).toBe("validation_error");
    expect(err.requestId).toBe("r1");
    expect(err.fieldMessages()).toEqual({ name: "too short" });
  });

  it("exposes the current version on conflicts and handles 204 / non-JSON bodies", async () => {
    fetchMock.mockResolvedValueOnce(json(409, { detail: "changed", current_version: 3 }));
    const conflict = (await api("/items/1").catch((e: unknown) => e)) as ApiError;
    expect(conflict.currentVersion).toBe(3);

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(api("/items/1", { method: "DELETE" })).resolves.toBeNull();

    fetchMock.mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }));
    await expect(api("/me")).rejects.toThrow("Bad gateway");
  });
});

describe("refreshSession", () => {
  it("shares one in-flight refresh between concurrent callers", async () => {
    let resolve!: (r: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((r) => (resolve = r)));
    const a = refreshSession();
    const b = refreshSession();
    resolve(json(200, { access_token: "t", token_type: "bearer", expires_in: 900 }));
    await expect(Promise.all([a, b])).resolves.toEqual([true, true]);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("returns false on network failure", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    await expect(refreshSession()).resolves.toBe(false);
  });
});
