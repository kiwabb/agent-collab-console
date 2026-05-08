import type { CodexIssue, CodexTask, ExecutionProcess, HelpRequest } from "./types";

export const PHASES = ["requirements", "architecture", "development", "testing"] as const;
export type Phase = (typeof PHASES)[number];

export const PHASE_CONFIG: Record<Phase, {
  labelKey: string;
  descriptionKey: string;
  buttonLabelKey: string;
  role: string;
}> = {
  requirements: {
    labelKey: "phase.requirements",
    descriptionKey: "phase.requirements",
    buttonLabelKey: "phase.runProductManager",
    role: "product_manager",
  },
  architecture: {
    labelKey: "phase.architecture",
    descriptionKey: "phase.architecture",
    buttonLabelKey: "phase.runArchitect",
    role: "architect",
  },
  development: {
    labelKey: "phase.development",
    descriptionKey: "phase.development",
    buttonLabelKey: "phase.runEngineer",
    role: "engineer",
  },
  testing: {
    labelKey: "phase.testing",
    descriptionKey: "phase.testing",
    buttonLabelKey: "phase.runQa",
    role: "qa",
  },
};

export function groupIssuesByPhase(issues: CodexIssue[]): Record<Phase, CodexIssue[]> {
  const result: Record<Phase, CodexIssue[]> = {
    requirements: [],
    architecture: [],
    development: [],
    testing: [],
  };
  for (const issue of issues) {
    const phase = (issue.current_phase || "requirements") as Phase;
    if (phase in result) {
      result[phase].push(issue);
    } else {
      result.requirements.push(issue);
    }
  }
  return result;
}

export interface IssueCounts {
  total: number;
  running: number;
  failed: number;
  waiting: number;
  helpCount: number;
}

export function deriveIssueCounts(
  issueId: string,
  tasks: CodexTask[],
  executionProcesses: ExecutionProcess[],
  helpRequests: HelpRequest[]
): IssueCounts {
  const issueTasks = tasks.filter((t) => t.issue_id === issueId);
  const taskIds = new Set(issueTasks.map((t) => t.id));

  const helpCount = helpRequests.filter((hr) => taskIds.has(hr.parent_task_id)).length;

  const relevantProcesses = executionProcesses.filter((p) => taskIds.has(p.task_id));
  const running = relevantProcesses.filter(
    (p) => p.status === "running" || p.status === "responding",
  ).length;
  const failed = relevantProcesses.filter((p) => p.status === "failed").length;
  const waiting = relevantProcesses.filter(
    (p) => p.status === "waiting" || p.status === "blocked",
  ).length;

  return {
    total: issueTasks.length,
    running,
    failed,
    waiting,
    helpCount,
  };
}

export interface TaskStatusSummary {
  pending: number;
  running: number;
  completed: number;
  failed: number;
  waiting: number;
  blocked: number;
}

export function deriveTaskStatusSummary(tasks: CodexTask[]): TaskStatusSummary {
  const summary: TaskStatusSummary = {
    pending: 0,
    running: 0,
    completed: 0,
    failed: 0,
    waiting: 0,
    blocked: 0,
  };
  for (const task of tasks) {
    const status = (task.status || "pending").toLowerCase() as keyof TaskStatusSummary;
    if (status in summary) {
      summary[status]++;
    }
  }
  return summary;
}

export function pickDisplayedExecutionProcess(
  executionProcesses: ExecutionProcess[],
  currentProcessId: string | null,
): ExecutionProcess | null {
  if (currentProcessId) {
    return executionProcesses.find((p) => p.id === currentProcessId) ?? null;
  }
  let newest: ExecutionProcess | null = null;
  let newestTime = 0;
  for (const p of executionProcesses) {
    const t = p.created_at ? new Date(p.created_at).getTime() : 0;
    if (t >= newestTime) {
      newestTime = t;
      newest = p;
    }
  }
  return newest;
}

export function pickLatestExecutionProcessForTask(
  executionProcesses: ExecutionProcess[],
  taskId: string | null | undefined,
): ExecutionProcess | null {
  if (!taskId) return null;

  let newest: ExecutionProcess | null = null;
  let newestTime = 0;
  for (const process of executionProcesses) {
    if (process.task_id !== taskId) continue;
    const t = process.created_at ? new Date(process.created_at).getTime() : 0;
    const started = process.started_at ? new Date(process.started_at).getTime() : 0;
    const updated = process.updated_at ? new Date(process.updated_at).getTime() : 0;
    const completed = process.completed_at ? new Date(process.completed_at).getTime() : 0;
    const time = Math.max(t, started, updated, completed);
    if (time >= newestTime) {
      newestTime = time;
      newest = process;
    }
  }
  return newest;
}

export function getTaskRuntimeStatus(
  task: CodexTask | null | undefined,
  executionProcesses: ExecutionProcess[],
): string {
  if (!task) return "pending";
  
  const taskStatus = String(task.status || "pending").toLowerCase();
  
  // Always return task status for business-level states
  // Task status represents the actual business state (done, awaiting_review, rework, etc.)
  // ExecutionProcess status only represents the runtime execution state (Running, Completed, Failed)
  
  // If task has a definitive status, use it
  if (taskStatus && taskStatus !== "pending") {
    return task.status || "pending";
  }
  
  // Only for pending tasks, check if there's an active execution process
  const latestProcess = pickLatestExecutionProcessForTask(executionProcesses, task.id);
  if (latestProcess?.status && String(latestProcess.status).toLowerCase() === "running") {
    return "running";
  }

  return task.status || "pending";
}

export function isTaskRuntimeActive(
  task: CodexTask | null | undefined,
  executionProcesses: ExecutionProcess[],
): boolean {
  const status = String(getTaskRuntimeStatus(task, executionProcesses) || "").toLowerCase();
  return status === "running" || status === "responding";
}
