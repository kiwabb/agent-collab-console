"use client";

import { useCallback, useState } from "react";
import {
  getIssueGraph,
  planIssue,
  saveIssueGraph,
  startIssueGraph,
  getCodexIssueArtifacts,
} from "@/lib/api";
import type { Artifact, CodexIssue } from "@/lib/types";
import { useToast } from "@/components/ui/toast";
import {
  actionToPhase,
  canTransition,
  isVisible,
  type PhaseAction,
  type PhaseSignals,
} from "./PhaseStateMachine";

export interface UsePhaseTransitionsOptions {
  issue: CodexIssue | null;
  signals: Omit<PhaseSignals, "isBusy">;
  onPhaseChanged?: (issueId: string, newPhase: string) => void;
  onArtifactsRefreshed?: (artifacts: Artifact[]) => void;
  toastMessages?: Partial<Record<PhaseAction, { ok: string; err: string }>>;
}

const DEFAULT_TOASTS: Record<PhaseAction, { ok: string; err: string }> = {
  to_architecture: { ok: "Transitioned to Architecture", err: "Failed to transition" },
  to_development: { ok: "Transitioned to Development", err: "Failed to transition" },
  to_testing: { ok: "已流转到测试阶段", err: "流转失败" },
};

export function usePhaseTransitions(opts: UsePhaseTransitionsOptions) {
  const { issue, signals, onPhaseChanged, onArtifactsRefreshed, toastMessages } = opts;
  const { addToast } = useToast();
  const [busy, setBusy] = useState<Record<PhaseAction, boolean>>({
    to_architecture: false,
    to_development: false,
    to_testing: false,
  });

  const fullSignals: PhaseSignals = { ...signals, isBusy: busy };

  const run = useCallback(
    async (action: PhaseAction) => {
      if (!issue) return;
      if (!canTransition(action, fullSignals)) return;
      const phase = actionToPhase(action);
      const toasts = { ...DEFAULT_TOASTS[action], ...toastMessages?.[action] };
      setBusy((b) => ({ ...b, [action]: true }));
      try {
        let graph = await getIssueGraph(issue.id);
        if (graph === null) {
          const proposed = await planIssue(issue.id);
          graph = await saveIssueGraph(issue.id, proposed);
        }
        await startIssueGraph(issue.id);
        onPhaseChanged?.(issue.id, phase);
        const fresh = await getCodexIssueArtifacts(issue.id);
        onArtifactsRefreshed?.(fresh);
        addToast({ type: "success", title: toasts.ok });
      } catch (err) {
        const msg = err instanceof Error ? err.message : toasts.err;
        addToast({ type: "error", title: toasts.err, message: msg });
      } finally {
        setBusy((b) => ({ ...b, [action]: false }));
      }
    },
    [issue, fullSignals, addToast, onPhaseChanged, onArtifactsRefreshed, toastMessages]
  );

  return {
    busy,
    canTransition: (a: PhaseAction) => canTransition(a, fullSignals),
    isVisible: (a: PhaseAction) => isVisible(a, signals.currentPhase),
    run,
  };
}
