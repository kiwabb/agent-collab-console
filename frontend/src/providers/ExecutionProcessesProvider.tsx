"use client";

import { useEffect, useMemo, type ReactNode } from "react";
import { useExecutionProcesses } from "@/hooks/useExecutionProcesses";
import {
  ExecutionProcessesContext,
  type ExecutionProcessesContextValue,
} from "@/contexts/ExecutionProcessesContext";
import { emitDataEvent } from "@/lib/dataEvents";
import type { ExecutionProcess } from "@/lib/types";

interface ExecutionProcessesProviderProps {
  workspaceId: string | null;
  children: ReactNode;
}

export function ExecutionProcessesProvider({ workspaceId, children }: ExecutionProcessesProviderProps) {
  const {
    executionProcesses,
    executionProcessesById,
    isAttemptRunning,
    isConnected,
    isInitialized,
    error,
    lastEvent,
    resumeGapCount,
  } = useExecutionProcesses(workspaceId);

  const visible = useMemo(() => executionProcesses, [executionProcesses]);

  const executionProcessesByIdVisible = useMemo(
    () => Object.fromEntries(visible.map((process: ExecutionProcess) => [process.id, process])),
    [visible],
  );

  const isAttemptRunningVisible = useMemo(
    () =>
      visible.some((process: ExecutionProcess) => {
        const status = String(process.status || "").toLowerCase();
        return status === "running" || status === "responding";
      }),
    [visible],
  );

  useEffect(() => {
    if (lastEvent?.type === "project_updated" || lastEvent?.type === "project_script_updated") {
      emitDataEvent("projects:changed");
    }
  }, [lastEvent]);

  const value = useMemo((): ExecutionProcessesContextValue => ({
    executionProcessesAll: executionProcesses,
    executionProcessesByIdAll: executionProcessesById,
    isAttemptRunningAll: isAttemptRunning,
    executionProcessesVisible: visible,
    executionProcessesByIdVisible,
    isAttemptRunningVisible,
    isLoading: Boolean(workspaceId) && !isInitialized && !error,
    isConnected,
    error,
    lastEvent,
    resumeGapCount,
  }), [
    error,
    executionProcesses,
    executionProcessesById,
    executionProcessesByIdVisible,
    isAttemptRunning,
    isAttemptRunningVisible,
    isConnected,
    isInitialized,
    workspaceId,
    visible,
    lastEvent,
    resumeGapCount,
  ]);

  return (
    <ExecutionProcessesContext.Provider value={value}>
      {children}
    </ExecutionProcessesContext.Provider>
  );
}
