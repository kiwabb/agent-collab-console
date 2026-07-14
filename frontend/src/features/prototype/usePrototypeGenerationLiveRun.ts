"use client";

import { useEffect, useRef, useState } from "react";

import {
  getPrototypeGenerationRun,
  getPrototypeGenerationRunEventsUrl,
} from "@/lib/api/prototypes";
import type { PrototypeGenerationRun } from "@/lib/types";
import {
  readPrototypeGenerationSnapshot,
  readPrototypeStreamHeartbeat,
} from "./prototypeStreamEvents";
import {
  isPrototypeGenerationRunActive,
  PROTOTYPE_POLL_EXHAUSTED_ERROR,
} from "./prototypePlanReviewState";

export type PrototypeGenerationConnectionIssue = "invalid_snapshot" | "disconnected" | "silent";

interface Options {
  run: PrototypeGenerationRun | null;
  onSnapshot: (run: PrototypeGenerationRun) => void;
  recoveryKey: number;
}

interface Result {
  connectionIssue: PrototypeGenerationConnectionIssue | null;
  pollingError: string | null;
  usingPollingFallback: boolean;
}

const POLL_INTERVAL_MS = 1_500;
export const PROTOTYPE_STREAM_SILENCE_MS = 15_000;
export const PROTOTYPE_POLL_MAX_ATTEMPTS = 20;
export const PROTOTYPE_POLL_DEADLINE_MS = 60_000;

export interface PrototypePollingRecoveryBudget {
  attempts: number;
  startedAt: number | null;
}

export type PrototypePollingRecoveryDecision =
  | { kind: "poll"; budget: PrototypePollingRecoveryBudget }
  | { kind: "exhausted"; budget: PrototypePollingRecoveryBudget };

export function advancePrototypePollingRecovery(
  budget: PrototypePollingRecoveryBudget,
  nowMs: number,
): PrototypePollingRecoveryDecision {
  const startedAt = budget.startedAt ?? nowMs;
  const nextBudget = { attempts: budget.attempts, startedAt };
  if (
    budget.attempts >= PROTOTYPE_POLL_MAX_ATTEMPTS ||
    nowMs - startedAt >= PROTOTYPE_POLL_DEADLINE_MS
  ) {
    return { kind: "exhausted", budget: nextBudget };
  }
  return {
    kind: "poll",
    budget: { attempts: budget.attempts + 1, startedAt },
  };
}

export function resetPrototypePollingRecovery(): PrototypePollingRecoveryBudget {
  return { attempts: 0, startedAt: null };
}

export function usePrototypeGenerationLiveRun({ run, onSnapshot, recoveryKey }: Options): Result {
  const [connectionIssue, setConnectionIssue] = useState<PrototypeGenerationConnectionIssue | null>(
    null,
  );
  const [pollingError, setPollingError] = useState<string | null>(null);
  const [usingPollingFallback, setUsingPollingFallback] = useState(false);
  const onSnapshotRef = useRef(onSnapshot);

  useEffect(() => {
    onSnapshotRef.current = onSnapshot;
  }, [onSnapshot]);

  const runId = run?.id ?? null;
  const isActive = isPrototypeGenerationRunActive(run);

  useEffect(() => {
    if (!runId || !isActive) {
      setConnectionIssue(null);
      setPollingError(null);
      setUsingPollingFallback(false);
      return;
    }

    let disposed = false;
    let polling = false;
    let issue: PrototypeGenerationConnectionIssue | null = null;
    let lastStreamActivityAt = Date.now();
    let recoveryBudget = resetPrototypePollingRecovery();
    let recoveryExhausted = false;
    const source = new EventSource(getPrototypeGenerationRunEventsUrl(runId));
    setConnectionIssue(null);
    setPollingError(null);
    setUsingPollingFallback(false);

    const updateIssue = (next: PrototypeGenerationConnectionIssue | null) => {
      issue = next;
      if (!disposed) setConnectionIssue(next);
    };

    const markStreamHealthy = () => {
      if (disposed) return;
      lastStreamActivityAt = Date.now();
      recoveryBudget = resetPrototypePollingRecovery();
      recoveryExhausted = false;
      updateIssue(null);
      setUsingPollingFallback(false);
      setPollingError(null);
    };

    const onStreamSnapshot = (event: MessageEvent<string>) => {
      const next = readPrototypeGenerationSnapshot(event);
      if (!next || next.id !== runId) {
        console.error("prototype generation snapshot parse failed", runId);
        updateIssue("invalid_snapshot");
        return;
      }
      markStreamHealthy();
      onSnapshotRef.current(next);
    };

    const onHeartbeat = (event: MessageEvent<string>) => {
      const heartbeat = readPrototypeStreamHeartbeat(event);
      if (!heartbeat || heartbeat.resource_id !== runId) return;
      markStreamHealthy();
    };

    const onError = () => {
      console.error("prototype generation event stream failed", runId);
      updateIssue("disconnected");
    };

    source.addEventListener("snapshot", onStreamSnapshot);
    source.addEventListener("heartbeat", onHeartbeat);
    source.addEventListener("error", onError);

    const interval = window.setInterval(() => {
      const streamIsSilent = Date.now() - lastStreamActivityAt >= PROTOTYPE_STREAM_SILENCE_MS;
      if ((!issue && !streamIsSilent) || polling || recoveryExhausted) return;
      if (!issue) updateIssue("silent");
      const recovery = advancePrototypePollingRecovery(recoveryBudget, Date.now());
      recoveryBudget = recovery.budget;
      if (recovery.kind === "exhausted") {
        recoveryExhausted = true;
        setUsingPollingFallback(false);
        setPollingError(PROTOTYPE_POLL_EXHAUSTED_ERROR);
        return;
      }
      polling = true;
      setUsingPollingFallback(true);
      void getPrototypeGenerationRun(runId)
        .then((next) => {
          if (disposed) return;
          onSnapshotRef.current(next);
          setPollingError(null);
        })
        .catch((error: unknown) => {
          if (disposed) return;
          console.error("prototype generation polling reconciliation failed", runId, error);
          setPollingError(error instanceof Error ? error.message : String(error));
        })
        .finally(() => {
          polling = false;
        });
    }, POLL_INTERVAL_MS);

    return () => {
      disposed = true;
      window.clearInterval(interval);
      source.removeEventListener("snapshot", onStreamSnapshot);
      source.removeEventListener("heartbeat", onHeartbeat);
      source.removeEventListener("error", onError);
      source.close();
    };
  }, [runId, isActive, recoveryKey]);

  return { connectionIssue, pollingError, usingPollingFallback };
}
