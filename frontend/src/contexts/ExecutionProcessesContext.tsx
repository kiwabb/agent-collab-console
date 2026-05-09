"use client";

import { createContext, useContext } from "react";
import type { ExecutionProcess, LogEvent } from "@/lib/types";

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
  lastEvent: LogEvent | null;
}

export const ExecutionProcessesContext = createContext<ExecutionProcessesContextValue | null>(null);

export function useExecutionProcessesContext(): ExecutionProcessesContextValue {
  const ctx = useContext(ExecutionProcessesContext);
  if (!ctx) {
    throw new Error("useExecutionProcessesContext must be used within ExecutionProcessesProvider");
  }
  return ctx;
}
