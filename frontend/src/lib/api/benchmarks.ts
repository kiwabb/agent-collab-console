// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiJsonRequest, apiRequestOr } from "./fetch";
import type {
  BenchmarkDiff,
  BenchmarkJob,
  BenchmarkJobStatus,
  BenchmarkRun,
  CalibrationReport,
} from "../types";

export async function listBenchmarkRuns(limit = 50): Promise<BenchmarkRun[]> {
  const body = await apiRequestOr<{ runs?: BenchmarkRun[] }>(
    `${API_BASE}/codex/benchmark/runs?limit=${limit}`,
    { runs: [] },
    {
      dedupe: true,
      errorMessage: (status) => `listBenchmarkRuns failed: HTTP ${status}`,
    },
  );
  return (body.runs ?? []) as BenchmarkRun[];
}
export async function getBenchmarkRun(runId: string): Promise<BenchmarkRun | null> {
  return apiRequestOr<BenchmarkRun | null>(`${API_BASE}/codex/benchmark/runs/${runId}`, null, {
    dedupe: true,
    errorMessage: (status) => `getBenchmarkRun(${runId}) failed: HTTP ${status}`,
  });
}
export async function getBenchmarkRunDiff(runId: string): Promise<BenchmarkDiff | null> {
  return apiRequestOr<BenchmarkDiff | null>(
    `${API_BASE}/codex/benchmark/runs/${runId}/diff`,
    null,
    {
      dedupe: true,
      errorMessage: (status) => `getBenchmarkRunDiff(${runId}) failed: HTTP ${status}`,
    },
  );
}
export interface TriggerBenchmarkBody {
  label?: string | undefined;
  epochs?: number | undefined;
  fixture_ids?: string[] | undefined;
  is_baseline?: boolean | undefined;
  max_budget_usd?: number | undefined;
  project_id?: string;
  workspace_id?: string;
  dry_run?: boolean;
}
export interface TriggerBenchmarkResponse {
  job_id: string;
  status: BenchmarkJobStatus;
  status_url: string;
}
export async function triggerBenchmarkRun(
  body: TriggerBenchmarkBody,
): Promise<TriggerBenchmarkResponse> {
  return apiJsonRequest<TriggerBenchmarkResponse>(`${API_BASE}/codex/benchmark/runs`, "POST", body);
}
export async function getBenchmarkJob(jobId: string): Promise<BenchmarkJob | null> {
  return apiRequestOr<BenchmarkJob | null>(`${API_BASE}/codex/benchmark/jobs/${jobId}`, null, {
    dedupe: true,
    errorMessage: (status) => `getBenchmarkJob(${jobId}) failed: HTTP ${status}`,
  });
}
export async function getBaselineRun(): Promise<BenchmarkRun | null> {
  const body = await apiRequestOr<{ baseline?: BenchmarkRun | null }>(
    `${API_BASE}/codex/benchmark/baseline`,
    { baseline: null },
    {
      dedupe: true,
      errorMessage: (status) => `getBaselineRun failed: HTTP ${status}`,
    },
  );
  return (body.baseline ?? null) as BenchmarkRun | null;
}
interface SetBaselineRunResponse {
  ok: boolean;
  run_id: string;
}
export async function setBaselineRun(runId: string): Promise<boolean> {
  const body = await apiRequestOr<SetBaselineRunResponse | null>(
    `${API_BASE}/codex/benchmark/baseline/${runId}`,
    null,
    {
      init: { method: "POST" },
      errorMessage: (status) => `setBaselineRun(${runId}) failed: HTTP ${status}`,
    },
  );
  return body?.ok === true;
}
export async function getCalibrationReport(floor = 0.7): Promise<CalibrationReport | null> {
  return apiRequestOr<CalibrationReport | null>(
    `${API_BASE}/codex/benchmark/calibration?floor=${floor}`,
    null,
    {
      dedupe: true,
      errorMessage: (status) => `getCalibrationReport failed: HTTP ${status}`,
    },
  );
}
