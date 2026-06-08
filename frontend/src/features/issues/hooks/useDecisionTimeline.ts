"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  titleKey?: string;
  titleParams?: Record<string, string | number>;
  summary: string;
  summaryKey?: string;
  summaryParams?: Record<string, string | number>;
  createdAt: string | null;
  durationMs: number | null;
  toolUseId?: string | null;
  taskId?: string | null;
  task?: CodexTask | null;
  result?: SubAgentResultPayload | null;
  rawTurns: ConductorTurn[];
  thinkingTurns: ConductorTurn[];
  rationale?: string | null;
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

/** A stray CLI/cmux control envelope (e.g. a SessionStart hook line) that a
 * failed subagent can leave in task.result — must never render as a summary. */
function looksLikeControlPayload(text: string): boolean {
  const s = text.trim();
  if (!(s.startsWith("{") && s.endsWith("}"))) return false;
  try {
    const obj = JSON.parse(s) as Record<string, unknown>;
    if (!obj || typeof obj !== "object") return false;
    if (obj.type === "system") return true;
    return ["hook_name", "hook_event", "hook_id"].some((k) => k in obj);
  } catch {
    return false;
  }
}

function cleanText(value: unknown): string {
  if (typeof value !== "string") return "";
  const s = value.trim();
  if (!s || looksLikeControlPayload(s)) return "";
  return extractSummaryFromJsonText(s) || s;
}

function extractSummaryFromJsonText(text: string): string {
  if (!(text.startsWith("{") && text.endsWith("}"))) return "";
  try {
    const obj = JSON.parse(text) as Record<string, unknown>;
    const candidates = [
      obj.summary,
      obj.message,
      obj.answer,
      obj.text,
      obj.content,
      obj.error,
      obj.error_message,
    ];
    for (const candidate of candidates) {
      if (typeof candidate !== "string") continue;
      const cleaned = candidate.trim();
      if (cleaned && !looksLikeControlPayload(cleaned)) return cleaned;
    }
  } catch {
    return "";
  }
  return "";
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
    const cleaned = cleanText(candidate);
    if (cleaned) return cleaned;
  }
  return "";
}

/** Pull the Conductor's free-text reasoning out of llm_response content blocks. */
function rationaleFromThinkingTurns(thinkingTurns: ConductorTurn[]): string {
  const parts: string[] = [];
  for (const turn of thinkingTurns) {
    if (turn.kind !== "llm_response") continue;
    const payload = asRecord(turn.payload);
    const content = payload.content;
    if (!Array.isArray(content)) continue;
    for (const block of content) {
      const b = asRecord(block);
      if (b.type === "text" && typeof b.text === "string" && b.text.trim()) {
        parts.push(b.text.trim());
      }
    }
  }
  return parts.join("\n\n").trim();
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
  if (toolName === "dispatch_batch") return "conductor";
  const raw = String(input.role || input.role_key || input.target_node_key || input.node_key || "");
  return DISPATCH_TO_ROLE[raw] ?? raw ?? toolName;
}

function roleFromBatchAgent(agent: unknown): string {
  const input = asRecord(agent);
  const raw = String(input.role || input.role_key || input.target_node_key || input.node_key || "");
  return DISPATCH_TO_ROLE[raw] ?? raw;
}

function titleForTool(
  toolName: string,
  role: string,
  input: Record<string, unknown>,
): { title: string; titleKey: string; titleParams?: Record<string, string | number> } {
  if (toolName === "request_user_clarification") return { title: "Conductor asked for clarification", titleKey: "issue.command.title.clarification" };
  if (toolName === "retrieve_cold_memory") return { title: "Retrieved cold memory", titleKey: "issue.command.title.memory" };
  if (toolName === "finalize_task") return { title: "Finalized the issue", titleKey: "issue.command.title.finalize" };
  if (toolName === "spawn_custom_subagent") {
    const fallback = role || "custom agent";
    return { title: `Spawned ${fallback}`, titleKey: "issue.command.title.spawn", titleParams: { role: fallback } };
  }
  if (toolName === "dispatch_subagent") {
    const fallback = role || "sub-agent";
    return { title: `Dispatched ${fallback}`, titleKey: "issue.command.title.dispatch", titleParams: { role: fallback } };
  }
  if (toolName === "dispatch_batch") {
    const agents = Array.isArray(input.agents) ? input.agents.length : 0;
    return {
      title: agents > 0 ? `Planned ${agents} parallel agents` : "Planned parallel agents",
      titleKey: agents > 0 ? "issue.command.title.dispatchBatchCount" : "issue.command.title.dispatchBatch",
      titleParams: agents > 0 ? { count: agents } : undefined,
    };
  }
  return { title: toolName || "Tool call", titleKey: "issue.command.title.tool" };
}

function summaryForTool(
  toolName: string,
  input: Record<string, unknown>,
): { summaryKey?: string; summaryParams?: Record<string, string | number> } {
  if (toolName !== "dispatch_batch") return {};
  const agents = Array.isArray(input.agents) ? input.agents.length : 0;
  return agents > 0
    ? { summaryKey: "issue.command.summary.dispatchBatchCount", summaryParams: { count: agents } }
    : { summaryKey: "issue.command.summary.dispatchBatch" };
}

function titleForBatchTask(role: string, index: number): { title: string; titleKey: string; titleParams: Record<string, string | number> } {
  if (role === "engineer") {
    return {
      title: `Development agent ${index}`,
      titleKey: "issue.command.title.developmentTask",
      titleParams: { index },
    };
  }
  return {
    title: `Batch agent ${role} ${index}`,
    titleKey: "issue.command.title.batchTask",
    titleParams: { role, index },
  };
}

