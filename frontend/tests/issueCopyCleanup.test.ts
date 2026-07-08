import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

import { getDictionaryValue } from "../src/lib/i18n";

test("user-facing zh-CN issue copy uses demand wording", () => {
  assert.equal(
    getDictionaryValue("zh-CN", "issue.deleteConfirmBody"),
    "将删除该需求下的任务、执行记录、消息和需求产物，工作区源码不会被删除。",
  );
  assert.equal(
    getDictionaryValue("zh-CN", "projects.setupScriptHelp"),
    "每次创建需求或聊天 worktree 时在工作目录下执行（例如 npm install）。空着代表不跑。",
  );
  assert.equal(
    getDictionaryValue("zh-CN", "projects.repairHelp"),
    "清理 .git/worktrees 残留元数据，并重置 worktree 目录已消失的需求。",
  );
  assert.equal(getDictionaryValue("zh-CN", "projects.repairToast"), "修复完成 — 重置了 {n} 个需求");
  assert.equal(
    getDictionaryValue("zh-CN", "task.abandonHelp"),
    "保留需求记录，但删掉 worktree，标记为已放弃。可用作历史归档。",
  );
  assert.equal(getDictionaryValue("zh-CN", "task.abandonConfirmTitle"), "放弃这个需求？");
  assert.equal(
    getDictionaryValue("zh-CN", "task.abandonConfirmBody"),
    "将分支 {branch} 标为已放弃并删除其 worktree。需求记录会保留。",
  );
  assert.equal(
    getDictionaryValue("zh-CN", "help.step2.body"),
    '在工作区控制台底部输入你想要完成的事情（例如 <em>"添加一个 /api/ping 端点，返回 &#123;pong: true&#125;"</em>）然后按 <Kbd>↵</Kbd>。系统会自动在一个新分支上为每个需求创建一个 git worktree。',
  );
});

test("remaining issue-facing views are wired to i18n", () => {
  const issueBoard = readSource("features/issues/IssueBoard.tsx");
  const steerDialog = readSource("features/issues/components/SteerIssueDialog.tsx");
  const sideStack = readSource("features/issues/components/IssueSideStack.tsx");
  const inboxDashboard = readSource("features/inbox/InboxDashboard.tsx");

  assert.match(issueBoard, /t\("issue\.toast\.created"\)/);
  assert.match(issueBoard, /t\("issue\.import\.title"\)/);
  assert.match(issueBoard, /t\("issue\.bulkDelete\.title"\)/);
  assert.match(issueBoard, /t\("issue\.exportJson"\)/);
  assert.match(issueBoard, /t\("issue\.importAction"\)/);
  // Acceptance checklist now lives in IssueSideStack (post-refactor).
  assert.match(sideStack, /t\("issue\.side\.acceptance"\)/);
  assert.match(steerDialog, /t\("issue\.steerDialogTitle"\)/);
  assert.match(steerDialog, /t\("issue\.steerPlaceholder"\)/);
  assert.match(inboxDashboard, /useI18n/);
  assert.match(inboxDashboard, /t\("inbox\.firstRunTitle"\)/);
  assert.match(inboxDashboard, /t\("inbox\.firstRun\.openIssues"\)/);
  assert.match(inboxDashboard, /t\("inbox\.statusDistribution"\)/);
  assert.match(inboxDashboard, /t\(statusLabelKey\(issue\.status\)\)/);
});

test("complete frontend i18n pass exposes newly localized keys", () => {
  const cases = [
    ["zh-CN", "project.dashboard.newWorkspace", "新建工作区"],
    ["en-US", "project.dashboard.newWorkspace", "New workspace"],
    ["zh-CN", "taskExecution.toast.runFailed", "运行失败"],
    ["en-US", "taskExecution.toast.runFailed", "Run failed"],
    ["zh-CN", "issue.retryNodeTitle", "重试这个失败节点？"],
    ["en-US", "issue.retryNodeTitle", "Retry this failed node?"],
    ["zh-CN", "inbox.statusDistribution", "状态分布"],
    ["en-US", "inbox.statusDistribution", "Status distribution"],
  ] as const;

  cases.forEach(([locale, key, value]) => {
    assert.equal(getDictionaryValue(locale, key), value);
  });

  const projectDashboard = readSource("features/projects/ProjectDashboard.tsx");
  const taskExecutionSheet = readSource("features/workbench/components/TaskExecutionSheet.tsx");
  const tasksRunsTab = readSource("features/issues/tabs/TasksRunsTab.tsx");
  const dagTab = readSource("features/issues/tabs/DagTab.tsx");

  assert.match(projectDashboard, /t\("project\.dashboard\.workspaceCreateFailed"\)/);
  assert.match(taskExecutionSheet, /t\("taskExecution\.toast\.terminateFailed"\)/);
  assert.match(tasksRunsTab, /t\("task\.runDispatched"\)/);
  assert.match(tasksRunsTab, /t\("run\.emptyDescription"\)/);
  assert.match(dagTab, /t\("issue\.retryNodeBody"/);
});
