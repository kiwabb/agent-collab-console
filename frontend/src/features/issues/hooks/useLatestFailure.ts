"use client";

import { useMemo } from "react";

import type { CodexTask } from "@/lib/types";
import type { DecisionTimelineItem } from "./useDecisionTimeline";

export interface LatestFailure {
  id: string;
  role: string;
  createdAt: string | null;
  summary: string;
  source: "task" | "conductor";
}

export function deriveLatestFailure(
  tasks: CodexTask[],
  timeline: DecisionTimelineItem[],
): LatestFailure | null {
  const successfulByRole = new Map<string, number>();
  const failedCandidates: LatestFailure[] = [];

  for (const task of tasks) {
    const role = task.role || "agent";
    const updated = task.updated_at ? new Date(task.updated_at).getTime() : 0;
    const status = String(task.status || "").toLowerCase();
    if (status === "done" || status === "completed") {
      successfulByRole.set(role, Math.max(successfulByRole.get(role) ?? 0, updated));
    }
    if (status === "failed") {
      failedCandidates.push({
        id: task.id,
        role,
        createdAt: task.updated_at ?? task.created_at,
        summary: task.result || task.review_comment || task.title || "Task failed",
        source: "task",
      });
    }
  }

  for (const item of timeline) {
    if (item.status !== "failed") continue;
    failedCandidates.push({
      id: item.id,
      role: item.role || "conductor",
      createdAt: item.createdAt,
      summary: item.why || item.summary || item.title,
      source: item.role === "conductor" ? "conductor" : "task",
    });
  }

  const stillOpen = failedCandidates.filter((candidate) => {
    if (candidate.source === "conductor") return true;
    const failedAt = candidate.createdAt ? new Date(candidate.createdAt).getTime() : 0;
    return (successfulByRole.get(candidate.role) ?? -1) <= failedAt;
  });

  return stillOpen.sort((a, b) => {
    const aTime = a.createdAt ? new Date(a.createdAt).getTime() : 0;
    const bTime = b.createdAt ? new Date(b.createdAt).getTime() : 0;
    return bTime - aTime;
  })[0] ?? null;
}

export function useLatestFailure(tasks: CodexTask[], timeline: DecisionTimelineItem[]) {
  return useMemo(() => deriveLatestFailure(tasks, timeline), [tasks, timeline]);
}
