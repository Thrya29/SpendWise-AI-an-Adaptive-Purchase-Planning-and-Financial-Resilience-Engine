/**
 * Same-origin proxy from the browser to the FastAPI service.
 *
 * Keeps the API off the public network, lets the refresh cookie stay SameSite=Strict,
 * and reads the upstream URL at request time (API_INTERNAL_URL), so one image works
 * in every environment.
 */

import type { NextRequest } from "next/server";

const UPSTREAM = (process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
const TIMEOUT_MS = 30_000;
const MAX_BODY_BYTES = 1_000_000;

const FORWARD_REQUEST_HEADERS = [
  "accept",
  "authorization",
  "content-type",
  "cookie",
  "x-request-id",
  "x-forwarded-for",
];
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "x-request-id",
  "www-authenticate",
  "cache-control",
  "retry-after",
];

function problem(status: number, detail: string): Response {
  return Response.json(
    {
      type: `https://spendwise.dev/problems/${status === 502 ? "bad_gateway" : "bad_request"}`,
      title: status === 502 ? "Bad gateway" : "Bad request",
      status,
      detail,
    },
    { status, headers: { "content-type": "application/problem+json" } },
  );
}

async function proxy(request: NextRequest, ctx: RouteContext<"/api/v1/[...path]">) {
  const { path } = await ctx.params;
  if (path.some((segment) => segment === ".." || segment === "." || segment.includes("/"))) {
    return problem(400, "Invalid path");
  }
  const target = `${UPSTREAM}/api/v1/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  let body: ArrayBuffer | undefined;
  if (request.method !== "GET" && request.method !== "HEAD") {
    const declared = Number(request.headers.get("content-length") ?? "0");
    if (declared > MAX_BODY_BYTES) return problem(400, "Request body too large");
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) return problem(400, "Request body too large");
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    return problem(502, "The SpendWise API is unavailable. Please try again shortly.");
  }

  const out = new Headers({ "cache-control": "no-store" });
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);

  return new Response(upstream.status === 204 ? null : upstream.body, {
    status: upstream.status,
    headers: out,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
