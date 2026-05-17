/**
 * Tiny per-issue event bus that the Agent Dock subscribes to.
 *
 * DagTab pushes streaming-orchestrator events (Auto-plan SSE) into this bus.
 * The dock reads from it via `useSyncExternalStore` so it never has to be
 * a child of DagTab and never duplicates an SSE subscription.
 *
 * Status itself is *derived* per-render in `useAgentStatus.ts`; this bus
 * only stores the raw inputs (last meta, accumulated log lines, node/edge
 * counts, terminal verdict) plus a per-role history of status moments
 * pushed during agent runs.
 */

import type { RoleId } from "./personas";

export interface StreamMeta {
  executor: string | null;
  model: string | null;
  reason?: string;
}

export type ConductorPhase =
  | "idle"
  | "connecting"
  | "planning"
  | "streaming"
  | "done"
  | "error";

export interface HistoryEntry {
  ts: number;
  role: RoleId;
  /** Short single-line status text shown in the bubble. */
  text: string;
  /** Optional second-line detail (e.g., "Reading pm/prd.json"). */
  detail?: string;
  /** Optional kind for filtering — "tool", "status", "artifact", "error". */
  kind?: "tool" | "status" | "artifact" | "error" | "done";
}

export interface IssueAgentState {
  // Conductor / Auto-plan state
  conductorPhase: ConductorPhase;
  streamMeta: StreamMeta | null;
  streamLogLines: string[];
  nodesStreamed: number;
  edgesStreamed: number;
  /** Last terminal message ("DAG ready ✓", "Failed — …"). */
  conductorTerminal: string | null;

  // Per-role history (ring-buffered to 100 entries each)
  history: Record<RoleId, HistoryEntry[]>;

  // Monotonic counter so consumers can cheaply detect change without
  // deep-equal-ing the state.
  rev: number;
}

const EMPTY_STATE: IssueAgentState = {
  conductorPhase: "idle",
  streamMeta: null,
  streamLogLines: [],
  nodesStreamed: 0,
  edgesStreamed: 0,
  conductorTerminal: null,
  history: {
    conductor: [],
    product_manager: [],
    architect: [],
    engineer: [],
    qa: [],
  },
  rev: 0,
};

const MAX_HISTORY_PER_ROLE = 100;

const stores = new Map<string, IssueAgentState>();
const listeners = new Map<string, Set<() => void>>();

function getState(issueId: string): IssueAgentState {
  return stores.get(issueId) ?? EMPTY_STATE;
}

function setState(
  issueId: string,
  update: (prev: IssueAgentState) => IssueAgentState,
): void {
  const prev = stores.get(issueId) ?? EMPTY_STATE;
  const next = update(prev);
  if (next === prev) return;
  // Bump rev so reference-equal consumers re-render.
  stores.set(issueId, { ...next, rev: prev.rev + 1 });
  const subs = listeners.get(issueId);
  if (subs) for (const fn of subs) fn();
}

function subscribe(issueId: string, cb: () => void): () => void {
  let set = listeners.get(issueId);
  if (!set) {
    set = new Set();
    listeners.set(issueId, set);
  }
  set.add(cb);
  return () => {
    set?.delete(cb);
  };
}

function appendHistory(
  issueId: string,
  entry: Omit<HistoryEntry, "ts"> & { ts?: number },
): void {
  setState(issueId, (prev) => {
    const arr = prev.history[entry.role];
    const stamped: HistoryEntry = {
      ts: entry.ts ?? Date.now(),
      role: entry.role,
      text: entry.text,
      detail: entry.detail,
      kind: entry.kind,
    };
    const next = [...arr, stamped];
    if (next.length > MAX_HISTORY_PER_ROLE) next.splice(0, next.length - MAX_HISTORY_PER_ROLE);
    return {
      ...prev,
      history: { ...prev.history, [entry.role]: next },
    };
  });
}

export const agentBus = {
  getState,
  subscribe,

  reset(issueId: string): void {
    setState(issueId, () => ({ ...EMPTY_STATE, history: { ...EMPTY_STATE.history } }));
  },

  // --- Conductor / Auto-plan event ingest ---
  onConductorConnecting(issueId: string): void {
    setState(issueId, (p) => ({
      ...p,
      conductorPhase: "connecting",
      streamMeta: null,
      streamLogLines: [],
      nodesStreamed: 0,
      edgesStreamed: 0,
      conductorTerminal: null,
    }));
    appendHistory(issueId, { role: "conductor", text: "Connecting…", kind: "status" });
  },

  onConductorMeta(issueId: string, meta: StreamMeta): void {
    setState(issueId, (p) => ({ ...p, conductorPhase: "planning", streamMeta: meta }));
    appendHistory(issueId, {
      role: "conductor",
      text: meta.executor ? `Planning · ${meta.executor}/${meta.model}` : "Planning",
      kind: "status",
    });
  },

  onConductorLog(issueId: string, msg: string): void {
    setState(issueId, (p) => ({
      ...p,
      streamLogLines: [...p.streamLogLines.slice(-19), msg],
    }));
    appendHistory(issueId, { role: "conductor", text: msg, kind: "status" });
  },

  onConductorNode(issueId: string, node: { node_key?: string; title?: string }): void {
    setState(issueId, (p) => ({
      ...p,
      conductorPhase: "streaming",
      nodesStreamed: p.nodesStreamed + 1,
    }));
    appendHistory(issueId, {
      role: "conductor",
      text: `+ Node: ${node.title || node.node_key || "?"}`,
      kind: "artifact",
    });
  },

  onConductorEdge(issueId: string, edge: { from_node_key?: string; to_node_key?: string }): void {
    setState(issueId, (p) => ({ ...p, edgesStreamed: p.edgesStreamed + 1 }));
    appendHistory(issueId, {
      role: "conductor",
      text: `+ Edge: ${edge.from_node_key} → ${edge.to_node_key}`,
      kind: "artifact",
    });
  },

  onConductorDone(issueId: string): void {
    setState(issueId, (p) => ({ ...p, conductorPhase: "done", conductorTerminal: "DAG ready ✓" }));
    appendHistory(issueId, { role: "conductor", text: "DAG ready ✓", kind: "done" });
  },

  onConductorError(issueId: string, msg: string): void {
    setState(issueId, (p) => ({ ...p, conductorPhase: "error", conductorTerminal: msg }));
    appendHistory(issueId, { role: "conductor", text: msg, kind: "error" });
  },

  // --- Generic role event push (used by useAgentStatus when a node transitions) ---
  push(issueId: string, entry: Omit<HistoryEntry, "ts">): void {
    appendHistory(issueId, entry);
  },
};
