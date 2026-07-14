import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { at } from "./testAssertions";
import {
  deriveAttentionItems,
  deriveIssueNextAction,
  deriveRunRecoveryActions,
} from "../src/features/workbench/interaction/interactionState";
import type { CodexIssue, CodexTask, ExecutionProcess } from "../src/lib/types";

function issueFixture(overrides: Partial<CodexIssue>): CodexIssue {
  return {
    id: "i1",
    session_id: "s1",
    project_id: null,
    title: "Issue",
    description: null,
    acceptance_criteria: [],
    acceptance_criteria_confirmed: false,
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

function taskFixture(overrides: Partial<CodexTask>): CodexTask {
  return {
    id: "t1",
    session_id: "s1",
    project_id: null,
    issue_id: null,
    phase: "requirements",
    title: "Task",
    prompt: "",
    role: "engineer",
    executor: "codex",
    status: "pending",
    result: null,
    parent_task_id: null,
    task_kind: "task",
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
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function processFixture(overrides: Partial<ExecutionProcess>): ExecutionProcess {
  return {
    id: "p1",
    task_id: "t1",
    session_id: "s1",
    status: "running",
    exit_code: null,
    started_at: null,
    completed_at: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

describe("interactionState", () => {
  it("prioritizes approvals, failures, and running work in attention items", () => {
    const items = deriveAttentionItems({
      issues: [
        issueFixture({
          id: "i1",
          title: "Needs review",
          status: "awaiting_approval",
          current_phase: "architecture",
          updated_at: "2026-05-22T08:00:00Z",
        }),
        issueFixture({
          id: "i2",
          title: "Broken run",
          status: "failed",
          current_phase: "development",
          updated_at: "2026-05-22T08:01:00Z",
        }),
        issueFixture({
          id: "i3",
          title: "Running",
          status: "in_progress",
          current_phase: "testing",
          updated_at: "2026-05-22T08:02:00Z",
        }),
      ],
      tasks: [],
      processes: [],
      approvals: [],
    });

    assert.deepEqual(
      items.map((item) => item.kind),
      ["approval", "failure", "running"],
    );
    assert.equal(at(items, 0, "attention item").href, "/issues/i1");
  });

  it("explains why issue next action is blocked by active task", () => {
    const action = deriveIssueNextAction({
      issue: issueFixture({
        id: "i1",
        status: "open",
        current_phase: "requirements",
        title: "Do it",
      }),
      tasks: [
        taskFixture({
          id: "t1",
          issue_id: "i1",
          role: "product_manager",
          status: "running",
        }),
      ],
      artifacts: [],
    });

    assert.equal(action.enabled, false);
    assert.match(action.disabledReason ?? "", /running/i);
  });

  it("offers rerun and logs recovery for failed processes", () => {
    const actions = deriveRunRecoveryActions({
      task: taskFixture({ id: "t1", status: "failed", executor: "codex" }),
      process: processFixture({ id: "p1", task_id: "t1", status: "failed" }),
    });

    assert.deepEqual(
      actions.map((action) => action.id),
      ["open_logs", "rerun_same", "change_executor"],
    );
  });
});
