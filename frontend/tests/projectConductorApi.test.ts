import test from "node:test";
import assert from "node:assert/strict";

import {
  askProjectConductor,
  getProjectConductorState,
  scheduleProjectConductorReview,
  startProjectConductorLoop,
} from "../src/lib/api";

type FetchCall = {
  input: RequestInfo | URL;
  init?: RequestInit;
};

function withMockFetch(
  responseBody: unknown,
  run: (calls: FetchCall[]) => Promise<void>,
) {
  const originalFetch = globalThis.fetch;
  const calls: FetchCall[] = [];

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ input, init });
    return new Response(JSON.stringify(responseBody), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  return run(calls).finally(() => {
    globalThis.fetch = originalFetch;
  });
}

test("getProjectConductorState hits the conductor state endpoint", async () => {
  await withMockFetch(
    {
      project_id: "project-1",
      hot_thread: [],
      warm_summaries: [],
      cold_memories: [],
      pinned_text: "",
      hot_tokens: 0,
      warm_tokens: 0,
      total_tasks_handled: 0,
      last_compaction_at: null,
      updated_at: null,
    },
    async (calls) => {
      const result = await getProjectConductorState("project-1");

      assert.equal(result.project_id, "project-1");
      assert.equal(calls.length, 1);
      assert.equal(String(calls[0].input), "/api/codex/projects/project-1/conductor-state");
      assert.equal(calls[0].init, undefined);
    },
  );
});

test("askProjectConductor posts the question body", async () => {
  await withMockFetch(
    { status: "done", answer: "Watch auth token drift.", task_id: "task-1" },
    async (calls) => {
      const result = await askProjectConductor("project-1", "What should we watch?");

      assert.equal(result.answer, "Watch auth token drift.");
      assert.equal(calls.length, 1);
      assert.equal(String(calls[0].input), "/api/codex/projects/project-1/conductor/ask");
      assert.equal(calls[0].init?.method, "POST");
      assert.equal(calls[0].init?.headers && (calls[0].init.headers as Record<string, string>)["Content-Type"], "application/json");
      assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { question: "What should we watch?" });
    },
  );
});

test("scheduleProjectConductorReview posts to the schedule-review endpoint", async () => {
  await withMockFetch(
    { status: "done", answer: "Checkpoint recorded.", task_id: "task-2" },
    async (calls) => {
      const result = await scheduleProjectConductorReview("project-1");

      assert.equal(result.task_id, "task-2");
      assert.equal(calls.length, 1);
      assert.equal(String(calls[0].input), "/api/codex/projects/project-1/conductor/schedule-review");
      assert.equal(calls[0].init?.method, "POST");
    },
  );
});

test("startProjectConductorLoop posts an optional prompt to the loop endpoint", async () => {
  await withMockFetch(
    {
      status: "done",
      answer: "Use memory before dispatching a helper.",
      task_id: "task-3",
      tool_events: [],
      turn_count: 2,
      llm: null,
    },
    async (calls) => {
      const result = await startProjectConductorLoop("project-1", "Inspect auth regression risk.");

      assert.equal(result.turn_count, 2);
      assert.equal(calls.length, 1);
      assert.equal(String(calls[0].input), "/api/codex/projects/project-1/conductor/start-loop");
      assert.equal(calls[0].init?.method, "POST");
      assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { prompt: "Inspect auth regression risk." });
    },
  );
});
