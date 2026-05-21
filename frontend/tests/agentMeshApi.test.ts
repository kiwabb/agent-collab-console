import test from "node:test";
import assert from "node:assert/strict";

import {
  getSubAgentResults,
  getAgentMesh,
  appendConductorMessage,
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

  await withMockFetch(mockResults, async (calls) => {
    const result = await getSubAgentResults("issue-1");

    assert.equal(result.length, 1);
    assert.equal(result[0].task_id, "task-1");
    assert.equal(result[0].role, "engineer");
    assert.equal(result[0].status, "done");
    assert.equal(calls.length, 1);
    assert.equal(
      String(calls[0].input),
      "/api/codex/issues/issue-1/subagent-results",
    );
    assert.equal(calls[0].init, undefined);
  });
});

test("getSubAgentResults URL-encodes issue ID", async () => {
  await withMockFetch([], async (calls) => {
    await getSubAgentResults("issue/with/slashes");

    assert.equal(
      String(calls[0].input),
      "/api/codex/issues/issue%2Fwith%2Fslashes/subagent-results",
    );
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

  await withMockFetch(mockMessages, async (calls) => {
    const result = await getAgentMesh("issue-1");

    assert.equal(result.length, 1);
    assert.equal(result[0].id, "msg-1");
    assert.equal(result[0].message_type, "handoff");
    assert.equal(calls.length, 1);
    assert.equal(
      String(calls[0].input),
      "/api/codex/issues/issue-1/agent-mesh",
    );
    assert.equal(calls[0].init, undefined);
  });
});

test("appendConductorMessage posts message to conductor message endpoint", async () => {
  await withMockFetch({ status: "ok" }, async (calls) => {
    const result = await appendConductorMessage("project-1", "Hello from user");

    assert.equal(result.status, "ok");
    assert.equal(calls.length, 1);
    assert.equal(
      String(calls[0].input),
      "/api/codex/projects/project-1/conductor/message",
    );
    assert.equal(calls[0].init?.method, "POST");
    assert.equal(
      calls[0].init?.headers &&
        (calls[0].init.headers as Record<string, string>)["Content-Type"],
      "application/json",
    );
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
      message: "Hello from user",
    });
  });
});

test("appendConductorMessage URL-encodes project ID", async () => {
  await withMockFetch({ status: "ok" }, async (calls) => {
    await appendConductorMessage("project/with/slashes", "test");

    assert.equal(
      String(calls[0].input),
      "/api/codex/projects/project%2Fwith%2Fslashes/conductor/message",
    );
  });
});
