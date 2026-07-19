import type {
  CodexTask,
  Project,
  ProjectEnvVarDisplay,
  ProjectApplicationReadinessState,
  ProjectRunLogLine,
  ProjectRunServiceState,
  ProjectRunStatus,
} from "@/lib/types";
import { safeJsonRecord } from "@/lib/utils";

import { describeScriptTaskTerminalStatus } from "./scriptTaskStatus";

export interface ProjectStartupAnalysis {
  taskId: string;
  status: string;
  accessUrl: string | null;
  notes: string[];
  updatedAt: string | null;
}

export type StartupStepStatus = "pending" | "active" | "complete" | "ready" | "error";
export type ProjectRunOutcome = "idle" | "running" | "completed" | "failed" | "stopped";
export type ProjectRunPresentation =
  | "managed_running"
  | "managed_starting"
  | "managed_unhealthy"
  | "external_ready"
  | "external_unhealthy"
  | "occupied_unknown"
  | "invalid_config"
  | "failed"
  | "completed"
  | "stopped"
  | "offline"
  | "unknown"
  | "ready";

export interface ProjectStartupState {
  analysis: StartupStepStatus;
  configure: StartupStepStatus;
  run: StartupStepStatus;
  envCount: number;
  missingCount: number;
  unsavedCount: number;
  canStart: boolean;
  runOutcome: ProjectRunOutcome;
  serviceState: ProjectRunServiceState;
  readinessState: ProjectApplicationReadinessState;
}

export interface ProjectRunRefreshErrors {
  status: string | null;
  logs: string | null;
}

export function updateProjectRunRefreshError(
  current: ProjectRunRefreshErrors,
  source: keyof ProjectRunRefreshErrors,
  error: string | null,
): ProjectRunRefreshErrors {
  return { ...current, [source]: error };
}

export function selectProjectRunRefreshError(errors: ProjectRunRefreshErrors): string | null {
  return errors.status ?? errors.logs;
}

export function deriveProjectRunOutcome(runStatus: ProjectRunStatus | null): ProjectRunOutcome {
  if (runStatus === null || runStatus.started_at === null) return "idle";
  if (runStatus.running) return "running";
  if (runStatus.exit_code === 0) return "completed";
  if (runStatus.exit_code !== null && runStatus.exit_code > 0) return "failed";
  return "stopped";
}

export function deriveProjectServiceState(
  runStatus: ProjectRunStatus | null,
): ProjectRunServiceState {
  return runStatus?.service.state ?? "unknown";
}

export function deriveProjectReadinessState(
  runStatus: ProjectRunStatus | null,
): ProjectApplicationReadinessState {
  return runStatus?.readiness.state ?? "invalid_config";
}

export function shouldPollProjectServiceStatus(runStatus: ProjectRunStatus | null): boolean {
  if (runStatus === null) return true;
  return (
    runStatus.service.state === "reachable" ||
    runStatus.service.state === "unreachable" ||
    runStatus.readiness.state === "identified_unready"
  );
}

export function deriveProjectRunPresentation(
  runStatus: ProjectRunStatus | null,
  startupState: ProjectStartupState,
): ProjectRunPresentation {
  const managedRunning = runStatus?.running === true;
  if (!managedRunning && startupState.readinessState === "ready") {
    return "external_ready";
  }
  if (!managedRunning && startupState.readinessState === "invalid_config") {
    return "invalid_config";
  }
  if (!managedRunning && startupState.readinessState === "identified_unready") {
    return "external_unhealthy";
  }
  if (!managedRunning && startupState.serviceState === "reachable") {
    return "occupied_unknown";
  }
  if (
    managedRunning &&
    (startupState.readinessState === "occupied_unknown" ||
      startupState.readinessState === "identified_unready")
  ) {
    return "managed_unhealthy";
  }
  if (managedRunning && startupState.readinessState !== "ready") {
    return "managed_starting";
  }
  if (managedRunning) return "managed_running";
  if (startupState.runOutcome === "failed") return "failed";
  if (startupState.runOutcome === "completed") return "completed";
  if (startupState.runOutcome === "stopped") return "stopped";
  if (startupState.serviceState === "unreachable") return "offline";
  if (startupState.serviceState === "invalid_url" || startupState.serviceState === "unknown") {
    return "unknown";
  }
  return "ready";
}

