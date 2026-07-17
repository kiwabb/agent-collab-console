import {
  getCurrentStructuredPrototypeDraft,
  getCurrentStructuredPrototypeGenerationJob,
  getPrototypeAiEditRun,
  getPrototypeAiThread,
  getStructuredPrototypeGenerationJob,
} from "@/lib/api/prototypes";

import {
  StructuredPrototypeOperationOutcomeError,
  StructuredPrototypeOperationRecoveryPendingError,
  waitForStructuredPrototypeOperationOutcome,
} from "./structuredPrototypeOperationRecovery";
import {
  finishStructuredPrototypePendingOperation,
  type StructuredPrototypePendingOperation,
} from "./structuredPrototypeStorage";
import type {
  PrototypeAiThreadSnapshot,
  StructuredPrototypeDraft,
  StructuredPrototypeGenerationJob,
} from "./types";

export type ReconciledPrototypeAiOperation =
  | { kind: "message"; snapshot: PrototypeAiThreadSnapshot }
  | {
      kind: "apply";
      draft: StructuredPrototypeDraft;
      snapshot: PrototypeAiThreadSnapshot;
    }
  | { kind: "reject"; snapshot: PrototypeAiThreadSnapshot };

export type ReconciledPrototypeGenerationOperation =
  | { kind: "start" | "confirm"; job: StructuredPrototypeGenerationJob }
  | {
      kind: "accept";
      job: StructuredPrototypeGenerationJob;
      draft: StructuredPrototypeDraft;
    }
  | { kind: "delete" };

function mismatch(message: string): Error {
  return new Error(`Structured prototype asynchronous recovery mismatch: ${message}`);
}

async function readOperationOutcome(descriptor: StructuredPrototypePendingOperation) {
  return waitForStructuredPrototypeOperationOutcome(descriptor);
}

function finishFailedAsyncOutcome(
  descriptor: StructuredPrototypePendingOperation,
  outcome: Awaited<ReturnType<typeof readOperationOutcome>>,
): void {
  if (!outcome.terminal || outcome.status === "succeeded") return;
  finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
  throw new StructuredPrototypeOperationOutcomeError(outcome);
}

function retainPendingOnResourceFailure(
  descriptor: StructuredPrototypePendingOperation,
  error: unknown,
): never {
  if (
    error instanceof StructuredPrototypeOperationOutcomeError ||
    error instanceof StructuredPrototypeOperationRecoveryPendingError
  ) {
    throw error;
  }
  throw new StructuredPrototypeOperationRecoveryPendingError(descriptor, error);
}

export async function reconcilePendingPrototypeAiOperation(
  descriptor: StructuredPrototypePendingOperation,
): Promise<ReconciledPrototypeAiOperation> {
  try {
    switch (descriptor.operationKind) {
      case "ai_edit": {
        const outcome = await readOperationOutcome(descriptor);
        if (outcome.resourceKind !== "ai_edit_run" || outcome.resourceId === null) {
          throw mismatch("AI message outcome has no edit run");
        }
        const snapshot = await getPrototypeAiThread(descriptor.resourceId);
        if (snapshot.latestRun?.id !== outcome.resourceId) {
          throw mismatch("AI thread does not expose the submitted edit run");
        }
        finishFailedAsyncOutcome(descriptor, outcome);
        finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
        return { kind: "message", snapshot };
      }
      case "apply_command_batch": {
        const outcome = await readOperationOutcome(descriptor);
        if (
          descriptor.contextId === null ||
          outcome.resourceKind !== "draft" ||
          outcome.resourceId !== descriptor.resourceId
        ) {
          throw mismatch("AI apply outcome does not match its run and draft");
        }
        const draft = await getCurrentStructuredPrototypeDraft(
          descriptor.projectId,
          crypto.randomUUID(),
        );
        if (draft === null || draft.draftId !== descriptor.resourceId) {
          throw mismatch("AI applied draft is not the current project draft");
        }
        const run = await getPrototypeAiEditRun(descriptor.contextId);
        const snapshot = await getPrototypeAiThread(run.threadId);
        finishFailedAsyncOutcome(descriptor, outcome);
        if (run.status !== "applied") throw mismatch("AI edit run is not applied");
        finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
        return { kind: "apply", draft, snapshot };
      }
      case "reject_ai_proposal": {
        const outcome = await readOperationOutcome(descriptor);
        if (
          outcome.resourceKind !== "ai_edit_run" ||
          outcome.resourceId !== descriptor.resourceId
        ) {
          throw mismatch("AI reject outcome does not match its edit run");
        }
        const run = await getPrototypeAiEditRun(descriptor.resourceId);
        const snapshot = await getPrototypeAiThread(run.threadId);
        finishFailedAsyncOutcome(descriptor, outcome);
        if (run.status !== "rejected") throw mismatch("AI edit run is not rejected");
        finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
        return { kind: "reject", snapshot };
      }
      default:
        throw mismatch("pending operation does not belong to the AI controller");
    }
  } catch (error) {
    retainPendingOnResourceFailure(descriptor, error);
  }
}

