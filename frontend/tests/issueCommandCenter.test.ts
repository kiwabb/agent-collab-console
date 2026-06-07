import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { buildDecisionTimeline } from "../src/features/issues/hooks/useDecisionTimeline";
import { deriveLatestFailure } from "../src/features/issues/hooks/useLatestFailure";
import type { CodexTask } from "../src/lib/types";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

function makeTask(overrides: Partial<CodexTask>): CodexTask {
  return {
    id: "task-1",
    session_id: "ws-1",
    project_id: null,
    issue_id: "issue-1",
    phase: "development",
    title: "Engineer",
    prompt: "",
    role: "engineer",
    executor: "codex",
    provider: null,
    model: null,
    status: "failed",
    result: "pytest failed",
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
    created_at: "2026-05-23T10:00:00Z",
    updated_at: "2026-05-23T10:01:00Z",
    ...overrides,
  };
}

test("issue detail page is a command-center over a 4-tab workbench", () => {
  const source = readSource("features/issues/IssueDetailPage.tsx");

  // The legacy six-tab components stay retired (no DAG/TasksRuns/Agent tabs).
  assert.doesNotMatch(source, /DagTab|TasksRunsTab|AgentTabContent/);
  // Command-center sections frame the workbench: status + failure alert on top,
  // chat bar docked below, dispatch detail in a drawer.
  assert.match(source, /<StatusStrip/);
  assert.match(source, /<LatestFailureAlert/);
  assert.match(source, /<WsConnectionBanner/);
  assert.match(source, /<CommandCenterChatBar/);
  assert.match(source, /<DispatchDrawer/);
  // Workbench is a 4-tab layout and honors ?tab=... deep links.
  assert.match(source, /useSearchParams/);
  assert.match(source, /value=\{activeTab\}/);
  assert.match(source, /onValueChange=\{handleTabChange\}/);
  assert.doesNotMatch(source, /defaultValue="timeline"/);
  assert.match(source, /<DecisionTimeline/);
  for (const value of ["timeline", "artifacts", "diff", "mesh"]) {
    assert.match(source, new RegExp(`value="${value}"`));
  }
});

test("issue detail page uses compact operations command-center chrome", () => {
  const pageSource = readSource("features/issues/IssueDetailPage.tsx");
  const statusSource = readSource("features/issues/components/StatusStrip.tsx");
  const sideStackSource = readSource("features/issues/components/IssueSideStack.tsx");
  const gitSource = readSource("features/issues/components/GitInfoCard.tsx");

  assert.match(statusSource, /data-density="command-header"/);
  assert.match(pageSource, /data-density="issue-workbench"/);
  assert.match(sideStackSource, /data-density="insight-rail"/);
  assert.match(gitSource, /data-density="git-ops"/);

  assert.doesNotMatch(pageSource, /radial-gradient|rounded-\[24px\]|rounded-2xl/);
  assert.doesNotMatch(statusSource, /agent-mesh-grid|Decorative ambient background glows|rounded-\[28px\]|blur-\[|animate-ping/);
  assert.doesNotMatch(sideStackSource, /rounded-\[24px\]|shadow-xl|animate-pulse|backdrop-blur-xl/);
  assert.doesNotMatch(gitSource, /rounded-\[24px\]|shadow-xl|animate-pulse|backdrop-blur-xl/);
});

test("decision timeline builds dispatch rows and latest failure clears after later success", () => {
  const timeline = buildDecisionTimeline(
    [
      {
        id: "turn-1",
        conductor_task_id: "cond-1",
        issue_id: "issue-1",
        turn_index: 1,
        sub_index: 0,
        kind: "tool_use",
        payload: { name: "dispatch_subagent", id: "tool-1", input: { role: "engineer" } },
        created_at: "2026-05-23T10:00:00Z",
      },
      {
        id: "turn-2",
        conductor_task_id: "cond-1",
        issue_id: "issue-1",
        turn_index: 1,
        sub_index: 1,
        kind: "tool_result",
        payload: { tool_use_id: "tool-1", output: { task_id: "task-1", status: "failed", error: "pytest failed" } },
        created_at: "2026-05-23T10:01:00Z",
      },
    ],
    [makeTask({})],
    [],
  );

  assert.equal(timeline[0]?.kind, "dispatch");
  assert.equal(timeline[0]?.status, "failed");
  assert.equal(deriveLatestFailure([makeTask({})], timeline)?.summary, "pytest failed");
  assert.equal(
    deriveLatestFailure(
      [
        makeTask({ id: "old", status: "failed", updated_at: "2026-05-23T10:01:00Z" }),
        makeTask({ id: "new", status: "done", updated_at: "2026-05-23T10:02:00Z" }),
      ],
      [],
    ),
    null,
  );
});
