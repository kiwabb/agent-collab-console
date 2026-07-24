import test from "node:test";
import assert from "node:assert/strict";

import {
  askProjectConductor,
  getProjectConductorState,
  scheduleProjectConductorReview,
  startProjectConductorLoop,
} from "../src/lib/api";
import { contentType, jsonRequestBody, withMockJsonFetch } from "./fetchTestUtils";
import { at } from "./testAssertions";

test("getProjectConductorState hits the conductor state endpoint", async () => {
  await withMockJsonFetch(
    {
      project_id: "project-1",
      hot_thread: [],
      hot_thread_total: 0,
      hot_thread_truncated: false,
      warm_summaries: [],
      warm_summaries_total: 0,
      warm_summaries_truncated: false,
      cold_memories: [],
      cold_memories_total: 0,
      cold_memories_truncated: false,
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
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/codex/projects/project-1/conductor/state");
      assert.equal(call.init, undefined);
    },
  );
});

test("project conductor endpoints encode project ids", async () => {
  await withMockJsonFetch(
    { status: "done", answer: "Checked.", task_id: "task-encoded" },
    async (calls) => {
      await askProjectConductor("project/a b", "Check the project.");

      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/codex/projects/project%2Fa%20b/conductor/ask");
    },
  );
});

test("askProjectConductor posts the question body", async () => {
  await withMockJsonFetch(
    { status: "done", answer: "Watch auth token drift.", task_id: "task-1" },
    async (calls) => {
      const result = await askProjectConductor("project-1", "What should we watch?");

      assert.equal(result.answer, "Watch auth token drift.");
      assert.equal(calls.length, 1);
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/codex/projects/project-1/conductor/ask");
      assert.equal(call.init?.method, "POST");
      assert.equal(contentType(call.init), "application/json");
      assert.deepEqual(jsonRequestBody(call), {
        question: "What should we watch?",
      });
    },
  );
});

test("scheduleProjectConductorReview posts to the schedule-review endpoint", async () => {
  await withMockJsonFetch(
    { status: "done", answer: "Checkpoint recorded.", task_id: "task-2" },
    async (calls) => {
      const result = await scheduleProjectConductorReview("project-1");

      assert.equal(result.task_id, "task-2");
      assert.equal(calls.length, 1);
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/codex/projects/project-1/conductor/schedule-review");
      assert.equal(call.init?.method, "POST");
    },
  );
});

test("startProjectConductorLoop posts an optional prompt to the loop endpoint", async () => {
  await withMockJsonFetch(
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
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/codex/projects/project-1/conductor/start-loop");
      assert.equal(call.init?.method, "POST");
      assert.deepEqual(jsonRequestBody(call), {
        prompt: "Inspect auth regression risk.",
      });
    },
  );
});