export async function reconcilePendingPrototypeGenerationOperation(
  descriptor: StructuredPrototypePendingOperation,
): Promise<ReconciledPrototypeGenerationOperation> {
  try {
    switch (descriptor.operationKind) {
      case "generation_job": {
        const outcome = await readOperationOutcome(descriptor);
        if (outcome.resourceKind !== "generation_job" || outcome.resourceId === null) {
          throw mismatch("generation operation has no job resource");
        }
        const current = await getCurrentStructuredPrototypeGenerationJob(descriptor.projectId);
        if (current === null || current.id !== outcome.resourceId) {
          throw mismatch("generation job is not the current project job");
        }
        finishFailedAsyncOutcome(descriptor, outcome);
        const kind = descriptor.resourceKind === "project" ? "start" : "confirm";
        if (
          kind === "confirm" &&
          (current.status === "awaiting_confirmation" || current.canConfirm)
        ) {
          throw mismatch("generation blueprint confirmation is not reflected in the job");
        }
        finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
        return { kind, job: current };
      }
      case "create_document": {
        const outcome = await readOperationOutcome(descriptor);
        if (outcome.resourceKind !== "document" || outcome.resourceId === null) {
          throw mismatch("generation acceptance has no document result");
        }
        const job = await getStructuredPrototypeGenerationJob(descriptor.resourceId);
        const draft = await getCurrentStructuredPrototypeDraft(
          descriptor.projectId,
          crypto.randomUUID(),
        );
        finishFailedAsyncOutcome(descriptor, outcome);
        if (
          job.status !== "accepted" ||
          job.documentId !== outcome.resourceId ||
          draft === null ||
          draft.documentId !== outcome.resourceId
        ) {
          throw mismatch("accepted generation job, document, and current draft disagree");
        }
        finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
        return { kind: "accept", job, draft };
      }
      case "delete_project_prototype": {
        const outcome = await readOperationOutcome(descriptor);
        if (
          outcome.resourceKind !== "project_prototype" ||
          outcome.resourceId !== descriptor.projectId
        ) {
          throw mismatch("generation deletion outcome does not match its project");
        }
        const [draft, job] = await Promise.all([
          getCurrentStructuredPrototypeDraft(descriptor.projectId, crypto.randomUUID()),
          getCurrentStructuredPrototypeGenerationJob(descriptor.projectId),
        ]);
        finishFailedAsyncOutcome(descriptor, outcome);
        if (draft !== null || job !== null) {
          throw mismatch("project prototype or generation job still exists after deletion");
        }
        finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
        return { kind: "delete" };
      }
      default:
        throw mismatch("pending operation does not belong to the generation controller");
    }
  } catch (error) {
    retainPendingOnResourceFailure(descriptor, error);
  }
}
