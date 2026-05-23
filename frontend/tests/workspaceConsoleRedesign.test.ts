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