const RUN_FAILURE_MARKERS = [
  "error",
  "failed",
  "failure",
  "timeout",
  "timed out",
  "refused",
  "denied",
];

export function selectProjectRunFailureLine(logs: ProjectRunLogLine[]): string | null {
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const entry = logs[index];
    if (!entry) continue;
    const normalized = entry.line.toLowerCase();
    if (RUN_FAILURE_MARKERS.some((marker) => normalized.includes(marker))) {
      return entry.line;
    }
  }
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const entry = logs[index];
    if (entry?.stream === "stderr" && entry.line.trim()) return entry.line;
  }
  return null;
}

function taskTimestamp(task: CodexTask): number {
  const raw = task.updated_at ?? task.created_at;
  if (!raw) return 0;
  const timestamp = Date.parse(raw);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

export function selectLatestProjectStartupTask(tasks: CodexTask[]): CodexTask | null {
  let latest: CodexTask | null = null;
  for (const task of tasks) {
    if (task.task_kind !== "project_script_suggestion" || task.role !== "operations_engineer") {
      continue;
    }
    if (latest === null || taskTimestamp(task) > taskTimestamp(latest)) {
      latest = task;
    }
  }
  return latest;
}

export function readProjectStartupAnalysis(task: CodexTask | null): ProjectStartupAnalysis | null {
  if (task === null) return null;
  const parsed = task.result ? safeJsonRecord(task.result) : null;
  const accessUrl =
    parsed && typeof parsed["access_url"] === "string" ? parsed["access_url"] : null;
  const rawNotes = parsed?.["notes"];
  const notes = Array.isArray(rawNotes)
    ? rawNotes.filter((note): note is string => typeof note === "string")
    : [];
  return {
    taskId: task.id,
    status: task.status,
    accessUrl,
    notes,
    updatedAt: task.updated_at ?? task.created_at,
  };
}

interface DeriveProjectStartupStateInput {
  project: Project;
  envVars: ProjectEnvVarDisplay[];
  latestTask: CodexTask | null;
  runStatus: ProjectRunStatus | null;
  isAnalysisActive?: boolean;
  unsavedCount?: number;
}

export function deriveProjectStartupState({
  project,
  envVars,
  latestTask,
  runStatus,
  isAnalysisActive = false,
  unsavedCount = 0,
}: DeriveProjectStartupStateInput): ProjectStartupState {
  const taskState = describeScriptTaskTerminalStatus(latestTask?.status);
  const analysisFailed = taskState.terminal && !taskState.success;
  const analysisActive = isAnalysisActive || (latestTask !== null && !taskState.terminal);
  const hasAnalysisResult =
    taskState.success || Boolean(project.setup_script?.trim() || project.run_command?.trim());
  const missingCount = envVars.filter((envVar) => !envVar.is_set).length;
  const configureComplete = hasAnalysisResult && missingCount === 0 && unsavedCount === 0;
  const runOutcome = deriveProjectRunOutcome(runStatus);
  const serviceState = deriveProjectServiceState(runStatus);
  const readinessState = deriveProjectReadinessState(runStatus);
  const running = runOutcome === "running";
  const canStart =
    hasAnalysisResult &&
    configureComplete &&
    Boolean(project.run_command?.trim()) &&
    !running &&
    serviceState !== "reachable" &&
    readinessState !== "invalid_config";

  return {
    analysis: analysisActive
      ? "active"
      : analysisFailed
        ? "error"
        : hasAnalysisResult
          ? "complete"
          : "pending",
    configure:
      !hasAnalysisResult || unsavedCount > 0 ? "pending" : missingCount > 0 ? "error" : "complete",
    run:
      readinessState === "ready"
        ? "complete"
        : readinessState === "invalid_config"
          ? "error"
          : runOutcome === "running"
            ? "active"
            : runOutcome === "failed"
              ? "error"
              : runOutcome === "completed"
                ? "complete"
                : canStart
                  ? "ready"
                  : "pending",
    envCount: envVars.length,
    missingCount,
    unsavedCount,
    canStart,
    runOutcome,
    serviceState,
    readinessState,
  };
}
