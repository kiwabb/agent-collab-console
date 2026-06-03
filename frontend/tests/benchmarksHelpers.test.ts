/**
 * Pure helper tests for the Benchmarks page (PR4).
 */
import { strict as assert } from "node:assert";
import test from "node:test";

import {
  classifyDelta,
  fmtPassAt1,
  fmtTimestamp,
  fmtUsd,
  pickLogTicks,
  pickLogTicksRounded,
  projectPoints,
  roundTick,
  summarizeDiff,
  type FrontierPoint,
} from "../src/features/benchmarks/helpers";
import type { BenchmarkDiffFixture } from "../src/lib/types";

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------


test("fmtUsd handles edge cases", () => {
  assert.equal(fmtUsd(0), "$0");
  assert.equal(fmtUsd(0.005), "$0.0050");
  assert.equal(fmtUsd(0.123), "$0.123");
  assert.equal(fmtUsd(1.5), "$1.50");
  assert.equal(fmtUsd(123.456), "$123.46");
  assert.equal(fmtUsd(null), "—");
  assert.equal(fmtUsd(undefined), "—");
  assert.equal(fmtUsd(Number.NaN), "—");
});


test("fmtPassAt1 formats score ± stderr", () => {
  assert.equal(fmtPassAt1(0.85, 0.05), "85.0% ± 5.0%");
  assert.equal(fmtPassAt1(0.85, null), "85.0%");
  assert.equal(fmtPassAt1(null, 0.05), "—");
});


