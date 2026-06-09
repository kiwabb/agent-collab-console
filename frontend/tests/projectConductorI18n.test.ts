import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { getDictionaryValue } from "../src/lib/i18n";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("project conductor views use i18n keys instead of hard-coded copy", () => {
  const page = readSource("features/projects/ProjectConductorPage.tsx");
  const dock = readSource("features/projects/components/ProjectConductorThreadDock.tsx");

  [
    't("projectConductor.title")',
    't("projectConductor.subtitle")',
    't("projectConductor.refresh")',
    't("projectConductor.scheduleReview")',
    't("projectConductor.metric.hotTokens")',
    't("projectConductor.metric.warmTokens")',
    't("projectConductor.metric.coldMemories")',
    't("projectConductor.metric.tasksHandled")',
    't("projectConductor.askTitle")',
    't("projectConductor.askPlaceholder")',
    't("projectConductor.askAction")',
    't("projectConductor.section.pinned")',
    't("projectConductor.section.warmSummaries")',
    't("projectConductor.section.coldMemory")',
    't("projectConductor.section.hotThread")',
    't("projectConductor.empty.pinned")',
    't("projectConductor.empty.warm")',
    't("projectConductor.empty.cold")',
    't("projectConductor.empty.hot")',
    't("projectConductor.loading")',
    't("projectConductor.toast.loadFailed")',
    't("projectConductor.toast.askFailed")',
    't("projectConductor.toast.reviewFailed")',
  ].forEach((needle) => {
    assert.match(page, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });

  [
    't("projectConductor.threadDock.title")',
    't("projectConductor.threadDock.listening")',
    't("projectConductor.threadDock.replayHint")',
    't("projectConductor.threadDock.status.running")',
    't("projectConductor.threadDock.status.streaming")',
    't("projectConductor.threadDock.status.idle")',
    't("projectConductor.threadDock.promptPlaceholder")',
    't("projectConductor.threadDock.startLoop")',
    't("projectConductor.threadDock.latest")',
    't("projectConductor.threadDock.turns")',
    't("projectConductor.threadDock.toolCards")',
    't("projectConductor.threadDock.empty.turns")',
    't("projectConductor.threadDock.empty.turn")',
    't("projectConductor.threadDock.empty.tools")',
    't("projectConductor.threadDock.toolState.error")',
    't("projectConductor.threadDock.toolState.ok")',
    't("projectConductor.toast.loopFailed")',
  ].forEach((needle) => {
    assert.match(dock, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });
});

test("project conductor translation keys are available in English", () => {
  assert.equal(getDictionaryValue("en-US", "projectConductor.title"), "Project Conductor");
  assert.equal(getDictionaryValue("en-US", "projectConductor.scheduleReview"), "Schedule review");
  assert.equal(getDictionaryValue("en-US", "projectConductor.metric.tasksHandled"), "Tasks handled");
  assert.equal(getDictionaryValue("en-US", "projectConductor.askAction"), "Ask");
  assert.equal(getDictionaryValue("en-US", "projectConductor.threadDock.startLoop"), "Start loop");
  assert.equal(getDictionaryValue("en-US", "projectConductor.threadDock.toolState.error"), "error");
});

test("project conductor thread dock marks streaming runs with scheduling motion", () => {
  const dock = readSource("features/projects/components/ProjectConductorThreadDock.tsx");

  assert.match(dock, /isProjectConductorStreaming/);
  assert.match(dock, /data-density="project-conductor-thread-dock"/);
  assert.match(dock, /"project-conductor-tool-card"/);
  assert.match(dock, /<AgentThinkingIndicator/);
  assert.match(dock, /animate-shimmer-sweep/);
  assert.match(dock, /phase=\{running \? "dispatching" : "streaming"\}/);
  assert.match(dock, /motion-essential/);
  assert.doesNotMatch(dock, /animate-pulse/);
});

test("project conductor page marks active ask or review requests with thinking motion", () => {
  const page = readSource("features/projects/ProjectConductorPage.tsx");

  assert.match(page, /isProjectConductorThinking/);
  assert.match(page, /data-density=\{isProjectConductorThinking \? "project-conductor-thinking-shell" : "project-conductor-shell"\}/);
  assert.match(page, /data-density=\{isProjectConductorThinking \? "project-conductor-thinking-actions" : "project-conductor-actions"\}/);
  assert.match(page, /<AgentThinkingIndicator/);
  assert.match(page, /animate-shimmer-sweep/);
  assert.match(page, /phase="thinking"/);
  assert.match(page, /motion-essential/);
  assert.doesNotMatch(page, /animate-pulse/);
});

test("project conductor refresh cta uses thinking motion while loading", () => {
  const page = readSource("features/projects/ProjectConductorPage.tsx");

  assert.match(page, /data-density=\{loading \? "project-conductor-refresh-thinking" : "project-conductor-refresh"\}/);
  assert.match(page, /loading && "motion-essential/);
  assert.match(page, /<AgentThinkingIndicator phase="thinking" size=\{14\}/);
  assert.match(page, /<RefreshCcw size=\{14\}/);
  assert.doesNotMatch(page, /loading \? <Loader2/);
  assert.doesNotMatch(page, /animate-pulse/);
});

test("project conductor start loop cta uses dispatch motion while running", () => {
  const dock = readSource("features/projects/components/ProjectConductorThreadDock.tsx");

  assert.match(dock, /data-density=\{running \? "project-conductor-loop-dispatch-cta" : "project-conductor-loop-cta"\}/);
  assert.match(dock, /running && "motion-essential/);
  assert.match(dock, /<AgentThinkingIndicator phase="dispatching" size=\{14\}/);
  assert.match(dock, /<Play size=\{14\}/);
  assert.doesNotMatch(dock, /running \? <Loader2/);
  assert.doesNotMatch(dock, /animate-pulse/);
});

test("project conductor latest tool card uses tool motion while streaming", () => {
  const dock = readSource("features/projects/components/ProjectConductorThreadDock.tsx");

  assert.match(dock, /const isProjectConductorToolActive = isProjectConductorStreaming && index === 0 && !tool\.is_error/);
  assert.match(dock, /data-density=\{isProjectConductorToolActive \? "project-conductor-active-tool-card" : "project-conductor-tool-card"\}/);
  assert.match(dock, /isProjectConductorToolActive && "motion-essential/);
  assert.match(dock, /<AgentThinkingIndicator phase="tool" size=\{12\}/);
  assert.match(dock, /isProjectConductorToolActive && \(/);
  assert.match(dock, /animate-shimmer-sweep/);
  assert.doesNotMatch(dock, /animate-pulse/);
});
