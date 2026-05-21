import test from "node:test";
import assert from "node:assert/strict";

import type { CodexIssue } from "../src/lib/types";

/** Simulates the QA-passed filter logic from ApprovalsPage */
function filterQaPassedIssues(issues: CodexIssue[]): CodexIssue[] {
  return issues.filter((i) => i.status === "awaiting_review");
}

test("filterQaPassedIssues returns only issues with status awaiting_review", () => {
  const mockIssues: CodexIssue[] = [
    {
      id: "issue-1",
      session_id: "s1",
      project_id: null,
      title: "Fix login bug",
      description: "Login fails on mobile",
      current_phase: "testing",
      status: "awaiting_review",
      git_branch: "fix/login",
      git_base_branch: "main",
      git_worktree_path: null,
      git_merge_status: "open",
      git_last_commit_sha: "abc123",
      created_at: null,
      updated_at: null,
    },
    {
      id: "issue-2",
      session_id: "s1",
      project_id: null,
      title: "Add dark mode",
      description: "Add dark mode support",
      current_phase: "development",
      status: "in_progress",
      git_branch: "feat/dark-mode",
      git_base_branch: "main",
      git_worktree_path: null,
      git_merge_status: "open",
      git_last_commit_sha: "def456",
      created_at: null,
      updated_at: null,
    },
    {
      id: "issue-3",
      session_id: "s1",
      project_id: null,
      title: "Update deps",
      description: "Update dependencies",
      current_phase: "requirements",
      status: "awaiting_approval",
      git_branch: "chore/deps",
      git_base_branch: "main",
      git_worktree_path: null,
      git_merge_status: "open",
      git_last_commit_sha: null,
      created_at: null,
      updated_at: null,
    },
    {
      id: "issue-4",
      session_id: "s1",
      project_id: null,
      title: "Refactor API",
      description: "Clean up API layer",
      current_phase: "testing",
      status: "awaiting_review",
      git_branch: "refactor/api",
      git_base_branch: "main",
      git_worktree_path: null,
      git_merge_status: "open",
      git_last_commit_sha: "ghi789",
      created_at: null,
      updated_at: null,
    },
  ];

  const result = filterQaPassedIssues(mockIssues);

  assert.equal(result.length, 2, "should return exactly 2 issues");
  assert.equal(result[0].id, "issue-1", "first result should be issue-1");
  assert.equal(result[1].id, "issue-4", "second result should be issue-4");
  assert.ok(result.every((i) => i.status === "awaiting_review"), "all results should have awaiting_review status");
});

test("filterQaPassedIssues returns empty array when no awaiting_review issues exist", () => {
  const mockIssues: CodexIssue[] = [
    {
      id: "issue-5",
      session_id: "s1",
      project_id: null,
      title: "Some task",
      description: "Description",
      current_phase: "development",
      status: "in_progress",
      git_branch: null,
      git_base_branch: null,
      git_worktree_path: null,
      git_merge_status: "open",
      git_last_commit_sha: null,
      created_at: null,
      updated_at: null,
    },
  ];

  const result = filterQaPassedIssues(mockIssues);
  assert.equal(result.length, 0, "should return empty array");
});
