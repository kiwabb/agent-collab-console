import assert from "node:assert/strict";
import test from "node:test";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("run detail status badge marks live execution with dispatch motion", () => {
  const source = readSource("features/runs/RunDetail.tsx");

  assert.match(source, /const isLiveRunStatus = s === "running" \|\| s === "responding"/);
  assert.match(
    source,
    /data-density=\{isLiveRunStatus \? "run-detail-live-status" : "run-detail-status"\}/,
  );
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /bg-brand animate-pulse/);
});

test("run detail process loading uses dispatch motion", () => {
  const source = readSource("features/runs/RunDetail.tsx");

  assert.match(source, /data-density="run-detail-process-loading"/);
  assert.match(
    source,
    /className="motion-essential flex flex-col h-full items-center justify-center gap-4 text-text-muted"/,
  );
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{32\} \/>/);
  assert.doesNotMatch(source, /<Activity size=\{32\} className="animate-spin text-brand" \/>/);
});

test("run detail messages loading uses streaming motion", () => {
  const source = readSource("features/runs/RunDetail.tsx");

  assert.match(source, /data-density="run-detail-messages-loading"/);
  assert.match(
    source,
    /className="motion-essential py-20 flex flex-col items-center justify-center gap-4 text-\[10px\] uppercase font-black tracking-widest text-text-muted opacity-40"/,
  );
  assert.match(source, /<AgentThinkingIndicator phase="streaming" size=\{24\} \/>/);
  assert.doesNotMatch(source, /<Activity size=\{24\} className="animate-spin text-brand" \/>/);
});

test("run detail logs loading uses tool motion", () => {
  const source = readSource("features/runs/RunDetail.tsx");

  assert.match(source, /data-density="run-detail-logs-loading"/);
  assert.match(
    source,
    /className="motion-essential py-20 flex flex-col items-center justify-center gap-4 text-\[10px\] uppercase font-black tracking-widest text-text-muted opacity-40"/,
  );
  assert.match(source, /<AgentThinkingIndicator phase="tool" size=\{24\} \/>/);
  assert.doesNotMatch(source, /<Terminal size=\{24\} className="animate-pulse text-brand" \/>/);
});

test("run detail terminate control uses tool motion", () => {
  const source = readSource("features/runs/RunDetail.tsx");

  assert.match(source, /data-density="run-detail-terminate-tool"/);
  assert.match(
    source,
    /className="motion-essential p-2\.5 rounded-lg hover:bg-error\/10 text-text-muted hover:text-error transition-all active:scale-\[0\.9\] border border-transparent hover:border-error\/20"/,
  );
  assert.match(
    source,
    /<AgentThinkingIndicator phase="tool" size=\{14\} className="text-error" \/>/,
  );
  assert.doesNotMatch(source, /<Activity size=\{14\} className="text-error animate-pulse" \/>/);
});

test("run detail pending assistant uses streaming motion", () => {
  const source = readSource("features/runs/RunDetail.tsx");

  assert.match(source, /data-density="run-detail-streaming-assistant"/);
  assert.match(source, /<AgentThinkingIndicator phase="streaming" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(
    source,
    /rounded-full bg-brand shadow-\[0_0_8px_rgba\(122,157,204,0\.6\)\] animate-pulse/,
  );
});

test("run detail phase transition ctas use dispatch motion while scheduling next phase", () => {
  const source = readSource("features/runs/RunDetail.tsx");

  assert.match(
    source,
    /data-density=\{isTransitioningToArchitecture \? "run-detail-transition-architecture-dispatch" : "run-detail-transition-architecture"\}/,
  );
  assert.match(
    source,
    /data-density=\{isTransitioningToDevelopment \? "run-detail-transition-development-dispatch" : "run-detail-transition-development"\}/,
  );
  assert.match(
    source,
    /data-density=\{isTransitioningToTesting \? "run-detail-transition-testing-dispatch" : "run-detail-transition-testing"\}/,
  );
  assert.match(source, /isTransitioningToArchitecture && "motion-essential"/);
  assert.match(source, /isTransitioningToDevelopment && "motion-essential"/);
  assert.match(source, /isTransitioningToTesting && "motion-essential"/);
  assert.match(
    source,
    /isTransitioningToArchitecture \? \(\s*<>\s*<AgentThinkingIndicator phase="dispatching" size=\{12\}/,
  );
  assert.match(
    source,
    /isTransitioningToDevelopment \? \(\s*<>\s*<AgentThinkingIndicator phase="dispatching" size=\{12\}/,
  );
  assert.match(
    source,
    /isTransitioningToTesting \? \(\s*<>\s*<AgentThinkingIndicator phase="dispatching" size=\{12\}/,
  );
});
