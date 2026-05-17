import test from "node:test";
import assert from "node:assert/strict";

import {
  deriveWorkspaceConsoleDefaultRuntime,
  deriveWorkspaceConsoleMode,
  formatWorkspaceConsoleRepoLabel,
  getWorkspaceConsoleRoleLabel,
  pickActiveIssueTask,
} from "../src/features/workspaces/workspaceConsoleState";
import type { CodexIssue, CodexTask, RuntimeCatalog } from "../src/lib/types";

function makeIssue(overrides: Partial<CodexIssue> = {}): CodexIssue {
  return {
    id: "issue-1",
    session_id: "ws-1",
    project_id: null,
    title: "Issue 1",
    description: null,
    current_phase: "requirements",
    status: "open",
    git_branch: null,
    git_base_branch: null,
    git_worktree_path: null,
    git_merge_status: "open",
    git_last_commit_sha: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function makeTask(overrides: Partial<CodexTask> = {}): CodexTask {
  return {
    id: "task-1",
    session_id: "ws-1",
    project_id: null,
    issue_id: "issue-1",
    phase: "requirements",
    title: "Task 1",
    prompt: "",
    role: "product_manager",
    executor: "codex",
    provider: null,
    model: null,
    status: "pending",
    result: null,
    parent_task_id: null,
    task_kind: "normal",
    blocked_by_help_id: null,
    workspace_path: null,
    git_branch: null,
    git_base_branch: null,
    git_worktree_path: null,
    git_merge_status: "open",
    git_last_commit_sha: null,
    resume_session_id: null,
    resume_message_id: null,
    last_execution_process_id: null,
    sequence_index: null,
    sequence_group: null,
    review_comment: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

test("deriveWorkspaceConsoleMode uses create when nothing is selected", () => {
  assert.equal(deriveWorkspaceConsoleMode(null), "create");
});

test("deriveWorkspaceConsoleMode uses chat when an issue is selected", () => {
  assert.equal(deriveWorkspaceConsoleMode("issue-1"), "chat");
});

test("deriveWorkspaceConsoleDefaultRuntime prefers the first enabled executor", () => {
  const catalog: RuntimeCatalog = {
    executors: [
      { id: "claude", label: "Claude", enabled: true, executor_type: "claude", default_model: "claude-sonnet", api_endpoint: null, api_key: null, providers: [], default_provider_id: null },
      { id: "codex", label: "Codex", enabled: true, executor_type: "codex", default_model: "gpt-5", api_endpoint: null, api_key: null, providers: [], default_provider_id: null },
    ],
  };

  assert.deepEqual(deriveWorkspaceConsoleDefaultRuntime(catalog), {
    executor: "claude",
    model: "claude-sonnet",
  });
});

test("deriveWorkspaceConsoleDefaultRuntime falls back to codex when catalog is absent", () => {
  assert.deepEqual(deriveWorkspaceConsoleDefaultRuntime(null), {
    executor: "codex",
    model: null,
  });
});

test("formatWorkspaceConsoleRepoLabel keeps the last two path segments", () => {
  assert.equal(
    formatWorkspaceConsoleRepoLabel("/Users/demo/src/agent-collab-console"),
    "~/src/agent-collab-console",
  );
});

test("getWorkspaceConsoleRoleLabel maps built-in workflow roles", () => {
  assert.equal(getWorkspaceConsoleRoleLabel("product_manager"), "PM");
  assert.equal(getWorkspaceConsoleRoleLabel("architect"), "Architect");
  assert.equal(getWorkspaceConsoleRoleLabel("engineer"), "Engineer");
  assert.equal(getWorkspaceConsoleRoleLabel("qa"), "QA");
});

test("pickActiveIssueTask prefers the in-flight task matching the issue phase", () => {
  const issue = makeIssue({ current_phase: "development" });
  const tasks = [
    makeTask({ id: "pm-1", role: "product_manager", phase: "requirements", status: "done", updated_at: "2026-05-17T10:00:00Z" }),
    makeTask({ id: "eng-1", role: "engineer", phase: "development", status: "running", updated_at: "2026-05-17T10:05:00Z" }),
    makeTask({ id: "qa-1", role: "qa", phase: "testing", status: "pending", updated_at: "2026-05-17T10:06:00Z" }),
  ];

  assert.equal(pickActiveIssueTask(issue, tasks)?.id, "eng-1");
});

test("pickActiveIssueTask falls back to the most recently updated task", () => {
  const issue = makeIssue({ current_phase: "development" });
  const tasks = [
    makeTask({ id: "pm-1", role: "product_manager", phase: "requirements", status: "done", updated_at: "2026-05-17T10:00:00Z" }),
    makeTask({ id: "qa-1", role: "qa", phase: "testing", status: "done", updated_at: "2026-05-17T10:06:00Z" }),
  ];

  assert.equal(pickActiveIssueTask(issue, tasks)?.id, "qa-1");
});
