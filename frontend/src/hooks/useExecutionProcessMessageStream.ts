"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { getProcessMessagesUrl } from "@/lib/api";
import type { CodexTaskMessage } from "@/lib/types";

function sortMessages<T extends { created_at?: string | null }>(messages: T[]): T[] {
  return [...messages].sort((a, b) => {
    const aTime = a?.created_at ? new Date(a.created_at).getTime() : 0;
    const bTime = b?.created_at ? new Date(b.created_at).getTime() : 0;
    return aTime - bTime;
  });
}

interface UseExecutionProcessMessageStreamResult {
  messages: CodexTaskMessage[];
  error: string | null;
}

export function useExecutionProcessMessageStream(processId: string | null): UseExecutionProcessMessageStreamResult {
  const [messages, setMessages] = useState<CodexTaskMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const connectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryAttemptsRef = useRef(0);
  const finishedRef = useRef(false);
  const messageIdsRef = useRef(new Set<string>());

  const scheduleReconnect = useCallback(() => {
    if (retryTimerRef.current || finishedRef.current) return;
    const attempt = retryAttemptsRef.current;
    const delay = Math.min(1500, 250 * (2 ** attempt));
    retryTimerRef.current = setTimeout(() => {
      retryTimerRef.current = null;
      connect();
    }, delay);
  }, []);

  function addMessage(message: CodexTaskMessage) {
    if (!message?.id || messageIdsRef.current.has(message.id)) return;
    messageIdsRef.current.add(message.id);
    setMessages((prev) => sortMessages([...prev, message]));
  }

  function connect() {
    if (!processId) return;
    if (wsRef.current || finishedRef.current) return;
    const wsUrl = getProcessMessagesUrl(processId);

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        retryAttemptsRef.current = 0;
        setError(null);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string) as { finished?: boolean } & CodexTaskMessage;
          if (data?.finished) {
            finishedRef.current = true;
            ws.close(1000, "finished");
            return;
          }
          addMessage(data);
        } catch {
          setError("Failed to process message stream update");
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
          setError("Message stream connection failed");
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
      messageIdsRef.current = new Set();
      setMessages([]);
      setError(null);
      return;
    }

    let cancelled = false;
    finishedRef.current = false;
    messageIdsRef.current = new Set();
    setMessages([]);
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

  return { messages, error };
}
