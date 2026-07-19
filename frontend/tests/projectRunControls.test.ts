import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

import { getDictionaryValue } from "../src/lib/i18n";

// i18n keys introduced for the one-click project run (dev server) feature.
const RUN_KEYS = [
  "projects.runStart",
  "projects.runStarting",
  "projects.runStop",
  "projects.runStopping",
  "projects.runRunning",
  "projects.runStopped",
  "projects.runExitCode",
  "projects.runNoCommand",
  "projects.runRefused",
  "projects.runAlreadyRunning",
  "projects.runStartFailed",
  "projects.runStopFailed",
  "projects.runLogsTitle",
  "projects.runClearLogs",
  "projects.runCommandLabel",
  "projects.runCommandHelp",
  "projects.runCommandPlaceholder",
  "projects.runCommandSaved",
] as const;

test("project run i18n keys exist in both zh-CN and en-US", () => {
  for (const key of RUN_KEYS) {
    const zh = getDictionaryValue("zh-CN", key as never);
    const en = getDictionaryValue("en-US", key as never);
    assert.ok(zh && zh !== key, `zh-CN missing or fell back for ${key}`);
    assert.ok(en && en !== key, `en-US missing or fell back for ${key}`);
  }
});

test("ProjectWorkspacesPage wires the start/stop/logs run controls", () => {
  const page = readSource("features/projects/ProjectWorkspacesPage.tsx");

  // API calls are imported and invoked.
  assert.match(page, /startProjectRun/);
  assert.match(page, /stopProjectRun/);
  assert.match(page, /getProjectRunLogs/);
  assert.match(page, /getProjectRunStatus/);
  assert.match(page, /isProjectRunStartError/);

  // Start / stop buttons reference the run i18n keys.
  assert.match(page, /t\("projects\.runStart"\)/);
  assert.match(page, /t\("projects\.runStop"\)/);

  // Play / Square icons from lucide-react drive the toggle.
  assert.match(page, /\bPlay\b/);
  assert.match(page, /\bSquare\b/);

  // The 409 refusal reasons each map to a distinct toast.
  assert.match(page, /"already_running"/);
  assert.match(page, /"no_run_command"/);
  assert.match(page, /t\("projects\.runRefused"\)/);

  // Log polling delta tracking + collapsible panel.
  assert.match(page, /lastSeqRef/);
  assert.match(page, /logsOpen/);
  assert.match(page, /t\("projects\.runLogsTitle"\)/);
  assert.match(page, /setInterval\(tick, SERVICE_STATUS_POLL_MS\)/);
  assert.match(page, /setInterval\(tick, RUN_LOG_POLL_MS\)/);
  assert.match(page, /updateProjectRunRefreshError/);
});

test("ProjectsPage exposes a RunCommandCard for editing run_command", () => {
  const page = readSource("features/projects/ProjectsPage.tsx");

  assert.match(page, /function RunCommandCard/);
  assert.match(page, /<RunCommandCard/);
  assert.match(page, /run_command: draft/);
  assert.match(page, /t\("projects\.runCommandLabel"\)/);
});

const STARTUP_CONFIG_KEYS = [
  "startupConfig.open",
  "startupConfig.title",
  "startupConfig.analyze",
  "startupConfig.reanalyze",
  "startupConfig.analyzing",
  "startupConfig.analysisCompleted",
  "startupConfig.analysisFailed",
  "startupConfig.stepAnalyze",
  "startupConfig.stepConfigure",
  "startupConfig.stepRun",
  "startupConfig.envTitle",
  "startupConfig.readyTitle",
  "startupConfig.runSubmitted",
  "startupConfig.failedTitle",
  "startupConfig.failedDetail",
  "startupConfig.retryRun",
  "startupConfig.runLogsTitle",
  "startupConfig.runLogsExited",
  "startupConfig.occupiedUnknownTitle",
  "startupConfig.invalidReadinessTitle",
  "startupConfig.externalServiceTitle",
  "startupConfig.serviceStartingTitle",
  "startupConfig.serviceOfflineTitle",
  "startupConfig.serviceOfflineDetail",
  "startupConfig.serviceUnknownTitle",
  "startupConfig.serviceUnknownDetail",
  "startupConfig.openService",
] as const;

