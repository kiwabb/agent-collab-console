"use client";

import { createContext, useContext } from "react";
import type { ExecutionProcess, LogEvent } from "@/lib/types";

// Event types that come through the event bus stream
export type BusEventType = "task_status" | "task_created" | "message_created" | "log" | "approval_required" | "approval_resolved" | "session_status" | "session_created" | "session_deleted" | "issue_deleted" | "task_deleted" | "issue_merged" | "issue_abandoned";

export interface BusIssueMergedEvent {
  type: "issue_merged";
  issue_id: string;
  sha: string;
  base_branch: string;
}

export interface BusIssueAbandonedEvent {
  type: "issue_abandoned";
  issue_id: string;
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

export type BusEvent = BusTaskStatusEvent | BusTaskCreatedEvent | BusIssueMergedEvent | BusIssueAbandonedEvent | (LogEvent & { type?: BusEventType });

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
