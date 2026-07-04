"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useExecutionProcessesContext } from "@/contexts/ExecutionProcessesContext";
import { checkBackendHealth } from "@/lib/api/health";

export type BackendStatus = "online" | "reconnecting" | "offline";

const HEALTH_INTERVAL_MS = 15_000;
const OFFLINE_GRACE_MS = 10_000;

export interface BackendStatusInfo {
  status: BackendStatus;
  retry: () => Promise<void>;
}

export function useBackendStatus(): BackendStatusInfo {
  const { isConnected } = useExecutionProcessesContext();
  const [healthOk, setHealthOk] = useState(true);
  const wsDownSinceRef = useRef<number | null>(null);
  const [, forceTick] = useState(0);

  const ping = useCallback(async () => {
    try {
      await checkBackendHealth();
      setHealthOk(true);
    } catch {
      setHealthOk(false);
    }
  }, []);

  useEffect(() => {
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      setHealthOk(false);
      return;
    }
    void ping();
    const id = window.setInterval(() => {
      if (typeof navigator !== "undefined" && navigator.onLine === false) {
        setHealthOk(false);
        return;
      }
      void ping();
    }, HEALTH_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [ping]);

  useEffect(() => {
    if (isConnected) {
      wsDownSinceRef.current = null;
      return;
    }
    if (wsDownSinceRef.current === null) {
      wsDownSinceRef.current = Date.now();
    }
    const id = window.setTimeout(() => forceTick((n) => n + 1), OFFLINE_GRACE_MS);
    return () => window.clearTimeout(id);
  }, [isConnected]);

  // `offline` is reserved for "the backend HTTP endpoint is failing". The
  // execution-process WebSocket only opens when a workspace is selected;
  // its disconnected state on the Inbox/Approvals/Settings routes is not
  // a backend problem and shouldn't surface here. Pages that care about
  // WS health surface their own loading/reconnecting indicators.
  void isConnected;
  const status: BackendStatus = healthOk ? "online" : "offline";

  return { status, retry: ping };
}
