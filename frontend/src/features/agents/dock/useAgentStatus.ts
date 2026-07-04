"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { getIssueGraph } from "@/lib/api/conductors";
import { getCodexTasks, getExecutionProcesses } from "@/lib/api/tasks";
import type { CodexTask, ExecutionProcess, WorkflowGraph } from "@/lib/types";
import { useExecutionProcessMessageStream } from "@/hooks/useExecutionProcessMessageStream";
import { agentBus, type HistoryEntry } from "./agentBus";
import { PERSONAS, ROLE_ORDER, type RoleId } from "./personas";

export interface RoleStatus {
  role: RoleId;
  /** One-line short status text. Empty string = idle. */
  text: string;
  /** Optional second-line detail (filename, tool args). */
  detail?: string;
  /** Visual mode for the tile. */
  mode: "idle" | "active" | "done" | "failed" | "waiting";
  /** Tone for the bubble border / text color. */
  tone: "neutral" | "info" | "success" | "warning" | "error";
}

export interface AgentStatusSnapshot {
  /** Map of role → current status. */
  byRole: Record<RoleId, RoleStatus>;
  /** Which role's bubble is the "active speaker" right now. */
  activeRole: RoleId | null;
  /** Full append-only per-role history for the timeline panel. */
  history: Record<RoleId, HistoryEntry[]>;
}

const IDLE: RoleStatus = { role: "conductor", text: "", mode: "idle", tone: "neutral" };

function blankStatus(role: RoleId): RoleStatus {
  return { role, text: "", mode: "idle", tone: "neutral" };
}

/**
 * Hook that drives the Agent Dock.
 *
 * Subscribes to:
 *   1. agentBus (DagTab streaming events) — drives Conductor
 *   2. issue graph (polled every 3 s while live) — drives role node states
 *   3. message stream of the currently-running role's task — drives sub-status
 */
