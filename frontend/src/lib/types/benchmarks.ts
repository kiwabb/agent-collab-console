// AUTO-SPLIT from lib/types.ts by domain (frontend lib split).

/** Job status returned by the in-memory JobRegistry. */
export type BenchmarkJobStatus = "pending" | "running" | "completed" | "failed";

/**
 * One benchmark run, returned by `GET /codex/benchmark/runs/{id}` and
 * the list endpoint. Mirrors the backend ``BenchmarkRun`` row.
 */
export interface BenchmarkRun {
  id: string;
  created_at: string;
  label: string | null;
  orchestrator_version: string | null;
  epoch_count: number;
  fixture_ids: string[];
  is_baseline: boolean;
  is_synthetic: boolean;
  status: "running" | "completed" | "failed";
  notes: string | null;
  aggregate_pass_at_1: number | null;
  aggregate_pass_at_1_stderr: number | null;
  cost_total_usd: number | null;
  cost_per_issue_usd: number | null;
  total_input_tokens: number | null;
  total_output_tokens: number | null;
  total_duration_s: number | null;
  n_epochs: number | null;
}

/** Per-epoch view (subset of ``BenchmarkEpoch``). */
export interface BenchmarkEpoch {
  id: string;
  run_id: string;
  fixture_id: string;
  epoch_index: number;
  pass_execution: boolean;
  pass_coverage: boolean;
  score_execution: number;
  score_coverage: number;
  score_aggregate: number;
  spent_usd: number;
  duration_s: number;
  error: string | null;
}

/**
 * Diff result for one candidate run against the current baseline.
 * ``null`` for ``diff`` means "no baseline pinned yet" or "the
 * candidate IS the baseline" — the leaderboard surfaces a
 * polite message rather than an empty diff.
 */
export interface BenchmarkDiffFixture {
  fixture_id: string;
  candidate_pass_at_1: number;
  baseline_pass_at_1: number;
  delta: number;
  status: "improved" | "regressed" | "unchanged";
}

export interface BenchmarkDiff {
  candidate: BenchmarkRun;
  baseline: BenchmarkRun | null;
  diff: {
    aggregate_delta: number;
    aggregate_status: "improved" | "regressed" | "unchanged";
    candidate_stderr: number;
    baseline_stderr: number;
    regressed_fixtures: string[];
    improved_fixtures: string[];
    per_fixture: BenchmarkDiffFixture[];
  } | null;
  note?: string;
}

/** In-memory job metadata returned by the trigger endpoint. */
export interface BenchmarkJob {
  id: string;
  kind: string;
  status: BenchmarkJobStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  result_ref: string | null;
  error: string | null;
  progress: number;
  meta: Record<string, unknown>;
}

/** One hand-labeled judge calibration item. */
export interface CalibrationItem {
  id: string;
  fixture_id: string | null;
  human_score: number;
  judge_score: number | null;
  note: string | null;
}

/** GET /codex/benchmark/calibration response. */
export interface CalibrationReport {
  n: number;
  pearson: number;
  spearman: number;
  floor: number;
  is_calibrated: boolean;
  weakest_item: string | null;
  summary: string;
  items: CalibrationItem[];
}
