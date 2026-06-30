// Phase 4b: extract shared fetch infrastructure from the 2061-line
// monolithic lib/api.ts. These helpers are referenced by every API
// call in the codebase; lifting them out of the per-domain file makes
// the upcoming per-domain split straightforward without duplication.

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";
export const WS_BASE = process.env.NEXT_PUBLIC_WS_BASE ?? "ws://localhost:9000";

interface ApiValidationError {
  loc?: unknown;
  msg?: unknown;
}

export function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (!item || typeof item !== "object") return String(item);
        const error = item as ApiValidationError;
        const loc = Array.isArray(error.loc)
          ? error.loc.map((part) => String(part)).join(".")
          : typeof error.loc === "string"
            ? error.loc
            : "";
        const msg = typeof error.msg === "string" ? error.msg : "";
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
      errorMessage = formatApiErrorDetail((err as { detail?: unknown }).detail, errorMessage);
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
  return response.json() as Promise<T>;
}
