import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { getDictionaryValue } from "../src/lib/i18n";

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

test("dag tab retry confirmation uses dispatch motion while redispatching", () => {
  const dagSource = readSource("features/issues/tabs/DagTab.tsx");
  const dialogSource = readSource("components/ui/confirm-dialog.tsx");

  assert.match(dagSource, /loadingMotionPhase="dispatching"/);
  assert.match(dagSource, /loadingDensity="dag-tab-retry-node-dispatch-confirm"/);
  assert.match(dagSource, /loadingIndicatorSize=\{12\}/);

  assert.match(dialogSource, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(dialogSource, /loadingMotionPhase\?: string;/);
  assert.match(dialogSource, /loadingDensity\?: string;/);
  assert.match(dialogSource, /loadingIndicatorSize\?: number;/);
  assert.match(dialogSource, /data-density=\{isLoading \? loadingDensity : undefined\}/);
  assert.match(dialogSource, /isLoading && loadingMotionPhase && "motion-essential"/);
  assert.match(dialogSource, /isLoading \? \(\s*loadingMotionPhase \? \(\s*<AgentThinkingIndicator\s*phase=\{loadingMotionPhase\}\s*size=\{loadingIndicatorSize\}/);
});

test("dag tab graph loading uses dispatch motion", () => {
  const source = readSource("features/issues/tabs/DagTab.tsx");

  assert.match(source, /data-density="dag-tab-graph-dispatch-loading"/);
  assert.match(source, /className="motion-essential relative flex min-h-\[220px\] items-center justify-center gap-2 overflow-hidden rounded-lg border border-brand\/25 bg-brand-muted\/10 text-sm font-semibold text-text-muted"/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{16\} \/>/);
  assert.match(source, /t\("issue\.workflow\.loading"\)/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.doesNotMatch(source, /<Loader variant="card" label="Loading Workflow Graph\.\.\." \/>/);
  assert.equal(getDictionaryValue("zh-CN", "issue.workflow.loading"), "加载工作流图中...");
  assert.equal(getDictionaryValue("en-US", "issue.workflow.loading"), "Loading workflow graph...");
});
