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
