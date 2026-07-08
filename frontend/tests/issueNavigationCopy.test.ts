import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

import { getDictionaryValue } from "../src/lib/i18n";

test("sidebar and issue page copy uses requirements wording", () => {
  assert.equal(getDictionaryValue("zh-CN", "sidebar.myTasks"), "需求");
  assert.equal(getDictionaryValue("en-US", "sidebar.myTasks"), "Issues");
  assert.equal(getDictionaryValue("zh-CN", "issue.gridSubtitle"), "查看并管理此工作区内的需求");
  assert.equal(
    getDictionaryValue("en-US", "issue.gridSubtitle"),
    "Review and manage issues in this workspace",
  );
});

test("updated requirements copy is wired into sidebar and issue/help views", () => {
  const sidebar = readSource("features/workbench/components/AppSidebar.tsx");
  const issueGrid = readSource("features/issues/IssueGrid.tsx");
  const helpPage = readSource("features/help/HelpPage.tsx");

  assert.match(sidebar, /t\("sidebar\.myTasks"\)/);
  assert.match(issueGrid, /t\("issue\.gridSubtitle"\)/);
  assert.match(issueGrid, /t\("issue\.searchPlaceholder"\)/);
  assert.match(helpPage, /t\("help\.step1\.body"\)/);
});
