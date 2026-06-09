import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("tasks overview gantt marks running stages with dispatch motion", () => {
  const source = readFileSync(
    path.join(root, "src/features/issues/components/TasksOverviewBar.tsx"),
    "utf8",
  );

  assert.match(source, /const isRunningStage = stage\.status === "running";/);
  assert.match(source, /data-density=\{isRunningStage \? "tasks-overview-running-gantt-bar" : "tasks-overview-gantt-bar"\}/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{10\}/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /bg-brand animate-pulse/);
});
