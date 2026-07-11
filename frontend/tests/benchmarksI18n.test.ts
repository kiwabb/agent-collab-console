import test from "node:test";
import assert from "node:assert/strict";
import { getDictionaryValue } from "../src/lib/i18n";
import { readCompactSource } from "./sourceTestUtils";

test("benchmark execution target copy uses i18n keys", () => {
  const source = readCompactSource("features/benchmarks/BenchmarksPage.tsx");

  [
    't("benchmark.trigger.target.legend")',
    't("benchmark.trigger.target.project")',
    't("benchmark.trigger.target.workspace")',
    't("benchmark.trigger.target.loadingProjects")',
    't("benchmark.trigger.target.selectProject")',
    't("benchmark.trigger.target.loadingWorkspaces")',
    't("benchmark.trigger.target.selectWorkspace")',
    't("benchmark.leaderboard.synthetic")',
  ].forEach((needle) =>
    assert.match(source, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))),
  );

  assert.doesNotMatch(
    source,
    /Real execution target|Loading projects|Select a workspace|>synthetic</,
  );
});

test("benchmark execution target keys are available in both locales", () => {
  assert.equal(
    getDictionaryValue("en-US", "benchmark.trigger.target.projectRequired"),
    "Select a project for the real benchmark run.",
  );
  assert.equal(
    getDictionaryValue("zh-CN", "benchmark.trigger.target.projectRequired"),
    "真实基准运行必须选择项目。",
  );
  assert.equal(getDictionaryValue("en-US", "benchmark.leaderboard.synthetic"), "Synthetic");
  assert.equal(getDictionaryValue("zh-CN", "benchmark.leaderboard.synthetic"), "模拟运行");
});
