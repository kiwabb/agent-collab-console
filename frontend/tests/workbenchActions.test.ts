import test from "node:test";
import assert from "node:assert/strict";

import {
  createIssueAndInitialTask,
  runCodexTaskWithExecutor,
} from "../src/features/workbench/workbenchActions";
import {
  updateCodexTaskExecutor,
  chatCodexTask,
  refineCodexTask,
  rerunCodexTask,
  sendCodexTask,
} from "../src/lib/api";
import type { CodexTask } from "@/lib/types";
import { jsonRequestBody, withMockFetch } from "./fetchTestUtils";
import { at } from "./testAssertions";

test("createIssueAndInitialTask creates issue then auto-starts the DAG graph", async () => {
  const calls: string[] = [];

  const result = await createIssueAndInitialTask({
    workspaceId: "ws-1",
    title: "Add delete button",
    description: "Please add a delete action",
    createCodexIssue: async (workspaceId, title, description) => {
      calls.push(`issue:${workspaceId}:${title}:${description}`);
      return {
        id: "issue-1",
        session_id: workspaceId,
        project_id: null,
        title,
        description,
        current_phase: "requirements",
        status: "open",
        git_branch: null,
        git_base_branch: null,
        git_worktree_path: null,
        git_merge_status: "open",
        git_last_commit_sha: null,
        created_at: null,
        updated_at: null,
      };
    },
    autoStartIssueGraph: async (issueId) => {
      calls.push(`autoStart:${issueId}`);
      return {
        id: "graph-1",
        issue_id: issueId,
        preset_id: null,
        status: "running",
        dag_json: "{}",
        created_by: "console",
        locked_at: null,
        nodes: [],
        edges: [],
        created_at: null,
        updated_at: null,
      };
    },
  });

  assert.equal(result.issue.id, "issue-1");
  assert.deepEqual(calls, [
    "issue:ws-1:Add delete button:Please add a delete action",
    "autoStart:issue-1",
  ]);
});

test("chatCodexTask posts to /chat with content", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          message: { id: "m1" },
          assistant_message: null,
          task: { id: "t1" },
          execution_process: { id: "ep1", kind: "chat" },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    async (calls) => {
      const result = await chatCodexTask("t1", "你好");
      assert.equal(result.execution_process.kind, "chat");
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/codex/tasks/t1/chat");
      assert.equal(call.init?.method, "POST");
      assert.equal(jsonRequestBody(call)["content"], "你好");
    },
  );
});

test("refineCodexTask posts to /refine with content", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          message: { id: "m1" },
          assistant_message: null,
          task: { id: "t1" },
          execution_process: { id: "ep1", kind: "refine" },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    async (calls) => {
      const result = await refineCodexTask("t1", "加一条 X");
      assert.equal(result.execution_process.kind, "refine");
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/codex/tasks/t1/refine");
      assert.equal(call.init?.method, "POST");
      assert.equal(jsonRequestBody(call)["content"], "加一条 X");
    },
  );
});

test("sendCodexTask posts to /send with content (auto mode)", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          message: { id: "m1" },
          assistant_message: null,
          task: { id: "t1" },
          execution_process: { id: "ep1", kind: "chat" },
          resolved_mode: "chat",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    async (calls) => {
      const result = await sendCodexTask("t1", "你好");
      assert.equal(result.resolved_mode, "chat");
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/codex/tasks/t1/send");
      const body = jsonRequestBody(call);
      assert.equal(body["content"], "你好");
      assert.equal(body["force_mode"], undefined);
    },
  );
});

test("sendCodexTask passes force_mode in body when provided", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          message: { id: "m1" },
          assistant_message: null,
          task: { id: "t1" },
          execution_process: { id: "ep1", kind: "refine" },
          resolved_mode: "refine",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    async (calls) => {
      await sendCodexTask("t1", "改一下", "refine");
      const call = at(calls, 0, "fetch call");
      assert.equal(jsonRequestBody(call)["force_mode"], "refine");
    },
  );
});

test("rerunCodexTask posts to /rerun with executor overrides in body", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          message: null,
          assistant_message: null,
          task: { id: "t1" },
          execution_process: { id: "ep1", kind: "rerun" },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    async (calls) => {
      await rerunCodexTask("t1", {
        executor: "claude",
        provider: "anthropic",
        model: "claude-opus-4-7",
      });
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/codex/tasks/t1/rerun");
      assert.equal(call.init?.method, "POST");
      const body = jsonRequestBody(call);
      assert.equal(body["executor"], "claude");
      assert.equal(body["provider"], "anthropic");
      assert.equal(body["model"], "claude-opus-4-7");
    },
  );
});

