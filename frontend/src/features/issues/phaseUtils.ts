import type { CodexIssue } from "@/lib/types";
import {
  PHASES,
  PHASE_CONFIG,
  groupIssuesByPhase as libGroupIssuesByPhase,
  type Phase as LibPhase,
} from "@/lib/task-selection";

export { PHASES, PHASE_CONFIG };
export type Phase = LibPhase;

export function groupIssuesByPhase(issues: CodexIssue[]): Record<Phase, CodexIssue[]> {
  return libGroupIssuesByPhase(issues);
}
