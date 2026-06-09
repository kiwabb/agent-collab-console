import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { buildDecisionTimeline } from "../src/features/issues/hooks/useDecisionTimeline";
import { deriveLatestFailure } from "../src/features/issues/hooks/useLatestFailure";
import { deriveTimelineExecutionSummary } from "../src/features/issues/components/deriveTimelineExecutionSummary";
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
  const timelineSource = readSource("features/issues/components/DecisionTimeline.tsx");
  const rowSource = readSource("features/issues/components/TimelineRow.tsx");
  const drawerSource = readSource("features/issues/components/DispatchDrawer.tsx");
  const chatSource = readSource("features/issues/components/CommandCenterChatBar.tsx");

  assert.match(statusSource, /data-density="command-header"/);
  assert.match(statusSource, /data-density="command-actions"/);
  assert.match(statusSource, /data-density="conductor-strip"/);
  assert.match(statusSource, /data-density="conductor-detail"/);
  assert.match(statusSource, /conductorStatus === "success"/);
  assert.match(statusSource, /phase\.phase === "done"/);
  assert.match(statusSource, /isConductorActive/);
  assert.match(statusSource, /<AgentThinkingIndicator/);
  assert.match(pageSource, /data-density="issue-workbench"/);
  assert.match(pageSource, /data-density=\{isWorkbenchSchedulingMotion \? "workbench-scheduling-tabs" : "workbench-tabs"\}/);
  assert.doesNotMatch(pageSource, /\?\? tasks\[0\]/);
  assert.match(sideStackSource, /data-density="insight-rail"/);
  assert.match(gitSource, /data-density="git-ops"/);
  assert.match(pageSource, /overflow-y-auto/);
  assert.match(pageSource, /2xl:grid-cols-\[minmax\(0,1fr\)_minmax\(320px,360px\)\]/);
  assert.doesNotMatch(pageSource, /hidden xl:flex/);
  assert.doesNotMatch(timelineSource, /overflow-y-auto|h-full|min-h-0|rounded-\[28px\]|rounded-2xl|shadow-\[/);
  assert.match(timelineSource, /data-timeline-execution-summary/);
  assert.match(timelineSource, /deriveTimelineExecutionSummary/);
  assert.doesNotMatch(rowSource, /truncate|line-clamp|max-h-36|rounded-2xl/);
  assert.match(rowSource, /isSchedulingMotion/);
  assert.match(rowSource, /data-density=\{isSchedulingMotion \? "decision-timeline-scheduling-row" : "decision-timeline-row"\}/);
  assert.match(rowSource, /isSchedulingMotion && "motion-essential"/);
  assert.match(rowSource, /animate-shimmer-sweep/);
  assert.match(rowSource, /phase=\{item\.kind === "dispatch" \? "dispatching" : "tool"\}/);
  assert.match(drawerSource, /isSchedulingDrawerMotion/);
  assert.match(drawerSource, /drawerMotionPhase/);
  assert.match(drawerSource, /data-density="dispatch-drawer-running"/);
  assert.match(drawerSource, /<AgentThinkingIndicator/);
  assert.match(drawerSource, /animate-shimmer-sweep/);
  assert.match(drawerSource, /phase=\{drawerMotionPhase\}/);

  assert.doesNotMatch(pageSource, /radial-gradient|rounded-\[24px\]|rounded-2xl/);
  assert.doesNotMatch(statusSource, /xl:grid-cols-\[minmax\(0,1\.2fr\)_minmax\(320px,0\.72fr\)_auto\]/);
  assert.doesNotMatch(statusSource, /line-clamp|agent-mesh-grid|Decorative ambient background glows|rounded-\[28px\]|blur-\[|animate-ping/);
  assert.doesNotMatch(sideStackSource, /rounded-\[24px\]|shadow-xl|animate-pulse|backdrop-blur-xl/);
  assert.doesNotMatch(gitSource, /rounded-\[24px\]|shadow-xl|animate-pulse|backdrop-blur-xl/);
  assert.doesNotMatch(chatSource, /rounded-2xl|rounded-xl/);
  assert.match(readSource("features/issues/hooks/useDecisionTimeline.ts"), /dispatch_batch/);
  assert.match(rowSource, /issue\.command\.timelineStatus\.info/);
  assert.match(rowSource, /issue\.command\.rationalePlan/);
});

test("workflow graph marks active dispatch batch lanes with scheduling motion", () => {
  const graphSource = readSource("features/workflow/WorkflowGraphView.tsx");
  const nodeSource = readSource("features/workflow/AgentDagNode.tsx");

  assert.match(graphSource, /isActiveSchedulingBatch/);
  assert.match(graphSource, /data-density="parallel-dispatch-lane"/);
  assert.match(graphSource, /<AgentThinkingIndicator/);
  assert.match(graphSource, /animate-shimmer-sweep/);
  assert.match(graphSource, /phase="dispatching"/);
  assert.match(nodeSource, /<AgentThinkingIndicator phase="dispatching" size=\{10\}/);
  assert.doesNotMatch(nodeSource, /animate-pulse/);
});

