// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, handleResponse } from "./fetch";

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
  status: string | null;
  duration_ms: number | null;
  /** Raw (already-truncated) JSON string; parse on the client. */
  payload_json: string | null;
  error: string | null;
}
export interface AuditLogPage {
  items: AuditLog[];
  next_cursor: string | null;
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
  const response = await fetch(`${API_BASE}/codex/audit-log${qs ? `?${qs}` : ""}`);
  return handleResponse<AuditLogPage>(response);
}
