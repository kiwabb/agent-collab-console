import assert from "node:assert/strict";
import test from "node:test";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("tasks overview gantt marks running stages with dispatch motion", () => {
  const source = readSource("features/issues/components/TasksOverviewBar.tsx");

  assert.match(source, /const isRunningStage = stage\.status === "running";/);
  assert.match(
    source,
    /data-density=\{isRunningStage \? "tasks-overview-running-gantt-bar" : "tasks-overview-gantt-bar"\}/,
  );
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{10\}/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /bg-brand animate-pulse/);
});
