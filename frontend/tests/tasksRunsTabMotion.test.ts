import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("tasks runs tab status dots use dispatch motion for active execution", () => {
  const source = readFileSync(
    path.join(root, "src/features/issues/tabs/TasksRunsTab.tsx"),
    "utf8",
  );

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /const isActive = status === "running" \|\| status === "in_progress";/);
  assert.match(source, /data-density=\{isActive \? "tasks-runs-active-status-dot" : "tasks-runs-status-dot"\}/);
  assert.match(source, /isActive && "motion-essential"/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{10\}/);
  assert.doesNotMatch(source, /bg-warning animate-pulse/);
});

test("tasks runs tab execution ctas use semantic motion while busy", () => {
  const source = readFileSync(
    path.join(root, "src/features/issues/tabs/TasksRunsTab.tsx"),
    "utf8",
  );

  assert.match(source, /const composerBusyMotionPhase = mode === "rerun" \? "dispatching" : "thinking";/);
  assert.match(source, /const composerBusyDensity = mode === "rerun"\s*\? "tasks-runs-rerun-dispatch-cta"\s*: mode === "refine"\s*\? "tasks-runs-refine-thinking-cta"\s*: "tasks-runs-chat-thinking-cta";/);
  assert.match(source, /data-density=\{busy \? "tasks-runs-run-dispatch-cta" : "tasks-runs-run-cta"\}/);
  assert.match(source, /data-density=\{busy \? composerBusyDensity : "tasks-runs-composer-cta"\}/);
  assert.match(source, /className=\{cn\(busy && "motion-essential"\)\}/);
  assert.match(source, /busy \? \(\s*<>\s*<AgentThinkingIndicator phase="dispatching" size=\{12\} \/>/);
  assert.match(source, /busy \? \(\s*<>\s*<AgentThinkingIndicator phase=\{composerBusyMotionPhase\} size=\{12\} \/>/);
  assert.doesNotMatch(source, /\{busy \? "Starting…" : "Run"\}/);
  assert.doesNotMatch(source, /\{busy \? "Sending…" : mode === "rerun" \? "Rerun" : mode === "refine" \? "Refine" : "Send"\}/);
});
