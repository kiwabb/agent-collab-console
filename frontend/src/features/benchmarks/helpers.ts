/**
 * Pure helpers for the Benchmarks page.
 *
 * These functions are imported by the React components and
 * unit-tested in isolation. Keeping them here means the
 * diff-classification, color tier, and SVG projection logic
 * have a single source of truth that does not depend on
 * React, hooks, or the network.
 */
import type { BenchmarkDiffFixture, BenchmarkJobStatus } from "@/lib/types";
import type { TriggerBenchmarkBody } from "@/lib/api/benchmarks";

export function benchmarkTargetError(
  dryRun: boolean,
  projectId: string,
  workspaceId: string,
): "project_required" | "workspace_required" | null {
  if (dryRun) return null;
  if (!projectId) return "project_required";
  if (!workspaceId) return "workspace_required";
  return null;
}

interface BenchmarkTriggerValues {
  label: string;
  epochs: number;
  dryRun: boolean;
  projectId: string;
  workspaceId: string;
  maxBudgetUsd: number | undefined;
}

export function buildBenchmarkTriggerBody(values: BenchmarkTriggerValues): TriggerBenchmarkBody {
  const selectionError = benchmarkTargetError(values.dryRun, values.projectId, values.workspaceId);
  if (selectionError) throw new Error(selectionError);

  const common = {
    label: values.label || undefined,
    epochs: values.epochs,
    max_budget_usd: values.maxBudgetUsd,
  };
  return values.dryRun
    ? { ...common, dry_run: true }
    : {
        ...common,
        dry_run: false,
        project_id: values.projectId,
        workspace_id: values.workspaceId,
      };
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

/** Format a USD amount as a short string (`$1.23`, `$0.045`, `$12`). */
export function fmtUsd(amount: number | null | undefined): string {
  if (amount == null || !Number.isFinite(amount)) return "—";
  if (amount === 0) return "$0";
  if (amount < 0.01) return `$${amount.toFixed(4)}`;
  if (amount < 1) return `$${amount.toFixed(3)}`;
  return `$${amount.toFixed(2)}`;
}

/** Format a 0..1 score as a percent string (`85.0%`). */
export function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Format a "passed 1.0 ± 0.05" style line. */
export function fmtPassAt1(
  value: number | null | undefined,
  stderr: number | null | undefined,
): string {
  if (value == null) return "—";
  const v = (value * 100).toFixed(1);
  if (stderr == null) return `${v}%`;
  return `${v}% ± ${(stderr * 100).toFixed(1)}%`;
}

/** Format an ISO-8601 timestamp as a short date+time (`2026-06-03 10:30`). */
export function fmtTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

// ---------------------------------------------------------------------------
// Diff classification
// ---------------------------------------------------------------------------

/**
 * Coarse "improved / regressed / unchanged" classification. The
 * `|delta| < tol` band is `unchanged`; a positive delta above tol
 * is `improved`; a negative delta below `-tol` is `regressed`.
 *
 * The default tolerance is 0.05 (5pp on pass@1). It matches the
 * backend's `RunDiff.fixture_status` granularity; the leaderboard
 * uses the same band so the two stay in sync.
 */
export type DiffStatus = "improved" | "regressed" | "unchanged";

export function classifyDelta(delta: number, tol = 0.05): DiffStatus {
  if (delta > tol) return "improved";
  if (delta < -tol) return "regressed";
  return "unchanged";
}

/** Count the regressed + improved per-fixture buckets for the summary line. */
export function summarizeDiff(fixtures: readonly BenchmarkDiffFixture[]): {
  improved: number;
  regressed: number;
  unchanged: number;
} {
  let improved = 0;
  let regressed = 0;
  let unchanged = 0;
  for (const f of fixtures) {
    if (f.status === "improved") improved += 1;
    else if (f.status === "regressed") regressed += 1;
    else unchanged += 1;
  }
  return { improved, regressed, unchanged };
}

// ---------------------------------------------------------------------------
// Score×cost frontier projection
// ---------------------------------------------------------------------------

/** A single (x, y) point on the frontier chart, in DATA coordinates
 * (USD, pass@1). The SVG projection is computed by ``projectPoints``. */
export interface FrontierPoint {
  runId: string;
  label: string;
  isBaseline: boolean;
  costPerIssueUsd: number; // x
  passAt1: number; // y
}

export interface ProjectedPoint {
  runId: string;
  label: string;
  isBaseline: boolean;
  /** Pixel x relative to the chart's left edge. */
  px: number;
  /** Pixel y relative to the chart's top edge. */
  py: number;
  /** Final radius of the dot in pixels (baseline = 6, others = 4). */
  r: number;
}

export interface ChartBox {
  width: number;
  height: number;
  padLeft: number;
  padRight: number;
  padTop: number;
  padBottom: number;
}

const DEFAULT_BOX: ChartBox = {
  width: 480,
  height: 280,
  padLeft: 44,
  padRight: 12,
  padTop: 12,
  padBottom: 32,
};

/**
 * Project a list of ``FrontierPoint`` into SVG pixel coordinates.
 *
 * The X axis is log-scaled: cost can span four orders of magnitude
 * ($0.001 .. $10) and a linear axis would squash every cheap
 * run into the lower-left corner. The Y axis is linear 0..1.
 */
export function projectPoints(
  points: readonly FrontierPoint[],
  box: ChartBox = DEFAULT_BOX,
): { projected: ProjectedPoint[]; axis: { xMin: number; xMax: number } } {
  if (points.length === 0) {
    return { projected: [], axis: { xMin: 0, xMax: 1 } };
  }
  const xs = points.map((p) => Math.max(p.costPerIssueUsd, 1e-4));
  // Pad the log scale so a single point doesn't sit on the edge.
  const xMinRaw = Math.min(...xs);
  const xMaxRaw = Math.max(...xs);
  const lo = Math.log10(xMinRaw);
  const hi = Math.log10(xMaxRaw);
  const xMin = hi - lo < 0.01 ? lo - 0.5 : lo;
  const xMax = hi - lo < 0.01 ? hi + 0.5 : hi;
  const xRange = xMax - xMin || 1;
  const innerW = box.width - box.padLeft - box.padRight;
  const innerH = box.height - box.padTop - box.padBottom;
  const projected: ProjectedPoint[] = points.map((p) => {
    const v = Math.max(p.costPerIssueUsd, 1e-4);
    const t = (Math.log10(v) - xMin) / xRange;
    const px = box.padLeft + t * innerW;
    const py = box.padTop + (1 - p.passAt1) * innerH;
    return {
      runId: p.runId,
      label: p.label,
      isBaseline: p.isBaseline,
      px,
      py,
      r: p.isBaseline ? 6 : 4,
    };
  });
  return { projected, axis: { xMin: 10 ** xMin, xMax: 10 ** xMax } };
}

/** Format a 10**x value for the X-axis tick label (`$0.01`, `$1`,
 * `$100`). Used by the SVG ``<text>`` ticks. */
export function fmtCostTick(value: number): string {
  if (value >= 1) return `$${value.toFixed(value >= 10 ? 0 : 1)}`;
  if (value >= 0.01) return `$${value.toFixed(2)}`;
  return `$${value.toFixed(3)}`;
}

// ---------------------------------------------------------------------------
// Run row helpers
// ---------------------------------------------------------------------------

/** Pick 5 evenly-spaced ticks across the log-scaled X axis. */
export function pickLogTicks(xMin: number, xMax: number, count = 5): number[] {
  if (xMin <= 0 || xMax <= 0 || xMin >= xMax) return [];
  const lo = Math.log10(xMin);
  const hi = Math.log10(xMax);
  const span = hi - lo;
  const step = span / (count - 1);
  const ticks: number[] = [];
  for (let i = 0; i < count; i += 1) {
    const exp = lo + step * i;
    const value = 10 ** exp;
    if (!Number.isFinite(value) || value <= 0) continue;
    ticks.push(value);
  }
  return ticks;
}

/** Stable, round number for an axis tick. Used to avoid
 * `Math.log10(0.030000000000000002)`-style display noise. */
export function roundTick(value: number): number {
  if (value >= 1) return Math.round(value);
  // For sub-1, round to 2 sig figs.
  const exp = Math.floor(Math.log10(value));
  return Math.round(value / 10 ** exp) * 10 ** exp;
}

export function pickLogTicksRounded(xMin: number, xMax: number, count = 5): number[] {
  return pickLogTicks(xMin, xMax, count).map(roundTick);
}

// ---------------------------------------------------------------------------
// Job status
// ---------------------------------------------------------------------------

/** Human-friendly job status — used to render the spinner label. */
export function jobStatusLabelKey(
  status: BenchmarkJobStatus,
):
  | "benchmark.status.pending"
  | "benchmark.status.running"
  | "benchmark.status.completed"
  | "benchmark.status.failed" {
  return `benchmark.status.${status}` as const;
}
