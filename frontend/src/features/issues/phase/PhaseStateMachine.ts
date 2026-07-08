import type { Phase } from "@/features/issues/phaseUtils";

export type PhaseTransitionAction = "to_architecture" | "to_development" | "to_testing";

export interface PhaseSignals {
  currentPhase: Phase;
  hasActiveIssueTask: boolean;
  isPmTaskDone: boolean;
  hasArchitectureArtifacts: boolean;
  allEngineerTasksDone: boolean;
  isBusy: Record<PhaseTransitionAction, boolean>;
}

const VISIBLE_FROM: Record<PhaseTransitionAction, readonly Phase[]> = {
  to_architecture: ["requirements"],
  to_development: ["architecture", "development"],
  to_testing: ["development", "testing"],
};

export function isVisible(action: PhaseTransitionAction, currentPhase: Phase): boolean {
  return VISIBLE_FROM[action].includes(currentPhase);
}

export function canTransition(action: PhaseTransitionAction, signals: PhaseSignals): boolean {
  if (signals.isBusy[action] || signals.hasActiveIssueTask) return false;
  if (!isVisible(action, signals.currentPhase)) return false;

  switch (action) {
    case "to_architecture":
      return signals.isPmTaskDone;
    case "to_development":
      return signals.hasArchitectureArtifacts;
    case "to_testing":
      return signals.allEngineerTasksDone;
  }
}
