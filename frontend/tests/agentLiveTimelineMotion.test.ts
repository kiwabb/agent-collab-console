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

test("agent live streaming assistant uses streaming motion", () => {
  const source = readSource("features/runs/AgentLiveTimeline.tsx");

  assert.match(source, /data-density="agent-live-streaming-assistant"/);
  assert.match(source, /<AgentThinkingIndicator phase="streaming" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
});

test("agent live execution controls use semantic busy motion", () => {
  const source = readSource("features/runs/AgentLiveTimeline.tsx");

  assert.match(source, /data-density=\{stopBusy \? "agent-live-stop-tool" : "agent-live-stop"\}/);
  assert.match(source, /stopBusy && "motion-essential"/);
  assert.match(source, /stopBusy \? \(\s*<AgentThinkingIndicator phase="tool" size=\{10\} \/>\s*\) : \(\s*<Square size=\{10\} className="fill-error" \/>\s*\)/);
  assert.doesNotMatch(source, /stopBusy \? \(\s*<Loader2 size=\{10\} className="animate-spin" \/>\s*\) :/);

  assert.match(source, /data-density=\{rerunBusy \? "agent-live-rerun-dispatch" : "agent-live-rerun"\}/);
  assert.match(source, /rerunBusy && "motion-essential"/);
  assert.match(source, /rerunBusy \? \(\s*<AgentThinkingIndicator phase="dispatching" size=\{11\} \/>\s*\) : \(\s*<RotateCcw size=\{11\} \/>\s*\)/);
  assert.doesNotMatch(source, /rerunBusy \? \(\s*<Loader2 size=\{11\} className="animate-spin" \/>\s*\) :/);
});
