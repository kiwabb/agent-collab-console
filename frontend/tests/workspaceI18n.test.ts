import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { getDictionaryValue } from "../src/lib/i18n";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("project workspace table strings come from i18n keys", () => {
  const source = readSource("features/projects/ProjectWorkspacesPage.tsx");

  [
    't("workspace.projectPage.new")',
    't("workspace.projectPage.searchPlaceholder")',
    't("workspace.table.title")',
    't("workspace.table.status")',
    't("workspace.table.issues")',
    't("workspace.table.workingDir")',
    't("workspace.table.updated")',
    't("workspace.table.actions")',
    't("workspace.emptyFiltered")',
    't("workspace.emptyCreatePrompt")',
    't("workspace.createFirst")',
    't("workspace.dialog.newTitle")',
    't("workspace.dialog.editTitle")',
    't("workspace.dialog.deleteTitle")',
    't("workspace.dialog.planFirstPm")',
  ].forEach((needle) => {
    assert.match(source, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });
});

test("workspace sidebar and board actions come from i18n keys", () => {
  const sidebar = readSource("features/workspaces/WorkspaceSidebar.tsx");
  const board = readSource("features/workspaces/WorkspaceBoard.tsx");

  [
    't("sidebar.workspaces")',
    't("workspace.refresh")',
    't("workspace.new")',
    't("workspace.namePlaceholder")',
    't("workspace.create")',
    't("workspace.cancel")',
    't("workspace.empty")',
    't("workspace.deleteAllData")',
    't("workspace.dialog.deleteSingleTitle")',
    't("workspace.dialog.deleteAllTitle")',
  ].forEach((needle) => {
    assert.match(sidebar, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });

  [
    't("workspace.export")',
    't("workspace.import")',
  ].forEach((needle) => {
    assert.match(board, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });
});

test("workspace translation keys are available in English", () => {
  assert.equal(getDictionaryValue("en-US", "workspace.projectPage.new"), "New workspace");
  assert.equal(getDictionaryValue("en-US", "workspace.table.workingDir"), "Working dir");
  assert.equal(getDictionaryValue("en-US", "workspace.dialog.deleteTitle"), "Delete workspace?");
  assert.equal(getDictionaryValue("en-US", "workspace.deleteAllData"), "Clean all data");
  assert.equal(getDictionaryValue("en-US", "workspace.console.createAndStart"), "Create and start ↵");
  assert.equal(getDictionaryValue("en-US", "workspace.dialog.planFirstPm"), "Pause after PM");
});

test("workspace console strings come from i18n keys", () => {
  const source = readSource("features/workspaces/WorkspaceConsole.tsx");
  const modal = readSource("features/workspaces/NewIssueDialog.tsx");

  [
    't("workspace.console.emptyTitle")',
    't("workspace.console.filter")',
    't("workspace.console.sort")',
    't("workspace.console.newIssue")',
    't("workspace.console.table.task")',
    't("workspace.console.table.status")',
    't("workspace.console.table.branch")',
    't("workspace.console.table.agent")',
    't("workspace.console.table.run")',
    't("workspace.console.emptyBody")',
    't("workspace.console.commandPlaceholder")',
    't("workspace.console.chatPlaceholder")',
    't("workspace.console.send")',
    't("workspace.console.newline")',
    't("workspace.console.runIssue")',
    't("workspace.console.chatSend")',
    'workspace.console.createBanner',
    'workspace.console.chatBanner',
    't("workspace.console.selectIssueHint")',
    'NewIssueDialog',
  ].forEach((needle) => {
    assert.match(source, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });

  [
    't("workspace.console.newIssueDesc")',
    't("workspace.console.planFirstNotice")',
    't("workspace.console.issueTitle")',
    't("workspace.console.issueDescription")',
    't("workspace.console.executor")',
    't("workspace.console.model")',
    't("workspace.console.modelFallback")',
    't("workspace.console.issueTitlePlaceholder")',
    't("workspace.console.issueDescriptionPlaceholder")',
    't("workspace.console.repo")',
    't("workspace.console.createAndStart")',
    't("workspace.console.creating")',
  ].forEach((needle) => {
    assert.match(modal, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });
});

test("issue detail approval copy is wired for plan-first review", () => {
  const source = readSource("features/issues/IssueDetailPage.tsx");

  [
    'approveCodexIssuePlan',
    't("issue.planApproval.title")',
    't("issue.planApproval.description")',
    't("issue.planApproval.placeholder")',
    't("issue.planApproval.helper")',
    't("issue.planApproval.approve")',
    't("issue.planApproval.saving")',
  ].forEach((needle) => {
    assert.match(source, new RegExp(needle.replace(/[.*?^${}()|[\]\\]/g, "\\$&")));
  });
});

test("diff merge copy is wired through i18n keys", () => {
  const tab = readSource("features/issues/tabs/DiffMergeTab.tsx");
  const card = readSource("features/issues/components/GitInfoCard.tsx");
  const panel = readSource("features/issues/components/DiffPanel.tsx");
  const undoBar = readSource("components/ui/undo-bar.tsx");

  [
    't("task.diffMerge.loadFailed")',
    't("task.review.submitted")',
    't("task.review.approved")',
    't("task.diffMerge.refreshPrHint")',
    't("task.diffMerge.openGitHubPr")',
    'task.diffMerge.mergeConfirmBody',
    'task.diffMerge.abandonedUndoMessage',
    't("task.review.rejectConfirmTitle")',
    't("task.diffMerge.timeAgo.justNow")',
  ].forEach((needle) => {
    if (needle.startsWith("task.diffMerge.")) {
      assert.match(tab, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    } else {
      assert.match(tab, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }
  });

  [
    't("task.git.title")',
    't("task.diffMerge.clipboardUnavailable")',
    't("task.diffMerge.loadFailed")',
    't("task.diffMerge.mergeFailed")',
    't("task.diffMerge.loading")',
  ].forEach((needle) => {
    assert.match(card, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });

  [
    't("task.diffMerge.changesBy")',
    'task.diffMerge.runLabel',
    't("task.base")',
    't("task.branch")',
  ].forEach((needle) => {
    if (needle.startsWith("task.diffMerge.")) {
      assert.match(panel, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    } else {
      assert.match(panel, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }
  });

  [
    't("task.diffMerge.undo")',
    't("task.diffMerge.dismiss")',
  ].forEach((needle) => {
    assert.match(undoBar, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });
});

test("diff merge translation keys are available in English", () => {
  assert.equal(getDictionaryValue("en-US", "task.diffMerge.refresh"), "Refresh");
  assert.equal(getDictionaryValue("en-US", "task.diffMerge.timeAgo.justNow"), "just now");
  assert.equal(getDictionaryValue("en-US", "task.review.submitted"), "Submitted for review");
  assert.equal(getDictionaryValue("en-US", "task.git.title"), "Git");
  assert.equal(getDictionaryValue("en-US", "task.diffMerge.openGitHubPr"), "Open GitHub PR");
  assert.equal(getDictionaryValue("en-US", "task.diff.fileCountOne"), "{count} file");
});
