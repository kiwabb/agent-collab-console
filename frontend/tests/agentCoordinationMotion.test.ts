import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("agent coordination panel marks active work with dispatch motion", () => {
  const source = readSource("features/agents/AgentCoordinationPanel.tsx");

  assert.match(source, /data-density="agent-coordination-active-process"/);
  assert.match(
    source,
    /data-density=\{isTaskRunning \? "agent-coordination-running-task" : "agent-coordination-task"\}/,
  );
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /animate-pulse/);
});
