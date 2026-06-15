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