test("conductor monitor marks live conductor rows with scheduling motion", () => {
  const monitorSource = readSource("features/conductors/ConductorMonitorPage.tsx");

  assert.match(monitorSource, /isConductorDispatching/);
  assert.match(monitorSource, /data-density="conductor-monitor-row"/);
  assert.match(monitorSource, /<AgentThinkingIndicator/);
  assert.match(monitorSource, /animate-shimmer-sweep/);
  assert.match(monitorSource, /phase=\{s\.phase \?\? "dispatching"\}/);
  assert.doesNotMatch(monitorSource, /animate-pulse/);
});

test("conductor monitor loading state uses thinking motion", () => {
  const monitorSource = readSource("features/conductors/ConductorMonitorPage.tsx");

  assert.match(monitorSource, /data-density="conductor-monitor-loading"/);
  assert.match(monitorSource, /<AgentThinkingIndicator phase="thinking" size=\{15\}/);
  assert.match(monitorSource, /animate-shimmer-sweep/);
  assert.match(monitorSource, /motion-essential/);
  assert.doesNotMatch(monitorSource, /<Loader2 size=\{15\} className="animate-spin"/);
});

test("issue side activity marks running pipeline stages with scheduling motion", () => {
  const sideStackSource = readSource("features/issues/components/IssueSideStack.tsx");

  assert.match(sideStackSource, /isScheduling/);
  assert.match(sideStackSource, /data-density=\{evt\.isScheduling \? "insight-activity-scheduling" : "insight-activity-event"\}/);
  assert.match(sideStackSource, /<AgentThinkingIndicator/);
  assert.match(sideStackSource, /animate-shimmer-sweep/);
  assert.match(sideStackSource, /phase="dispatching"/);
  assert.match(sideStackSource, /motion-essential/);
  assert.doesNotMatch(sideStackSource, /animate-pulse/);
});

test("command chat bar marks conductor clarification with scheduling motion", () => {
  const chatSource = readSource("features/issues/components/CommandCenterChatBar.tsx");

  assert.match(chatSource, /data-density="conductor-clarification-banner"/);
  assert.match(chatSource, /<AgentThinkingIndicator/);
  assert.match(chatSource, /animate-shimmer-sweep/);
  assert.match(chatSource, /phase="thinking"/);
  assert.match(chatSource, /motion-essential/);
});

test("command chat bar send cta uses thinking motion while sending", () => {
  const chatSource = readSource("features/issues/components/CommandCenterChatBar.tsx");

  assert.match(chatSource, /data-density=\{sending \? "command-chat-send-thinking" : "command-chat-send"\}/);
  assert.match(chatSource, /sending && "motion-essential"/);
  assert.match(chatSource, /<AgentThinkingIndicator phase="thinking" size=\{14\}/);
  assert.doesNotMatch(chatSource, /sending \? <Loader2 size=\{14\} className="animate-spin"/);
});

test("conductor chat bar uses thinking motion while sending", () => {
  const chatSource = readSource("features/issues/components/ConductorChatBar.tsx");

  assert.match(chatSource, /<AgentThinkingIndicator phase="thinking" size=\{14\}/);
  assert.doesNotMatch(chatSource, /<Loader2 size=\{14\} className="animate-spin"/);
});

test("steer issue dialog send cta uses thinking motion while sending", () => {
  const dialogSource = readSource("features/issues/components/SteerIssueDialog.tsx");

  assert.match(dialogSource, /data-density=\{sending \? "steer-issue-send-thinking" : "steer-issue-send"\}/);
  assert.match(dialogSource, /sending && "motion-essential"/);
  assert.match(dialogSource, /<AgentThinkingIndicator phase="thinking" size=\{12\}/);
  assert.doesNotMatch(dialogSource, /<Loader2 size=\{12\} className="animate-spin"/);
});

test("agent decision drawer loading state uses thinking motion", () => {
  const drawerSource = readSource("features/issues/components/AgentDecisionDrawer.tsx");

  assert.match(drawerSource, /data-density="agent-decision-loading"/);
  assert.match(drawerSource, /<AgentThinkingIndicator phase="thinking" size=\{14\}/);
  assert.match(drawerSource, /animate-shimmer-sweep/);
  assert.match(drawerSource, /motion-essential/);
  assert.doesNotMatch(drawerSource, /<Loader2 size=\{14\} className="animate-spin"/);
});

