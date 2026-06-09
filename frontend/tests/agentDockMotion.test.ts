import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("agent dock active tile uses dispatch motion", () => {
  const source = readSource("features/agents/dock/AgentTile.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density=\{isActive \? "agent-dock-active-tile" : "agent-dock-tile"\}/);
  assert.match(source, /isActive && "motion-essential"/);
  assert.match(source, /data-density="agent-dock-active-status"/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{10\} \/>/);
  assert.doesNotMatch(source, /animate-pulse/);
});
