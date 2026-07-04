import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { getDictionaryValue } from "../src/lib/i18n";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

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
});

test("ProjectsPage exposes a RunCommandCard for editing run_command", () => {
  const page = readSource("features/projects/ProjectsPage.tsx");

  assert.match(page, /function RunCommandCard/);
  assert.match(page, /<RunCommandCard/);
  assert.match(page, /run_command: draft/);
  assert.match(page, /t\("projects\.runCommandLabel"\)/);
});

const SCRIPT_TASK_KEYS = [
  "projects.generateStartupScripts",
  "projects.generatingStartupScripts",
  "projects.scriptSuggestionSuccess",
  "projects.scriptSuggestionCompleted",
  "projects.scriptSuggestionAlreadyRunning",
  "projects.scriptSuggestionStillRunning",
  "projects.scriptSuggestionFailed",
] as const;

test("operations engineer startup script i18n keys exist in both zh-CN and en-US", () => {
  for (const key of SCRIPT_TASK_KEYS) {
    const zh = getDictionaryValue("zh-CN", key as never);
    const en = getDictionaryValue("en-US", key as never);
    assert.ok(zh && zh !== key, `zh-CN missing or fell back for ${key}`);
    assert.ok(en && en !== key, `en-US missing or fell back for ${key}`);
  }
});

test("ProjectsPage wires operations engineer startup-script task flow", () => {
  const page = readSource("features/projects/ProjectsPage.tsx");

  assert.match(page, /startProjectScriptTask/);
  assert.match(page, /getCodexTask/);
  assert.match(page, /suggestingTaskId/);
  assert.match(page, /describeScriptTaskTerminalStatus/);
  assert.match(page, /projects\.generateStartupScripts/);
  assert.match(page, /projects\.generatingStartupScripts/);
  assert.match(page, /projects\.scriptSuggestionAlreadyRunning/);
  assert.match(page, /projects\.scriptSuggestionSuccess/);
  assert.match(page, /projects\.scriptSuggestionCompleted/);
  assert.match(page, /projects\.scriptSuggestionStillRunning/);
  assert.match(page, /task\.reused \? t\("projects\.scriptSuggestionAlreadyRunning"\)/);
  assert.match(page, /if \(!activeProject \|\| suggestingProjectId\) return;/);
  assert.match(page, /handledScriptTaskIdsRef\.current\.delete\(task\.task_id\)/);
  assert.match(page, /setSuggestingTaskId\(task\.task_id\)/);
  assert.match(page, /lastEvent\.project_id !== suggestingProjectId/);
  assert.match(page, /lastEvent\.task_kind !== "project_script_suggestion"/);
  assert.match(page, /lastEvent\.role !== "operations_engineer"/);
  assert.match(page, /generating=\{suggestingProjectId !== null\}/);
  assert.match(page, /setSelectedProjectId\(p\.id\);\s*setActiveId\(p\.id\);/);
  assert.match(page, /useContext\(ExecutionProcessesContext\)/);
  assert.match(page, /useDataEvent\("projects:changed", refreshFromProjectEvent\)/);
  assert.match(page, /const refreshFromProjectEvent = useCallback\(\(\) => \{\s*void refresh\(\);\s*\}, \[refresh\]\);/);
  assert.doesNotMatch(page, /setTimeout\(\(\) => \{\s*setSuggestingProjectId/);
  assert.doesNotMatch(page, /setTimeout\(\(\) => \{\s*setSuggestingTaskId/);
  assert.doesNotMatch(page, /useExecutionProcessesContext/);
  assert.doesNotMatch(page, /suggestProjectScript\(/);
});

test("ProjectsPage script task poll timeout does not report failure", () => {
  const page = readSource("features/projects/ProjectsPage.tsx");
  const timeoutBranch = page.slice(
    page.indexOf("Date.now() - startedAt > SCRIPT_TASK_POLL_LIMIT_MS"),
    page.indexOf("try {", page.indexOf("Date.now() - startedAt > SCRIPT_TASK_POLL_LIMIT_MS")),
  );

  assert.match(timeoutBranch, /projects\.scriptSuggestionStillRunning/);
  assert.doesNotMatch(timeoutBranch, /projects\.scriptSuggestionFailed/);
});

test("ProjectsPage handles script task terminal events by task id first", () => {
  const page = readSource("features/projects/ProjectsPage.tsx");
  const taskIdGuard = page.indexOf("!suggestingTaskId");
  const taskIdMatch = page.indexOf("lastEvent.task_id !== suggestingTaskId");
  const projectIdCheck = page.indexOf("lastEvent.project_id !== suggestingProjectId");

  assert.ok(taskIdGuard > -1, "script task terminal handling should wait for a task id");
  assert.ok(taskIdMatch > taskIdGuard, "terminal events should match the tracked task id");
  assert.ok(projectIdCheck > taskIdMatch, "project id should only narrow after exact task-id matching");
});

test("ProjectScriptTaskResponse keeps reused as a required boolean", () => {
  const types = readSource("lib/types.ts");
  const start = types.indexOf("export interface ProjectScriptTaskResponse");
  const end = types.indexOf("export interface MergeIssueResult", start);
  const block = types.slice(start, end);

  assert.match(block, /reused: boolean;/);
  assert.doesNotMatch(block, /reused\?:/);
});