test("issue workbench tabs surface active conductor scheduling motion", () => {
  const pageSource = readSource("features/issues/IssueDetailPage.tsx");

  assert.match(pageSource, /isWorkbenchSchedulingMotion/);
  assert.match(pageSource, /workbenchMotionPhase/);
  assert.match(pageSource, /data-density=\{isWorkbenchSchedulingMotion \? "workbench-scheduling-tabs" : "workbench-tabs"\}/);
  assert.match(pageSource, /data-density="workbench-scheduling-tab"/);
  assert.match(pageSource, /<AgentThinkingIndicator/);
  assert.match(pageSource, /animate-shimmer-sweep/);
  assert.match(pageSource, /phase=\{workbenchMotionPhase\}/);
  assert.match(pageSource, /motion-essential/);
});

test("mesh feed marks active specialist calls with dispatch motion", () => {
  const feedSource = readSource("features/issues/tabs/CollabFeedTab.tsx");

  assert.match(feedSource, /isActiveSpecialistDispatch/);
  assert.match(feedSource, /data-density=\{isActiveSpecialistDispatch \? "mesh-specialist-dispatch" : "mesh-agent-message"\}/);
  assert.match(feedSource, /<AgentThinkingIndicator/);
  assert.match(feedSource, /animate-shimmer-sweep/);
  assert.match(feedSource, /phase="dispatching"/);
  assert.match(feedSource, /motion-essential/);
  assert.doesNotMatch(feedSource, /animate-pulse/);
});

