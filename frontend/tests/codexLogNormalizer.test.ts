import test from "node:test";
import assert from "node:assert/strict";

import { normalizeLogs } from "../src/lib/codexLogNormalizer";
import { at } from "./testAssertions";

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
  const firstEntry = at(entries, 0, "normalized entry");
  const secondEntry = at(entries, 1, "normalized entry");
  assert.equal(firstEntry.type, "status");
  assert.equal(firstEntry.label, "started");
  assert.equal(secondEntry.type, "assistant");
  assert.equal(secondEntry.content, "你好");
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
  const firstEntry = at(entries, 0, "normalized entry");
  const secondEntry = at(entries, 1, "normalized entry");
  assert.equal(firstEntry.type, "assistant");
  assert.equal(firstEntry.content, "你好呀");
  assert.equal(secondEntry.type, "command");
  assert.equal(secondEntry.status, "success");
  assert.equal(secondEntry.output, "hello\n");
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
  const firstEntry = at(entries, 0, "normalized entry");
  assert.equal(firstEntry.type, "raw");
  assert.equal(firstEntry.content, "");
});

test("normalizeLogs treats malformed or non-object JSON as raw output", () => {
  const entries = normalizeLogs([
    {
      id: "array-json",
      stream: "stdout",
      content: '["not","an","event"]',
    },
    {
      id: "bad-json",
      stream: "stdout",
      content: "{bad",
    },
  ]);

  assert.equal(entries.length, 2);
  const firstEntry = at(entries, 0, "normalized entry");
  const secondEntry = at(entries, 1, "normalized entry");
  assert.equal(firstEntry.type, "raw");
  assert.equal(firstEntry.content, '["not","an","event"]');
  assert.equal(secondEntry.type, "raw");
  assert.equal(secondEntry.content, "{bad");
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

  assert.notEqual(
    at(first, 0, "first normalized entry").id,
    at(second, 0, "second normalized entry").id,
  );
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
  const firstEntry = at(entries, 0, "normalized entry");
  assert.equal(firstEntry.type, "assistant");
  assert.equal(firstEntry.content, "你好");
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
  const firstEntry = at(entries, 0, "normalized entry");
  assert.equal(firstEntry.type, "error");
  assert.match(firstEntry.content || "", /gpt-5\.5/);
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
  const firstEntry = at(entries, 0, "normalized entry");
  const secondEntry = at(entries, 1, "normalized entry");
  assert.equal(firstEntry.type, "status");
  assert.equal(firstEntry.label, "Runtime");
  assert.equal(secondEntry.type, "error");
  assert.equal(secondEntry.content, "Codex app-server failed: boom");
});
