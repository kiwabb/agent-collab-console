"use client";

import { createContext, useContext } from "react";

export interface ExecutionProcessesContextValue {
  executionProcessesAll: unknown[];
  executionProcessesByIdAll: Record<string, unknown>;
  isAttemptRunningAll: boolean;
  executionProcessesVisible: unknown[];
  executionProcessesByIdVisible: Record<string, unknown>;
  isAttemptRunningVisible: boolean;
  isLoading: boolean;
  isConnected: boolean;
  error: string | null;
  lastEvent: any | null;
}

export const ExecutionProcessesContext = createContext<ExecutionProcessesContextValue | null>(null);

export function useExecutionProcessesContext(): ExecutionProcessesContextValue {
  const ctx = useContext(ExecutionProcessesContext);
  if (!ctx) {
    throw new Error("useExecutionProcessesContext must be used within ExecutionProcessesProvider");
  }
  return ctx;
}
