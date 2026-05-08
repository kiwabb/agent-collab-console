import test from "node:test";
import assert from "node:assert/strict";

import { normalizeLogs } from "../src/lib/codexLogNormalizer";

test("notification logs are unwrapped into visible Codex entries", () => {
  const logs = [
    {
      stream: "notification",
      content: JSON.stringify({
        method: "turn/started",
        params: {
          threadId: "thread-1",
          turn: { id: "turn-1" },
        },
      }),
    },
    {
      stream: "notification",
      content: JSON.stringify({
        method: "item/completed",
        params: {
          item: {
            id: "item_0",
            type: "agent_message",
            text: "你好",
          },
        },
      }),
    },
  ];

  const entries = normalizeLogs(logs);

  assert.equal(entries.length, 2);
  assert.equal(entries[0].type, "status");
  assert.equal(entries[0].label, "started");
  assert.equal(entries[1].type, "assistant");
  assert.equal(entries[1].content, "你好");
});

test("notification logs accept camelCase Codex item types", () => {
  const logs = [
    {
      stream: "notification",
      content: JSON.stringify({
        method: "item/completed",
        params: {
          item: {
            id: "item_1",
            type: "agentMessage",
            text: "你好呀",
          },
        },
      }),
    },
    {
      stream: "notification",
      content: JSON.stringify({
        method: "item/completed",
        params: {
          item: {
            id: "item_2",
            type: "commandExecution",
            command: "echo hello",
            aggregated_output: "hello\n",
            exit_code: 0,
          },
        },
      }),
    },
  ];

  const entries = normalizeLogs(logs);

  assert.equal(entries.length, 2);
  assert.equal(entries[0].type, "assistant");
  assert.equal(entries[0].content, "你好呀");
  assert.equal(entries[1].type, "command");
  assert.equal(entries[1].status, "success");
  assert.equal(entries[1].output, "hello\n");
});

test("normalizeLogs tolerates realtime events with missing content", () => {
  const logs = [
    {
      stream: "notification",
      content: undefined,
    },
  ];

  const entries = normalizeLogs(logs);

  assert.equal(entries.length, 1);
  assert.equal(entries[0].type, "raw");
  assert.equal(entries[0].content, "");
});

test("normalizeLogs uses log ids to keep realtime keys unique", () => {
  const first = normalizeLogs([
    {
      id: "evt-1",
      stream: "notification",
      content: JSON.stringify({
        method: "turn/started",
        params: { turn: { id: "turn-1" } },
      }),
    },
  ]);
  const second = normalizeLogs([
    {
      id: "evt-2",
      stream: "notification",
      content: JSON.stringify({
        method: "turn/started",
        params: { turn: { id: "turn-2" } },
      }),
    },
  ]);

  assert.notEqual(first[0].id, second[0].id);
});

test("notification logs surface agent message delta events as assistant entries", () => {
  const entries = normalizeLogs([
    {
      id: "evt-delta-1",
      stream: "notification",
      content: JSON.stringify({
        method: "item/agentMessage/delta",
        params: {
          itemId: "item_4",
          delta: "你",
        },
      }),
    },
    {
      id: "evt-delta-2",
      stream: "notification",
      content: JSON.stringify({
        method: "item/agentMessage/delta",
        params: {
          itemId: "item_4",
          delta: "好",
        },
      }),
    },
  ]);

  assert.equal(entries.length, 1);
  assert.equal(entries[0].type, "assistant");
  assert.equal(entries[0].content, "你好");
});

test("notification error logs are visible error entries", () => {
  const entries = normalizeLogs([
    {
      id: "evt-error",
      stream: "notification",
      content: JSON.stringify({
        method: "error",
        params: {
          error: {
            message: "The 'gpt-5.5' model requires a newer version of Codex.",
          },
        },
      }),
    },
  ]);

  assert.equal(entries.length, 1);
  assert.equal(entries[0].type, "error");
  assert.match(entries[0].content || "", /gpt-5\.5/);
});

test("runtime and error streams become readable progress entries", () => {
  const entries = normalizeLogs([
    {
      id: "runtime-1",
      stream: "runtime",
      content: "Starting Codex turn",
    },
    {
      id: "error-1",
      stream: "error",
      content: "Codex app-server failed: boom",
    },
  ]);

  assert.equal(entries.length, 2);
  assert.equal(entries[0].type, "status");
  assert.equal(entries[0].label, "Runtime");
  assert.equal(entries[1].type, "error");
  assert.equal(entries[1].content, "Codex app-server failed: boom");
});
