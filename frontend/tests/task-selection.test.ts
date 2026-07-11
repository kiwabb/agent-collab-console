import test from "node:test";
import assert from "node:assert/strict";
import { at } from "./testAssertions";

import {
  groupIssuesByPhase,
  deriveIssueCounts,
  deriveTaskStatusSummary,
  getTaskRuntimeStatus,
  isTaskRuntimeActive,
  pickLatestExecutionProcessForTask,
  pickDisplayedExecutionProcess,
  PHASES,
} from "../src/lib/task-selection";
import type { CodexIssue, CodexTask, ExecutionProcess, HelpRequest } from "../src/lib/types";

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
    status,
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

test("groupIssuesByPhase groups issues by current_phase", () => {
  const issues: CodexIssue[] = [
    {
      id: "i1",
      session_id: "s1",
      project_id: null,
      title: "Issue 1",
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
    },
    {
      id: "i2",
      session_id: "s1",
      project_id: null,
      title: "Issue 2",
      description: null,
      acceptance_criteria: [],
      acceptance_criteria_confirmed: false,
      current_phase: "architecture",
      status: "open",
      git_branch: null,
      git_base_branch: null,
      git_worktree_path: null,
      git_merge_status: "open",
      git_last_commit_sha: null,
      created_at: null,
      updated_at: null,
    },
    {
      id: "i3",
      session_id: "s1",
      project_id: null,
      title: "Issue 3",
      description: null,
      acceptance_criteria: [],
      acceptance_criteria_confirmed: false,
      current_phase: "development",
      status: "open",
      git_branch: null,
      git_base_branch: null,
      git_worktree_path: null,
      git_merge_status: "open",
      git_last_commit_sha: null,
      created_at: null,
      updated_at: null,
    },
    {
      id: "i4",
      session_id: "s1",
      project_id: null,
      title: "Issue 4",
      description: null,
      acceptance_criteria: [],
      acceptance_criteria_confirmed: false,
      current_phase: "testing",
      status: "open",
      git_branch: null,
      git_base_branch: null,
      git_worktree_path: null,
      git_merge_status: "open",
      git_last_commit_sha: null,
      created_at: null,
      updated_at: null,
    },
  ];

  const result = groupIssuesByPhase(issues);

  assert.equal(result.requirements.length, 1);
  assert.equal(at(result.requirements, 0, "requirements issue").id, "i1");
  assert.equal(result.architecture.length, 1);
  assert.equal(at(result.architecture, 0, "architecture issue").id, "i2");
  assert.equal(result.development.length, 1);
  assert.equal(at(result.development, 0, "development issue").id, "i3");
  assert.equal(result.testing.length, 1);
  assert.equal(at(result.testing, 0, "testing issue").id, "i4");
});

test("groupIssuesByPhase defaults unknown phases to requirements", () => {
  const issues: CodexIssue[] = [
    {
      id: "i1",
      session_id: "s1",
      project_id: null,
      title: "Issue 1",
      description: null,
      acceptance_criteria: [],
      acceptance_criteria_confirmed: false,
      current_phase: "unknown_phase",
      status: "open",
      git_branch: null,
      git_base_branch: null,
      git_worktree_path: null,
      git_merge_status: "open",
      git_last_commit_sha: null,
      created_at: null,
      updated_at: null,
    },
  ];

  const result = groupIssuesByPhase(issues);

  assert.equal(result.requirements.length, 1);
  assert.equal(result.architecture.length, 0);
});

test("deriveIssueCounts counts tasks and processes for an issue", () => {
  const tasks = [
    makeTask("t1", "i1", "pending"),
    makeTask("t2", "i1", "running"),
    makeTask("t3", "i2", "pending"),
  ];
  const executionProcesses = [
    makeProcess("p1", "t1", "completed"),
    makeProcess("p2", "t2", "running"),
    makeProcess("p3", "t2", "failed"),
  ];
  const helpRequests: HelpRequest[] = [
    {
      id: "h1",
      workspace_id: "w1",
      parent_task_id: "t1",
      child_task_id: "t2",
      source_executor: "codex",
      target_executor: "claude",
      title: "Help",
      prompt: "",
      context_summary: null,
      status: "pending",
      error_message: null,
      continuation_payload: null,
      created_at: null,
      started_at: null,
      completed_at: null,
      timeout_at: null,
      consumed_at: null,
    },
  ];

  const counts = deriveIssueCounts("i1", tasks, executionProcesses, helpRequests);

  assert.equal(counts.total, 2);
  assert.equal(counts.running, 1);
  assert.equal(counts.failed, 1);
  assert.equal(counts.waiting, 0);
  assert.equal(counts.helpCount, 1);
});

