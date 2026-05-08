import test from "node:test";
import assert from "node:assert/strict";

import {
  buildConversationMessages,
  buildTaskConversationDetail,
} from "../src/hooks/taskConversationDetailUtils.js";

test("buildConversationMessages includes assistant deltas from logs", () => {
  const messages = [
    {
      id: "msg-user-1",
      role: "user",
      content: "你好",
      created_at: "2026-04-18T12:00:00Z",
    },
  ];
  const logs = [
    {
      id: "log-1",
      stream: "notification",
      content: JSON.stringify({
        method: "item/agentMessage/delta",
        params: {
          itemId: "item_1",
          delta: "你",
        },
      }),
      created_at: "2026-04-18T12:00:01Z",
    },
    {
      id: "log-2",
      stream: "notification",
      content: JSON.stringify({
        method: "item/agentMessage/delta",
        params: {
          itemId: "item_1",
          delta: "好",
        },
      }),
      created_at: "2026-04-18T12:00:02Z",
    },
  ];

  const result = buildConversationMessages(messages, logs);

  assert.equal(result.length, 2);
  assert.equal(result[0].role, "user");
  assert.equal(result[1].role, "assistant");
  assert.equal(result[1].content, "你好");
});

test("buildConversationMessages does not duplicate codex final assistant text after deltas", () => {
  const messages = [];
  const logs = [
    {
      id: "log-d1",
      execution_process_id: "proc-1",
      stream: "notification",
      content: JSON.stringify({
        method: "item/agentMessage/delta",
        params: { itemId: "item_1", delta: "p" },
      }),
      created_at: "2026-04-18T12:00:01Z",
    },
    {
      id: "log-d2",
      execution_process_id: "proc-1",
      stream: "notification",
      content: JSON.stringify({
        method: "item/agentMessage/delta",
        params: { itemId: "item_1", delta: "o" },
      }),
      created_at: "2026-04-18T12:00:02Z",
    },
    {
      id: "log-d3",
      execution_process_id: "proc-1",
      stream: "notification",
      content: JSON.stringify({
        method: "item/agentMessage/delta",
        params: { itemId: "item_1", delta: "n" },
      }),
      created_at: "2026-04-18T12:00:03Z",
    },
    {
      id: "log-d4",
      execution_process_id: "proc-1",
      stream: "notification",
      content: JSON.stringify({
        method: "item/agentMessage/delta",
        params: { itemId: "item_1", delta: "g" },
      }),
      created_at: "2026-04-18T12:00:04Z",
    },
    {
      id: "log-final",
      execution_process_id: "proc-1",
      stream: "notification",
      content: JSON.stringify({
        method: "item/completed",
        params: {
          item: {
            id: "item_1",
            type: "agentMessage",
            text: "pong",
          },
        },
      }),
      created_at: "2026-04-18T12:00:05Z",
    },
  ];

  const result = buildConversationMessages(messages, logs);

  assert.equal(result.length, 1);
  assert.equal(result[0].role, "assistant");
  assert.equal(result[0].content, "pong");
});

test("buildConversationMessages keeps assistant replies from different execution processes separate", () => {
  const messages = [];
  const logs = [
    {
      id: "log-p1",
      execution_process_id: "proc-1",
      stream: "notification",
      content: JSON.stringify({
        method: "item/completed",
        params: {
          item: {
            id: "item_1",
            type: "agentMessage",
            text: "pong",
          },
        },
      }),
      created_at: "2026-04-18T12:00:01Z",
    },
    {
      id: "log-p2",
      execution_process_id: "proc-2",
      stream: "notification",
      content: JSON.stringify({
        method: "item/completed",
        params: {
          item: {
            id: "item_2",
            type: "agentMessage",
            text: "pong",
          },
        },
      }),
      created_at: "2026-04-18T12:00:02Z",
    },
  ];

  const result = buildConversationMessages(messages, logs);

  assert.equal(result.length, 2);
  assert.equal(result[0].content, "pong");
  assert.equal(result[1].content, "pong");
});

test("buildTaskConversationDetail derives merged logs and messages from execution process views", () => {
  const detail = buildTaskConversationDetail(
    [
      {
        id: "task-msg-1",
        role: "user",
        content: "start",
        created_at: "2026-04-18T12:00:00Z",
      },
    ],
    [
      {
        id: "proc-1",
        messages: {
          "msg-1": {
            id: "msg-1",
            role: "assistant",
            content: "first reply",
            execution_process_id: "proc-1",
            created_at: "2026-04-18T12:00:01Z",
          },
        },
        logs: [
          {
            id: "log-1",
            content: "first log",
            created_at: "2026-04-18T12:00:01Z",
          },
        ],
      },
      {
        id: "proc-2",
        messages: {
          "msg-2": {
            id: "msg-2",
            role: "assistant",
            content: "second reply",
            execution_process_id: "proc-2",
            created_at: "2026-04-18T12:00:02Z",
          },
        },
        logs: [
          {
            id: "log-2",
            content: "second log",
            created_at: "2026-04-18T12:00:02Z",
          },
        ],
      },
    ],
  );

  assert.deepEqual(detail.logs.map((log) => log.id), ["log-1", "log-2"]);
  assert.deepEqual(
    detail.messages.map((message) => message.id),
    ["task-msg-1", "msg-1", "msg-2"],
  );
});
