import test from "node:test";
import assert from "node:assert/strict";

import {
  buildConversationMessages,
  buildTaskConversationDetail,
} from "../src/lib/taskConversationDetailUtils";
import type { CodexTask, CodexTaskMessage, ExecutionProcess } from "../src/lib/types";

function makeTask(id: string, issueId: string | null, status: string): CodexTask {
  return {
    id,
    session_id: "s1",
    project_id: null,
    issue_id: issueId,
    phase: "dev",
    title: `Task ${id}`,
    prompt: "",
    role: "engineer",
    executor: "codex",
    provider: null,
    model: null,
    status,
    result: null,
    parent_task_id: null,
    task_kind: "task",
    blocked_by_help_id: null,
    workspace_path: null,
    git_branch: null,
    git_base_branch: null,
    git_worktree_path: null,
    git_merge_status: "open" as any,
    git_last_commit_sha: null,
    resume_session_id: null,
    resume_message_id: null,
    last_execution_process_id: null,
    created_at: null,
    updated_at: null,
  };
}

function makeProcess(id: string, taskId: string, status: string): ExecutionProcess {
  return {
    id,
    task_id: taskId,
    session_id: "s1",
    status,
    exit_code: null,
    started_at: null,
    completed_at: null,
    created_at: null,
    updated_at: null,
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
  assert.equal(result[0].role, "user");
  assert.equal(result[1].role, "assistant");
  assert.equal(result[1].content, "你好");
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
  assert.equal(result[0].role, "assistant");
  assert.equal(result[0].content, "pong");
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
  assert.equal(result[0].content, "pong");
  assert.equal(result[1].content, "pong");
});

test("buildTaskConversationDetail derives merged logs and messages from execution process views", () => {
  const proc1 = {
    id: "proc-1",
    task_id: "task-1",
    session_id: "sess-1",
    status: "running",
    exit_code: null,
    started_at: null,
    completed_at: null,
    created_at: "2026-04-18T12:00:00Z",
    updated_at: null,
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
        content: "first log",
        created_at: "2026-04-18T12:00:01Z",
      },
    ],
  } as unknown as ExecutionProcess;

  const proc2 = {
    id: "proc-2",
    task_id: "task-1",
    session_id: "sess-1",
    status: "running",
    exit_code: null,
    started_at: null,
    completed_at: null,
    created_at: "2026-04-18T12:00:00Z",
    updated_at: null,
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
        content: "second log",
        created_at: "2026-04-18T12:00:02Z",
      },
    ],
  } as unknown as ExecutionProcess;

  const detail = buildTaskConversationDetail(
    [
      {
        id: "task-msg-1",
        task_id: "task-1",
        role: "user",
        content: "start",
        created_at: "2026-04-18T12:00:00Z",
        execution_process_id: null,
      },
    ],
    [proc1, proc2],
  );

  assert.deepEqual(detail.logs.map((log) => (log as { id: string }).id), ["log-1", "log-2"]);
  assert.deepEqual(
    detail.messages.map((message) => message.id),
    ["task-msg-1", "msg-1", "msg-2"],
  );
});
