import test from "node:test";
import assert from "node:assert/strict";

import {
  mergeTaskConversationLogs,
  mergeTaskConversationMessages,
} from "../src/lib/taskConversationDetailUtils";
import type { CodexTaskMessage } from "../src/lib/types";

// Inline a minimal applyPatch to avoid fast-json-patch broken ESM
function applyPatch<T extends object>(document: T, patch: { op: string; path: string; value?: unknown }[]): T {
  const result = JSON.parse(JSON.stringify(document));
  for (const p of patch) {
    if (p.op === "add" || p.op === "replace") {
      const parts = p.path.split("/").filter(Boolean);
      let target: Record<string, unknown> = result;
      for (let i = 0; i < parts.length - 1; i++) {
        target = target[parts[i]] as Record<string, unknown>;
      }
      target[parts[parts.length - 1]] = p.value;
    } else if (p.op === "remove") {
      const parts = p.path.split("/").filter(Boolean);
      let target: Record<string, unknown> = result;
      for (let i = 0; i < parts.length - 1; i++) {
        target = target[parts[i]] as Record<string, unknown>;
      }
      delete target[parts[parts.length - 1]];
    }
  }
  return result;
}

interface ExecutionProcessesState {
  execution_processes: Record<string, { id: string; status: string }>;
}

function applyExecutionProcessPatch(
  current: ExecutionProcessesState | null,
  patches: { op: string; path: string; value?: unknown }[]
): ExecutionProcessesState {
  const base = current ?? { execution_processes: {} };
  return applyPatch(base, patches);
}

test("applyExecutionProcessPatch stores data under execution_processes", () => {
  const next = applyExecutionProcessPatch(
    { execution_processes: {} },
    [{ op: "add", path: "/execution_processes/exec-1", value: { id: "exec-1", status: "Running" } }],
  );

  assert.equal(next.execution_processes["exec-1"].status, "Running");
});

test("mergeTaskConversationMessages preserves history across multiple execution processes", () => {
  const messages: CodexTaskMessage[] = [
    { id: "m1", task_id: "task-1", role: "user", content: "first", execution_process_id: null, created_at: "2026-04-18T10:00:00Z" },
    { id: "m2", task_id: "task-1", role: "assistant", content: "reply1", execution_process_id: null, created_at: "2026-04-18T10:01:00Z" },
  ];
  const messages2: CodexTaskMessage[] = [
    { id: "m3", task_id: "task-1", role: "user", content: "follow up", execution_process_id: null, created_at: "2026-04-18T10:02:00Z" },
    { id: "m4", task_id: "task-1", role: "assistant", content: "reply2", execution_process_id: null, created_at: "2026-04-18T10:03:00Z" },
  ];

  const result = mergeTaskConversationMessages([messages, messages2]);

  assert.deepEqual(result.map((message) => message.id), ["m1", "m2", "m3", "m4"]);
});

test("mergeTaskConversationLogs deduplicates repeated realtime log entries", () => {
  const logs1 = [
    { id: "l1", content: "first", created_at: "2026-04-18T10:00:00Z" },
  ];
  const logs2 = [
    { id: "l1", content: "first", created_at: "2026-04-18T10:00:00Z" },
    { id: "l2", content: "second", created_at: "2026-04-18T10:01:00Z" },
  ];

  const result = mergeTaskConversationLogs([logs1, logs2]);

  assert.deepEqual(result.map((log) => (log as { id: string }).id), ["l1", "l2"]);
});
