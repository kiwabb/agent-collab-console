import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("dag tab running graph status uses dispatch motion", () => {
  const source = readSource("features/issues/tabs/DagTab.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density=\{\s*graph\.status === "running"\s*\? "dag-tab-running-status"\s*: "dag-tab-status"\s*\}/);
  assert.match(source, /graph\.status === "running" && "motion-essential"/);
  assert.match(source, /graph\.status === "running" && \(\s*<AgentThinkingIndicator phase="dispatching" size=\{10\} \/>/);
  assert.doesNotMatch(source, /<span className="size-1\.5 rounded-full bg-brand animate-pulse" \/>/);
});
