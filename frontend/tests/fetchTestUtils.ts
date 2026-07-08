import assert from "node:assert/strict";

import { safeJsonRecord } from "../src/lib/utils";

export interface FetchCall {
  input: string;
  init?: RequestInit | undefined;
}

export async function withMockFetch(
  handler: (input: RequestInfo | URL, init: RequestInit | undefined) => Response,
  run: (calls: FetchCall[]) => Promise<void>,
): Promise<void> {
  const originalFetch = globalThis.fetch;
  const calls: FetchCall[] = [];
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ input: String(input), init });
    return handler(input, init);
  };
  try {
    await run(calls);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

export function withMockJsonFetch(
  responseBody: unknown,
  run: (calls: FetchCall[]) => Promise<void>,
): Promise<void> {
  return withMockFetch(
    () =>
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    run,
  );
}

export function contentType(init: RequestInit | undefined): string | null {
  return new Headers(init?.headers).get("Content-Type");
}

export function jsonRequestBody(call: FetchCall): Record<string, unknown> {
  const body = call.init?.body;
  if (typeof body !== "string") {
    assert.fail("Expected request body to be a JSON string");
  }
  const payload = safeJsonRecord(body);
  assert.ok(payload, "Expected request body to be a JSON object");
  return payload;
}
