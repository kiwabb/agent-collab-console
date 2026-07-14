"use client";

import { useEffect, useRef, useState } from "react";

import { getPrototypePlan, getPrototypePlanEventsUrl } from "@/lib/api/prototypes";
import type { PrototypePlan } from "@/lib/types";
import { readPrototypePlanSnapshot, readPrototypeStreamHeartbeat } from "./prototypeStreamEvents";
import { matchesPrototypePlanStreamResource } from "./prototypePlanReviewState";
import {
  advancePrototypePollingRecovery,
  PROTOTYPE_STREAM_SILENCE_MS,
  resetPrototypePollingRecovery,
} from "./usePrototypeGenerationLiveRun";

export type PrototypePlanConnectionIssue =
  "invalid_snapshot" | "invalid_resource" | "disconnected" | "silent";
export type PrototypePlanPollingIssue = "request_failed" | "invalid_resource" | "exhausted";

interface Options {
  plan: PrototypePlan | null;
  planId: string;
  projectId: string;
  onSnapshot: (plan: PrototypePlan) => void;
  recoveryKey: number;
}

interface Result {
  connectionIssue: PrototypePlanConnectionIssue | null;
  pollingIssue: PrototypePlanPollingIssue | null;
  usingPollingFallback: boolean;
}

const POLL_INTERVAL_MS = 1_500;

function isActivePlan(plan: PrototypePlan | null, planId: string, projectId: string): boolean {
  return (
    plan !== null &&
    plan.id === planId &&
    plan.project_id === projectId &&
    (plan.status === "queued" || plan.status === "analyzing")
  );
}

export function usePrototypePlanLiveRecovery({
  plan,
  planId,
  projectId,
  onSnapshot,
  recoveryKey,
}: Options): Result {
  const [connectionIssue, setConnectionIssue] = useState<PrototypePlanConnectionIssue | null>(null);
  const [pollingIssue, setPollingIssue] = useState<PrototypePlanPollingIssue | null>(null);
  const [usingPollingFallback, setUsingPollingFallback] = useState(false);
  const onSnapshotRef = useRef(onSnapshot);

  useEffect(() => {
    onSnapshotRef.current = onSnapshot;
  }, [onSnapshot]);

  const isActive = isActivePlan(plan, planId, projectId);

  useEffect(() => {
    if (!isActive) {
      setConnectionIssue(null);
      setPollingIssue(null);
      setUsingPollingFallback(false);
      return;
    }

    let disposed = false;
    let polling = false;
    let issue: PrototypePlanConnectionIssue | null = null;
    let lastStreamActivityAt = Date.now();
    let recoveryBudget = resetPrototypePollingRecovery();
    let recoveryExhausted = false;
    const source = new EventSource(getPrototypePlanEventsUrl(planId));
    setConnectionIssue(null);
    setPollingIssue(null);
    setUsingPollingFallback(false);

    const updateIssue = (next: PrototypePlanConnectionIssue | null) => {
      issue = next;
      if (!disposed) setConnectionIssue(next);
    };

    const markStreamHealthy = () => {
      if (disposed) return;
      lastStreamActivityAt = Date.now();
      recoveryBudget = resetPrototypePollingRecovery();
      recoveryExhausted = false;
      updateIssue(null);
      setPollingIssue(null);
      setUsingPollingFallback(false);
    };

    const onStreamSnapshot = (event: MessageEvent<string>) => {
      const next = readPrototypePlanSnapshot(event);
      if (!next) {
        console.error("prototype plan snapshot parse failed", planId);
        updateIssue("invalid_snapshot");
        return;
      }
      if (!matchesPrototypePlanStreamResource(next, planId, projectId, projectId)) {
        console.error(
          "prototype plan snapshot resource mismatch",
          planId,
          next.id,
          next.project_id,
        );
        updateIssue("invalid_resource");
        return;
      }
      markStreamHealthy();
      onSnapshotRef.current(next);
    };

    const onHeartbeat = (event: MessageEvent<string>) => {
      const heartbeat = readPrototypeStreamHeartbeat(event);
      if (!heartbeat) {
        console.error("prototype plan heartbeat parse failed", planId);
        updateIssue("invalid_snapshot");
        return;
      }
      if (heartbeat.resource_id !== planId) {
        console.error("prototype plan heartbeat resource mismatch", planId, heartbeat.resource_id);
        updateIssue("invalid_resource");
        return;
      }
      markStreamHealthy();
    };

    const onError = () => {
      console.error("prototype plan event stream failed", planId);
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
        setPollingIssue("exhausted");
        return;
      }

      polling = true;
      setUsingPollingFallback(true);
      void getPrototypePlan(planId)
        .then((next) => {
          if (disposed) return;
          if (!matchesPrototypePlanStreamResource(next, planId, projectId, projectId)) {
            console.error(
              "prototype plan polling resource mismatch",
              planId,
              next.id,
              next.project_id,
            );
            updateIssue("invalid_resource");
            setPollingIssue("invalid_resource");
            return;
          }
          onSnapshotRef.current(next);
          setPollingIssue(null);
        })
        .catch((error: unknown) => {
          if (disposed) return;
          console.error("prototype plan polling reconciliation failed", planId, error);
          setPollingIssue("request_failed");
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
  }, [isActive, planId, projectId, recoveryKey]);

  return { connectionIssue, pollingIssue, usingPollingFallback };
}
