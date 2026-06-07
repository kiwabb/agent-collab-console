import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("workspace console is a scheduler surface that opens issue detail rows", () => {
  const consoleSource = readSource("features/workspaces/WorkspaceConsole.tsx");
  const rowSource = readSource("features/workspaces/IssueRow.tsx");

  assert.doesNotMatch(consoleSource, /RunDetailColumn/);
  assert.doesNotMatch(consoleSource, /chatCodexTask/);
  assert.doesNotMatch(consoleSource, /textarea/);
  assert.match(consoleSource, /router\.push\(`\/issues\/\$\{issueId\}`\)/);
  assert.match(rowSource, /getIssueStatusBucket/);
  assert.match(rowSource, /getPhaseProgress/);
  assert.match(rowSource, /onClick=\{onOpen\}/);
});

test("workspace console uses dense operations queue chrome", () => {
  const consoleSource = readSource("features/workspaces/WorkspaceConsole.tsx");
  const headerSource = readSource("features/workspaces/WorkspaceConsoleHeader.tsx");
  const panelSource = readSource("features/workspaces/IssueListPanel.tsx");
  const rowSource = readSource("features/workspaces/IssueRow.tsx");

  assert.match(panelSource, /data-density="operations-queue"/);
  assert.match(rowSource, /grid-cols-\[minmax\(0,1fr\)_128px_156px_84px\]/);
  assert.match(rowSource, /min-h-\[72px\]/);
  assert.doesNotMatch(consoleSource, /radial-gradient/);
  assert.doesNotMatch(headerSource, /rounded-\[1\.4rem\]|rounded-full|tracking-\[-/);
  assert.doesNotMatch(panelSource, /rounded-\[1\.4rem\]|rounded-2xl|shadow-\[0_24px_80px/);
  assert.doesNotMatch(rowSource, /hover:-translate-y|rounded-2xl|tracking-\[-/);
});