test("startup configuration i18n keys exist in both zh-CN and en-US", () => {
  for (const key of STARTUP_CONFIG_KEYS) {
    const zh = getDictionaryValue("zh-CN", key as never);
    const en = getDictionaryValue("en-US", key as never);
    assert.ok(zh && zh !== key, `zh-CN missing or fell back for ${key}`);
    assert.ok(en && en !== key, `en-US missing or fell back for ${key}`);
  }
});

test("ProjectsPage links to Startup Config instead of starting analysis", () => {
  const projectsPage = readSource("features/projects/ProjectsPage.tsx");

  assert.match(projectsPage, /startupConfigHref=\{`\/projects\/\$\{activeProject\.id\}\/env`\}/);
  assert.match(projectsPage, /t\("startupConfig\.open"\)/);
  assert.doesNotMatch(projectsPage, /startProjectScriptTask/);
  assert.doesNotMatch(projectsPage, /suggestingTaskId/);
});

test("Startup Config owns analysis polling and project run actions", () => {
  const hook = readSource("features/projects/useProjectStartupConfig.ts");
  const page = readSource("features/projects/ProjectStartupConfigPage.tsx");
  const runPanel = readSource("features/projects/ProjectRunStatusPanel.tsx");

  assert.match(hook, /startProjectScriptTask/);
  assert.match(hook, /getCodexTask\(analysisTaskId\)/);
  assert.match(hook, /setAnalysisTaskId\(response\.task_id\)/);
  assert.match(hook, /response\.reused/);
  assert.match(hook, /startupConfig\.analysisStillRunning|still_running/);
  assert.match(hook, /startProjectRun/);
  assert.match(hook, /stopProjectRun/);
  assert.match(hook, /getProjectRunStatus/);
  assert.match(hook, /getProjectRunLogs/);
  assert.match(hook, /shouldPollProjectServiceStatus\(runStatus\)/);
  assert.match(hook, /service_address_occupied/);
  assert.match(hook, /startup_config_invalid/);
  assert.match(hook, /lastRunLogSeqRef/);
  assert.match(hook, /window\.setInterval\(pollStatus, SERVICE_STATUS_POLL_MS\)/);
  assert.match(hook, /window\.setInterval\(pollLogs, RUN_LOG_POLL_MS\)/);
  assert.match(hook, /updateProjectRunRefreshError/);
  assert.match(page, /ProjectEnvVarEditor/);
  assert.match(page, /startupConfig\.stepAnalyze/);
  assert.match(page, /startupConfig\.stepConfigure/);
  assert.match(page, /startupConfig\.stepRun/);
  assert.match(page, /ProjectRunStatusPanel/);
  assert.match(runPanel, /startupConfig\.failedDetail/);
  assert.match(runPanel, /startupConfig\.runLogsTitle/);
  assert.match(runPanel, /externalReady/);
  assert.match(runPanel, /occupied_unknown/);
  assert.match(runPanel, /managedRunning/);
  assert.match(runPanel, /startupConfig\.openService/);
});

test("project run status keeps managed ownership separate from service reachability", () => {
  const types = readSource("lib/types/projects.ts");

  assert.match(types, /export interface ProjectRunServiceStatus/);
  assert.match(types, /service: ProjectRunServiceStatus/);
  assert.match(types, /readiness: ProjectApplicationReadinessStatus/);
  assert.match(types, /service_address_occupied/);
  assert.match(types, /startup_config_invalid/);
});

test("ProjectScriptTaskResponse keeps reused as a required boolean", () => {
  const types = readSource("lib/types.ts");
  const start = types.indexOf("export interface ProjectScriptTaskResponse");
  const end = types.indexOf("export interface MergeIssueResult", start);
  const block = types.slice(start, end);

  assert.match(block, /reused: boolean;/);
  assert.doesNotMatch(block, /reused\?:/);
});
