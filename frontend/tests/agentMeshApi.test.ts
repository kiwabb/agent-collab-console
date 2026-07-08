import test from "node:test";
import assert from "node:assert/strict";

import { getSubAgentResults, getAgentMesh, appendConductorMessage } from "../src/lib/api";
import { contentType, jsonRequestBody, withMockJsonFetch } from "./fetchTestUtils";
import { at } from "./testAssertions";

test("getSubAgentResults hits the subagent-results endpoint", async () => {
  const mockResults = [
    {
      task_id: "task-1",
      role: "engineer",
      title: "Implement feature",
      status: "done",
      task_kind: "initial",
      parent_task_id: null,
      summary: "Feature implemented.",
      artifact_json: { key: "value" },
      updated_at: "2026-05-21T10:00:00",
    },
  ];

  await withMockJsonFetch(mockResults, async (calls) => {
    const result = await getSubAgentResults("issue-1");

    assert.equal(result.length, 1);
    const firstResult = at(result, 0, "subagent result");
    assert.equal(firstResult.task_id, "task-1");
    assert.equal(firstResult.role, "engineer");
    assert.equal(firstResult.status, "done");
    assert.equal(calls.length, 1);
    const call = at(calls, 0, "fetch call");
    assert.equal(call.input, "/api/codex/issues/issue-1/subagent-results");
    assert.equal(call.init, undefined);
  });
});

test("getSubAgentResults URL-encodes issue ID", async () => {
  await withMockJsonFetch([], async (calls) => {
    await getSubAgentResults("issue/with/slashes");

    const call = at(calls, 0, "fetch call");
    assert.equal(call.input, "/api/codex/issues/issue%2Fwith%2Fslashes/subagent-results");
  });
});

test("getAgentMesh hits the agent-mesh endpoint", async () => {
  const mockMessages = [
    {
      id: "msg-1",
      issue_id: "issue-1",
      graph_id: "graph-1",
      from_node_key: "engineer",
      to_node_key: "qa",
      message_type: "handoff",
      body: "Work is done.",
      created_at: "2026-05-21T10:00:00",
    },
  ];

  await withMockJsonFetch(mockMessages, async (calls) => {
    const result = await getAgentMesh("issue-1");

    assert.equal(result.length, 1);
    const firstMessage = at(result, 0, "agent mesh message");
    assert.equal(firstMessage.id, "msg-1");
    assert.equal(firstMessage.message_type, "handoff");
    assert.equal(calls.length, 1);
    const call = at(calls, 0, "fetch call");
    assert.equal(call.input, "/api/codex/issues/issue-1/agent-mesh");
    assert.equal(call.init, undefined);
  });
});

test("appendConductorMessage posts message to conductor message endpoint", async () => {
  await withMockJsonFetch({ status: "ok" }, async (calls) => {
    const result = await appendConductorMessage("project-1", "Hello from user");

    assert.equal(result.status, "ok");
    assert.equal(calls.length, 1);
    const call = at(calls, 0, "fetch call");
    assert.equal(call.input, "/api/codex/projects/project-1/conductor/message");
    assert.equal(call.init?.method, "POST");
    assert.equal(contentType(call.init), "application/json");
    assert.deepEqual(jsonRequestBody(call), {
      message: "Hello from user",
    });
  });
});

test("appendConductorMessage URL-encodes project ID", async () => {
  await withMockJsonFetch({ status: "ok" }, async (calls) => {
    await appendConductorMessage("project/with/slashes", "test");

    const call = at(calls, 0, "fetch call");
    assert.equal(call.input, "/api/codex/projects/project%2Fwith%2Fslashes/conductor/message");
  });
});
