"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getConductorState,
  getConductorStateLog,
  type ConductorStateLogEntry,
  type ConductorStatePayload,
} from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

export interface ConductorPhaseView {
  state: ConductorStatePayload | null;
  stateLog: ConductorStateLogEntry[];
  phase: string | null;
  detail: string | null;
  phaseStartedAt: string | null;
  phaseDurationMs: number | null;
  severity: "ok" | "warn" | "danger";
  refresh: () => Promise<void>;
}

const PHASE_THRESHOLDS: Record<string, { warn: number; danger: number }> = {
  awaiting_llm: { warn: 30_000, danger: 60_000 },
  awaiting_subagent: { warn: 180_000, danger: 360_000 },
  streaming_llm: { warn: 120_000, danger: Number.POSITIVE_INFINITY },
};

export function getPhaseSeverity(phase: string | null, durationMs: number | null): "ok" | "warn" | "danger" {
  if (!phase || durationMs == null) return "ok";
  const threshold = PHASE_THRESHOLDS[phase];
  if (!threshold) return "ok";
  if (durationMs >= threshold.danger) return "danger";
  if (durationMs >= threshold.warn) return "warn";
  return "ok";
}

export function useConductorPhase(issueId: string): ConductorPhaseView {
  const { addToast } = useToast();
  const { t } = useI18n();
  const [state, setState] = useState<ConductorStatePayload | null>(null);
  const [stateLog, setStateLog] = useState<ConductorStateLogEntry[]>([]);
  const [now, setNow] = useState(() => Date.now());

  const refresh = useCallback(async () => {
    const [nextState, nextLog] = await Promise.all([
      getConductorState(issueId).catch(() => null),
      getConductorStateLog(issueId, { limit: 80 }).catch(() => []),
    ]);
    setState(nextState);
    setStateLog(nextLog);
  }, [issueId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("conductor_status", "conductor_state_violation", "conductor_failed"),
    ),
    onEvent: (event) => {
      if (event.type === "conductor_state_violation") {
        const fromPhase = "from_phase" in event ? event.from_phase : null;
        const toPhase = "to_phase" in event && typeof event.to_phase === "string" ? event.to_phase : "unknown";
        addToast({
          type: "warning",
          title: t("conductor.toastStateViolation"),
          message: t("conductor.toastStateViolationMessage", {
            from: fromPhase ?? "unknown",
            to: toPhase,
          }),
        });
      }
      void refresh();
    },
    throttleMs: 500,
  });

  const latest = stateLog[0] ?? null;
  const phase = state?.phase ?? latest?.to_phase ?? null;
  const detail = state?.detail ?? latest?.to_detail ?? null;
  const phaseStartedAt = latest?.transition_at ?? state?.updated_at ?? null;
  const phaseDurationMs = useMemo(() => {
    if (!phaseStartedAt) return null;
    const started = new Date(phaseStartedAt).getTime();
    if (!Number.isFinite(started)) return null;
    return Math.max(0, now - started);
  }, [now, phaseStartedAt]);

  return {
    state,
    stateLog,
    phase,
    detail,
    phaseStartedAt,
    phaseDurationMs,
    severity: getPhaseSeverity(phase, phaseDurationMs),
    refresh,
  };
}
