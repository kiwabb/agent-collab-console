export type StructuredPrototypeFlowRuleMutationTarget =
  { kind: "ruleKey"; ruleKey: string } | { kind: "ruleId"; ruleId: string } | { kind: "clear" };

export interface StructuredPrototypeFlowRuleMutation {
  baseDocumentHash: string;
  target: StructuredPrototypeFlowRuleMutationTarget;
  failureMessage: string;
  requestSettled: boolean;
}

export type StructuredPrototypeFlowRuleMutationOutcome =
  | { kind: "pending" }
  | { kind: "persisted"; target: StructuredPrototypeFlowRuleMutationTarget }
  | { kind: "failed"; message: string };

export function resolveStructuredPrototypeFlowRuleMutationOutcome(
  mutation: StructuredPrototypeFlowRuleMutation,
  currentDocumentHash: string | null,
  saving: boolean,
): StructuredPrototypeFlowRuleMutationOutcome {
  if (currentDocumentHash !== null && currentDocumentHash !== mutation.baseDocumentHash) {
    return { kind: "persisted", target: mutation.target };
  }
  if (!mutation.requestSettled || saving) return { kind: "pending" };
  return { kind: "failed", message: mutation.failureMessage };
}