export function useAgentStatus(issueId: string): AgentStatusSnapshot {
  // ---- (1) Subscribe to the agent bus ----
  const busState = useSyncExternalStore(
    (cb) => agentBus.subscribe(issueId, cb),
    () => agentBus.getState(issueId),
    () => agentBus.getState(issueId),
  );

  // ---- (2) Poll the issue graph + tasks ----
  const [graph, setGraph] = useState<WorkflowGraph | null>(null);
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [runs, setRuns] = useState<Record<string, ExecutionProcess[]>>({});

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function pull() {
      try {
        const [g, ts] = await Promise.all([
          getIssueGraph(issueId).catch(() => null),
          getCodexTasks(null, issueId).catch(() => [] as CodexTask[]),
        ]);
        if (cancelled) return;
        if (g) setGraph(g);
        setTasks(ts);
        // For the currently running task, fetch its execution processes
        // (cheap; runs list is small). Other roles don't need polling.
        const running = ts.filter((t) => t.status === "running" || t.status === "responding");
        const newRuns: Record<string, ExecutionProcess[]> = {};
        await Promise.all(
          running.map(async (t) => {
            const list = await getExecutionProcesses(null, t.id).catch(() => []);
            newRuns[t.id] = list;
          }),
        );
        if (!cancelled) setRuns(newRuns);
        // Adaptive poll: fast (3s) while something is in flight, slow
        // (30s) when the issue has gone quiet. Saves ~10 redundant
        // graph+tasks fetches per minute on completed issues.
        if (!cancelled) {
          const fast = running.length > 0;
          timer = setTimeout(pull, fast ? 3000 : 30000);
        }
      } catch {
        /* silent — handled by other UIs */
        if (!cancelled) {
          timer = setTimeout(pull, 30000);
        }
      }
    }

    void pull();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [issueId]);

  // ---- (3) Find the active running task, stream its messages for sub-status ----
  const activeTask = useMemo(
    () => tasks.find((t) => t.status === "running" || t.status === "responding") ?? null,
    [tasks],
  );
  const activeRunId = useMemo(() => {
    if (!activeTask) return null;
    const list = runs[activeTask.id] ?? [];
    // Newest running run.
    const live = list.find((p) => String(p.status).toLowerCase() === "running");
    return (live ?? list[0])?.id ?? activeTask.last_execution_process_id ?? null;
  }, [activeTask, runs]);
  const { messages, pendingAssistant } = useExecutionProcessMessageStream(activeRunId);

  // ---- Build per-role status ----
  const snapshot: AgentStatusSnapshot = useMemo(() => {
    const byRole: Record<RoleId, RoleStatus> = {
      conductor: blankStatus("conductor"),
      product_manager: blankStatus("product_manager"),
      architect: blankStatus("architect"),
      engineer: blankStatus("engineer"),
      engineer_frontend: blankStatus("engineer_frontend"),
      engineer_backend: blankStatus("engineer_backend"),
      qa: blankStatus("qa"),
    };

    // ----- Conductor -----
    switch (busState.conductorPhase) {
      case "connecting":
        byRole.conductor = {
          role: "conductor",
          text: "Connecting…",
          mode: "active",
          tone: "info",
        };
        break;
      case "planning": {
        const meta = busState.streamMeta;
        byRole.conductor = {
          role: "conductor",
          text: meta?.executor ? `Planning · ${meta.executor}/${meta.model}` : "Planning",
          detail: busState.streamLogLines.at(-1),
          mode: "active",
          tone: "info",
        };
        break;
      }
      case "streaming":
        byRole.conductor = {
          role: "conductor",
          text: `Streaming · ${busState.nodesStreamed} nodes · ${busState.edgesStreamed} edges`,
          mode: "active",
          tone: "info",
        };
        break;
      case "done":
        byRole.conductor = {
          role: "conductor",
          text: busState.conductorTerminal ?? "DAG ready ✓",
          mode: "done",
          tone: "success",
        };
        break;
      case "error":
        byRole.conductor = {
          role: "conductor",
          text: "Failed",
          detail: busState.conductorTerminal ?? undefined,
          mode: "failed",
          tone: "error",
        };
        break;
      case "idle":
      default:
        // If the graph is running and no role node is active, the
        // Conductor is "routing".
        if (graph && graph.status === "running") {
          const anyRunning = graph.nodes.some((n) => n.status === "running");
          byRole.conductor = anyRunning
            ? { role: "conductor", text: "Watching", mode: "idle", tone: "neutral" }
            : { role: "conductor", text: "Routing to next agent…", mode: "active", tone: "info" };
        } else if (graph && graph.status === "done") {
          byRole.conductor = {
            role: "conductor",
            text: "Pipeline complete",
            mode: "done",
            tone: "success",
          };
        } else {
          byRole.conductor = IDLE;
        }
    }

    // ----- Role agents (PM / Architect / Engineer / QA) -----
    type WfNode = WorkflowGraph["nodes"][number];
    const nodesByRole = new Map<string, WfNode>();
    if (graph) {
      for (const n of graph.nodes) {
        nodesByRole.set(n.node_key, n);
      }
    }

    for (const role of ROLE_ORDER) {
      if (role === "conductor") continue;
      const node = nodesByRole.get(role);
      if (!node) {
        byRole[role] = blankStatus(role);
        continue;
      }
      const status = node.status;
      if (status === "pending" || status === "blocked") {
        byRole[role] = { role, text: "Waiting", mode: "waiting", tone: "neutral" };
      } else if (status === "ready") {
        byRole[role] = { role, text: "Up next", mode: "waiting", tone: "info" };
      } else if (status === "running") {
        // Use live message stream for sub-status detail.
        const detail = deriveSubStatusFromMessages(messages, pendingAssistant?.text);
        byRole[role] = {
          role,
          text: "Working…",
          detail,
          mode: "active",
          tone: "info",
        };
      } else if (status === "done") {
        // Try to surface the task.result summary that persist_result writes
        // (e.g. "PRD generated for X. Files: prd.json, prd.md.").
        const task = tasks.find((t) => t.id === node.task_id);
        const summary = task?.result?.split("\n")[0]?.slice(0, 160);
        byRole[role] = {
          role,
          text: "Done",
          detail: summary,
          mode: "done",
          tone: "success",
        };
      } else if (status === "failed") {
        const task = tasks.find((t) => t.id === node.task_id);
        const reason = task?.result?.split("\n")[0]?.slice(0, 160);
        byRole[role] = {
          role,
          text: "Failed",
          detail: reason,
          mode: "failed",
          tone: "error",
        };
      } else if (status === "skipped") {
        byRole[role] = { role, text: "Skipped", mode: "waiting", tone: "neutral" };
      } else {
        byRole[role] = { role, text: status, mode: "waiting", tone: "neutral" };
      }
    }

    // ----- Decide active speaker -----
    let activeRole: RoleId | null = null;
    if (
      busState.conductorPhase !== "idle" &&
      busState.conductorPhase !== "done"
    ) {
      activeRole = "conductor";
    } else {
      const runningRole = ROLE_ORDER.find(
        (r) => r !== "conductor" && byRole[r].mode === "active",
      );
      if (runningRole) activeRole = runningRole;
      else if (byRole.conductor.text) activeRole = "conductor";
    }

    return { byRole, activeRole, history: busState.history };
  }, [busState, graph, tasks, messages, pendingAssistant?.text]);

  return snapshot;
}

