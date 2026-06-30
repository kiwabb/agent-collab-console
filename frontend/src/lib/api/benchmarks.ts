// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, dedupedFetch } from "./fetch";
import type {
  BenchmarkDiff,
  BenchmarkJob,
  BenchmarkJobStatus,
  BenchmarkRun,
  CalibrationReport,
} from "../types";

export async function listBenchmarkRuns(limit = 50): Promise<import("../types").BenchmarkRun[]> {
  const response = await dedupedFetch(`${API_BASE}/codex/benchmark/runs?limit=${limit}`);
  if (!response.ok) {
    console.error(`listBenchmarkRuns failed: HTTP ${response.status}`);
    return [];
  }
  const body = await response.json();
  return (body.runs ?? []) as import("../types").BenchmarkRun[];
}
export async function getBenchmarkRun(
  runId: string,
): Promise<import("../types").BenchmarkRun | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/benchmark/runs/${runId}`);
  if (!response.ok) {
    console.error(`getBenchmarkRun(${runId}) failed: HTTP ${response.status}`);
    return null;
  }
  return response.json() as Promise<import("../types").BenchmarkRun>;
}
export async function getBenchmarkRunDiff(
  runId: string,
): Promise<import("../types").BenchmarkDiff | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/benchmark/runs/${runId}/diff`);
  if (!response.ok) {
    console.error(`getBenchmarkRunDiff(${runId}) failed: HTTP ${response.status}`);
    return null;
  }
  return response.json() as Promise<import("../types").BenchmarkDiff>;
}
export interface TriggerBenchmarkBody {
  label?: string;
  epochs?: number;
  fixture_ids?: string[];
  is_baseline?: boolean;
  max_budget_usd?: number;
  project_id?: string;
  workspace_id?: string;
  dry_run?: boolean;
}
export interface TriggerBenchmarkResponse {
  job_id: string;
  status: import("../types").BenchmarkJobStatus;
  status_url: string;
}
export async function triggerBenchmarkRun(
  body: TriggerBenchmarkBody,
): Promise<TriggerBenchmarkResponse> {
  const response = await fetch(`${API_BASE}/codex/benchmark/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(
      `triggerBenchmarkRun failed: HTTP ${response.status} — ${JSON.stringify(detail.detail)}`,
    );
  }
  return response.json() as Promise<TriggerBenchmarkResponse>;
}
export async function getBenchmarkJob(
  jobId: string,
): Promise<import("../types").BenchmarkJob | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/benchmark/jobs/${jobId}`);
  if (!response.ok) {
    console.error(`getBenchmarkJob(${jobId}) failed: HTTP ${response.status}`);
    return null;
  }
  return response.json() as Promise<import("../types").BenchmarkJob>;
}
export async function getBaselineRun(): Promise<import("../types").BenchmarkRun | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/benchmark/baseline`);
  if (!response.ok) {
    console.error(`getBaselineRun failed: HTTP ${response.status}`);
    return null;
  }
  const body = await response.json();
  return (body.baseline ?? null) as import("../types").BenchmarkRun | null;
}
export async function setBaselineRun(runId: string): Promise<boolean> {
  const response = await fetch(`${API_BASE}/codex/benchmark/baseline/${runId}`, { method: "POST" });
  if (!response.ok) {
    console.error(`setBaselineRun(${runId}) failed: HTTP ${response.status}`);
    return false;
  }
  return true;
}
export async function getCalibrationReport(
  floor = 0.7,
): Promise<import("../types").CalibrationReport | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/benchmark/calibration?floor=${floor}`);
  if (!response.ok) {
    console.error(`getCalibrationReport failed: HTTP ${response.status}`);
    return null;
  }
  return response.json() as Promise<import("../types").CalibrationReport>;
}