test("dispatch drawer action buttons use semantic motion while busy", () => {
  const drawerSource = readSource("features/issues/components/DispatchDrawer.tsx");

  assert.match(drawerSource, /busyAction === "chat" \? \(\s*<AgentThinkingIndicator phase="thinking" size=\{13\}/);
  assert.match(drawerSource, /busyAction === "refine" \? \(\s*<AgentThinkingIndicator phase="thinking" size=\{13\}/);
  assert.match(drawerSource, /busyAction === "rerun" \? \(\s*<AgentThinkingIndicator phase="dispatching" size=\{13\}/);
  assert.doesNotMatch(drawerSource, /busyAction === "(chat|refine|rerun)" \? \(\s*<Loader2 size=\{13\} className="animate-spin"/);
});

test("dispatch drawer running summary uses semantic motion without spinner fallback", () => {
  const drawerSource = readSource("features/issues/components/DispatchDrawer.tsx");

  assert.match(drawerSource, /data-density="dispatch-drawer-running"/);
  assert.match(drawerSource, /<AgentThinkingIndicator phase=\{drawerMotionPhase\} size=\{16\}/);
  assert.match(drawerSource, /animate-shimmer-sweep/);
  assert.match(drawerSource, /motion-essential/);
  assert.doesNotMatch(drawerSource, /<Loader2 size=\{16\} className="animate-spin text-brand shrink-0"/);
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

test("decision timeline labels dispatch_batch as a parallel execution plan", () => {
  const timeline = buildDecisionTimeline(
    [
      {
        id: "turn-0",
        conductor_task_id: "cond-1",
        issue_id: "issue-1",
        turn_index: 1,
        sub_index: 0,
        kind: "llm_response",
        payload: {
          content: [
            {
              type: "text",
              text: "**Analysis:** three files are independent.\n\n**Plan:** dispatch in parallel.",
            },
          ],
        },
        created_at: "2026-05-23T10:00:00Z",
      },
      {
        id: "turn-1",
        conductor_task_id: "cond-1",
        issue_id: "issue-1",
        turn_index: 1,
        sub_index: 1,
        kind: "tool_use",
        payload: {
          name: "dispatch_batch",
          id: "tool-1",
          input: {
            agents: [
              { role: "engineer" },
              { role: "engineer" },
              { role: "engineer" },
            ],
          },
        },
        created_at: "2026-05-23T10:00:01Z",
      },
      {
        id: "turn-2",
        conductor_task_id: "cond-1",
        issue_id: "issue-1",
        turn_index: 1,
        sub_index: 2,
        kind: "tool_result",
        payload: { tool_use_id: "tool-1", output: { status: "success" } },
        created_at: "2026-05-23T10:00:02Z",
      },
    ],
    [],
    [],
  );

  assert.equal(timeline[0]?.kind, "dispatch");
  assert.equal(timeline[0]?.role, "conductor");
  assert.equal(timeline[0]?.status, "done");
  assert.equal(timeline[0]?.titleKey, "issue.command.title.dispatchBatchCount");
  assert.deepEqual(timeline[0]?.titleParams, { count: 3 });
  assert.equal(timeline[0]?.summaryKey, "issue.command.summary.dispatchBatchCount");
  assert.deepEqual(timeline[0]?.summaryParams, { count: 3 });
  assert.match(timeline[0]?.rationale ?? "", /Analysis/);
});

test("decision timeline expands dispatch_batch engineer tasks into visible rows", () => {
  const timeline = buildDecisionTimeline(
    [
      {
        id: "turn-1",
        conductor_task_id: "cond-1",
        issue_id: "issue-1",
        turn_index: 1,
        sub_index: 1,
        kind: "tool_use",
        payload: {
          name: "dispatch_batch",
          id: "tool-1",
          input: {
            agents: [
              { role: "engineer" },
              { role: "engineer" },
              { role: "engineer" },
            ],
          },
        },
        created_at: "2026-05-23T10:00:01Z",
      },
      {
        id: "turn-2",
        conductor_task_id: "cond-1",
        issue_id: "issue-1",
        turn_index: 1,
        sub_index: 2,
        kind: "tool_result",
        payload: { tool_use_id: "tool-1", output: { status: "success" } },
        created_at: "2026-05-23T10:00:02Z",
      },
    ],
    [
      makeTask({ id: "eng-a", role: "engineer", status: "done", result: "created module_a.py", created_at: "2026-05-23T10:00:03Z" }),
      makeTask({ id: "eng-b", role: "engineer", status: "pending", result: null, created_at: "2026-05-23T10:00:04Z" }),
      makeTask({ id: "eng-c", role: "engineer", status: "running", result: null, created_at: "2026-05-23T10:00:05Z" }),
    ],
    [
      {
        task_id: "eng-a",
        role: "engineer",
        title: "Engineer A",
        status: "done",
        task_kind: "normal",
        parent_task_id: null,
        summary: "{\"status\":\"completed\",\"summary\":\"Created module_a.py\"}",
        artifact_json: null,
        updated_at: "2026-05-23T10:00:10Z",
      },
    ],
  );

  const engineerRows = timeline.filter((item) => item.role === "engineer");

  assert.equal(engineerRows.length, 3);
  assert.deepEqual(engineerRows.map((item) => item.taskId), ["eng-a", "eng-b", "eng-c"]);
  assert.deepEqual(engineerRows.map((item) => item.titleKey), [
    "issue.command.title.developmentTask",
    "issue.command.title.developmentTask",
    "issue.command.title.developmentTask",
  ]);
  assert.deepEqual(engineerRows.map((item) => item.titleParams), [{ index: 1 }, { index: 2 }, { index: 3 }]);
  assert.deepEqual(engineerRows.map((item) => item.status), ["done", "waiting", "running"]);
  assert.equal(engineerRows[0]?.summary, "Created module_a.py");
  assert.equal(engineerRows[1]?.summaryKey, "issue.command.summary.developmentTaskWaiting");
  assert.equal(engineerRows[2]?.summaryKey, "issue.command.summary.developmentTaskRunning");
});

test("decision timeline treats queued batch tasks as waiting work", () => {
  const timeline = buildDecisionTimeline(
    [
      {
        id: "turn-1",
        conductor_task_id: "cond-1",
        issue_id: "issue-1",
        turn_index: 1,
        sub_index: 1,
        kind: "tool_use",
        payload: {
          name: "dispatch_batch",
          id: "tool-1",
          input: {
            agents: [
              { role: "engineer" },
              { role: "qa" },
            ],
          },
        },
        created_at: "2026-05-23T10:00:01Z",
      },
      {
        id: "turn-2",
        conductor_task_id: "cond-1",
        issue_id: "issue-1",
        turn_index: 1,
        sub_index: 2,
        kind: "tool_result",
        payload: { tool_use_id: "tool-1", output: { status: "success" } },
        created_at: "2026-05-23T10:00:02Z",
      },
    ],
    [
      makeTask({ id: "eng-queued", role: "engineer", status: "queued", result: null, created_at: "2026-05-23T10:00:03Z" }),
      makeTask({ id: "qa-created", role: "qa", status: "created", result: null, created_at: "2026-05-23T10:00:04Z" }),
    ],
    [],
  );

  const queuedRows = timeline.filter((item) => item.id.startsWith("task:"));

  assert.deepEqual(queuedRows.map((item) => item.status), ["waiting", "waiting"]);
  assert.deepEqual(queuedRows.map((item) => item.summaryKey), [
    "issue.command.summary.developmentTaskWaiting",
    "issue.command.summary.batchTaskWaiting",
  ]);
});

test("decision timeline execution summary surfaces dispatched development, QA, and finalize", () => {
  const summary = deriveTimelineExecutionSummary([
    {
      kind: "dispatch",
      role: "conductor",
      status: "info",
      titleKey: "issue.command.title.dispatchBatchCount",
      titleParams: { count: 3 },
    },
    {
      kind: "dispatch",
      role: "qa",
      status: "done",
      titleKey: "issue.command.title.dispatch",
    },
    {
      kind: "finalize",
      role: "conductor",
      status: "done",
      titleKey: "issue.command.title.finalize",
    },
  ]);

  assert.deepEqual(summary, {
    developmentDispatched: 3,
    qaDone: 1,
    finalized: true,
  });
});
