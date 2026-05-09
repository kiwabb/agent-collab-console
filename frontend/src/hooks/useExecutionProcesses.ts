"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { applyExecutionProcessPatch } from "@/lib/applyExecutionProcessPatch";
import { getExecutionProcesses, getWorkspaceStreamUrl } from "@/lib/api";
import type { ExecutionProcessesState, ExecutionProcess, LogEvent } from "@/lib/types";

function createEmptyExecutionProcesses(): ExecutionProcessesState {
  return { execution_processes: {} };
}

interface UseExecutionProcessesResult {
  executionProcesses: ExecutionProcess[];
  executionProcessesById: Record<string, ExecutionProcess>;
  isAttemptRunning: boolean;
  isConnected: boolean;
  isInitialized: boolean;
  error: string | null;
  lastEvent: LogEvent | null;
}

export function useExecutionProcesses(workspaceId: string | null, onEvent?: (event: LogEvent) => void): UseExecutionProcessesResult {
  const [data, setData] = useState<ExecutionProcessesState>(createEmptyExecutionProcesses);
  const [lastEvent, setLastEvent] = useState<LogEvent | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const connectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dataRef = useRef<ExecutionProcessesState>(createEmptyExecutionProcesses());
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryAttemptsRef = useRef(0);
  const [retryNonce, setRetryNonce] = useState(0);
  const finishedRef = useRef(false);

  const scheduleReconnect = useCallback(() => {
    if (retryTimerRef.current) return;
    const attempt = retryAttemptsRef.current;
    const delay = Math.min(8000, 1000 * Math.pow(2, attempt));
    retryTimerRef.current = setTimeout(() => {
      retryTimerRef.current = null;
      setRetryNonce((n) => n + 1);
    }, delay);
  }, []);

  useEffect(() => {
    if (!workspaceId) {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (connectTimerRef.current) {
        clearTimeout(connectTimerRef.current);
        connectTimerRef.current = null;
      }
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      retryAttemptsRef.current = 0;
      finishedRef.current = false;
      setData(createEmptyExecutionProcesses());
      setIsConnected(false);
      setIsInitialized(false);
      setError(null);
      dataRef.current = createEmptyExecutionProcesses();
      return;
    }

    if (!dataRef.current) {
      dataRef.current = createEmptyExecutionProcesses();
    }

    let cancelled = false;

    async function loadInitialSnapshot() {
      try {
        const snapshot = await getExecutionProcesses(workspaceId);
        if (cancelled || !workspaceId) return;

        const executionProcesses = Array.isArray(snapshot) ? snapshot : [];
        const next: ExecutionProcessesState = {
          execution_processes: Object.fromEntries(
            executionProcesses.map((process) => [process.id, process]),
          ),
        };
        dataRef.current = next;
        setData(next);
        setIsInitialized(true);
        setError(null);
      } catch {
        // Fall through to websocket bootstrap. The stream still supplies
        // the authoritative initial snapshot on connect.
      }
    }

    function connect() {
      if (wsRef.current || cancelled) return;
      finishedRef.current = false;
      if (!workspaceId) return;

      const wsUrl = getWorkspaceStreamUrl(workspaceId);

      try {
        const ws = new WebSocket(wsUrl);

        if (cancelled) {
          ws.close();
          return;
        }

        ws.onopen = () => {
          setError(null);
          setIsConnected(true);
          retryAttemptsRef.current = 0;
          if (retryTimerRef.current) {
            clearTimeout(retryTimerRef.current);
            retryTimerRef.current = null;
          }
        };

        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data as string) as { 
              JsonPatch?: unknown[]; 
              Events?: LogEvent[];
              Ready?: boolean; 
              finished?: boolean 
            };

            if (msg.JsonPatch) {
              const patches = msg.JsonPatch;
              const current = dataRef.current;

              if (!patches.length || !current) return;

              const next = applyExecutionProcessPatch(current, patches as Parameters<typeof applyExecutionProcessPatch>[1]);
              dataRef.current = next;
              setData(next);
            }

            if (msg.Events) {
              msg.Events.forEach((evt) => {
                setLastEvent(evt);
                if (onEvent) onEvent(evt);
              });
            }

            if (msg.Ready) {
              setIsInitialized(true);
              setError(null);
            }

            if (msg.finished) {
              finishedRef.current = true;
              ws.close(1000, "finished");
              wsRef.current = null;
              setIsConnected(false);
            }
          } catch (err) {
            console.error("Failed to process WebSocket message:", err);
            setError("Failed to process stream update");
          }
        };

        ws.onerror = () => {
          // onclose always fires after onerror, handle retry there
        };

        ws.onclose = (evt) => {
          setIsConnected(false);
          wsRef.current = null;

          if (
            cancelled ||
            finishedRef.current ||
            (evt?.code === 1000 && evt?.wasClean)
          ) {
            return;
          }

          retryAttemptsRef.current += 1;
          if (!dataRef.current && retryAttemptsRef.current > 6) {
            setError("Connection failed");
          }
          scheduleReconnect();
        };

        wsRef.current = ws;
      } catch (error) {
        if (cancelled) {
          return;
        }
        console.error("Failed to open WebSocket stream:", error);
        retryAttemptsRef.current += 1;
        scheduleReconnect();
      }
    }

    if (!wsRef.current && !connectTimerRef.current) {
      connectTimerRef.current = setTimeout(() => {
        connectTimerRef.current = null;
        void loadInitialSnapshot().finally(() => {
          if (!cancelled) {
            connect();
          }
        });
      }, 0);
    }

    return () => {
      cancelled = true;
      if (connectTimerRef.current) {
        clearTimeout(connectTimerRef.current);
        connectTimerRef.current = null;
      }
      if (wsRef.current) {
        const ws = wsRef.current;
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        ws.close();
        wsRef.current = null;
      }
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      finishedRef.current = false;
      dataRef.current = createEmptyExecutionProcesses();
      setData(createEmptyExecutionProcesses());
      setIsInitialized(false);
    };
  }, [workspaceId, retryNonce, scheduleReconnect]);

  const executionProcessesById = data.execution_processes || {};
  const executionProcesses = Object.values(executionProcessesById).sort((a, b) => {
    const aTime = Date.parse((a as ExecutionProcess).created_at || (a as ExecutionProcess).started_at || (a as ExecutionProcess).updated_at || "") || 0;
    const bTime = Date.parse((b as ExecutionProcess).created_at || (b as ExecutionProcess).started_at || (b as ExecutionProcess).updated_at || "") || 0;
    return bTime - aTime;
  });
  const isAttemptRunning = executionProcesses.some((process) => {
    const status = String((process as ExecutionProcess).status || "").toLowerCase();
    return status === "running" || status === "responding";
  });

  return {
    executionProcesses: executionProcesses as ExecutionProcess[],
    executionProcessesById: executionProcessesById as Record<string, ExecutionProcess>,
    isAttemptRunning,
    isConnected,
    isInitialized,
    error,
    lastEvent,
  };
}
