export type Phase = "requirements" | "architecture" | "development" | "testing";
export type PhaseAction = "to_architecture" | "to_development" | "to_testing";

export interface PhaseSignals {
  currentPhase: Phase | null;
  hasActiveIssueTask: boolean;
  isPmTaskDone: boolean;
  hasArchitectureArtifacts: boolean;
  allEngineerTasksDone: boolean;
  isBusy: Record<PhaseAction, boolean>;
}

export function actionToPhase(action: PhaseAction): Phase {
  switch (action) {
    case "to_architecture": return "architecture";
    case "to_development": return "development";
    case "to_testing": return "testing";
  }
}

export function isVisible(action: PhaseAction, currentPhase: Phase | null): boolean {
  switch (action) {
    case "to_architecture":
      return currentPhase === "requirements";
    case "to_development":
      return currentPhase === "architecture" || currentPhase === "development";
    case "to_testing":
      return currentPhase === "development" || currentPhase === "testing";
  }
}

export function canTransition(action: PhaseAction, s: PhaseSignals): boolean {
  if (!isVisible(action, s.currentPhase)) return false;
  if (s.hasActiveIssueTask) return false;
  if (s.isBusy[action]) return false;
  switch (action) {
    case "to_architecture":
      return s.isPmTaskDone;
    case "to_development":
      return s.hasArchitectureArtifacts;
    case "to_testing":
      return s.allEngineerTasksDone;
  }
}
