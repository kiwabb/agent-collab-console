import test from "node:test";
import assert from "node:assert/strict";
import { at } from "./testAssertions";
import { jsonRequestBody, withMockFetch } from "./fetchTestUtils";

import { apiDedupedRequest, apiJsonRequest, apiRequest, apiRequestOr } from "../src/lib/api/fetch";

test("apiJsonRequest posts JSON and returns the typed response body", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    async (calls) => {
      const result = await apiJsonRequest<{ ok: boolean }>("/api/example", "PATCH", {
        title: "Ship it",
      });

      assert.deepEqual(result, { ok: true });
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/example");
      assert.equal(call.init?.method, "PATCH");
      assert.deepEqual(call.init?.headers, { "Content-Type": "application/json" });
      assert.deepEqual(jsonRequestBody(call), { title: "Ship it" });
    },
  );
});

test("apiRequest formats FastAPI validation detail arrays", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          detail: [{ loc: ["body", "title"], msg: "Field required" }],
        }),
        { status: 422 },
      ),
    async () => {
      await assert.rejects(
        apiRequest<{ ok: boolean }>("/api/example"),
        /body\.title: Field required/,
      );
    },
  );
});

test("apiRequest treats 204 responses as void without parsing JSON", async () => {
  await withMockFetch(
    () => new Response(null, { status: 204 }),
    async () => {
      const result = await apiRequest<void>("/api/no-content", { method: "DELETE" });

      assert.equal(result, undefined);
    },
  );
});

test("apiDedupedRequest shares concurrent GET requests", async () => {
  let fetchCount = 0;
  await withMockFetch(
    () => {
      fetchCount += 1;
      return new Response(JSON.stringify({ value: fetchCount }), { status: 200 });
    },
    async () => {
      const [first, second] = await Promise.all([
        apiDedupedRequest<{ value: number }>("/api/deduped-helper-test"),
        apiDedupedRequest<{ value: number }>("/api/deduped-helper-test"),
      ]);

      assert.deepEqual(first, { value: 1 });
      assert.deepEqual(second, { value: 1 });
      assert.equal(fetchCount, 1);
    },
  );
});

test("apiRequestOr returns a fallback and logs soft failures", async () => {
  const originalConsoleError = console.error;
  const errors: string[] = [];
  console.error = (...data: unknown[]) => {
    errors.push(data.map(String).join(" "));
  };
  try {
    await withMockFetch(
      () => new Response(JSON.stringify({ detail: "offline" }), { status: 503 }),
      async () => {
        const result = await apiRequestOr<{ items: string[] }>(
          "/api/soft-failure",
          { items: [] },
          {
            errorMessage: (status) => `soft endpoint failed: HTTP ${status}`,
          },
        );

        assert.deepEqual(result, { items: [] });
        assert.deepEqual(errors, ["soft endpoint failed: HTTP 503"]);
      },
    );
  } finally {
    console.error = originalConsoleError;
  }
});

test("apiRequestOr can share concurrent fallback-capable GET requests", async () => {
  let fetchCount = 0;
  await withMockFetch(
    () => {
      fetchCount += 1;
      return new Response(JSON.stringify({ value: fetchCount }), { status: 200 });
    },
    async () => {
      const [first, second] = await Promise.all([
        apiRequestOr<{ value: number }>(
          "/api/soft-dedupe-helper-test",
          { value: 0 },
          {
            dedupe: true,
          },
        ),
        apiRequestOr<{ value: number }>(
          "/api/soft-dedupe-helper-test",
          { value: 0 },
          {
            dedupe: true,
          },
        ),
      ]);

      assert.deepEqual(first, { value: 1 });
      assert.deepEqual(second, { value: 1 });
      assert.equal(fetchCount, 1);
    },
  );
});
