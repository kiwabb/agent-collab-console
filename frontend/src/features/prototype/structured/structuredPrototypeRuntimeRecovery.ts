import {
  StructuredPrototypeApiError,
  type StructuredPrototypeOperationOutcome,
} from "@/lib/api/prototypes";

import { StructuredPrototypeOperationOutcomeError } from "./structuredPrototypeOperationRecovery";
import type { StructuredPrototypePendingOperation } from "./structuredPrototypeStorage";
import type { StructuredPrototypeRuntimeSession } from "./types";

export const STRUCTURED_PROTOTYPE_RUNTIME_RESET_REQUIRED_CODES = [
  "runtime_session_corrupt",
  "runtime_replay_version_mismatch",
  "runtime_replay_contract_unsupported",
] as const;

export type StructuredPrototypeRuntimeRecoveryCode =
  (typeof STRUCTURED_PROTOTYPE_RUNTIME_RESET_REQUIRED_CODES)[number] | "runtime_reset_failed";

export interface StructuredPrototypeRuntimeRecoveryIssue {
  code: StructuredPrototypeRuntimeRecoveryCode;
  sessionId: string;
  operationId: string | null;
  correlationId: string | null;
  resetEvidence: StructuredPrototypeRuntimeResetEvidence | null;
}

export interface StructuredPrototypeRuntimeResetEvidence {
  sessionId: string;
  headSequenceNo: number;
  stateHash: string;
  viewModelHash: string;
  runtimeCoreBundleHash: string;
}

export function shouldRecreateMissingStoredRuntimeSession(
  error: unknown,
  context: {
    hasCommittedReset: boolean;
    hasResetOutcomeError: boolean;
  },
): boolean {
  return (
    !context.hasCommittedReset &&
    !context.hasResetOutcomeError &&
    error instanceof StructuredPrototypeApiError &&
    error.status === 404 &&
    error.code === "runtime_session_missing"
  );
}

export interface StructuredPrototypeRuntimeResetCommitEffects {
  writeReplacementPointer: (replacementSessionId: string) => void;
  clearPendingOperation: () => void;
}

export interface StructuredPrototypeCommittedRuntimeReset {
  replacedSessionId: string;
  replacementSessionId: string;
}

const RUNTIME_RESET_REQUIRED_CODE_SET: ReadonlySet<string> = new Set(
  STRUCTURED_PROTOTYPE_RUNTIME_RESET_REQUIRED_CODES,
);

export function commitSucceededStructuredPrototypeRuntimeResetOutcome(
  descriptor: StructuredPrototypePendingOperation,
  outcome: StructuredPrototypeOperationOutcome,
  effects: StructuredPrototypeRuntimeResetCommitEffects,
): StructuredPrototypeCommittedRuntimeReset {
  if (descriptor.operationKind !== "reset_runtime_session") {
    throw new Error("Only a pending runtime reset can commit a replacement session");
  }
  if (
    outcome.status !== "succeeded" ||
    outcome.resourceKind !== "runtime_session" ||
    outcome.resourceId === null ||
    outcome.resourceId === descriptor.resourceId
  ) {
    throw new Error("Succeeded runtime reset outcome has no replacement session");
  }
  const committedReset = {
    replacedSessionId: descriptor.resourceId,
    replacementSessionId: outcome.resourceId,
  };
  effects.writeReplacementPointer(committedReset.replacementSessionId);
  effects.clearPendingOperation();
  return committedReset;
}

export function structuredPrototypeRuntimeResetEvidenceFromSession(
  session: StructuredPrototypeRuntimeSession,
): StructuredPrototypeRuntimeResetEvidence {
  return {
    sessionId: session.sessionId,
    headSequenceNo: session.headSequenceNo,
    stateHash: session.stateHash,
    viewModelHash: session.viewModelHash,
    runtimeCoreBundleHash: session.runtimeCoreBundleHash,
  };
}

export function structuredPrototypeRuntimeResetEvidenceFromApiError(
  error: unknown,
  sessionId: string,
): StructuredPrototypeRuntimeResetEvidence | null {
  if (!(error instanceof StructuredPrototypeApiError)) return null;
  if (
    error.currentHeadSequenceNo === null ||
    error.currentStateHash === null ||
    error.currentViewModelHash === null ||
    error.currentRuntimeCoreBundleHash === null
  ) {
    return null;
  }
  return {
    sessionId,
    headSequenceNo: error.currentHeadSequenceNo,
    stateHash: error.currentStateHash,
    viewModelHash: error.currentViewModelHash,
    runtimeCoreBundleHash: error.currentRuntimeCoreBundleHash,
  };
}

export function structuredPrototypeRuntimeResetFailureIssue(
  error: unknown,
  resetEvidence: StructuredPrototypeRuntimeResetEvidence,
): StructuredPrototypeRuntimeRecoveryIssue {
  const operationId =
    error instanceof StructuredPrototypeApiError
      ? error.operationId
      : error instanceof StructuredPrototypeOperationOutcomeError
        ? error.outcome.operationId
        : null;
  const correlationId =
    error instanceof StructuredPrototypeApiError
      ? error.correlationId
      : error instanceof StructuredPrototypeOperationOutcomeError
        ? error.outcome.correlationId
        : null;
  return {
    code: "runtime_reset_failed",
    sessionId: resetEvidence.sessionId,
    operationId,
    correlationId,
    resetEvidence,
  };
}

function isStructuredPrototypeRuntimeRecoveryCode(
  code: string,
): code is StructuredPrototypeRuntimeRecoveryCode {
  return RUNTIME_RESET_REQUIRED_CODE_SET.has(code);
}

export function readStructuredPrototypeRuntimeRecoveryIssue(
  error: unknown,
  sessionId: string,
  lastSession: StructuredPrototypeRuntimeSession | null = null,
): StructuredPrototypeRuntimeRecoveryIssue | null {
  if (!(error instanceof StructuredPrototypeApiError)) return null;
  if (!isStructuredPrototypeRuntimeRecoveryCode(error.code)) return null;
  const responseEvidence = structuredPrototypeRuntimeResetEvidenceFromApiError(error, sessionId);
  const lastSnapshotEvidence =
    lastSession?.sessionId === sessionId
      ? structuredPrototypeRuntimeResetEvidenceFromSession(lastSession)
      : null;
  return {
    code: error.code,
    sessionId,
    operationId: error.operationId,
    correlationId: error.correlationId,
    resetEvidence: responseEvidence ?? lastSnapshotEvidence,
  };
}