test("deriveTaskStatusSummary counts tasks by status", () => {
  const tasks = [
    makeTask("t1", "i1", "pending"),
    makeTask("t2", "i1", "running"),
    makeTask("t3", "i1", "completed"),
    makeTask("t4", "i1", "failed"),
    makeTask("t5", "i1", "pending"),
  ];

  const summary = deriveTaskStatusSummary(tasks);

  assert.equal(summary.pending, 2);
  assert.equal(summary.running, 1);
  assert.equal(summary.completed, 1);
  assert.equal(summary.failed, 1);
});

test("pickDisplayedExecutionProcess returns selected process when currentProcessId is set", () => {
  const processes: ExecutionProcess[] = [
    {
      id: "p1",
      task_id: "t1",
      session_id: "s1",
      status: "completed",
      exit_code: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-04-18T10:00:00Z",
      updated_at: null,
    },
    {
      id: "p2",
      task_id: "t1",
      session_id: "s1",
      status: "running",
      exit_code: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-04-18T10:05:00Z",
      updated_at: null,
    },
  ];

  const result = pickDisplayedExecutionProcess(processes, "p1");

  assert.equal(result?.id, "p1");
});

test("pickDisplayedExecutionProcess falls back to newest process when no selection", () => {
  const processes: ExecutionProcess[] = [
    {
      id: "p1",
      task_id: "t1",
      session_id: "s1",
      status: "completed",
      exit_code: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-04-18T10:00:00Z",
      updated_at: null,
    },
    {
      id: "p2",
      task_id: "t1",
      session_id: "s1",
      status: "running",
      exit_code: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-04-18T10:05:00Z",
      updated_at: null,
    },
  ];

  const result = pickDisplayedExecutionProcess(processes, null);

  assert.equal(result?.id, "p2");
});

test("pickLatestExecutionProcessForTask returns the newest process for a task", () => {
  const processes: ExecutionProcess[] = [
    {
      id: "p1",
      task_id: "t1",
      session_id: "s1",
      status: "completed",
      exit_code: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-04-18T10:00:00Z",
      updated_at: null,
    },
    {
      id: "p2",
      task_id: "t1",
      session_id: "s1",
      status: "running",
      exit_code: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-04-18T10:05:00Z",
      updated_at: null,
    },
    {
      id: "p3",
      task_id: "t2",
      session_id: "s1",
      status: "running",
      exit_code: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-04-18T10:10:00Z",
      updated_at: null,
    },
  ];

  const result = pickLatestExecutionProcessForTask(processes, "t1");

  assert.equal(result?.id, "p2");
});

test("getTaskRuntimeStatus prefers the latest execution process over stale task status", () => {
  const task = makeTask("t1", "i1", "responding");
  const processes: ExecutionProcess[] = [
    {
      id: "p1",
      task_id: "t1",
      session_id: "s1",
      status: "completed",
      exit_code: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-04-18T10:05:00Z",
      updated_at: null,
    },
  ];

  const result = getTaskRuntimeStatus(task, processes);

  assert.equal(result, "completed");
});

test("getTaskRuntimeStatus preserves waiting states from task metadata", () => {
  const task = makeTask("t1", "i1", "waiting_for_help");
  const processes: ExecutionProcess[] = [
    {
      id: "p1",
      task_id: "t1",
      session_id: "s1",
      status: "completed",
      exit_code: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-04-18T10:05:00Z",
      updated_at: null,
    },
  ];

  const result = getTaskRuntimeStatus(task, processes);

  assert.equal(result, "waiting_for_help");
});

test("isTaskRuntimeActive uses the latest execution process instead of stale task status", () => {
  const task = makeTask("t1", "i1", "running");
  const processes: ExecutionProcess[] = [
    {
      id: "p1",
      task_id: "t1",
      session_id: "s1",
      status: "Completed",
      exit_code: 0,
      started_at: null,
      completed_at: "2026-04-18T10:05:00Z",
      created_at: "2026-04-18T10:00:00Z",
      updated_at: "2026-04-18T10:05:00Z",
    },
  ];

  const result = isTaskRuntimeActive(task, processes);

  assert.equal(result, false);
});

test("PHASES has the expected four phase values", () => {
  assert.deepEqual(PHASES, ["requirements", "architecture", "development", "testing"]);
});