/** Inspect the most recent assistant SDK envelope to extract a human-readable
 * sub-status. Returns e.g. "Reading pm/prd.json", "Writing api.py",
 * "Running: pytest tests/", "Thinking…" or "" if nothing useful is visible.
 */
function deriveSubStatusFromMessages(
  messages: { content: string; role: string }[] | undefined,
  pendingText: string | undefined,
): string | undefined {
  if (pendingText) {
    const trimmed = pendingText.slice(-80).trim();
    if (trimmed) return `Streaming: ${trimmed.slice(0, 80)}`;
  }
  if (!messages || messages.length === 0) return undefined;
  for (let i = messages.length - 1; i >= 0 && i >= messages.length - 10; i--) {
    const m = messages[i];
    if (m.role !== "assistant") continue;
    const content = m.content || "";
    if (!content.startsWith("{") && !content.startsWith("[")) continue;
    try {
      const obj = JSON.parse(content);
      const found = scanForToolUse(obj);
      if (found) return found;
    } catch {
      /* ignore */
    }
  }
  return undefined;
}

function scanForToolUse(node: unknown): string | undefined {
  if (!node) return undefined;
  if (Array.isArray(node)) {
    for (const item of node) {
      const r = scanForToolUse(item);
      if (r) return r;
    }
    return undefined;
  }
  if (typeof node !== "object") return undefined;
  const n = node as Record<string, unknown>;
  if (n.type === "tool_use" && typeof n.name === "string") {
    const input = (n.input ?? {}) as Record<string, unknown>;
    const file = String(input.file_path ?? input.path ?? "");
    const base = file.split("/").filter(Boolean).slice(-2).join("/");
    switch (n.name) {
      case "Read":
        return base ? `Reading ${base}` : "Reading file";
      case "Write":
      case "Edit":
      case "MultiEdit":
        return base ? `Writing ${base}` : "Writing file";
      case "Bash": {
        const cmd = String(input.command ?? "").slice(0, 40);
        return cmd ? `Running: ${cmd}` : "Running command";
      }
      case "Glob":
      case "Grep":
        return "Searching files";
      default:
        return `Calling ${String(n.name)}`;
    }
  }
  if (n.type === "thinking" && typeof n.thinking === "string") {
    const t = n.thinking.trim().slice(0, 60);
    return t ? `Thinking: ${t}` : "Thinking…";
  }
  // Recurse into nested fields.
  for (const v of Object.values(n)) {
    const r = scanForToolUse(v);
    if (r) return r;
  }
  return undefined;
}

export const _PERSONAS_FOR_EXPORT = PERSONAS; // ensure tree-shake doesn't drop personas import path
