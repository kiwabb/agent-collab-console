import test from "node:test";
import assert from "node:assert/strict";
import { at } from "./testAssertions";

import {
  buildConversationMessages,
  buildTaskConversationDetail,
} from "../src/lib/taskConversationDetailUtils";
import type { CodexTaskMessage, ExecutionProcess } from "../src/lib/types";

function executionProcessFixture(overrides: Partial<ExecutionProcess>): ExecutionProcess {
  return {
    id: "proc-1",
    task_id: "task-1",
    session_id: "sess-1",
    status: "running",
    exit_code: null,
    started_at: null,
    completed_at: null,
    created_at: "2026-04-18T12:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

test("buildConversationMessages includes assistant deltas from logs", () => {
  const messages: CodexTaskMessage[] = [
    {
      id: "msg-user-1",
      task_id: "task-1",
      role: "user",
      content: "你好",
      created_at: "2026-04-18T12:00:00Z",
      execution_process_id: null,
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
  assert.equal(at(result, 0, "conversation message").role, "user");
  const assistantMessage = at(result, 1, "conversation message");
  assert.equal(assistantMessage.role, "assistant");
  assert.equal(assistantMessage.content, "你好");
});

test("buildConversationMessages does not duplicate codex final assistant text after deltas", () => {
  const messages: CodexTaskMessage[] = [];
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
  const assistantMessage = at(result, 0, "conversation message");
  assert.equal(assistantMessage.role, "assistant");
  assert.equal(assistantMessage.content, "pong");
});

test("buildConversationMessages keeps assistant replies from different execution processes separate", () => {
  const messages: CodexTaskMessage[] = [];
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
  assert.equal(at(result, 0, "conversation message").content, "pong");
  assert.equal(at(result, 1, "conversation message").content, "pong");
});

test("buildTaskConversationDetail derives merged logs and messages from execution process views", () => {
  const taskMessages: CodexTaskMessage[] = [
    {
      id: "task-msg-1",
      task_id: "task-1",
      role: "user",
      content: "original request",
      execution_process_id: null,
      created_at: "2026-04-18T12:00:00Z",
    },
  ];
  const proc1 = executionProcessFixture({
    id: "proc-1",
    messages: {
      "msg-1": {
        id: "msg-1",
        task_id: "task-1",
        role: "assistant",
        content: "first reply",
        execution_process_id: "proc-1",
        created_at: "2026-04-18T12:00:01Z",
      },
    },
    logs: [
      {
        id: "log-1",
        session_id: "sess-1",
        stream: "stdout",
        content: "first log",
        task_id: "task-1",
        execution_process_id: "proc-1",
        created_at: "2026-04-18T12:00:01Z",
      },
    ],
  });

  const proc2 = executionProcessFixture({
    id: "proc-2",
    messages: {
      "msg-2": {
        id: "msg-2",
        task_id: "task-1",
        role: "assistant",
        content: "second reply",
        execution_process_id: "proc-2",
        created_at: "2026-04-18T12:00:02Z",
      },
    },
    logs: [
      {
        id: "log-2",
        session_id: "sess-1",
        stream: "stdout",
        content: "second log",
        task_id: "task-1",
        execution_process_id: "proc-2",
        created_at: "2026-04-18T12:00:02Z",
      },
    ],
  });

  const detail = buildTaskConversationDetail(taskMessages, [proc1, proc2]);

  assert.deepEqual(
    detail.logs.map((log) => log.id),
    ["log-1", "log-2"],
  );
  assert.deepEqual(
    detail.messages.map((message) => message.id),
    ["task-msg-1", "msg-1", "msg-2"],
  );
});

test("buildTaskConversationDetail tolerates process views without messages or logs", () => {
  const detail = buildTaskConversationDetail([], [executionProcessFixture({ id: "proc-empty" })]);

  assert.deepEqual(detail.messages, []);
  assert.deepEqual(detail.logs, []);
});

test("buildTaskConversationDetail keeps task messages when execution process list is empty", () => {
  const taskMessages: CodexTaskMessage[] = [
    {
      id: "task-msg-1",
      task_id: "task-1",
      role: "assistant",
      content: "persisted reply",
      execution_process_id: null,
      created_at: "2026-04-18T12:00:01Z",
    },
  ];

  const detail = buildTaskConversationDetail(taskMessages, []);

  assert.equal(detail.messages.length, 1);
  assert.equal(at(detail.messages, 0, "conversation message").content, "persisted reply");
  assert.deepEqual(detail.logs, []);
});