test("rerunCodexTask posts to /rerun with no body", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          message: null,
          assistant_message: null,
          task: { id: "t1" },
          execution_process: { id: "ep1", kind: "rerun" },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    async (calls) => {
      const result = await rerunCodexTask("t1");
      assert.equal(result.execution_process.kind, "rerun");
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/codex/tasks/t1/rerun");
      assert.equal(call.init?.method, "POST");
      assert.equal(call.init?.body, undefined);
    },
  );
});

test("updateCodexTaskExecutor posts PATCH with executor to the update endpoint", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          id: "task-1",
          session_id: "ws-1",
          issue_id: "issue-1",
          phase: "development",
          title: "开发 - 购物车 - 实现购物车API",
          prompt: "实现购物车增删改查接口",
          role: "engineer",
          executor: "claude",
          provider: null,
          model: null,
          status: "pending",
          result: null,
          parent_task_id: null,
          task_kind: "normal",
          blocked_by_help_id: null,
          workspace_path: "/tmp",
          resume_session_id: null,
          resume_message_id: null,
          last_execution_process_id: null,
          sequence_index: 0,
          sequence_group: "issue-1",
          created_at: null,
          updated_at: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    async (calls) => {
      const result = await updateCodexTaskExecutor("task-1", "claude");
      assert.equal(result.executor, "claude");
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/codex/tasks/task-1");
      assert.equal(call.init?.method, "PATCH");
      assert.equal(jsonRequestBody(call)["executor"], "claude");
    },
  );
});

test("runCodexTaskWithExecutor skips update when executor unchanged", async () => {
  const calls: string[] = [];

  await runCodexTaskWithExecutor({
    taskId: "task-1",
    selectedExecutor: "codex",
    currentExecutor: "codex",
    selectedProvider: null,
    currentProvider: null,
    selectedModel: null,
    currentModel: null,
    updateTask: async (taskId, executor) => {
      calls.push(`update:${taskId}:${executor}`);
      return { id: taskId, executor } as CodexTask;
    },
    runTask: async (taskId) => {
      calls.push(`run:${taskId}`);
      return {
        id: "process-1",
        task_id: taskId,
        session_id: "ws-1",
        status: "Running",
        exit_code: null,
        started_at: null,
        completed_at: null,
        created_at: null,
        updated_at: null,
      };
    },
  });

  assert.deepEqual(calls, ["run:task-1"]);
});

test("runCodexTaskWithExecutor calls update then run when executor changed", async () => {
  const calls: string[] = [];

  await runCodexTaskWithExecutor({
    taskId: "task-1",
    selectedExecutor: "claude",
    currentExecutor: "codex",
    selectedProvider: null,
    currentProvider: null,
    selectedModel: null,
    currentModel: null,
    updateTask: async (taskId, executor) => {
      calls.push(`update:${taskId}:${executor}`);
      return { id: taskId, executor } as CodexTask;
    },
    runTask: async (taskId) => {
      calls.push(`run:${taskId}`);
      return {
        id: "process-1",
        task_id: taskId,
        session_id: "ws-1",
        status: "Running",
        exit_code: null,
        started_at: null,
        completed_at: null,
        created_at: null,
        updated_at: null,
      };
    },
  });

  assert.deepEqual(calls, ["update:task-1:claude", "run:task-1"]);
});

test("runCodexTaskWithExecutor does not call run when update fails", async () => {
  const calls: string[] = [];

  try {
    await runCodexTaskWithExecutor({
      taskId: "task-1",
      selectedExecutor: "claude",
      currentExecutor: "codex",
      selectedProvider: null,
      currentProvider: null,
      selectedModel: null,
      currentModel: null,
      updateTask: async (_taskId, _executor) => {
        calls.push("update:fail");
        throw new Error("Update failed");
      },
      runTask: async (taskId) => {
        calls.push(`run:${taskId}`);
        return {
          id: "process-1",
          task_id: taskId,
          session_id: "ws-1",
          status: "Running",
          exit_code: null,
          started_at: null,
          completed_at: null,
          created_at: null,
          updated_at: null,
        };
      },
    });
    assert.fail("Should have thrown");
  } catch (err) {
    assert.ok(err instanceof Error);
    assert.equal((err as Error).message, "Update failed");
    assert.deepEqual(calls, ["update:fail"]);
  }
});
