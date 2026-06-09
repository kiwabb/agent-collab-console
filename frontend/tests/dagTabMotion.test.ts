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

test("dag tab start conductor ctas use dispatch motion while scheduling", () => {
  const source = readSource("features/issues/tabs/DagTab.tsx");

  assert.match(source, /data-density=\{\s*busy\s*\? "dag-tab-start-conductor-dispatch-cta"\s*: "dag-tab-start-conductor-cta"\s*\}/);
  assert.match(source, /data-density=\{\s*busy\s*\? "dag-tab-toolbar-start-dispatch-cta"\s*: "dag-tab-toolbar-start-cta"\s*\}/);
  assert.match(source, /className=\{cn\(\s*"bg-brand text-black hover:bg-brand-strong font-semibold shadow-sm",\s*busy && "motion-essential",\s*\)\}/);
  assert.match(source, /className=\{cn\(\s*"h-7 px-2\.5 text-\[12px\] bg-brand hover:bg-brand-strong text-black font-semibold",\s*busy && "motion-essential",\s*\)\}/);
  assert.match(source, /busy \? \(\s*<>\s*<AgentThinkingIndicator phase="dispatching" size=\{12\} \/>/);
  assert.match(source, /busy \? \(\s*<>\s*<AgentThinkingIndicator phase="dispatching" size=\{11\} \/>/);
  assert.doesNotMatch(source, /\{busy \? "Starting…" : "Start Conductor"\}/);
  assert.doesNotMatch(source, /busy\s*\?\s*"Starting…"\s*:\s*graph\.status === "running"/);
});
