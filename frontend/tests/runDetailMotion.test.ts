import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("run detail status badge marks live execution with dispatch motion", () => {
  const source = readFileSync(
    path.join(root, "src/features/runs/RunDetail.tsx"),
    "utf8",
  );

  assert.match(source, /const isLiveRunStatus = s === "running" \|\| s === "responding"/);
  assert.match(source, /data-density=\{isLiveRunStatus \? "run-detail-live-status" : "run-detail-status"\}/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /bg-brand animate-pulse/);
});

test("run detail process loading uses dispatch motion", () => {
  const source = readFileSync(
    path.join(root, "src/features/runs/RunDetail.tsx"),
    "utf8",
  );

  assert.match(source, /data-density="run-detail-process-loading"/);
  assert.match(source, /className="motion-essential flex flex-col h-full items-center justify-center gap-4 text-text-muted"/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{32\} \/>/);
  assert.doesNotMatch(source, /<Activity size=\{32\} className="animate-spin text-brand" \/>/);
});

test("run detail pending assistant uses streaming motion", () => {
  const source = readFileSync(
    path.join(root, "src/features/runs/RunDetail.tsx"),
    "utf8",
  );

  assert.match(source, /data-density="run-detail-streaming-assistant"/);
  assert.match(source, /<AgentThinkingIndicator phase="streaming" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /rounded-full bg-brand shadow-\[0_0_8px_rgba\(122,157,204,0\.6\)\] animate-pulse/);
});

test("run detail phase transition ctas use dispatch motion while scheduling next phase", () => {
  const source = readFileSync(
    path.join(root, "src/features/runs/RunDetail.tsx"),
    "utf8",
  );

  assert.match(source, /data-density=\{isTransitioningToArchitecture \? "run-detail-transition-architecture-dispatch" : "run-detail-transition-architecture"\}/);
  assert.match(source, /data-density=\{isTransitioningToDevelopment \? "run-detail-transition-development-dispatch" : "run-detail-transition-development"\}/);
  assert.match(source, /data-density=\{isTransitioningToTesting \? "run-detail-transition-testing-dispatch" : "run-detail-transition-testing"\}/);
  assert.match(source, /isTransitioningToArchitecture && "motion-essential"/);
  assert.match(source, /isTransitioningToDevelopment && "motion-essential"/);
  assert.match(source, /isTransitioningToTesting && "motion-essential"/);
  assert.match(source, /isTransitioningToArchitecture \? \(\s*<>\s*<AgentThinkingIndicator phase="dispatching" size=\{12\}/);
  assert.match(source, /isTransitioningToDevelopment \? \(\s*<>\s*<AgentThinkingIndicator phase="dispatching" size=\{12\}/);
  assert.match(source, /isTransitioningToTesting \? \(\s*<>\s*<AgentThinkingIndicator phase="dispatching" size=\{12\}/);
});