function durationBetween(startedAt: string | null, endedAt: string | null): number | null {
  return startedAt && endedAt
    ? Math.max(0, new Date(endedAt).getTime() - new Date(startedAt).getTime())
    : null;
}

export function buildDecisionTimeline(
  turns: ConductorTurn[],
  tasks: CodexTask[],
  results: SubAgentResultPayload[],
): DecisionTimelineItem[] {
  const taskById = new Map(tasks.map((task) => [task.id, task]));
  const resultByTask = new Map(results.map((result) => [result.task_id, result]));
  const items: DecisionTimelineItem[] = [];
  const representedTaskIds = new Set<string>();
  const batchRoles = new Set<string>();
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
        titleKey: body.startsWith("[CLARIFY]") ? "issue.command.title.youAnswered" : "issue.command.title.youInterrupted",
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
        titleKey: "issue.command.title.conductorError",
        summary: textFromPayload(payload) || "",
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
    if (toolName === "dispatch_batch" && Array.isArray(input.agents)) {
      for (const agent of input.agents) {
        const role = roleFromBatchAgent(agent);
        if (role) batchRoles.add(role);
      }
    }
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
    if (task?.id) representedTaskIds.add(task.id);
    const createdAt = turn.created_at;
    const endedAt = matchingResult?.created_at ?? task?.updated_at ?? null;
    const durationMs = durationBetween(createdAt, endedAt);
    const summary = textFromPayload(output) || textFromPayload(input) || cleanText(result?.summary) || "";

    const title = titleForTool(toolName, role, input);
    const toolSummary = summary ? {} : summaryForTool(toolName, input);
    items.push({
      id: `${turn.id}:${toolUseId}`,
      kind: toolName === "request_user_clarification"
        ? "clarification"
        : toolName === "retrieve_cold_memory"
          ? "memory"
          : toolName === "finalize_task"
            ? "finalize"
            : toolName === "dispatch_subagent" || toolName === "spawn_custom_subagent" || toolName === "dispatch_batch"
              ? "dispatch"
              : "tool",
      role: role || "conductor",
      status,
      title: title.title,
      titleKey: title.titleKey,
      titleParams: title.titleParams,
      summary,
      summaryKey: toolSummary.summaryKey,
      summaryParams: toolSummary.summaryParams,
      createdAt,
      durationMs,
      toolUseId,
      taskId: task?.id ?? taskId,
      task,
      result,
      rawTurns: matchingResult ? [turn, matchingResult] : [turn],
      thinkingTurns,
      rationale: rationaleFromThinkingTurns(thinkingTurns) || null,
      why: status === "failed" ? summary || cleanText(task?.result) || cleanText(result?.summary) || "" : null,
    });
  }

  const taskIndexesByRole = new Map<string, number>();
  const batchTasks = tasks
    .filter((task) => batchRoles.has(task.role) && !representedTaskIds.has(task.id))
    .sort((a, b) => {
      const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
      const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
      return aTime - bTime || a.id.localeCompare(b.id);
    });

  for (const task of batchTasks) {
    const index = (taskIndexesByRole.get(task.role) ?? 0) + 1;
    taskIndexesByRole.set(task.role, index);
    const status = taskStatusToTimeline(task.status);
    const result = resultByTask.get(task.id) ?? null;
    const summary = cleanText(result?.summary) || cleanText(task.result) || "";
    const title = titleForBatchTask(task.role, index);

    items.push({
      id: `task:${task.id}`,
      kind: "dispatch",
      role: task.role,
      status,
      title: title.title,
      titleKey: title.titleKey,
      titleParams: title.titleParams,
      summary,
      summaryKey: summary
        ? undefined
        : task.role === "engineer"
          ? "issue.command.summary.developmentTaskDone"
          : "issue.command.summary.batchTaskDone",
      createdAt: task.created_at,
      durationMs: durationBetween(task.created_at, task.updated_at),
      taskId: task.id,
      task,
      result,
      rawTurns: [],
      thinkingTurns: [],
      why: status === "failed" ? summary || cleanText(task.result) || cleanText(result?.summary) || "" : null,
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
  const [liveThinking, setLiveThinking] = useState("");
  const liveTurnRef = useRef<number | null>(null);

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
    onEvent: (event) => {
      // Once a turn's response is persisted, its rationale shows via refresh —
      // clear the live streaming buffer so we don't double-render it.
      if (event.type === "conductor_turn" && asRecord(event).kind === "llm_response") {
        setLiveThinking("");
        liveTurnRef.current = null;
      }
      void refresh();
    },
    throttleMs: 600,
  });

  // Stream the Conductor's in-progress reasoning token-by-token.
  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("conductor_turn_delta"),
    ),
    onEvent: (event) => {
      const e = asRecord(event);
      if (e.kind !== "text" || typeof e.chunk !== "string") return;
      const turnIndex = typeof e.turn_index === "number" ? e.turn_index : null;
      setLiveThinking((prev) => {
        if (liveTurnRef.current !== turnIndex) {
          liveTurnRef.current = turnIndex;
          return e.chunk as string;
        }
        return prev + (e.chunk as string);
      });
    },
  });

  const items = useMemo(() => buildDecisionTimeline(turns, tasks, results), [turns, tasks, results]);
  return { turns, items, refresh, liveThinking };
}
