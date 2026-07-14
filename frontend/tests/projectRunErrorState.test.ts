import test from "node:test";
import assert from "node:assert/strict";

import { getDictionaryValue } from "../src/lib/i18n";
import { readCompactSource } from "./sourceTestUtils";

test("project run refresh failures have localized visible feedback", () => {
  for (const locale of ["zh-CN", "en-US"] as const) {
    const value = getDictionaryValue(locale, "projects.runRefreshFailed" as never);
    assert.ok(value && value !== "projects.runRefreshFailed", `${locale} is missing run feedback`);
  }

  const page = readCompactSource("features/projects/ProjectWorkspacesPage.tsx");
  assert.match(page, /role="alert"/);
  assert.match(page, /t\("projects\.runRefreshFailed"\)/);
  assert.match(page, /\{runLoadError\}/);
});

test("legacy project run refresh errors preserve status and logs", () => {
  const page = readCompactSource("features/projects/ProjectWorkspacesPage.tsx");
  const reporterStart = page.indexOf("const reportRunRefreshFailure");
  const reporterEnd = page.indexOf("const load =", reporterStart);
  assert.ok(reporterStart >= 0 && reporterEnd > reporterStart, "run failure reporter is missing");

  const reporter = page.slice(reporterStart, reporterEnd);
  assert.match(reporter, /console\.error/);
  assert.match(reporter, /updateProjectRunRefreshError/);
  assert.doesNotMatch(reporter, /setRunStatus/);
  assert.doesNotMatch(reporter, /setRunLogs/);

  assert.match(
    page,
    /catch \(err\) {if \(cancelled\) return; reportRunRefreshFailure\("status", "status load", err\);}/,
  );
  assert.match(
    page,
    /catch \(err\) {if \(cancelled\) return; reportRunRefreshFailure\("logs", "log poll", err\);}/,
  );
  assert.match(page, /catch \(err\) {reportRunRefreshFailure\("status", "status resync", err\);}/);
  assert.doesNotMatch(page, /getProjectRunStatus\(projectId\)\.catch\(\(\) => null\)/);
});
