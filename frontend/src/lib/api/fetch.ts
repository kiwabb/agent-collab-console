// Phase 4b: extract shared fetch infrastructure from the 2061-line
// monolithic lib/api.ts. These helpers are referenced by every API
// call in the codebase; lifting them out of the per-domain file makes
// the upcoming per-domain split straightforward without duplication.

import { isRecord } from "@/lib/utils";

export const API_BASE = process.env["NEXT_PUBLIC_API_BASE"] ?? "/api";
const CONFIGURED_WS_BASE = process.env["NEXT_PUBLIC_WS_BASE"]?.replace(/\/$/, "");
export const WS_BASE = CONFIGURED_WS_BASE ?? "ws://127.0.0.1:9000";

export function getWebSocketBase(): string {
  if (CONFIGURED_WS_BASE) return CONFIGURED_WS_BASE;
  if (typeof window === "undefined") return WS_BASE;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.hostname}:9000`;
}

export function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (!isRecord(item)) return String(item);
        const locValue = item["loc"];
        const loc = Array.isArray(locValue)
          ? locValue.map((part) => String(part)).join(".")
          : typeof locValue === "string"
            ? locValue
            : "";
        const msg = typeof item["msg"] === "string" ? item["msg"] : "";
        if (loc && msg) return `${loc}: ${msg}`;
        return msg || loc || JSON.stringify(item);
      })
      .filter(Boolean);
    if (parts.length > 0) return parts.join("; ");
  }
  return fallback;
}

/**
 * Short-window GET dedupe. When multiple components ask for the same URL
 * within `ttlMs`, they share one in-flight Promise instead of each firing
 * its own request. Cuts the 80+ XHR storm on the issue detail page
 * (pipeline-stages × 12, graph × 13, tasks × 15, etc) down to ~10.
 *
 * Only applies to GETs. POST/PUT/DELETE bypass — those mutate state.
 */
const _dedupeCache = new Map<string, { promise: Promise<Response>; expires: number }>();
const _DEDUPE_TTL_MS = 1500;

export async function dedupedFetch(url: string, init?: RequestInit): Promise<Response> {
  // Bypass dedupe for non-GET — those have side effects.
  const method = (init?.method ?? "GET").toUpperCase();
  if (method !== "GET") {
    return fetch(url, init);
  }
  const now = Date.now();
  const key = url;
  const cached = _dedupeCache.get(key);
  if (cached && cached.expires > now) {
    // Clone is required because Response bodies can only be read once.
    return cached.promise.then((r) => r.clone());
  }
  const p = fetch(url, init);
  _dedupeCache.set(key, { promise: p, expires: now + _DEDUPE_TTL_MS });
  // Garbage-collect after TTL so stale errors don't linger.
  p.finally(() => {
    const c = _dedupeCache.get(key);
    if (c && c.expires <= Date.now()) _dedupeCache.delete(key);
  });
  return p.then((r) => r.clone());
}

export async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}`;
    try {
      const err = await response.json();
      const detail = isRecord(err) ? err["detail"] : undefined;
      errorMessage = formatApiErrorDetail(detail, errorMessage);
    } catch {
      // If JSON parsing fails, try reading as text
      try {
        const text = await response.text();
        if (text.includes("<html>") || text.includes("<!DOCTYPE html>")) {
          errorMessage = `Server Error (${response.status}): The request returned an invalid response. This often happens if the API endpoint is incorrect or the server is down.`;
        } else if (text.length > 0 && text.length < 200) {
          errorMessage = text;
        }
      } catch {
        // Fallback to default errorMessage
      }
    }
    throw new Error(errorMessage);
  }
  if (response.status === 204 || response.status === 205) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export async function apiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  return handleResponse<T>(response);
}

export function apiRawRequest(url: string, init?: RequestInit): Promise<Response> {
  return fetch(url, init);
}

export async function apiDedupedRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await dedupedFetch(url, init);
  return handleResponse<T>(response);
}

export async function apiRequestOr<T>(
  url: string,
  fallback: T,
  options: {
    init?: RequestInit;
    dedupe?: boolean;
    errorMessage?: (status: number) => string;
  } = {},
): Promise<T> {
  const response = options.dedupe
    ? await dedupedFetch(url, options.init)
    : await fetch(url, options.init);
  if (!response.ok) {
    const message = options.errorMessage?.(response.status);
    if (message) console.error(message);
    return fallback;
  }
  return response.json() as Promise<T>;
}

export function jsonRequestInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export async function apiJsonRequest<T>(url: string, method: string, body: unknown): Promise<T> {
  return apiRequest<T>(url, jsonRequestInit(method, body));
}
