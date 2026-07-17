import {
  getStructuredPrototypeOperationOutcome,
  isStructuredPrototypeOperationOutcomeUnknownError,
  StructuredPrototypeApiError,
  StructuredPrototypeRequestDeadlineError,
  type StructuredPrototypeOperationOutcome,
} from "@/lib/api/prototypes";

import type { StructuredPrototypePendingOperation } from "./structuredPrototypeStorage";

export const STRUCTURED_PROTOTYPE_OUTCOME_POLL_ATTEMPTS = 12;
export const STRUCTURED_PROTOTYPE_OUTCOME_POLL_INTERVAL_MS = 500;

export class StructuredPrototypeOperationRecoveryPendingError extends Error {
  readonly descriptor: StructuredPrototypePendingOperation;

  constructor(descriptor: StructuredPrototypePendingOperation, cause?: unknown) {
    super(
      `Structured prototype operation ${descriptor.operationKind} still has an unknown outcome`,
      cause === undefined ? undefined : { cause },
    );
    this.name = "StructuredPrototypeOperationRecoveryPendingError";
    this.descriptor = descriptor;
  }
}

export class StructuredPrototypeOperationOutcomeError extends Error {
  readonly outcome: StructuredPrototypeOperationOutcome;

  constructor(outcome: StructuredPrototypeOperationOutcome) {
    const code = outcome.errorCode ?? outcome.status;
    super(
      `Structured prototype operation ${outcome.operationKind} ended in ${outcome.status} (${code}; operation ${outcome.operationId}; correlation ${outcome.correlationId})`,
    );
    this.name = "StructuredPrototypeOperationOutcomeError";
    this.outcome = outcome;
  }
}

interface StructuredPrototypeOperationOutcomePollOptions {
  maxAttempts?: number;
  intervalMs?: number;
  readOutcome?: (
    descriptor: StructuredPrototypePendingOperation,
  ) => Promise<StructuredPrototypeOperationOutcome>;
  wait?: (milliseconds: number) => Promise<void>;
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

function isRetryableOutcomeReadError(error: unknown): boolean {
  return (
    isStructuredPrototypeOperationOutcomeUnknownError(error) ||
    error instanceof StructuredPrototypeRequestDeadlineError ||
    error instanceof TypeError ||
    (error instanceof StructuredPrototypeApiError && error.retryable)
  );
}

function assertOutcomeIdentity(
  descriptor: StructuredPrototypePendingOperation,
  outcome: StructuredPrototypeOperationOutcome,
): void {
  if (
    outcome.projectId !== descriptor.projectId ||
    outcome.operationKind !== descriptor.operationKind ||
    outcome.clientRequestId !== descriptor.clientRequestId
  ) {
    throw new Error("Structured prototype operation outcome identity does not match pending state");
  }
}

export async function waitForStructuredPrototypeOperationOutcome(
  descriptor: StructuredPrototypePendingOperation,
  options: StructuredPrototypeOperationOutcomePollOptions = {},
): Promise<StructuredPrototypeOperationOutcome> {
  const maxAttempts = options.maxAttempts ?? STRUCTURED_PROTOTYPE_OUTCOME_POLL_ATTEMPTS;
  const intervalMs = options.intervalMs ?? STRUCTURED_PROTOTYPE_OUTCOME_POLL_INTERVAL_MS;
  if (!Number.isSafeInteger(maxAttempts) || maxAttempts <= 0) {
    throw new RangeError("Structured prototype outcome poll attempts must be a positive integer");
  }
  if (!Number.isSafeInteger(intervalMs) || intervalMs < 0) {
    throw new RangeError(
      "Structured prototype outcome poll interval must be a non-negative integer",
    );
  }
  const readOutcome =
    options.readOutcome ??
    ((pending: StructuredPrototypePendingOperation) =>
      getStructuredPrototypeOperationOutcome(
        pending.projectId,
        pending.operationKind,
        pending.clientRequestId,
      ));
  const waitForNextAttempt = options.wait ?? wait;
  let lastRetryableError: unknown;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const outcome = await readOutcome(descriptor);
      assertOutcomeIdentity(descriptor, outcome);
      if (outcome.terminal) return outcome;
      lastRetryableError = undefined;
    } catch (error) {
      if (!isRetryableOutcomeReadError(error)) throw error;
      lastRetryableError = error;
    }
    if (attempt < maxAttempts) await waitForNextAttempt(intervalMs);
  }
  throw new StructuredPrototypeOperationRecoveryPendingError(descriptor, lastRetryableError);
}
