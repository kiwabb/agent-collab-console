import test from "node:test";
import assert from "node:assert/strict";

import { createIssueAndInitialTask, runCodexTaskWithExecutor } from "../src/features/workbench/workbenchActions";
import { transitionIssueToArchitecture, transitionIssueToDevelopment } from "../src/lib/api";
import type { CodexTask } from "@/lib/types";

test("createIssueAndInitialTask runs the initial task after creating it", async () => {
  const calls: string[] = [];

  const result = await createIssueAndInitialTask({
    workspaceId: "ws-1",
    title: "Add delete button",
    description: "Please add a delete action",
    executor: "codex",
    issueTitle: "Requirements - Add delete button",
    createCodexIssue: async (workspaceId, title, description) => {
      calls.push(`issue:${workspaceId}:${title}:${description}`);
      return {
        id: "issue-1",
        session_id: workspaceId,
        title,
        description,
        current_phase: "requirements",
        status: "open",
        created_at: null,
        updated_at: null,
      };
    },
    createCodexTask: async (workspaceId, title, prompt, parentTaskId, executor, role, issueId, phase) => {
      calls.push(`task:${workspaceId}:${title}:${prompt}:${parentTaskId}:${executor}:${role}:${issueId}:${phase}`);
      return {
        id: "task-1",
        session_id: workspaceId,
        issue_id: issueId,
        phase,
        title,
        prompt,
        role,
        executor,
        status: "pending",
        result: null,
        parent_task_id: parentTaskId,
        task_kind: "normal",
        blocked_by_help_id: null,
        workspace_path: null,
        resume_session_id: null,
        resume_message_id: null,
        last_execution_process_id: null,
        created_at: null,
        updated_at: null,
      };
    },
    runCodexTask: async (taskId) => {
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

  assert.equal(result.issue.id, "issue-1");
  assert.equal(result.initialTask.id, "task-1");
  assert.equal(result.initialTask.last_execution_process_id, "process-1");
  assert.equal(result.executionProcess.id, "process-1");
  assert.deepEqual(calls, [
    "issue:ws-1:Add delete button:Please add a delete action",
    "task:ws-1:Requirements - Add delete button:Please add a delete action:null:codex:product_manager:issue-1:requirements",
    "run:task-1",
  ]);
});

test("transitionIssueToArchitecture posts to the transition endpoint", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];

  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        issue: {
          id: "issue-1",
          session_id: "ws-1",
          title: "Add delete button",
          description: "Please add a delete action",
          current_phase: "architecture",
          status: "open",
          created_at: null,
          updated_at: null,
        },
        task: null,
        created: false,
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    );
  };

  try {
    const result = await transitionIssueToArchitecture("issue-1");
    assert.equal(result.issue.current_phase, "architecture");
    assert.equal(calls.length, 1);
    assert.equal(String(calls[0].input), "/api/codex/issues/issue-1/transition-to-architecture");
    assert.equal(calls[0].init?.method, "POST");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("transitionIssueToArchitecture returns a pending architect task that can be run later", async () => {
  const originalFetch = globalThis.fetch;

  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        issue: {
          id: "issue-1",
          session_id: "ws-1",
          title: "Add delete button",
          description: "Please add a delete action",
          current_phase: "architecture",
          status: "open",
          created_at: null,
          updated_at: null,
        },
        task: {
          id: "task-arch-1",
          session_id: "ws-1",
          issue_id: "issue-1",
          phase: "architecture",
          title: "架构 - Add delete button",
          prompt: "请基于当前需求产物进行架构设计。",
          role: "architect",
          executor: "codex",
          status: "pending",
          result: null,
          parent_task_id: null,
          task_kind: "normal",
          blocked_by_help_id: null,
          workspace_path: "/tmp/ws-1",
          resume_session_id: null,
          resume_message_id: null,
          last_execution_process_id: null,
          created_at: null,
          updated_at: null,
        },
        created: true,
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    );

  try {
    const result = await transitionIssueToArchitecture("issue-1");
    assert.equal(result.created, true);
    assert.equal(result.task?.status, "pending");
    assert.equal(result.task?.last_execution_process_id, null);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("transitionIssueToDevelopment posts to the development transition endpoint", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];

  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        issue: {
          id: "issue-1",
          session_id: "ws-1",
          title: "Add dashboard",
          description: "Build dashboard",
          current_phase: "development",
          status: "open",
          created_at: null,
          updated_at: null,
        },
        tasks: [],
        created: true,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const result = await transitionIssueToDevelopment("issue-1");
    assert.equal(result.issue.current_phase, "development");
    assert.equal(String(calls[0].input), "/api/codex/issues/issue-1/transition-to-development");
    assert.equal(calls[0].init?.method, "POST");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("updateCodexTaskExecutor posts PATCH with executor to the update endpoint", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];

  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        id: "task-1",
        session_id: "ws-1",
        issue_id: "issue-1",
        phase: "development",
        title: "开发 - 购物车 - 实现购物车API",
        prompt: "实现购物车增删改查接口",
        role: "engineer",
        executor: "claude",
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
    );
  };

  try {
    const result = await import("../src/lib/api").then(m => m.updateCodexTaskExecutor("task-1", "claude"));
    assert.equal(result.executor, "claude");
    assert.equal(String(calls[0].input), "/api/codex/tasks/task-1");
    assert.equal(calls[0].init?.method, "PATCH");
    const body = JSON.parse(calls[0].init?.body as string);
    assert.equal(body.executor, "claude");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("runCodexTaskWithExecutor skips update when executor unchanged", async () => {
  const calls: string[] = [];

  await runCodexTaskWithExecutor({
    taskId: "task-1",
    selectedExecutor: "codex",
    currentExecutor: "codex",
    updateExecutor: async (taskId, executor) => {
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
    updateExecutor: async (taskId, executor) => {
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
      updateExecutor: async (_taskId, _executor) => {
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
