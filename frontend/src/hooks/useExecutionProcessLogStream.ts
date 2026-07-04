"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { getProcessLogsUrl } from "@/lib/api/tasks";
import type { LogEvent } from "@/lib/types";

function sortLogs<T extends { created_at?: string | null }>(logs: T[]): T[] {
  return [...logs].sort((a, b) => {
    const aTime = a?.created_at ? new Date(a.created_at).getTime() : 0;
    const bTime = b?.created_at ? new Date(b.created_at).getTime() : 0;
    return aTime - bTime;
  });
}

export interface StreamingAssistant {
  seq: number;
  text: string;
  receivedAt: number;
}

export interface HeartbeatInfo {
  phase: string;
  elapsedSinceLastMs: number;
  lastEventAt: number | null;
  receivedAt: number;
}

interface UseExecutionProcessLogStreamResult {
  logs: LogEvent[];
  error: string | null;
  streamingAssistant: StreamingAssistant | null;
  heartbeat: HeartbeatInfo | null;
  finished: boolean;
  disconnected: boolean;
}

export function useExecutionProcessLogStream(processId: string | null): UseExecutionProcessLogStreamResult {
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [streamingAssistant, setStreamingAssistant] = useState<StreamingAssistant | null>(null);
  const [heartbeat, setHeartbeat] = useState<HeartbeatInfo | null>(null);
  const [finished, setFinished] = useState(false);
  const [disconnected, setDisconnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const connectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryAttemptsRef = useRef(0);
  const finishedRef = useRef(false);
  const logIdsRef = useRef(new Set<string>());
  const streamingTextRef = useRef("");
  const streamingSeqRef = useRef(0);
  const connectRef = useRef<() => void>(() => {});

  const scheduleReconnect = useCallback(() => {
    if (retryTimerRef.current || finishedRef.current) return;
    const attempt = retryAttemptsRef.current;
    const delay = Math.min(1500, 250 * (2 ** attempt));
    retryTimerRef.current = setTimeout(() => {
      retryTimerRef.current = null;
      connectRef.current();
    }, delay);
  }, []);

  function addLog(log: LogEvent) {
    if (!log?.id || logIdsRef.current.has(log.id)) return;
    logIdsRef.current.add(log.id);
    setLogs((prev) => sortLogs([...prev, log]));
  }

  const connect = useCallback(() => {
    if (!processId) return;
    if (wsRef.current || finishedRef.current) return;
    const wsUrl = getProcessLogsUrl(processId);

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        retryAttemptsRef.current = 0;
        setError(null);
        setDisconnected(false);
        // Keepalive: send ping every 30s so idle connections survive VPN/proxy timeouts.
        const heartbeat = window.setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, 30_000);
        ws.addEventListener("close", () => window.clearInterval(heartbeat), { once: true });
      };

      ws.onmessage = (event) => {
        const raw = event.data;
        // The server replies "pong" (plain text) to client pings. Anything that
        // isn't a JSON envelope is a control frame we don't need to surface.
        if (typeof raw !== "string" || raw === "pong" || raw.length === 0 || raw[0] !== "{") {
          return;
        }
        let data:
          | ({ finished?: boolean; kind?: string } & Partial<LogEvent> & {
              seq?: number;
              delta_text?: string;
              phase?: string;
              last_event_at?: number | null;
              elapsed_since_last_ms?: number;
            })
          | null = null;
        try {
          data = JSON.parse(raw);
        } catch {
          // Non-JSON server frame — ignore instead of surfacing a user-visible
          // error. Real schema problems show up in `addLog` / handler code.
          return;
        }
        try {

          if (data?.finished) {
            finishedRef.current = true;
            setFinished(true);
            // Clear the in-flight streaming bubble — final assistant text will
            // arrive via the normal log stream / messages.
            streamingTextRef.current = "";
            streamingSeqRef.current = 0;
            setStreamingAssistant(null);
            ws.close(1000, "finished");
            return;
          }

          if (data?.kind === "assistant_delta") {
            const incomingSeq = typeof data.seq === "number" ? data.seq : streamingSeqRef.current + 1;
            const delta = typeof data.delta_text === "string" ? data.delta_text : "";
            // The backend folds deltas itself (entry.last_emitted_assistant_text);
            // seq is monotonic per-turn. If we see a lower seq, that's a new turn
            // — reset the buffer.
            if (incomingSeq <= streamingSeqRef.current) {
              streamingTextRef.current = delta;
            } else {
              streamingTextRef.current += delta;
            }
            streamingSeqRef.current = incomingSeq;
            setStreamingAssistant({
              seq: incomingSeq,
              text: streamingTextRef.current,
              receivedAt: Date.now(),
            });
            return;
          }

          if (data?.kind === "heartbeat") {
            setHeartbeat({
              phase: data.phase || "idle",
              elapsedSinceLastMs: data.elapsed_since_last_ms ?? 0,
              lastEventAt: data.last_event_at ?? null,
              receivedAt: Date.now(),
            });
            return;
          }

          // Plain LogEvent row (has an id and stream). When a final assistant
          // message arrives, drop the streaming buffer so the bubble doesn't
          // duplicate.
          if ((data as LogEvent).id && (data as LogEvent).stream) {
            if ((data as LogEvent).stream === "stdout" && streamingTextRef.current) {
              // The full assistant text will be rendered from the LogEvent itself
              // once normalized — kill the in-flight ghost.
              streamingTextRef.current = "";
              streamingSeqRef.current = 0;
              setStreamingAssistant(null);
            }
            addLog(data as LogEvent);
            return;
          }
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
        if (retryAttemptsRef.current > 1) setDisconnected(true);
        if (retryAttemptsRef.current > 6) {
          setError("Log stream connection failed");
        }
        scheduleReconnect();
      };

      wsRef.current = ws;
    } catch {
      retryAttemptsRef.current += 1;
      scheduleReconnect();
    }
  }, [processId, scheduleReconnect]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

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
      streamingTextRef.current = "";
      streamingSeqRef.current = 0;
      setLogs([]);
      setError(null);
      setStreamingAssistant(null);
      setHeartbeat(null);
      setFinished(false);
      setDisconnected(false);
      return;
    }

    let cancelled = false;
    finishedRef.current = false;
    logIdsRef.current = new Set();
    streamingTextRef.current = "";
    streamingSeqRef.current = 0;
    setLogs([]);
    setError(null);
    setStreamingAssistant(null);
    setHeartbeat(null);
    setFinished(false);
    setDisconnected(false);

    connectTimerRef.current = setTimeout(() => {
      connectTimerRef.current = null;
      if (!cancelled) {
        connectRef.current();
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
  }, [processId]);

  return { logs, error, streamingAssistant, heartbeat, finished, disconnected };
}
