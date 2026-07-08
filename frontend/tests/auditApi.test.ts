import test from "node:test";
import assert from "node:assert/strict";

import { getBestAuditTrace, type AuditLog } from "../src/lib/api/audit";
import { withMockFetch } from "./fetchTestUtils";

function auditEntry(overrides: Partial<AuditLog> = {}): AuditLog {
  return {
    id: "audit-cli",
    created_at: "2026-06-27T12:00:00",
    category: "cli_spawn",
    actor: "claude",
    issue_id: "issue-1",
    task_id: "task-1",
    conductor_task_id: null,
    execution_process_id: "exec-1",
    correlation_id: null,
    trace_id: null,
    span_id: null,
    parent_span_id: null,
    status: "ok",
    duration_ms: null,
    payload_json: "{}",
    error: null,
    ...overrides,
  };
}

test("getBestAuditTrace falls back to audit-row runtime logs when trace collection is empty", async () => {
  await withMockFetch(
    (input) => {
      const url = String(input);
      if (url.endsWith("/codex/traces/trace-cli")) {
        return new Response(
          JSON.stringify({
            available: false,
            trace_id: "trace-cli",
            reason: "trace_not_recorded",
            items: [],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/codex/audit-log/audit-cli/trace")) {
        return new Response(
          JSON.stringify({
            available: true,
            id: "runtime-audit-cli",
            audit_log_id: "audit-cli",
            trace_id: "trace-cli",
            span_id: null,
            parent_span_id: null,
            issue_id: "issue-1",
            task_id: "task-1",
            execution_process_id: "exec-1",
            kind: "runtime_logs",
            title: "Engineer task",
            request: { prompt: "full task prompt" },
            response: { messages: [{ role: "assistant", content: "done" }], logs: [] },
            request_preview: "full task prompt",
            response_preview: null,
            metadata: { source: "log_events" },
            is_truncated: false,
            created_at: "2026-06-27T12:00:00",
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: `unexpected ${url}` }), { status: 500 });
    },
    async (calls) => {
      const result = await getBestAuditTrace(auditEntry({ trace_id: "trace-cli" }));

      assert.equal(result.available, true);
      assert.equal("items" in result, false);
      if ("items" in result) assert.fail("Expected audit-row trace fallback, not trace collection");
      assert.equal(result.kind, "runtime_logs");
      assert.deepEqual(
        calls.map((call) => call.input),
        ["/api/codex/traces/trace-cli", "/api/codex/audit-log/audit-cli/trace"],
      );
    },
  );
});

test("getBestAuditTrace keeps saved trace collections without audit-row fallback", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          available: true,
          trace_id: "trace-llm",
          items: [
            {
              available: true,
              id: "trace-row",
              audit_log_id: null,
              trace_id: "trace-llm",
              span_id: null,
              parent_span_id: null,
              issue_id: null,
              task_id: null,
              execution_process_id: null,
              kind: "llm",
              title: "System Planner",
              request: { prompt: "full" },
              response: { content: "ok" },
              request_preview: "full",
              response_preview: "ok",
              metadata: {},
              is_truncated: false,
              created_at: "2026-06-27T12:00:00",
            },
          ],
        }),
        { status: 200 },
      ),
    async (calls) => {
      const result = await getBestAuditTrace(auditEntry({ trace_id: "trace-llm" }));

      assert.equal(result.available, true);
      assert.equal("items" in result, true);
      assert.equal(calls.length, 1);
      assert.equal(calls[0]?.input, "/api/codex/traces/trace-llm");
    },
  );
});
