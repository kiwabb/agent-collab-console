"use client";

import { useEffect, useState } from "react";

import { useExecutionProcessesContext } from "@/contexts/ExecutionProcessesContext";

export function useWsConnectionStatus() {
  const { isConnected, resumeGapCount } = useExecutionProcessesContext();
  const [showDisconnected, setShowDisconnected] = useState(false);
  const [recoveredCount, setRecoveredCount] = useState<number | null>(null);

  useEffect(() => {
    if (isConnected) {
      setShowDisconnected(false);
      return;
    }
    const id = window.setTimeout(() => setShowDisconnected(true), 3000);
    return () => window.clearTimeout(id);
  }, [isConnected]);

  useEffect(() => {
    if (!isConnected || resumeGapCount <= 0) return;
    setRecoveredCount(resumeGapCount);
    const id = window.setTimeout(() => setRecoveredCount(null), 2200);
    return () => window.clearTimeout(id);
  }, [isConnected, resumeGapCount]);

  return { isConnected, showDisconnected, recoveredCount };
}
