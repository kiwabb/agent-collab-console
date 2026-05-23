import { PHASE_CONFIG, type Phase } from "@/lib/task-selection";
import type { CodexIssue, CodexTask, RuntimeCatalog } from "@/lib/types";

const ACTIVE_TASK_STATUSES = new Set([
  "running",
  "responding",
  "pending",
  "queued",
  "ready",
  "awaiting_review",
  "rework",
]);

const ROLE_LABELS: Record<string, string> = {
  product_manager: "PM",
  architect: "Architect",
  engineer: "Engineer",
  qa: "QA",
};

export function deriveWorkspaceConsoleDefaultRuntime(
  catalog: RuntimeCatalog | null,
): { executor: string; model: string | null } {
  const executor = catalog?.executors.find((candidate) => candidate.enabled) ?? null;
  return {
    executor: executor?.id ?? "codex",
    model: executor?.default_model ?? null,
  };
}

export function formatWorkspaceConsoleRepoLabel(repoPath: string | null | undefined): string {
  if (!repoPath) return "—";
  const parts = repoPath.split("/").filter(Boolean);
  if (parts.length === 0) return "—";
  return `~/${parts.slice(-2).join("/")}`;
}

export function getWorkspaceConsoleRoleLabel(role: string | null | undefined): string {
  if (!role) return "Agent";
  return ROLE_LABELS[role] ?? role;
}

export function pickActiveIssueTask(
  issue: CodexIssue | null,
  tasks: CodexTask[],
): CodexTask | null {
  if (!issue || tasks.length === 0) return null;

  const expectedRole =
    PHASE_CONFIG[(issue.current_phase || "requirements") as Phase]?.role ?? null;

  let best: CodexTask | null = null;
  let bestRank: [number, number, number] = [-1, -1, -1];

  for (const task of tasks) {
    const rank: [number, number, number] = [
      ACTIVE_TASK_STATUSES.has(String(task.status || "").toLowerCase()) ? 1 : 0,
      task.role === expectedRole ? 1 : 0,
      Math.max(
        task.updated_at ? new Date(task.updated_at).getTime() : 0,
        task.created_at ? new Date(task.created_at).getTime() : 0,
      ),
    ];
    if (
      rank[0] > bestRank[0]
      || (rank[0] === bestRank[0] && rank[1] > bestRank[1])
      || (rank[0] === bestRank[0] && rank[1] === bestRank[1] && rank[2] >= bestRank[2])
    ) {
      best = task;
      bestRank = rank;
    }
  }

  return best;
}
