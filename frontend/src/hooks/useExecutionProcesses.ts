"use client";

import { useEffect, useRef, useState, useCallback, useMemo, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { applyExecutionProcessPatch } from "@/lib/applyExecutionProcessPatch";
import { getExecutionProcesses, getGlobalEventsStreamUrl, getWorkspaceStreamUrl } from "@/lib/api";
import type { ExecutionProcessesState, ExecutionProcess, LogEvent } from "@/lib/types";
import type { BusEvent } from "@/contexts/ExecutionProcessesContext";
import { useWorkbenchStore } from "@/store/workbenchStore";

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
  lastEvent: BusEvent | null;
  resumeGapCount: number;
}

const LAST_EVENT_ID_KEY = "execution-processes:last-event-id";

export function useExecutionProcesses(workspaceId: string | null, onEvent?: (event: LogEvent) => void): UseExecutionProcessesResult {
  const [data, setData] = useState<ExecutionProcessesState>(createEmptyExecutionProcesses);
  const [lastEvent, setLastEvent] = useState<BusEvent | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resumeGapCount, setResumeGapCount] = useState(0);

  const workspaceWsRef = useRef<WebSocket | null>(null);
  const globalWsRef = useRef<WebSocket | null>(null);
  const workspaceConnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dataRef = useRef<ExecutionProcessesState>(createEmptyExecutionProcesses());
  const globalRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const workspaceRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const globalRetryAttemptsRef = useRef(0);
  const workspaceRetryAttemptsRef = useRef(0);
  const lastSeenEventIdRef = useRef<string | null>(null);
  const onEventRef = useRef(onEvent);
  const [globalRetryNonce, setGlobalRetryNonce] = useState(0);
  const [workspaceRetryNonce, setWorkspaceRetryNonce] = useState(0);
  const finishedRef = useRef(false);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  const scheduleReconnect = useCallback((
    attemptRef: MutableRefObject<number>,
    timerRef: MutableRefObject<ReturnType<typeof setTimeout> | null>,
    bump: Dispatch<SetStateAction<number>>,
  ) => {
    if (timerRef.current) return;
    const attempt = attemptRef.current;
    const baseDelay = Math.min(8000, 200 * Math.pow(2, attempt));
    const jitter = Math.floor(Math.random() * 250);
    const delay = baseDelay + jitter;
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      bump((n) => n + 1);
    }, delay);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    lastSeenEventIdRef.current = window.sessionStorage.getItem(LAST_EVENT_ID_KEY);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    let cancelled = false;

    function connectGlobal() {
      if (cancelled || globalWsRef.current) return;
      try {
        const ws = new WebSocket(getGlobalEventsStreamUrl(lastSeenEventIdRef.current));
        globalWsRef.current = ws;

        ws.onopen = () => {
          setError(null);
          setIsConnected(true);
          setIsInitialized(true);
          useWorkbenchStore.getState().setIsConnected(true);
          globalRetryAttemptsRef.current = 0;
          if (globalRetryTimerRef.current) {
            clearTimeout(globalRetryTimerRef.current);
            globalRetryTimerRef.current = null;
          }
        };

        ws.onmessage = (event) => {
          try {
            const envelope = JSON.parse(String(event.data)) as {
              v: number;
              ts: string;
              event_id: string;
              type: string;
              payload: Record<string, unknown>;
            };
            if (envelope.type === "ping") {
              ws.send("pong");
              return;
            }
            const nextEvent = { ...(envelope.payload ?? {}), type: envelope.type } as BusEvent;
            if (envelope.type === "resume_gap") {
              lastSeenEventIdRef.current = null;
              window.sessionStorage.removeItem(LAST_EVENT_ID_KEY);
              setResumeGapCount((count) => count + 1);
            } else if (envelope.event_id) {
              lastSeenEventIdRef.current = envelope.event_id;
              window.sessionStorage.setItem(LAST_EVENT_ID_KEY, envelope.event_id);
            }
            setLastEvent(nextEvent);
            useWorkbenchStore.getState().setLastEvent(nextEvent);
          } catch (err) {
            console.error("Failed to process global event stream message:", err);
            setError("Failed to process event stream update");
          }
        };

        ws.onclose = (evt) => {
          globalWsRef.current = null;
          setIsConnected(false);
          useWorkbenchStore.getState().setIsConnected(false);
          if (cancelled || (evt?.code === 1000 && evt?.wasClean)) return;
          globalRetryAttemptsRef.current += 1;
          scheduleReconnect(globalRetryAttemptsRef, globalRetryTimerRef, setGlobalRetryNonce);
        };
      } catch (err) {
        console.error("Failed to open global event stream:", err);
        globalRetryAttemptsRef.current += 1;
        scheduleReconnect(globalRetryAttemptsRef, globalRetryTimerRef, setGlobalRetryNonce);
      }
    }

    connectGlobal();
    return () => {
      cancelled = true;
      if (globalRetryTimerRef.current) {
        clearTimeout(globalRetryTimerRef.current);
        globalRetryTimerRef.current = null;
      }
      if (globalWsRef.current) {
        const ws = globalWsRef.current;
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        ws.close();
        globalWsRef.current = null;
      }
    };
  }, [globalRetryNonce, scheduleReconnect]);

  useEffect(() => {
    if (!workspaceId) {
      if (workspaceWsRef.current) {
        workspaceWsRef.current.close();
        workspaceWsRef.current = null;
      }
      if (workspaceConnectTimerRef.current) {
        clearTimeout(workspaceConnectTimerRef.current);
        workspaceConnectTimerRef.current = null;
      }
      if (workspaceRetryTimerRef.current) {
        clearTimeout(workspaceRetryTimerRef.current);
        workspaceRetryTimerRef.current = null;
      }
      workspaceRetryAttemptsRef.current = 0;
      finishedRef.current = false;
      setData(createEmptyExecutionProcesses());
      dataRef.current = createEmptyExecutionProcesses();
      useWorkbenchStore.getState().setExecutionProcesses({});
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
        useWorkbenchStore.getState().setExecutionProcesses(next.execution_processes);
        setIsInitialized(true);
        setError(null);
      } catch {
        // Fall through to websocket bootstrap. The stream still supplies
        // the authoritative initial snapshot on connect.
      }
    }

    function connect() {
      if (workspaceWsRef.current || cancelled) return;
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
          workspaceRetryAttemptsRef.current = 0;
          if (workspaceRetryTimerRef.current) {
            clearTimeout(workspaceRetryTimerRef.current);
            workspaceRetryTimerRef.current = null;
          }
          const heartbeat = window.setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send("ping");
          }, 30_000);
          ws.addEventListener("close", () => window.clearInterval(heartbeat), { once: true });
        };

        ws.onmessage = (event) => {
          try {
            // Server pings the socket with the literal string "pong" as a
            // keep-alive — not JSON. Skip those before attempting parse so
            // we don't spam the console with SyntaxError every 30s.
            const raw = event.data as string;
            if (typeof raw === "string" && (raw === "pong" || raw === "ping")) {
              return;
            }
            const msg = JSON.parse(raw) as {
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
              useWorkbenchStore.getState().setExecutionProcesses(next.execution_processes);
            }

            if (msg.Events) {
              msg.Events.forEach((evt) => {
                if (onEventRef.current) onEventRef.current(evt);
              });
            }

            if (msg.Ready) {
              setIsInitialized(true);
              setError(null);
            }

            if (msg.finished) {
              finishedRef.current = true;
              ws.close(1000, "finished");
              workspaceWsRef.current = null;
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
          workspaceWsRef.current = null;

          if (
            cancelled ||
            finishedRef.current ||
            (evt?.code === 1000 && evt?.wasClean)
          ) {
            return;
          }

          workspaceRetryAttemptsRef.current += 1;
          if (!dataRef.current && workspaceRetryAttemptsRef.current > 6) {
            setError("Connection failed");
          }
          scheduleReconnect(workspaceRetryAttemptsRef, workspaceRetryTimerRef, setWorkspaceRetryNonce);
        };

        workspaceWsRef.current = ws;
      } catch (error) {
        if (cancelled) {
          return;
        }
        console.error("Failed to open WebSocket stream:", error);
        workspaceRetryAttemptsRef.current += 1;
        scheduleReconnect(workspaceRetryAttemptsRef, workspaceRetryTimerRef, setWorkspaceRetryNonce);
      }
    }

    if (!workspaceWsRef.current && !workspaceConnectTimerRef.current) {
      workspaceConnectTimerRef.current = setTimeout(() => {
        workspaceConnectTimerRef.current = null;
        void loadInitialSnapshot().finally(() => {
          if (!cancelled) {
            connect();
          }
        });
      }, 0);
    }

    return () => {
      cancelled = true;
      if (workspaceConnectTimerRef.current) {
        clearTimeout(workspaceConnectTimerRef.current);
        workspaceConnectTimerRef.current = null;
      }
      if (workspaceWsRef.current) {
        const ws = workspaceWsRef.current;
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        ws.close();
        workspaceWsRef.current = null;
      }
      if (workspaceRetryTimerRef.current) {
        clearTimeout(workspaceRetryTimerRef.current);
        workspaceRetryTimerRef.current = null;
      }
      finishedRef.current = false;
      dataRef.current = createEmptyExecutionProcesses();
      setData(createEmptyExecutionProcesses());
      setIsInitialized(false);
    };
  }, [workspaceId, workspaceRetryNonce, scheduleReconnect]);

  const executionProcesses = useMemo(() => {
    const executionProcessesById = data.execution_processes || {};
    return Object.values(executionProcessesById).sort((a, b) => {
      const aTime = Date.parse((a as ExecutionProcess).created_at || (a as ExecutionProcess).started_at || (a as ExecutionProcess).updated_at || "") || 0;
      const bTime = Date.parse((b as ExecutionProcess).created_at || (b as ExecutionProcess).started_at || (b as ExecutionProcess).updated_at || "") || 0;
      return bTime - aTime;
    });
  }, [data.execution_processes]);
  const executionProcessesById = data.execution_processes || {};
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
    resumeGapCount,
  };
}
