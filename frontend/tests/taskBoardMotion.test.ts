import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("task board cards mark running task work with dispatch motion", () => {
  const source = readSource("features/tasks/TaskBoard.tsx");

  assert.match(source, /data-density=\{isRunningTask \? "task-board-running-card" : "task-board-card"\}/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /status === "running" \|\| status === "responding" \? "bg-brand animate-pulse"/);
});
