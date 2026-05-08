"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { getProcessLogsUrl } from "@/lib/api";
import type { LogEvent } from "@/lib/types";

function sortLogs<T extends { created_at?: string | null }>(logs: T[]): T[] {
  return [...logs].sort((a, b) => {
    const aTime = a?.created_at ? new Date(a.created_at).getTime() : 0;
    const bTime = b?.created_at ? new Date(b.created_at).getTime() : 0;
    return aTime - bTime;
  });
}

interface UseExecutionProcessLogStreamResult {
  logs: LogEvent[];
  error: string | null;
}

export function useExecutionProcessLogStream(processId: string | null): UseExecutionProcessLogStreamResult {
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const connectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryAttemptsRef = useRef(0);
  const finishedRef = useRef(false);
  const logIdsRef = useRef(new Set<string>());

  const scheduleReconnect = useCallback(() => {
    if (retryTimerRef.current || finishedRef.current) return;
    const attempt = retryAttemptsRef.current;
    const delay = Math.min(1500, 250 * (2 ** attempt));
    retryTimerRef.current = setTimeout(() => {
      retryTimerRef.current = null;
      connect();
    }, delay);
  }, []);

  function addLog(log: LogEvent) {
    if (!log?.id || logIdsRef.current.has(log.id)) return;
    logIdsRef.current.add(log.id);
    setLogs((prev) => sortLogs([...prev, log]));
  }

  function connect() {
    if (!processId) return;
    if (wsRef.current || finishedRef.current) return;
    const wsUrl = getProcessLogsUrl(processId);

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        retryAttemptsRef.current = 0;
        setError(null);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string) as { finished?: boolean } & LogEvent;
          if (data?.finished) {
            finishedRef.current = true;
            ws.close(1000, "finished");
            return;
          }
          addLog(data as LogEvent);
        } catch {
          setError("Failed to process log stream update");
        }
      };

      ws.onerror = () => {
        // handled by onclose
      };

      ws.onclose = (evt) => {
        wsRef.current = null;
        if (
          finishedRef.current ||
          (evt?.code === 1000 && evt?.wasClean)
        ) {
          return;
        }
        retryAttemptsRef.current += 1;
        if (retryAttemptsRef.current > 6) {
          setError("Log stream connection failed");
          return;
        }
        scheduleReconnect();
      };

      wsRef.current = ws;
    } catch {
      retryAttemptsRef.current += 1;
      scheduleReconnect();
    }
  }

  useEffect(() => {
    if (!processId) {
      if (connectTimerRef.current) {
        clearTimeout(connectTimerRef.current);
        connectTimerRef.current = null;
      }
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      retryAttemptsRef.current = 0;
      finishedRef.current = false;
      logIdsRef.current = new Set();
      setLogs([]);
      setError(null);
      return;
    }

    let cancelled = false;
    finishedRef.current = false;
    logIdsRef.current = new Set();
    setLogs([]);
    setError(null);

    connectTimerRef.current = setTimeout(() => {
      connectTimerRef.current = null;
      if (!cancelled) {
        connect();
      }
    }, 0);

    return () => {
      cancelled = true;
      if (connectTimerRef.current) {
        clearTimeout(connectTimerRef.current);
        connectTimerRef.current = null;
      }
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
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
    };
  }, [processId, scheduleReconnect]);

  return { logs, error };
}
