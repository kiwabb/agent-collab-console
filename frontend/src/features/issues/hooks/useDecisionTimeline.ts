"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getConductorTurns,
  type ConductorTurn,
  type SubAgentResultPayload,
} from "@/lib/api";
import type { CodexTask } from "@/lib/types";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

export interface DecisionTimelineItem {
  id: string;
  kind: "dispatch" | "clarification" | "memory" | "finalize" | "user" | "error" | "tool";
  role: string;
  status: "running" | "done" | "failed" | "waiting" | "info";
  title: string;
  summary: string;
  createdAt: string | null;
  durationMs: number | null;
  toolUseId?: string | null;
  taskId?: string | null;
  task?: CodexTask | null;
  result?: SubAgentResultPayload | null;
  rawTurns: ConductorTurn[];
  thinkingTurns: ConductorTurn[];
  why?: string | null;
}

const DISPATCH_TO_ROLE: Record<string, string> = {
  pm: "product_manager",
  product_manager: "product_manager",
  architect: "architect",
  engineer: "engineer",
  qa: "qa",
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function textFromPayload(payload: Record<string, unknown>): string {
  const candidates = [
    payload.summary,
    payload.error,
    payload.error_message,
    payload.message,
    payload.answer,
    payload.text,
    payload.content,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
  }
  return "";
}

function taskStatusToTimeline(status: string | null | undefined): DecisionTimelineItem["status"] {
  const s = String(status || "").toLowerCase();
  if (s === "failed" || s.includes("error")) return "failed";
  if (s === "done" || s === "completed" || s === "success") return "done";
  if (s === "running" || s === "responding" || s === "in_progress") return "running";
  if (s.includes("await") || s === "paused") return "waiting";
  return "info";
}

function roleFromTool(toolName: string, input: Record<string, unknown>): string {
  const raw = String(input.role || input.role_key || input.target_node_key || input.node_key || "");
  return DISPATCH_TO_ROLE[raw] ?? raw ?? toolName;
}

function titleForTool(toolName: string, role: string): string {
  if (toolName === "request_user_clarification") return "Conductor asked for clarification";
  if (toolName === "retrieve_cold_memory") return "Retrieved cold memory";
  if (toolName === "finalize_task") return "Finalized the issue";
  if (toolName === "spawn_custom_subagent") return `Spawned ${role || "custom agent"}`;
  if (toolName === "dispatch_subagent") return `Dispatched ${role || "sub-agent"}`;
  return toolName || "Tool call";
}

export function buildDecisionTimeline(
  turns: ConductorTurn[],
  tasks: CodexTask[],
  results: SubAgentResultPayload[],
): DecisionTimelineItem[] {
  const taskById = new Map(tasks.map((task) => [task.id, task]));
  const resultByTask = new Map(results.map((result) => [result.task_id, result]));
  const items: DecisionTimelineItem[] = [];
  const sorted = [...turns].sort((a, b) => {
    const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
    const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
    return aTime - bTime || a.turn_index - b.turn_index || a.sub_index - b.sub_index;
  });

  for (let index = 0; index < sorted.length; index += 1) {
    const turn = sorted[index];
    const payload = asRecord(turn.payload);
    if (turn.kind === "user_message") {
      const body = textFromPayload(payload);
      items.push({
        id: turn.id,
        kind: "user",
        role: "user",
        status: "info",
        title: body.startsWith("[CLARIFY]") ? "You answered Conductor" : "You interrupted",
        summary: body,
        createdAt: turn.created_at,
        durationMs: null,
        rawTurns: [turn],
        thinkingTurns: [],
      });
      continue;
    }
    if (turn.kind === "error") {
      items.push({
        id: turn.id,
        kind: "error",
        role: "conductor",
        status: "failed",
        title: "Conductor error",
        summary: textFromPayload(payload) || "Conductor failed",
        createdAt: turn.created_at,
        durationMs: null,
        rawTurns: [turn],
        thinkingTurns: [],
        why: textFromPayload(payload),
      });
      continue;
    }
    if (turn.kind !== "tool_use") continue;

    const toolName = String(payload.name || payload.tool || payload.tool_name || "tool");
    const input = asRecord(payload.input || payload.arguments || payload.args);
    const toolUseId = String(payload.tool_use_id || payload.id || turn.id);
    const matchingResult = sorted.find((candidate) => {
      if (candidate.kind !== "tool_result") return false;
      const candidatePayload = asRecord(candidate.payload);
      return String(candidatePayload.tool_use_id || candidatePayload.id || "") === toolUseId;
    });
    const resultPayload = asRecord(matchingResult?.payload);
    const output = asRecord(resultPayload.output || resultPayload.result || resultPayload);
    const taskId = typeof output.task_id === "string"
      ? output.task_id
      : typeof input.task_id === "string"
        ? input.task_id
        : null;
    const role = roleFromTool(toolName, input);
    const task = taskId ? taskById.get(taskId) ?? null : tasks.find((candidate) => candidate.role === role) ?? null;
    const status = taskStatusToTimeline(
      task?.status ?? (typeof output.status === "string" ? output.status : matchingResult ? "done" : "running"),
    );
    const thinkingTurns = sorted.filter((candidate) => {
      if (candidate.turn_index !== turn.turn_index) return false;
      if (candidate.sub_index >= turn.sub_index) return false;
      return candidate.kind === "llm_response" || candidate.kind === "llm_request";
    });
    const result = task?.id ? resultByTask.get(task.id) ?? null : null;
    const createdAt = turn.created_at;
    const endedAt = matchingResult?.created_at ?? task?.updated_at ?? null;
    const durationMs = createdAt && endedAt
      ? Math.max(0, new Date(endedAt).getTime() - new Date(createdAt).getTime())
      : null;
    const summary = textFromPayload(output) || textFromPayload(input) || result?.summary || "";

    items.push({
      id: `${turn.id}:${toolUseId}`,
      kind: toolName === "request_user_clarification"
        ? "clarification"
        : toolName === "retrieve_cold_memory"
          ? "memory"
          : toolName === "finalize_task"
            ? "finalize"
            : toolName === "dispatch_subagent" || toolName === "spawn_custom_subagent"
              ? "dispatch"
              : "tool",
      role: role || "conductor",
      status,
      title: titleForTool(toolName, role),
      summary,
      createdAt,
      durationMs,
      toolUseId,
      taskId: task?.id ?? taskId,
      task,
      result,
      rawTurns: matchingResult ? [turn, matchingResult] : [turn],
      thinkingTurns,
      why: status === "failed" ? summary || task?.result || result?.summary || "Failed without a captured summary" : null,
    });
  }

  return items.sort((a, b) => {
    const aTime = a.createdAt ? new Date(a.createdAt).getTime() : 0;
    const bTime = b.createdAt ? new Date(b.createdAt).getTime() : 0;
    return aTime - bTime;
  });
}

export function useDecisionTimeline(
  issueId: string,
  tasks: CodexTask[],
  results: SubAgentResultPayload[],
) {
  const [turns, setTurns] = useState<ConductorTurn[]>([]);

  const refresh = useCallback(async () => {
    setTurns(await getConductorTurns(issueId, { limit: 300 }).catch(() => []));
  }, [issueId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("conductor_turn", "conductor_failed", "conductor_status"),
    ),
    onEvent: () => { void refresh(); },
    throttleMs: 600,
  });

  const items = useMemo(() => buildDecisionTimeline(turns, tasks, results), [turns, tasks, results]);
  return { turns, items, refresh };
}
