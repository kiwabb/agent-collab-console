// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiRequest } from "./fetch";

export type AuditLogCategory =
  | "llm_call"
  | "llm_return"
  | "tool_use"
  | "tool_result"
  | "command_exec"
  | "git_command"
  | "cli_spawn"
  | "event"
  | "agent_finalize";
export interface AuditLog {
  id: string;
  created_at: string | null;
  category: string;
  actor: string | null;
  issue_id: string | null;
  task_id: string | null;
  conductor_task_id: string | null;
  execution_process_id: string | null;
  correlation_id: string | null;
  trace_id?: string | null;
  span_id?: string | null;
  parent_span_id?: string | null;
  status: string | null;
  duration_ms: number | null;
  /** Raw (already-truncated) JSON string; parse on the client. */
  payload_json: string | null;
  error: string | null;
  role?: string | null;
  role_label?: string | null;
  operation_task_id?: string | null;
  task_title?: string | null;
  turn_index?: number | null;
  sub_index?: number | null;
  call_name?: string | null;
  call_input?: unknown;
  call_output?: unknown;
  call_summary?: string | null;
}
export interface AuditLogPage {
  items: AuditLog[];
  next_cursor: string | null;
}

/** Semantic Agent Timeline operation.
 *
 * Kept under the historical AuditLogChainOperation name so older components do
 * not need a wide rename, but new callers should treat this as the product
 * timeline view rather than raw audit-log grouping.
 */
export interface AuditLogChainOperation {
  id: string;
  timeline_kind?: string | null;
  event_type?: string | null;
  role: string | null;
  role_label: string | null;
  title: string;
  summary: string;
  result?: Record<string, unknown> | null;
  status: string | null;
  status_source?: string | null;
  issue_id: string | null;
  task_id: string | null;
  operation_task_id: string | null;
  task_title: string | null;
  conductor_task_id: string | null;
  execution_process_id?: string | null;
  trace_id?: string | null;
  span_id?: string | null;
  parent_span_id?: string | null;
  turn_index: number | null;
  started_at: string | null;
  last_at: string | null;
  duration_ms: number | null;
  entry_count: number;
  entries: AuditLog[];
}

export interface AuditLogChainPage {
  items: AuditLogChainOperation[];
  next_cursor: string | null;
}

export type AgentTimelineOperation = AuditLogChainOperation;

export interface AgentTimelinePage {
  items: AgentTimelineOperation[];
  next_cursor: string | null;
}

export interface AuditTraceItem {
  available: true;
  id: string;
  audit_log_id: string | null;
  trace_id: string | null;
  span_id: string | null;
  parent_span_id: string | null;
  issue_id: string | null;
  task_id: string | null;
  execution_process_id: string | null;
  kind: string;
  title: string | null;
  request: unknown;
  response: unknown;
  request_preview: string | null;
  response_preview: string | null;
  metadata: Record<string, unknown>;
  is_truncated: boolean;
  created_at: string | null;
}

export interface AuditTraceUnavailable {
  available: false;
  audit_log_id?: string | null;
  trace_id?: string | null;
  reason: string;
  items?: [];
}

export type AuditTraceDetail = AuditTraceItem | AuditTraceUnavailable;

export interface AuditTraceCollection {
  available: boolean;
  trace_id: string;
  reason?: string;
  items: AuditTraceItem[];
}
export async function getAuditLog(
  params: {
    category?: string[] | null;
    issueId?: string | null;
    taskId?: string | null;
    since?: string | null;
    until?: string | null;
    q?: string | null;
    cursor?: string | null;
    limit?: number | null;
  } = {},
): Promise<AuditLogPage> {
  const search = new URLSearchParams();
  for (const cat of params.category ?? []) {
    if (cat) search.append("category", cat);
  }
  if (params.issueId) search.set("issue_id", params.issueId);
  if (params.taskId) search.set("task_id", params.taskId);
  if (params.since) search.set("since", params.since);
  if (params.until) search.set("until", params.until);
  if (params.q) search.set("q", params.q);
  if (params.cursor) search.set("cursor", params.cursor);
  if (params.limit != null) search.set("limit", String(params.limit));
  const qs = search.toString();
  return apiRequest<AuditLogPage>(`${API_BASE}/codex/audit-log${qs ? `?${qs}` : ""}`);
}

export async function getAuditLogChains(
  params: {
    category?: string[] | null;
    issueId?: string | null;
    taskId?: string | null;
    since?: string | null;
    until?: string | null;
    q?: string | null;
    cursor?: string | null;
    limit?: number | null;
  } = {},
): Promise<AuditLogChainPage> {
  const search = new URLSearchParams();
  for (const cat of params.category ?? []) {
    if (cat) search.append("category", cat);
  }
  if (params.issueId) search.set("issue_id", params.issueId);
  if (params.taskId) search.set("task_id", params.taskId);
  if (params.since) search.set("since", params.since);
  if (params.until) search.set("until", params.until);
  if (params.q) search.set("q", params.q);
  if (params.cursor) search.set("cursor", params.cursor);
  if (params.limit != null) search.set("limit", String(params.limit));
  const qs = search.toString();
  return apiRequest<AuditLogChainPage>(
    `${API_BASE}/codex/audit-log/chains${qs ? `?${qs}` : ""}`,
  );
}

export async function getAgentTimeline(
  params: {
    category?: string[] | null;
    issueId?: string | null;
    taskId?: string | null;
    since?: string | null;
    until?: string | null;
    q?: string | null;
    cursor?: string | null;
    limit?: number | null;
  } = {},
): Promise<AgentTimelinePage> {
  const search = new URLSearchParams();
  for (const cat of params.category ?? []) {
    if (cat) search.append("category", cat);
  }
  if (params.issueId) search.set("issue_id", params.issueId);
  if (params.taskId) search.set("task_id", params.taskId);
  if (params.since) search.set("since", params.since);
  if (params.until) search.set("until", params.until);
  if (params.q) search.set("q", params.q);
  if (params.cursor) search.set("cursor", params.cursor);
  if (params.limit != null) search.set("limit", String(params.limit));
  const qs = search.toString();
  return apiRequest<AgentTimelinePage>(
    `${API_BASE}/codex/agent-timeline${qs ? `?${qs}` : ""}`,
  );
}

export async function getAuditTrace(auditId: string): Promise<AuditTraceDetail> {
  return apiRequest<AuditTraceDetail>(
    `${API_BASE}/codex/audit-log/${encodeURIComponent(auditId)}/trace`,
  );
}

export async function getTrace(traceId: string): Promise<AuditTraceCollection> {
  return apiRequest<AuditTraceCollection>(
    `${API_BASE}/codex/traces/${encodeURIComponent(traceId)}`,
  );
}

export async function getBestAuditTrace(
  entry: Pick<AuditLog, "id" | "trace_id">,
): Promise<AuditTraceDetail | AuditTraceCollection> {
  let rowTrace: AuditTraceDetail | null = null;
  try {
    rowTrace = await getAuditTrace(entry.id);
    if (rowTrace.available) return rowTrace;
  } catch (exc) {
    if (!entry.trace_id) throw exc;
  }
  if (!entry.trace_id) return rowTrace ?? getAuditTrace(entry.id);

  try {
    const trace = await getTrace(entry.trace_id);
    if (trace.available && trace.items.length > 0) return trace;
  } catch {
    // Fall through to the audit-row fallback below. CLI runtimes often expose
    // reconstructable task messages/logs even when no full trace row exists.
  }

  return rowTrace ?? getAuditTrace(entry.id);
}
