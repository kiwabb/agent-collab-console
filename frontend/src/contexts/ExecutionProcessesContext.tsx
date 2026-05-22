"use client";

import { createContext, useContext } from "react";
import type { ExecutionProcess, LogEvent } from "@/lib/types";

// Event types that come through the event bus stream
export type BusEventType =
  | "task_status"
  | "task_created"
  | "task_deleted"
  | "message_created"
  | "message_delta"
  | "log"
  | "heartbeat"
  | "approval_required"
  | "approval_resolved"
  | "session_status"
  | "session_created"
  | "session_updated"
  | "session_deleted"
  | "issue_created"
  | "issue_updated"
  | "issue_deleted"
  | "issue_merged"
  | "issue_abandoned"
  | "issue_restored"
  | "issue_steered"
  | "workflow_node_updated"
  | "worktree_dirty"
  | "conductor_decision"
  | "conductor_turn"
  | "conductor_turn_delta"
  | "conductor_failed"
  | "conductor_status"
  | "agent_message_posted";

export interface BusIssueMergedEvent {
  type: "issue_merged";
  issue_id: string;
  session_id?: string;
  sha: string;
  base_branch: string;
}

export interface BusIssueAbandonedEvent {
  type: "issue_abandoned";
  issue_id: string;
  session_id?: string;
}

export interface BusIssueUpdatedEvent {
  type: "issue_updated";
  issue_id: string;
  session_id?: string;
  status?: string;
  current_phase?: string;
  review_comment?: string | null;
  is_pinned?: boolean;
  git_worktree_path?: string | null;
}

export interface BusIssueCreatedEvent {
  type: "issue_created";
  issue_id: string;
  session_id?: string;
  issue?: { [key: string]: unknown };
  forked_from?: string;
}

export interface BusIssueRestoredEvent {
  type: "issue_restored";
  issue_id: string;
  session_id?: string;
}

export interface BusIssueSteeredEvent {
  type: "issue_steered";
  issue_id: string;
  session_id?: string;
  message?: string;
}

export interface BusIssueDeletedEvent {
  type: "issue_deleted";
  issue_id: string;
  session_id?: string;
}

export interface BusWorkflowNodeUpdatedEvent {
  type: "workflow_node_updated";
  issue_id: string;
  session_id?: string;
  node_id: string;
  node_key: string;
  status: string;
  task_id?: string | null;
}

export interface BusWorktreeDirtyEvent {
  type: "worktree_dirty";
  issue_id: string;
  session_id?: string;
  task_id?: string;
  tool_name?: string;
}

export interface BusConductorDecisionEvent {
  type: "conductor_decision";
  issue_id: string;
  session_id?: string;
  task_id?: string;
  role?: string;
  /** "proceed" | "note" | "escalate" */
  action: string;
  reason?: string;
  note?: string | null;
}

export interface BusConductorTurnEvent {
  type: "conductor_turn";
  id: string;
  issue_id: string;
  session_id?: string;
  conductor_task_id: string;
  turn_index: number;
  sub_index: number;
  kind: "llm_request" | "llm_response" | "tool_use" | "tool_result" | "error" | "finalize";
  payload: Record<string, unknown>;
  summary?: string;
  created_at: string | null;
}

export interface BusConductorTurnDeltaEvent {
  type: "conductor_turn_delta";
  issue_id: string;
  session_id?: string;
  conductor_task_id: string;
  turn_index: number;
  sub_index: number;
  kind: "text" | "tool_input_json";
  chunk: string;
  content_block_index: number;
  created_at: string | null;
}

export interface BusConductorFailedEvent {
  type: "conductor_failed";
  issue_id: string;
  session_id?: string;
  conductor_task_id: string;
  error_class?: string;
  error_message?: string;
  traceback?: string;
}

export interface BusConductorStatusEvent {
  type: "conductor_status";
  issue_id: string;
  session_id?: string;
  conductor_task_id: string;
  status: string;
  phase?: string | null;
  detail?: string | null;
  updated_at?: string | null;
}

export function isBusIssueMergedEvent(event: BusEvent): event is BusIssueMergedEvent {
  return event.type === "issue_merged";
}

export function isBusIssueAbandonedEvent(event: BusEvent): event is BusIssueAbandonedEvent {
  return event.type === "issue_abandoned";
}

export interface BusTaskStatusEvent {
  type: "task_status";
  task_id: string;
  session_id?: string;
  status: string;
  result?: string | null;
  review_comment?: string | null;
  execution_process_id?: string | null;
}

export interface BusTaskCreatedEvent {
  type: "task_created";
  task: {
    id: string;
    session_id: string;
    title: string;
    status: string;
    [key: string]: unknown;
  };
}

export function isBusTaskStatusEvent(event: BusEvent): event is BusTaskStatusEvent {
  return event.type === "task_status";
}

export function isBusTaskCreatedEvent(event: BusEvent): event is BusTaskCreatedEvent {
  return event.type === "task_created";
}

export type BusEvent =
  | BusTaskStatusEvent
  | BusTaskCreatedEvent
  | BusIssueCreatedEvent
  | BusIssueUpdatedEvent
  | BusIssueMergedEvent
  | BusIssueAbandonedEvent
  | BusIssueRestoredEvent
  | BusIssueSteeredEvent
  | BusIssueDeletedEvent
  | BusWorkflowNodeUpdatedEvent
  | BusWorktreeDirtyEvent
  | BusConductorDecisionEvent
  | BusConductorTurnEvent
  | BusConductorTurnDeltaEvent
  | BusConductorFailedEvent
  | BusConductorStatusEvent
  | (LogEvent & { type?: BusEventType });

export interface ExecutionProcessesContextValue {
  executionProcessesAll: ExecutionProcess[];
  executionProcessesByIdAll: Record<string, ExecutionProcess>;
  isAttemptRunningAll: boolean;
  executionProcessesVisible: ExecutionProcess[];
  executionProcessesByIdVisible: Record<string, ExecutionProcess>;
  isAttemptRunningVisible: boolean;
  isLoading: boolean;
  isConnected: boolean;
  error: string | null;
  lastEvent: BusEvent | null;
}

export const ExecutionProcessesContext = createContext<ExecutionProcessesContextValue | null>(null);

export function useExecutionProcessesContext(): ExecutionProcessesContextValue {
  const ctx = useContext(ExecutionProcessesContext);
  if (!ctx) {
    throw new Error("useExecutionProcessesContext must be used within ExecutionProcessesProvider");
  }
  return ctx;
}
