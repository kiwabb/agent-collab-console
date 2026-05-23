import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { getDictionaryValue } from "../src/lib/i18n";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

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
  assert.equal(
    getDictionaryValue("zh-CN", "projects.repairToast"),
    "修复完成 — 重置了 {n} 个需求",
  );
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
    "在工作区控制台底部输入你想要完成的事情（例如 <em>\"添加一个 /api/ping 端点，返回 &#123;pong: true&#125;\"</em>）然后按 <Kbd>↵</Kbd>。系统会自动在一个新分支上为每个需求创建一个 git worktree。",
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
  // Acceptance checklist now lives in IssueSideStack (post-refactor).
  assert.match(sideStack, /t\("issue\.side\.acceptance"\)/);
  assert.match(steerDialog, /t\("issue\.steerDialogTitle"\)/);
  assert.match(steerDialog, /t\("issue\.steerPlaceholder"\)/);
  assert.match(inboxDashboard, /useI18n/);
  assert.match(inboxDashboard, /t\("inbox\.firstRunTitle"\)/);
  assert.match(inboxDashboard, /t\("inbox\.firstRun\.openIssues"\)/);
});
