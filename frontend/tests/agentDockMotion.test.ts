import assert from "node:assert/strict";
import test from "node:test";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("agent dock active tile uses dispatch motion", () => {
  const source = readSource("features/agents/dock/AgentTile.tsx");

  assert.match(
    source,
    /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/,
  );
  assert.match(source, /data-density=\{isActive \? "agent-dock-active-tile" : "agent-dock-tile"\}/);
  assert.match(source, /isActive && "motion-essential"/);
  assert.match(source, /data-density="agent-dock-active-status"/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{10\} \/>/);
  assert.doesNotMatch(source, /animate-pulse/);
});
