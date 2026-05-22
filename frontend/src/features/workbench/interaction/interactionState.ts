import type {
  Approval,
  Artifact,
  CodexIssue,
  CodexTask,
  ExecutionProcess,
} from "@/lib/types";

export type AttentionKind = "approval" | "failure" | "running" | "question";

export interface AttentionItem {
  id: string;
  kind: AttentionKind;
  title: string;
  detail: string;
  href: string;
  priority: number;
}

export interface IssueNextAction {
  id:
    | "approve_plan"
    | "review_qa"
    | "run_phase"
    | "inspect_failure"
    | "wait_for_agent"
    | "open_tasks";
  label: string;
  detail: string;
  enabled: boolean;
  disabledReason?: string;
  href?: string;
}

export interface RecoveryAction {
  id:
    | "open_logs"
    | "rerun_same"
    | "change_executor"
    | "submit_review"
    | "stop_run";
  label: string;
  detail: string;
  tone: "neutral" | "primary" | "warning" | "danger";
}

export function deriveAttentionItems(input: {
  issues: CodexIssue[];
  tasks: CodexTask[];
  processes: ExecutionProcess[];
  approvals: Approval[];
}): AttentionItem[] {
  const items: AttentionItem[] = [];

  for (const issue of input.issues) {
    const title = issue.title || issue.id.slice(0, 8);
    if (
      issue.status === "awaiting_approval" ||
      issue.status === "awaiting_review"
    ) {
      items.push({
        id: issue.id,
        kind: "approval",
        title,
        detail: "Human review required",
        href: `/issues/${issue.id}`,
        priority: 10,
      });
    } else if (issue.status === "failed") {
      items.push({
        id: issue.id,
        kind: "failure",
        title,
        detail: "Workflow needs recovery",
        href: `/issues/${issue.id}?tab=tasks`,
        priority: 8,
      });
    } else if (issue.status === "in_progress") {
      items.push({
        id: issue.id,
        kind: "running",
        title,
        detail: `Phase ${issue.current_phase ?? "unknown"}`,
        href: `/issues/${issue.id}`,
        priority: 6,
      });
    }
  }

  for (const task of input.tasks) {
    if ((task.review_comment || "").startsWith("[CLARIFY] ")) {
      items.push({
        id: task.id,
        kind: "question",
        title: task.title || task.id.slice(0, 8),
        detail: "Agent question waiting for answer",
        href: task.issue_id
          ? `/issues/${task.issue_id}?tab=tasks&taskId=${task.id}`
          : "/approvals",
        priority: 9,
      });
    }
  }

  return items.sort((a, b) => b.priority - a.priority).slice(0, 8);
}

export function deriveIssueNextAction(input: {
  issue: CodexIssue | null;
  tasks: CodexTask[];
  artifacts: Artifact[];
}): IssueNextAction {
  const issue = input.issue;
  if (!issue) {
    return {
      id: "open_tasks",
      label: "Select an issue",
      detail: "No issue is loaded.",
      enabled: false,
    };
  }

  const issueTasks = input.tasks.filter((task) => task.issue_id === issue.id);
  const hasActiveTask = issueTasks.some((task) =>
    ["running", "responding"].includes(
      String(task.status || "").toLowerCase(),
    ),
  );
  const hasFailure =
    issue.status === "failed" ||
    issueTasks.some(
      (task) => String(task.status || "").toLowerCase() === "failed",
    );

  if (hasFailure) {
    return {
      id: "inspect_failure",
      label: "Inspect failure",
      detail: "Open task logs and recovery actions.",
      enabled: true,
      href: `/issues/${issue.id}?tab=tasks`,
    };
  }
  if (issue.status === "awaiting_approval") {
    return {
      id: "approve_plan",
      label: "Review plan",
      detail: "Plan approval is required before agents continue.",
      enabled: true,
    };
  }
  if (issue.status === "awaiting_review") {
    return {
      id: "review_qa",
      label: "Review QA",
      detail: "QA passed and awaits human review.",
      enabled: true,
    };
  }
  if (hasActiveTask) {
    return {
      id: "wait_for_agent",
      label: "Agent running",
      detail: "Live work is in progress.",
      enabled: false,
      disabledReason:
        "A task is currently running. Wait for completion or open the live run.",
    };
  }
  return {
    id: "run_phase",
    label: "Run current phase",
    detail: `Dispatch the next agent for ${issue.current_phase ?? "this phase"}.`,
    enabled: true,
  };
}

export function deriveRunRecoveryActions(input: {
  task: CodexTask | null;
  process: ExecutionProcess | null;
}): RecoveryAction[] {
  const status = String(
    input.process?.status || input.task?.status || "",
  ).toLowerCase();

  if (status === "failed") {
    return [
      {
        id: "open_logs",
        label: "Open logs",
        detail: "Inspect the failure before retrying.",
        tone: "neutral",
      },
      {
        id: "rerun_same",
        label: "Rerun same executor",
        detail: "Retry with the current runtime.",
        tone: "primary",
      },
      {
        id: "change_executor",
        label: "Change executor",
        detail: "Switch runtime before rerun.",
        tone: "warning",
      },
    ];
  }
  if (status === "running" || status === "responding") {
    return [
      {
        id: "stop_run",
        label: "Stop run",
        detail: "Terminate the active execution process.",
        tone: "danger",
      },
    ];
  }
  if (status === "completed" || status === "done") {
    return [
      {
        id: "submit_review",
        label: "Submit for review",
        detail: "Move completed work into review.",
        tone: "primary",
      },
    ];
  }
  return [];
}
