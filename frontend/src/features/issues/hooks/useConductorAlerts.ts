"use client";

import { useCallback, useState } from "react";

import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

export type ConductorAlertSeverity = "danger" | "warn" | "info";

export interface ConductorAlert {
  id: string;
  type: string;
  severity: ConductorAlertSeverity;
  titleKey: string;
  params: Record<string, string | number>;
  createdAt: string;
}

/** Severity per backend reliability/observability event (Phases 1-3). */
const SEVERITY: Record<string, ConductorAlertSeverity> = {
  conductor_relaunch_exhausted: "danger",
  executor_failed_to_start: "danger",
  artifact_validation_failed: "warn",
  conductor_heartbeat_degraded: "warn",
  stall_detected: "warn",
  stall_nudge_failed: "warn",
};

const ALERT_TYPES = [...Object.keys(SEVERITY), "stall_recovered"];
const MAX_ALERTS = 6;

function str(v: unknown, fallback = ""): string {
  return typeof v === "string" && v.trim() ? v : fallback;
}

function num(v: unknown): number {
  return typeof v === "number" ? v : Number(v) || 0;
}

export function alertSeverityFor(type: string): ConductorAlertSeverity {
  return SEVERITY[type] ?? "info";
}

export function describeAlert(e: Record<string, unknown>): {
  titleKey: string;
  params: Record<string, string | number>;
} {
  switch (e["type"]) {
    case "conductor_relaunch_exhausted":
      return {
        titleKey: "issue.command.alert.relaunchExhausted",
        params: { attempts: num(e["relaunch_attempts"]) },
      };
    case "executor_failed_to_start":
      return {
        titleKey: "issue.command.alert.executorFailedToStart",
        params: { executor: str(e["executor"], "executor"), reason: str(e["reason"], "unknown") },
      };
    case "artifact_validation_failed":
      return {
        titleKey: "issue.command.alert.artifactInvalid",
        params: { role: str(e["role"], "subagent") },
      };
    case "conductor_heartbeat_degraded":
      return { titleKey: "issue.command.alert.heartbeatDegraded", params: {} };
    case "stall_detected":
      return {
        titleKey: "issue.command.alert.stallDetected",
        params: { role: str(e["role"], "subagent"), silence: Math.round(num(e["silence_s"])) },
      };
    case "stall_nudge_failed":
      return {
        titleKey: "issue.command.alert.stallNudgeFailed",
        params: { role: str(e["role"], "subagent") },
      };
    default:
      return { titleKey: "issue.command.alert.generic", params: {} };
  }
}

/**
 * Surfaces the backend hardening events (relaunch exhausted, executor-failed-to-start,
 * artifact validation failures, stalls, heartbeat degradation) as a rolling list of
 * dismissible alerts for the issue. `stall_recovered` resolves the matching stall alert.
 */
export function useConductorAlerts(issueId: string) {
  const [alerts, setAlerts] = useState<ConductorAlert[]>([]);

  const dismiss = useCallback((id: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const clear = useCallback(() => setAlerts([]), []);

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn(...ALERT_TYPES),
    ),
    onEvent: (event) => {
      const e = event as {
        type: string;
        role?: unknown;
        task_id?: unknown;
        message?: unknown;
        detail?: unknown;
        severity?: unknown;
      };
      const role = str(e.role);

      // A recovered stall resolves its detected-stall alert instead of stacking.
      if (e.type === "stall_recovered") {
        setAlerts((prev) =>
          prev.filter(
            (a) => !(a.type === "stall_detected" && (!role || a.params["role"] === role)),
          ),
        );
        return;
      }

      const { titleKey, params } = describeAlert(e);
      const alert: ConductorAlert = {
        id: `${e.type}:${Date.now()}:${Math.random().toString(36).slice(2, 7)}`,
        type: e.type,
        severity: SEVERITY[e.type] ?? "info",
        titleKey,
        params,
        createdAt: new Date().toISOString(),
      };
      setAlerts((prev) => [...prev, alert].slice(-MAX_ALERTS));
    },
  });

  return { alerts, dismiss, clear };
}
