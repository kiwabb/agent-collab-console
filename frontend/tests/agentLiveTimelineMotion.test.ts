import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("agent live working indicator marks active run work with scheduling motion", () => {
  const source = readSource("features/runs/AgentLiveTimeline.tsx");

  assert.match(source, /data-density="agent-live-working-indicator"/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.match(source, /<AgentThinkingIndicator phase=\{phase\} label=\{subtitle\} size=\{14\} \/>/);
});