test("fmtTimestamp handles null + parses ISO", () => {
  assert.equal(fmtTimestamp(null), "—");
  assert.equal(fmtTimestamp("not-a-date"), "—");
  // 2026-06-03T10:30:00 in local time; just check the shape.
  const out = fmtTimestamp("2026-06-03T10:30:00");
  assert.match(out, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
});


// ---------------------------------------------------------------------------
// Diff classification
// ---------------------------------------------------------------------------


test("classifyDelta: positive above tol is improved", () => {
  assert.equal(classifyDelta(0.10, 0.05), "improved");
  assert.equal(classifyDelta(0.06, 0.05), "improved");
});


test("classifyDelta: negative below -tol is regressed", () => {
  assert.equal(classifyDelta(-0.10, 0.05), "regressed");
  assert.equal(classifyDelta(-0.06, 0.05), "regressed");
});


test("classifyDelta: in the band is unchanged", () => {
  assert.equal(classifyDelta(0.0, 0.05), "unchanged");
  assert.equal(classifyDelta(0.05, 0.05), "unchanged");
  assert.equal(classifyDelta(-0.05, 0.05), "unchanged");
  assert.equal(classifyDelta(0.04, 0.05), "unchanged");
});


test("summarizeDiff counts the three buckets", () => {
  const items: BenchmarkDiffFixture[] = [
    { fixture_id: "a", candidate_pass_at_1: 0.9, baseline_pass_at_1: 0.5, delta: 0.4, status: "improved" },
    { fixture_id: "b", candidate_pass_at_1: 0.2, baseline_pass_at_1: 0.7, delta: -0.5, status: "regressed" },
    { fixture_id: "c", candidate_pass_at_1: 0.5, baseline_pass_at_1: 0.5, delta: 0.0, status: "unchanged" },
    { fixture_id: "d", candidate_pass_at_1: 0.4, baseline_pass_at_1: 0.5, delta: -0.1, status: "regressed" },
  ];
  const out = summarizeDiff(items);
  assert.equal(out.improved, 1);
  assert.equal(out.regressed, 2);
  assert.equal(out.unchanged, 1);
});


// ---------------------------------------------------------------------------
// Score × cost frontier projection
// ---------------------------------------------------------------------------


const FRONTIER_POINTS: FrontierPoint[] = [
  { runId: "r1", label: "v0.5",     isBaseline: true,  costPerIssueUsd: 0.05, passAt1: 0.7 },
  { runId: "r2", label: "v0.6-cheap", isBaseline: false, costPerIssueUsd: 0.02, passAt1: 0.5 },
  { runId: "r3", label: "v0.6-mid",  isBaseline: false, costPerIssueUsd: 0.20, passAt1: 0.8 },
  { runId: "r4", label: "v0.6-big",  isBaseline: false, costPerIssueUsd: 2.0,  passAt1: 0.9 },
];


test("projectPoints projects all points inside the chart box", () => {
  const { projected, axis } = projectPoints(FRONTIER_POINTS);
  assert.equal(projected.length, 4);
  for (const p of projected) {
    assert.ok(p.px >= 0 && p.px <= 480, `px ${p.px} out of range`);
    assert.ok(p.py >= 0 && p.py <= 280, `py ${p.py} out of range`);
  }
  // The baseline (true) should be drawn larger than the others.
  const baseline = projected.find((p) => p.isBaseline);
  assert.ok(baseline, "baseline point present");
  assert.equal(baseline.r, 6);
  for (const p of projected) {
    if (!p.isBaseline) assert.equal(p.r, 4);
  }
  assert.ok(axis.xMin > 0 && axis.xMax > axis.xMin);
});


test("projectPoints log-scaled x preserves order on log axis", () => {
  // r1 ($0.05) sits to the LEFT of r4 ($2.00) on the chart.
  const { projected } = projectPoints(FRONTIER_POINTS);
  const r1 = projected.find((p) => p.runId === "r1")!;
  const r4 = projected.find((p) => p.runId === "r4")!;
  assert.ok(r1.px < r4.px, "cheaper run should sit to the left");
});


test("projectPoints y axis is linear 0..1 (inverted)", () => {
  // Higher pass@1 → smaller py (closer to top of chart).
  const { projected } = projectPoints(FRONTIER_POINTS);
  const r1 = projected.find((p) => p.runId === "r1")!; // 0.7
  const r4 = projected.find((p) => p.runId === "r4")!; // 0.9
  assert.ok(r4.py < r1.py, "higher pass@1 should be higher on chart (smaller y)");
});


test("projectPoints empty input returns empty", () => {
  const { projected, axis } = projectPoints([]);
  assert.equal(projected.length, 0);
  assert.equal(axis.xMin, 0);
});


test("projectPoints pads a single point", () => {
  // One point would give xMin == xMax; the function pads to ±0.5
  // log units so the point is visible in the middle of the chart.
  const { projected, axis } = projectPoints([
    { runId: "solo", label: "solo", isBaseline: false, costPerIssueUsd: 0.10, passAt1: 0.5 },
  ]);
  assert.equal(projected.length, 1);
  assert.ok(axis.xMax > axis.xMin);
  // The point sits at the centre of the chart's plotting area
  // (which is `padLeft + innerW/2`, not the bounding-box centre
  // because the padding is asymmetric: left=44, right=12).
  const expectedMidX = 44 + (480 - 44 - 12) / 2;
  assert.ok(Math.abs(projected[0].px - expectedMidX) < 5);
});


test("pickLogTicks returns N sorted values across [xMin, xMax]", () => {
  const ticks = pickLogTicks(0.01, 10, 5);
  assert.equal(ticks.length, 5);
  // Strictly increasing.
  for (let i = 1; i < ticks.length; i += 1) {
    assert.ok(ticks[i] > ticks[i - 1], "ticks must be increasing");
  }
  // First and last within an order of magnitude of the bounds.
  assert.ok(ticks[0] >= 0.01 * 0.5);
  assert.ok(ticks[ticks.length - 1] <= 10 * 2);
});


test("pickLogTicks handles degenerate range", () => {
  // xMin == xMax (single value): no usable ticks.
  const ticks = pickLogTicks(1.0, 1.0);
  assert.equal(ticks.length, 0);
});


test("roundTick: 0.030000000000000002 → 0.03", () => {
  assert.equal(roundTick(0.03), 0.03);
  assert.equal(roundTick(0.03000001), 0.03);
  assert.equal(roundTick(0.5), 0.5);
  assert.equal(roundTick(7), 7);
});


test("pickLogTicksRounded returns clean values", () => {
  const ticks = pickLogTicksRounded(0.01, 100, 5);
  for (const t of ticks) {
    // No floating point noise: 0.0300000001 should round to 0.03.
    assert.equal(t, roundTick(t));
  }
});
