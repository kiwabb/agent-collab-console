"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  applyStructuredPrototypeCommands,
  applyStructuredPrototypeRuntimeEvents,
  checkpointStructuredPrototypeRuntimeSession,
  createStructuredPrototypeRuntimeSession,
  deleteProjectStructuredPrototype,
  getCurrentStructuredPrototypeDraft,
  getStructuredPrototypePublication,
  publishStructuredPrototypeDraft,
  redoStructuredPrototypeDraft,
  recoverStructuredPrototypeRuntimeSession,
  resetStructuredPrototypeRuntimeSession,
  type StructuredPrototypeOperationOutcome,
  undoStructuredPrototypeDraft,
} from "@/lib/api/prototypes";

import {
  parsePrototypeRuntimeStateJson,
  parseRuntimeViewModelJson,
  RuntimeStateCodecError,
} from "../runtime/runtimeStateCodec";
import type { PrototypeRuntimeState, RuntimeEvent, RuntimeViewModel } from "../runtime/types";
import { defaultRuntimeScenarioId } from "./structuredPrototypeDerived";
import {
  resolveStructuredPrototypeRecoveredOperationFailure,
  StructuredPrototypeOperationOutcomeError,
  StructuredPrototypeOperationRecoveryPendingError,
  waitForStructuredPrototypeOperationOutcome,
} from "./structuredPrototypeOperationRecovery";
import {
  beginStructuredPrototypePendingOperation,
  clearStructuredPrototypeProjectStorage,
  finishStructuredPrototypePendingOperation,
  isStructuredPrototypeStudioPendingOperation,
  loadStructuredPrototypePendingOperation,
  readStructuredPrototypePendingLockState,
  STRUCTURED_PROTOTYPE_DELETE_REQUEST_KEY,
  structuredPrototypeCommandRequestKey,
  structuredPrototypeHistoryRequestKey,
  structuredPrototypePublishRequestKey,
  structuredPrototypeRuntimeCheckpointRequestKey,
  structuredPrototypeRuntimeCreateRequestKey,
  structuredPrototypeRuntimeEventRequestKey,
  structuredPrototypeRuntimeResetRequestKey,
  structuredPrototypeStorageKey,
  StructuredPrototypeStorageError,
  type StructuredPrototypeHistoryOperation,
  type StructuredPrototypePendingOperation,
} from "./structuredPrototypeStorage";
import {
  commitSucceededStructuredPrototypeRuntimeResetOutcome,
  readStructuredPrototypeRuntimeRecoveryIssue,
  shouldRecreateMissingStoredRuntimeSession,
  structuredPrototypeRuntimeResetEvidenceFromApiError,
  structuredPrototypeRuntimeResetEvidenceFromSession,
  structuredPrototypeRuntimeResetFailureIssue,
  type StructuredPrototypeRuntimeRecoveryIssue,
  type StructuredPrototypeRuntimeResetEvidence,
} from "./structuredPrototypeRuntimeRecovery";
import type {
  AppliedStructuredPrototypeCommands,
  StructuredPrototypeCommandBatch,
  StructuredPrototypeDraft,
  StructuredPrototypePublication,
  StructuredPrototypeRuntimeSession,
} from "./types";

interface RuntimeSnapshot {
  session: StructuredPrototypeRuntimeSession;
  state: PrototypeRuntimeState;
  viewModel: RuntimeViewModel;
}

interface StudioState {
  draft: StructuredPrototypeDraft | null;
  runtime: RuntimeSnapshot | null;
  publication: StructuredPrototypePublication | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
  runtimeRecovery: StructuredPrototypeRuntimeRecoveryIssue | null;
}

export interface StructuredPrototypeCommandApplicationResult {
  draft: StructuredPrototypeDraft;
  allocatedEntityIds: AppliedStructuredPrototypeCommands["allocatedEntityIds"] | null;
  runtimeReady: boolean;
}

interface StructuredPrototypeStudioController extends StudioState {
  applyCommands: (batch: StructuredPrototypeCommandBatch) => Promise<boolean>;
  applyCommandsWithResult: (
    batch: StructuredPrototypeCommandBatch,
  ) => Promise<StructuredPrototypeCommandApplicationResult | null>;
  undo: () => Promise<boolean>;
  redo: () => Promise<boolean>;
  sendRuntimeEvents: (events: RuntimeEvent[]) => Promise<boolean>;
  checkpointRuntime: () => Promise<boolean>;
  publish: (summary?: string | null) => Promise<boolean>;
  deletePrototype: () => Promise<boolean>;
  adoptAiDraft: (draft: StructuredPrototypeDraft) => Promise<boolean>;
  resetRuntimePreview: () => Promise<boolean>;
  retry: () => Promise<void>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function decodeRuntime(session: StructuredPrototypeRuntimeSession): RuntimeSnapshot {
  const state = parsePrototypeRuntimeStateJson(session.stateJson);
  const viewModel = parseRuntimeViewModelJson(session.viewModelJson);
  if (
    state.sessionId !== session.sessionId ||
    state.sequenceNo !== session.headSequenceNo ||
    state.runtimeCoreVersion !== session.runtimeCoreVersion ||
    state.stateMachineKernelVersion !== session.stateMachineKernelVersion
  ) {
    throw new RuntimeStateCodecError("runtime response metadata does not match its state JSON");
  }
  return { session, state, viewModel };
}

function decodeDraftRuntime(
  session: StructuredPrototypeRuntimeSession,
  draft: StructuredPrototypeDraft,
): RuntimeSnapshot {
  if (
    session.documentId !== draft.documentId ||
    session.sourceKind !== "draft" ||
    session.sourceId !== draft.draftId ||
    session.pinnedDocumentObjectHash !== draft.documentHash
  ) {
    throw operationResourceMismatch("runtime session does not match its source draft head");
  }
  return decodeRuntime(session);
}

function decodeReplacementRuntime(
  session: StructuredPrototypeRuntimeSession,
  replacedSessionId: string,
  requireResetManifest: boolean,
): RuntimeSnapshot {
  if (
    session.replacesSessionId !== replacedSessionId ||
    (requireResetManifest && session.resetManifestHash === null)
  ) {
    throw operationResourceMismatch(
      "reset runtime does not replace the old session with required evidence",
    );
  }
  return decodeRuntime(session);
}

function decodeResetRuntime(
  session: StructuredPrototypeRuntimeSession,
  replacedSessionId: string,
  targetDraft: StructuredPrototypeDraft,
  requireResetManifest: boolean,
): RuntimeSnapshot {
  const runtime = decodeReplacementRuntime(session, replacedSessionId, requireResetManifest);
  if (
    session.documentId !== targetDraft.documentId ||
    session.sourceKind !== "draft" ||
    session.sourceId !== targetDraft.draftId ||
    session.pinnedDocumentObjectHash !== targetDraft.documentHash
  ) {
    throw operationResourceMismatch("reset runtime does not match its target draft head");
  }
  return runtime;
}

type ReconciledStudioOperation =
  | { kind: "draft"; draft: StructuredPrototypeDraft }
  | { kind: "runtime"; runtime: RuntimeSnapshot }
  | { kind: "runtimeCreate"; runtime: RuntimeSnapshot; clientRequestId: string }
  | {
      kind: "runtimeResetCommitted";
      replacedSessionId: string;
      replacementSessionId: string;
    }
  | {
      kind: "publication";
      draft: StructuredPrototypeDraft;
      publication: StructuredPrototypePublication;
    }
  | { kind: "deleted" };

type RuntimeResetResult =
  | { kind: "ready"; runtime: RuntimeSnapshot }
  | { kind: "recoveryRequired"; issue: StructuredPrototypeRuntimeRecoveryIssue };

function operationResourceMismatch(message: string): Error {
  return new Error(`Structured prototype operation recovery mismatch: ${message}`);
}

function finishFailedStudioOutcome(
  descriptor: StructuredPrototypePendingOperation,
  outcome: StructuredPrototypeOperationOutcome,
): never {
  finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
  throw new StructuredPrototypeOperationOutcomeError(outcome);
}

async function reconcilePendingStudioOperation(
  descriptor: StructuredPrototypePendingOperation,
): Promise<ReconciledStudioOperation> {
  const outcome = await waitForStructuredPrototypeOperationOutcome(descriptor);
  try {
    switch (descriptor.operationKind) {
      case "apply_command_batch":
      case "undo":
      case "redo": {
        if (outcome.resourceKind !== "draft" || outcome.resourceId !== descriptor.resourceId) {
          throw operationResourceMismatch("draft outcome does not match the pending draft");
        }
        const draft = await getCurrentStructuredPrototypeDraft(
          descriptor.projectId,
          crypto.randomUUID(),
        );
        if (draft === null || draft.draftId !== descriptor.resourceId) {
          throw operationResourceMismatch("current draft is not the completed mutation draft");
        }
        if (outcome.status !== "succeeded") finishFailedStudioOutcome(descriptor, outcome);
        finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
        return { kind: "draft", draft };
      }
      case "create_runtime_session": {
        if (outcome.resourceKind !== "runtime_session" || outcome.resourceId === null) {
          throw operationResourceMismatch("runtime creation has no runtime session result");
        }
        if (outcome.status !== "succeeded") {
          const draft = await getCurrentStructuredPrototypeDraft(
            descriptor.projectId,
            crypto.randomUUID(),
          );
          if (draft === null || draft.draftId !== descriptor.resourceId) {
            throw operationResourceMismatch("failed runtime creation draft is no longer current");
          }
          finishFailedStudioOutcome(descriptor, outcome);
        }
        const session = await recoverStructuredPrototypeRuntimeSession(
          outcome.resourceId,
          crypto.randomUUID(),
        );
        const draft = await getCurrentStructuredPrototypeDraft(
          descriptor.projectId,
          crypto.randomUUID(),
        );
        if (draft === null || draft.draftId !== descriptor.resourceId) {
          throw operationResourceMismatch("runtime creation draft is no longer current");
        }
        const runtime = decodeDraftRuntime(session, draft);
        return {
          kind: "runtimeCreate",
          runtime,
          clientRequestId: descriptor.clientRequestId,
        };
      }
      case "reset_runtime_session": {
        if (outcome.status !== "succeeded") finishFailedStudioOutcome(descriptor, outcome);
        const committedReset = commitSucceededStructuredPrototypeRuntimeResetOutcome(
          descriptor,
          outcome,
          {
            writeReplacementPointer: (sessionId) => {
              window.localStorage.setItem(
                structuredPrototypeStorageKey(descriptor.projectId, "runtime-session-id"),
                sessionId,
              );
            },
            clearPendingOperation: () => {
              finishStructuredPrototypePendingOperation(
                descriptor.projectId,
                descriptor.clientRequestId,
              );
            },
          },
        );
        return {
          kind: "runtimeResetCommitted",
          ...committedReset,
        };
      }
      case "apply_runtime_event":
      case "create_checkpoint": {
        if (
          outcome.resourceKind !== "runtime_session" ||
          outcome.resourceId !== descriptor.resourceId
        ) {
          throw operationResourceMismatch("runtime outcome does not match the pending session");
        }
        const session = await recoverStructuredPrototypeRuntimeSession(
          descriptor.resourceId,
          crypto.randomUUID(),
        );
        const runtime = decodeRuntime(session);
        if (outcome.status !== "succeeded") finishFailedStudioOutcome(descriptor, outcome);
        finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
        return { kind: "runtime", runtime };
      }
      case "publish": {
        if (outcome.resourceKind !== "draft" || outcome.resourceId !== descriptor.resourceId) {
          throw operationResourceMismatch("publication outcome does not match the pending draft");
        }
        const draft = await getCurrentStructuredPrototypeDraft(
          descriptor.projectId,
          crypto.randomUUID(),
        );
        if (draft === null || draft.draftId !== descriptor.resourceId) {
          throw operationResourceMismatch("published draft is no longer current");
        }
        const publication = await getStructuredPrototypePublication(draft.documentId);
        if (outcome.status !== "succeeded") finishFailedStudioOutcome(descriptor, outcome);
        if (publication === null || publication.documentId !== draft.documentId) {
          throw operationResourceMismatch("published pointer is not available");
        }
        finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
        return { kind: "publication", draft, publication };
      }
      case "delete_project_prototype": {
        if (
          outcome.resourceKind !== "project_prototype" ||
          outcome.resourceId !== descriptor.projectId
        ) {
          throw operationResourceMismatch("deletion outcome does not match the pending project");
        }
        const draft = await getCurrentStructuredPrototypeDraft(
          descriptor.projectId,
          crypto.randomUUID(),
        );
        if (outcome.status !== "succeeded") {
          if (draft === null) {
            throw operationResourceMismatch("failed deletion removed the current prototype");
          }
          finishFailedStudioOutcome(descriptor, outcome);
        }
        if (draft !== null) {
          throw operationResourceMismatch("project still has a current prototype draft");
        }
        finishStructuredPrototypePendingOperation(descriptor.projectId, descriptor.clientRequestId);
        return { kind: "deleted" };
      }
      default:
        throw operationResourceMismatch("pending operation belongs to another controller");
    }
  } catch (error) {
    if (
      error instanceof StructuredPrototypeOperationOutcomeError ||
      error instanceof StructuredPrototypeOperationRecoveryPendingError ||
      error instanceof StructuredPrototypeStorageError
    ) {
      throw error;
    }
    throw new StructuredPrototypeOperationRecoveryPendingError(descriptor, error);
  }
}

async function reconcileAfterRequestFailure(
  descriptor: StructuredPrototypePendingOperation,
): Promise<ReconciledStudioOperation> {
  return reconcilePendingStudioOperation(descriptor);
}

export function useStructuredPrototypeStudio(
  projectId: string,
): StructuredPrototypeStudioController {
  const [studio, setStudio] = useState<StudioState>({
    draft: null,
    runtime: null,
    publication: null,
    loading: true,
    saving: false,
    error: null,
    runtimeRecovery: null,
  });
  const mountedRef = useRef(true);
  const bootstrapInFlightRef = useRef<Promise<void> | null>(null);
  const studioRef = useRef(studio);
  studioRef.current = studio;

  const updateError = useCallback((context: string, error: unknown) => {
    console.error(`${context}:`, error);
    if (!mountedRef.current) return;
    setStudio((current) => ({ ...current, error: errorMessage(error) }));
  }, []);

  const reportMutationFailure = useCallback(
    (context: string, error: unknown): false => {
      const pending = readStructuredPrototypePendingLockState(
        projectId,
        isStructuredPrototypeStudioPendingOperation,
      );
      const reportedError = pending.storageError ?? error;
      updateError(context, reportedError);
      if (mountedRef.current) {
        setStudio((current) => ({
          ...current,
          loading: false,
          saving: pending.locked,
        }));
      }
      return false;
    },
    [projectId, updateError],
  );

  const createRuntime = useCallback(
    async (draft: StructuredPrototypeDraft): Promise<RuntimeSnapshot> => {
      const requestKey = structuredPrototypeRuntimeCreateRequestKey(
        draft.draftId,
        draft.headSequenceNo,
        draft.documentHash,
      );
      const descriptor = beginStructuredPrototypePendingOperation(projectId, {
        operationKind: "create_runtime_session",
        resourceKind: "draft",
        resourceId: draft.draftId,
        requestKey,
      });
      try {
        const session = await createStructuredPrototypeRuntimeSession(draft.draftId, {
          contractVersion: 1,
          clientRequestId: descriptor.clientRequestId,
          scenarioId: defaultRuntimeScenarioId(draft.document),
          recordingKind: "studio_preview",
          actorSubjectId: null,
        });
        const decoded = decodeDraftRuntime(session, draft);
        window.localStorage.setItem(
          structuredPrototypeStorageKey(projectId, "runtime-session-id"),
          session.sessionId,
        );
        finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
        return decoded;
      } catch (error) {
        const recovered = await reconcileAfterRequestFailure(descriptor);
        if (recovered.kind !== "runtimeCreate") {
          throw operationResourceMismatch("runtime creation recovered a non-runtime resource");
        }
        window.localStorage.setItem(
          structuredPrototypeStorageKey(projectId, "runtime-session-id"),
          recovered.runtime.session.sessionId,
        );
        finishStructuredPrototypePendingOperation(projectId, recovered.clientRequestId);
        return recovered.runtime;
      }
    },
    [projectId],
  );

  const resetRuntime = useCallback(
    async (
      evidence: StructuredPrototypeRuntimeResetEvidence,
      draft: StructuredPrototypeDraft,
      causeOperationId: string | null,
    ): Promise<RuntimeResetResult> => {
      const scenarioId = defaultRuntimeScenarioId(draft.document);
      const requestKey = structuredPrototypeRuntimeResetRequestKey(
        evidence.sessionId,
        evidence.headSequenceNo,
        evidence.stateHash,
        evidence.viewModelHash,
        evidence.runtimeCoreBundleHash,
        draft.draftId,
        draft.headSequenceNo,
        draft.documentHash,
        scenarioId,
        causeOperationId,
      );
      const descriptor = beginStructuredPrototypePendingOperation(projectId, {
        operationKind: "reset_runtime_session",
        resourceKind: "runtime_session",
        resourceId: evidence.sessionId,
        requestKey,
      });
      try {
        const session = await resetStructuredPrototypeRuntimeSession(evidence.sessionId, {
          contractVersion: 1,
          clientRequestId: descriptor.clientRequestId,
          causeOperationId,
          expectedOldHeadSequenceNo: evidence.headSequenceNo,
          expectedOldStateHash: evidence.stateHash,
          expectedOldViewModelHash: evidence.viewModelHash,
          expectedOldRuntimeCoreBundleHash: evidence.runtimeCoreBundleHash,
          targetDraftId: draft.draftId,
          expectedTargetHeadSequenceNo: draft.headSequenceNo,
          expectedTargetDocumentHash: draft.documentHash,
          scenarioId,
        });
        const runtime = decodeResetRuntime(session, evidence.sessionId, draft, true);
        window.localStorage.setItem(
          structuredPrototypeStorageKey(projectId, "runtime-session-id"),
          runtime.session.sessionId,
        );
        finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
        return { kind: "ready", runtime };
      } catch {
        const reconciled = await reconcileAfterRequestFailure(descriptor);
        if (reconciled.kind !== "runtimeResetCommitted") {
          throw operationResourceMismatch("runtime reset recovered a non-runtime resource");
        }
        try {
          const session = await recoverStructuredPrototypeRuntimeSession(
            reconciled.replacementSessionId,
            crypto.randomUUID(),
          );
          return {
            kind: "ready",
            runtime: decodeReplacementRuntime(session, evidence.sessionId, false),
          };
        } catch (recoveryError) {
          const issue = readStructuredPrototypeRuntimeRecoveryIssue(
            recoveryError,
            reconciled.replacementSessionId,
          );
          if (issue === null) throw recoveryError;
          return { kind: "recoveryRequired", issue };
        }
      }
    },
    [projectId],
  );

  const load = useCallback(async () => {
    if (bootstrapInFlightRef.current) return bootstrapInFlightRef.current;
    const inFlight = (async () => {
      if (mountedRef.current) {
        setStudio((current) => ({ ...current, loading: true, error: null }));
      }
      try {
        let pendingDraftChanged = false;
        let committedReset: Extract<
          ReconciledStudioOperation,
          { kind: "runtimeResetCommitted" }
        > | null = null;
        let resetOutcomeError: StructuredPrototypeOperationOutcomeError | null = null;
        const pendingOperation = loadStructuredPrototypePendingOperation(projectId);
        if (
          pendingOperation !== null &&
          isStructuredPrototypeStudioPendingOperation(pendingOperation)
        ) {
          if (mountedRef.current) {
            setStudio((current) => ({ ...current, saving: true }));
          }
          try {
            const reconciled = await reconcilePendingStudioOperation(pendingOperation);
            switch (reconciled.kind) {
              case "draft":
              case "publication":
                pendingDraftChanged = true;
                break;
              case "runtime":
                window.localStorage.setItem(
                  structuredPrototypeStorageKey(projectId, "runtime-session-id"),
                  reconciled.runtime.session.sessionId,
                );
                break;
              case "runtimeCreate":
                window.localStorage.setItem(
                  structuredPrototypeStorageKey(projectId, "runtime-session-id"),
                  reconciled.runtime.session.sessionId,
                );
                finishStructuredPrototypePendingOperation(projectId, reconciled.clientRequestId);
                break;
              case "runtimeResetCommitted":
                committedReset = reconciled;
                break;
              case "deleted":
                clearStructuredPrototypeProjectStorage(projectId);
                break;
            }
          } catch (error) {
            if (
              pendingOperation.operationKind !== "reset_runtime_session" ||
              !(error instanceof StructuredPrototypeOperationOutcomeError)
            ) {
              throw error;
            }
            resetOutcomeError = error;
          }
        }
        const draft = await getCurrentStructuredPrototypeDraft(projectId, crypto.randomUUID());
        if (!draft) {
          if (!mountedRef.current) return;
          setStudio({
            draft: null,
            runtime: null,
            publication: null,
            loading: false,
            saving: false,
            error: null,
            runtimeRecovery: null,
          });
          return;
        }

        const publication = await getStructuredPrototypePublication(draft.documentId);
        if (mountedRef.current) {
          setStudio((current) => ({
            ...current,
            draft,
            publication,
          }));
        }
        const storedSessionId = window.localStorage.getItem(
          structuredPrototypeStorageKey(projectId, "runtime-session-id"),
        );
        let runtime: RuntimeSnapshot;
        if (storedSessionId) {
          try {
            const recovered = await recoverStructuredPrototypeRuntimeSession(
              storedSessionId,
              crypto.randomUUID(),
            );
            const recoveredRuntime =
              committedReset?.replacementSessionId === storedSessionId
                ? decodeReplacementRuntime(recovered, committedReset.replacedSessionId, false)
                : decodeRuntime(recovered);
            if (resetOutcomeError !== null) {
              if (!mountedRef.current) return;
              const resetEvidence = structuredPrototypeRuntimeResetEvidenceFromSession(recovered);
              setStudio((current) => ({
                ...current,
                draft,
                runtime: recoveredRuntime,
                publication,
                loading: false,
                saving: false,
                error: errorMessage(resetOutcomeError),
                runtimeRecovery: structuredPrototypeRuntimeResetFailureIssue(
                  resetOutcomeError,
                  resetEvidence,
                ),
              }));
              return;
            }
            if (
              pendingDraftChanged ||
              recovered.documentId !== draft.documentId ||
              recovered.sourceKind !== "draft" ||
              recovered.sourceId !== draft.draftId ||
              recovered.pinnedDocumentObjectHash !== draft.documentHash
            ) {
              const resetEvidence = structuredPrototypeRuntimeResetEvidenceFromSession(recovered);
              try {
                const reset = await resetRuntime(resetEvidence, draft, null);
                if (reset.kind === "recoveryRequired") {
                  if (!mountedRef.current) return;
                  setStudio((current) => ({
                    ...current,
                    draft,
                    runtime: recoveredRuntime,
                    publication,
                    loading: false,
                    saving: false,
                    error: null,
                    runtimeRecovery: reset.issue,
                  }));
                  return;
                }
                runtime = reset.runtime;
              } catch (error) {
                if (!mountedRef.current) return;
                const pending = readStructuredPrototypePendingLockState(
                  projectId,
                  isStructuredPrototypeStudioPendingOperation,
                );
                const reportedError = pending.storageError ?? error;
                const latestResetEvidence =
                  structuredPrototypeRuntimeResetEvidenceFromApiError(
                    error,
                    resetEvidence.sessionId,
                  ) ?? resetEvidence;
                console.error("structured prototype bootstrap runtime reset failed:", error);
                setStudio((current) => ({
                  ...current,
                  draft,
                  runtime: recoveredRuntime,
                  publication,
                  loading: false,
                  saving: pending.locked,
                  error: errorMessage(reportedError),
                  runtimeRecovery: structuredPrototypeRuntimeResetFailureIssue(
                    error,
                    latestResetEvidence,
                  ),
                }));
                return;
              }
            } else {
              runtime = recoveredRuntime;
            }
          } catch (error) {
            if (
              !shouldRecreateMissingStoredRuntimeSession(error, {
                hasCommittedReset: committedReset !== null,
                hasResetOutcomeError: resetOutcomeError !== null,
              })
            ) {
              const issue = readStructuredPrototypeRuntimeRecoveryIssue(
                error,
                storedSessionId,
                studioRef.current.runtime?.session ?? null,
              );
              const responseResetEvidence = structuredPrototypeRuntimeResetEvidenceFromApiError(
                error,
                storedSessionId,
              );
              let runtimeRecovery: StructuredPrototypeRuntimeRecoveryIssue;
              if (issue === null) {
                if (resetOutcomeError === null || responseResetEvidence === null) throw error;
                runtimeRecovery = structuredPrototypeRuntimeResetFailureIssue(
                  resetOutcomeError,
                  responseResetEvidence,
                );
              } else if (resetOutcomeError !== null && issue.resetEvidence !== null) {
                runtimeRecovery = structuredPrototypeRuntimeResetFailureIssue(
                  resetOutcomeError,
                  issue.resetEvidence,
                );
              } else {
                runtimeRecovery = issue;
              }
              if (!mountedRef.current) return;
              setStudio((current) => ({
                ...current,
                draft,
                publication,
                loading: false,
                saving: false,
                error: resetOutcomeError === null ? null : errorMessage(resetOutcomeError),
                runtimeRecovery,
              }));
              return;
            }
            runtime = await createRuntime(draft);
          }
        } else {
          if (resetOutcomeError !== null && pendingOperation !== null) {
            if (!mountedRef.current) return;
            setStudio((current) => ({
              ...current,
              draft,
              publication,
              loading: false,
              saving: false,
              error: errorMessage(resetOutcomeError),
              runtimeRecovery: {
                code: "runtime_reset_failed",
                sessionId: pendingOperation.resourceId,
                operationId: resetOutcomeError.outcome.operationId,
                correlationId: resetOutcomeError.outcome.correlationId,
                resetEvidence: null,
              },
            }));
            return;
          }
          runtime = await createRuntime(draft);
        }
        if (!mountedRef.current) return;
        setStudio({
          draft,
          runtime,
          publication,
          loading: false,
          saving: false,
          error: null,
          runtimeRecovery: null,
        });
      } catch (error) {
        reportMutationFailure("structured prototype studio recovery failed", error);
      }
    })().finally(() => {
      bootstrapInFlightRef.current = null;
    });
    bootstrapInFlightRef.current = inFlight;
    return inFlight;
  }, [createRuntime, projectId, reportMutationFailure, resetRuntime]);

  useEffect(() => {
    mountedRef.current = true;
    void load();
    return () => {
      mountedRef.current = false;
    };
  }, [load]);

  const stageDraftAndRebuildRuntime = useCallback(
    async (
      draft: StructuredPrototypeDraft,
      publication?: StructuredPrototypePublication,
    ): Promise<boolean> => {
      const previousRuntime = studioRef.current.runtime;
      if (mountedRef.current) {
        setStudio((current) => ({
          draft,
          runtime: current.runtime,
          publication: publication ?? current.publication,
          loading: false,
          saving: true,
          error: null,
          runtimeRecovery: current.runtimeRecovery,
        }));
      }
      const resetEvidence =
        previousRuntime === null
          ? null
          : structuredPrototypeRuntimeResetEvidenceFromSession(previousRuntime.session);
      let runtime: RuntimeSnapshot;
      try {
        if (resetEvidence === null) {
          runtime = await createRuntime(draft);
        } else {
          const reset = await resetRuntime(resetEvidence, draft, null);
          if (reset.kind === "recoveryRequired") {
            if (!mountedRef.current) return false;
            setStudio((current) => ({
              ...current,
              draft,
              runtime: previousRuntime,
              publication: publication ?? current.publication,
              loading: false,
              saving: false,
              error: null,
              runtimeRecovery: reset.issue,
            }));
            return false;
          }
          runtime = reset.runtime;
        }
      } catch (error) {
        if (resetEvidence !== null && mountedRef.current) {
          const latestResetEvidence =
            structuredPrototypeRuntimeResetEvidenceFromApiError(error, resetEvidence.sessionId) ??
            resetEvidence;
          setStudio((current) => ({
            ...current,
            draft,
            runtime: previousRuntime,
            publication: publication ?? current.publication,
            runtimeRecovery: structuredPrototypeRuntimeResetFailureIssue(
              error,
              latestResetEvidence,
            ),
          }));
        }
        throw error;
      }
      if (!mountedRef.current) return false;
      setStudio((current) => ({
        draft,
        runtime,
        publication: publication ?? current.publication,
        loading: false,
        saving: false,
        error: null,
        runtimeRecovery: null,
      }));
      return true;
    },
    [createRuntime, resetRuntime],
  );

  const applyReconciledOperation = useCallback(
    async (reconciled: ReconciledStudioOperation): Promise<boolean> => {
      switch (reconciled.kind) {
        case "draft":
          return stageDraftAndRebuildRuntime(reconciled.draft);
        case "runtime":
          window.localStorage.setItem(
            structuredPrototypeStorageKey(projectId, "runtime-session-id"),
            reconciled.runtime.session.sessionId,
          );
          if (!mountedRef.current) return false;
          setStudio((current) => ({
            ...current,
            runtime: reconciled.runtime,
            loading: false,
            saving: false,
            error: null,
            runtimeRecovery: null,
          }));
          return true;
        case "runtimeCreate":
          window.localStorage.setItem(
            structuredPrototypeStorageKey(projectId, "runtime-session-id"),
            reconciled.runtime.session.sessionId,
          );
          finishStructuredPrototypePendingOperation(projectId, reconciled.clientRequestId);
          if (!mountedRef.current) return false;
          setStudio((current) => ({
            ...current,
            runtime: reconciled.runtime,
            loading: false,
            saving: false,
            error: null,
            runtimeRecovery: null,
          }));
          return true;
        case "runtimeResetCommitted":
          throw operationResourceMismatch(
            "committed runtime reset must continue through replacement recovery",
          );
        case "publication":
          return stageDraftAndRebuildRuntime(reconciled.draft, reconciled.publication);
        case "deleted":
          clearStructuredPrototypeProjectStorage(projectId);
          if (!mountedRef.current) return false;
          setStudio({
            draft: null,
            runtime: null,
            publication: null,
            loading: false,
            saving: false,
            error: null,
            runtimeRecovery: null,
          });
          return true;
      }
    },
    [projectId, stageDraftAndRebuildRuntime],
  );

  const applyCommandsWithResult = useCallback(
    async (
      batch: StructuredPrototypeCommandBatch,
    ): Promise<StructuredPrototypeCommandApplicationResult | null> => {
      const currentDraft = studio.draft;
      if (!currentDraft || studio.saving || studio.runtimeRecovery !== null) return null;
      setStudio((current) => ({ ...current, saving: true, error: null }));
      const requestKey = structuredPrototypeCommandRequestKey(
        currentDraft.draftId,
        currentDraft.headSequenceNo,
        currentDraft.documentHash,
      );
      let descriptor: StructuredPrototypePendingOperation;
      try {
        descriptor = beginStructuredPrototypePendingOperation(projectId, {
          operationKind: "apply_command_batch",
          resourceKind: "draft",
          resourceId: currentDraft.draftId,
          requestKey,
        });
      } catch (error) {
        reportMutationFailure("structured prototype command persistence failed", error);
        return null;
      }
      let applied: AppliedStructuredPrototypeCommands;
      try {
        applied = await applyStructuredPrototypeCommands(currentDraft.draftId, {
          contractVersion: 1,
          clientRequestId: descriptor.clientRequestId,
          expectedHeadSequenceNo: currentDraft.headSequenceNo,
          expectedDocumentHash: currentDraft.documentHash,
          batch,
        });
        finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
      } catch (error) {
        let reconciled: ReconciledStudioOperation;
        try {
          reconciled = await reconcileAfterRequestFailure(descriptor);
        } catch (recoveryError) {
          reportMutationFailure(
            "structured prototype command recovery failed",
            resolveStructuredPrototypeRecoveredOperationFailure(error, recoveryError),
          );
          return null;
        }
        if (reconciled.kind !== "draft") {
          reportMutationFailure(
            "structured prototype command recovery failed",
            operationResourceMismatch("command recovery did not return a draft"),
          );
          return null;
        }
        try {
          const runtimeReady = await applyReconciledOperation(reconciled);
          return { draft: reconciled.draft, allocatedEntityIds: null, runtimeReady };
        } catch (rebuildError) {
          reportMutationFailure(
            "structured prototype command runtime rebuild failed",
            rebuildError,
          );
          return {
            draft: reconciled.draft,
            allocatedEntityIds: null,
            runtimeReady: false,
          };
        }
      }
      try {
        const runtimeReady = await stageDraftAndRebuildRuntime(applied);
        return {
          draft: applied,
          allocatedEntityIds: applied.allocatedEntityIds,
          runtimeReady,
        };
      } catch (rebuildError) {
        reportMutationFailure("structured prototype command runtime rebuild failed", rebuildError);
        return {
          draft: applied,
          allocatedEntityIds: applied.allocatedEntityIds,
          runtimeReady: false,
        };
      }
    },
    [
      applyReconciledOperation,
      projectId,
      reportMutationFailure,
      stageDraftAndRebuildRuntime,
      studio.draft,
      studio.runtimeRecovery,
      studio.saving,
    ],
  );

  const applyCommands = useCallback(
    async (batch: StructuredPrototypeCommandBatch): Promise<boolean> =>
      (await applyCommandsWithResult(batch))?.runtimeReady === true,
    [applyCommandsWithResult],
  );

  const mutateHistory = useCallback(
    async (operation: StructuredPrototypeHistoryOperation): Promise<boolean> => {
      const currentDraft = studio.draft;
      if (!currentDraft || studio.saving || studio.runtimeRecovery !== null) return false;
      if (operation === "undo" ? !currentDraft.canUndo : !currentDraft.canRedo) return false;
      setStudio((current) => ({ ...current, saving: true, error: null }));
      const requestKey = structuredPrototypeHistoryRequestKey(
        operation,
        currentDraft.draftId,
        currentDraft.headSequenceNo,
        currentDraft.documentHash,
      );
      let descriptor: StructuredPrototypePendingOperation;
      try {
        descriptor = beginStructuredPrototypePendingOperation(projectId, {
          operationKind: operation,
          resourceKind: "draft",
          resourceId: currentDraft.draftId,
          requestKey,
        });
      } catch (error) {
        return reportMutationFailure(`structured prototype ${operation} persistence failed`, error);
      }
      const request = {
        contractVersion: 1 as const,
        clientRequestId: descriptor.clientRequestId,
        expectedHeadSequenceNo: currentDraft.headSequenceNo,
        expectedDocumentHash: currentDraft.documentHash,
      };
      let applied: StructuredPrototypeDraft;
      try {
        applied =
          operation === "undo"
            ? await undoStructuredPrototypeDraft(currentDraft.draftId, request)
            : await redoStructuredPrototypeDraft(currentDraft.draftId, request);
        finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
      } catch (error) {
        let reconciled: ReconciledStudioOperation;
        try {
          reconciled = await reconcileAfterRequestFailure(descriptor);
        } catch (recoveryError) {
          return reportMutationFailure(
            `structured prototype ${operation} recovery failed`,
            recoveryError,
          );
        }
        try {
          return await applyReconciledOperation(reconciled);
        } catch (rebuildError) {
          return reportMutationFailure(
            `structured prototype ${operation} runtime rebuild failed`,
            rebuildError,
          );
        }
      }
      try {
        return await stageDraftAndRebuildRuntime(applied);
      } catch (rebuildError) {
        return reportMutationFailure(
          `structured prototype ${operation} runtime rebuild failed`,
          rebuildError,
        );
      }
    },
    [
      applyReconciledOperation,
      projectId,
      reportMutationFailure,
      stageDraftAndRebuildRuntime,
      studio.draft,
      studio.runtimeRecovery,
      studio.saving,
    ],
  );

  const undo = useCallback(() => mutateHistory("undo"), [mutateHistory]);
  const redo = useCallback(() => mutateHistory("redo"), [mutateHistory]);

  const sendRuntimeEvents = useCallback(
    async (events: RuntimeEvent[]): Promise<boolean> => {
      const current = studio.runtime;
      if (!current || studio.saving || studio.runtimeRecovery !== null || events.length === 0)
        return false;
      setStudio((value) => ({ ...value, saving: true, error: null }));
      const requestKey = structuredPrototypeRuntimeEventRequestKey(
        current.session.sessionId,
        current.session.headSequenceNo,
        current.session.stateHash,
      );
      let descriptor: StructuredPrototypePendingOperation;
      try {
        descriptor = beginStructuredPrototypePendingOperation(projectId, {
          operationKind: "apply_runtime_event",
          resourceKind: "runtime_session",
          resourceId: current.session.sessionId,
          requestKey,
        });
      } catch (error) {
        return reportMutationFailure(
          "structured prototype runtime event persistence failed",
          error,
        );
      }
      try {
        const applied = await applyStructuredPrototypeRuntimeEvents(current.session.sessionId, {
          contractVersion: 1,
          clientRequestId: descriptor.clientRequestId,
          expectedHeadSequenceNo: current.session.headSequenceNo,
          expectedStateHash: current.session.stateHash,
          batch: {
            clientEventId: descriptor.clientRequestId,
            expectedSequenceNo: current.session.headSequenceNo,
            events,
          },
        });
        const runtime = decodeRuntime(applied);
        finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
        if (!mountedRef.current) return false;
        setStudio((value) => ({ ...value, runtime, saving: false, error: null }));
        return true;
      } catch (error) {
        let reconciled: ReconciledStudioOperation;
        try {
          reconciled = await reconcileAfterRequestFailure(descriptor);
        } catch (recoveryError) {
          return reportMutationFailure(
            "structured prototype runtime event recovery failed",
            recoveryError,
          );
        }
        if (reconciled.kind !== "runtime") {
          return reportMutationFailure(
            "structured prototype runtime event recovery failed",
            operationResourceMismatch("runtime event recovered a non-runtime resource"),
          );
        }
        return applyReconciledOperation(reconciled);
      }
    },
    [
      applyReconciledOperation,
      projectId,
      reportMutationFailure,
      studio.runtime,
      studio.runtimeRecovery,
      studio.saving,
    ],
  );

  const checkpointRuntime = useCallback(async (): Promise<boolean> => {
    const current = studio.runtime;
    if (!current || studio.saving || studio.runtimeRecovery !== null) return false;
    setStudio((value) => ({ ...value, saving: true, error: null }));
    const requestKey = structuredPrototypeRuntimeCheckpointRequestKey(
      current.session.sessionId,
      current.session.headSequenceNo,
      current.session.stateHash,
    );
    let descriptor: StructuredPrototypePendingOperation;
    try {
      descriptor = beginStructuredPrototypePendingOperation(projectId, {
        operationKind: "create_checkpoint",
        resourceKind: "runtime_session",
        resourceId: current.session.sessionId,
        requestKey,
      });
    } catch (error) {
      return reportMutationFailure(
        "structured prototype runtime checkpoint persistence failed",
        error,
      );
    }
    try {
      const checkpointed = await checkpointStructuredPrototypeRuntimeSession(
        current.session.sessionId,
        { contractVersion: 1, clientRequestId: descriptor.clientRequestId },
      );
      const runtime = decodeRuntime(checkpointed);
      finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
      if (!mountedRef.current) return false;
      setStudio((value) => ({ ...value, runtime, saving: false, error: null }));
      return true;
    } catch (error) {
      let reconciled: ReconciledStudioOperation;
      try {
        reconciled = await reconcileAfterRequestFailure(descriptor);
      } catch (recoveryError) {
        return reportMutationFailure(
          "structured prototype runtime checkpoint recovery failed",
          recoveryError,
        );
      }
      if (reconciled.kind !== "runtime") {
        return reportMutationFailure(
          "structured prototype runtime checkpoint recovery failed",
          operationResourceMismatch("runtime checkpoint recovered a non-runtime resource"),
        );
      }
      return applyReconciledOperation(reconciled);
    }
  }, [
    applyReconciledOperation,
    projectId,
    reportMutationFailure,
    studio.runtime,
    studio.runtimeRecovery,
    studio.saving,
  ]);

  const publish = useCallback(async (summary?: string | null): Promise<boolean> => {
    const currentDraft = studio.draft;
    if (!currentDraft || studio.saving || studio.runtimeRecovery !== null) return false;
    const releaseNote = summary?.trim().slice(0, 200) || null;
    setStudio((current) => ({ ...current, saving: true, error: null }));
    const requestKey = structuredPrototypePublishRequestKey(
      currentDraft.draftId,
      currentDraft.headSequenceNo,
      currentDraft.documentHash,
    );
    let descriptor: StructuredPrototypePendingOperation;
    try {
      descriptor = beginStructuredPrototypePendingOperation(projectId, {
        operationKind: "publish",
        resourceKind: "draft",
        resourceId: currentDraft.draftId,
        requestKey,
      });
    } catch (error) {
      return reportMutationFailure("structured prototype publication persistence failed", error);
    }
    let activeDraft: StructuredPrototypeDraft;
    let publication: StructuredPrototypePublication;
    try {
      const published = await publishStructuredPrototypeDraft(currentDraft.draftId, {
        contractVersion: 1,
        clientRequestId: descriptor.clientRequestId,
        expectedHeadSequenceNo: currentDraft.headSequenceNo,
        expectedDocumentHash: currentDraft.documentHash,
        summary: releaseNote,
      });
      activeDraft = published.activeDraft;
      publication = published;
      finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
    } catch (error) {
      let reconciled: ReconciledStudioOperation;
      try {
        reconciled = await reconcileAfterRequestFailure(descriptor);
      } catch (recoveryError) {
        return reportMutationFailure(
          "structured prototype publication recovery failed",
          recoveryError,
        );
      }
      if (reconciled.kind !== "publication") {
        return reportMutationFailure(
          "structured prototype publication recovery failed",
          operationResourceMismatch("publication recovered a non-publication resource"),
        );
      }
      return applyReconciledOperation(reconciled);
    }
    try {
      return await stageDraftAndRebuildRuntime(activeDraft, publication);
    } catch (rebuildError) {
      return reportMutationFailure(
        "structured prototype publication runtime rebuild failed",
        rebuildError,
      );
    }
  }, [
    applyReconciledOperation,
    projectId,
    reportMutationFailure,
    stageDraftAndRebuildRuntime,
    studio.draft,
    studio.runtimeRecovery,
    studio.saving,
  ]);

  const deletePrototype = useCallback(async (): Promise<boolean> => {
    if (studio.saving) return false;
    setStudio((current) => ({ ...current, saving: true, error: null }));
    let descriptor: StructuredPrototypePendingOperation;
    try {
      descriptor = beginStructuredPrototypePendingOperation(projectId, {
        operationKind: "delete_project_prototype",
        resourceKind: "project_prototype",
        resourceId: projectId,
        requestKey: STRUCTURED_PROTOTYPE_DELETE_REQUEST_KEY,
      });
    } catch (error) {
      return reportMutationFailure("structured prototype deletion persistence failed", error);
    }
    try {
      await deleteProjectStructuredPrototype(projectId, descriptor.clientRequestId);
      finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
    } catch (error) {
      let reconciled: ReconciledStudioOperation;
      try {
        reconciled = await reconcileAfterRequestFailure(descriptor);
      } catch (recoveryError) {
        return reportMutationFailure(
          "structured prototype deletion recovery failed",
          recoveryError,
        );
      }
      if (reconciled.kind !== "deleted") {
        return reportMutationFailure(
          "structured prototype deletion recovery failed",
          operationResourceMismatch("deletion recovered a non-deletion resource"),
        );
      }
    }
    return applyReconciledOperation({ kind: "deleted" });
  }, [applyReconciledOperation, projectId, reportMutationFailure, studio.saving]);

  const resetRuntimePreview = useCallback(async (): Promise<boolean> => {
    const current = studioRef.current;
    const issue = current.runtimeRecovery;
    if (
      current.draft === null ||
      current.saving ||
      issue === null ||
      issue.resetEvidence === null
    ) {
      return false;
    }
    setStudio((value) => ({ ...value, saving: true, error: null }));
    let resetEvidence = issue.resetEvidence;
    let causeOperationId = issue.operationId;
    if (issue.code === "runtime_reset_failed") {
      try {
        const latestSession = await recoverStructuredPrototypeRuntimeSession(
          issue.sessionId,
          crypto.randomUUID(),
        );
        resetEvidence = structuredPrototypeRuntimeResetEvidenceFromSession(latestSession);
      } catch (error) {
        const latestIssue = readStructuredPrototypeRuntimeRecoveryIssue(error, issue.sessionId);
        if (latestIssue !== null && latestIssue.resetEvidence !== null) {
          resetEvidence = latestIssue.resetEvidence;
          causeOperationId = latestIssue.operationId;
        } else {
          const latestResetEvidence =
            structuredPrototypeRuntimeResetEvidenceFromApiError(error, issue.sessionId) ??
            resetEvidence;
          if (!mountedRef.current) return false;
          console.error("structured prototype runtime reset evidence refresh failed:", error);
          setStudio((value) => ({
            ...value,
            loading: false,
            saving: false,
            error: errorMessage(error),
            runtimeRecovery: structuredPrototypeRuntimeResetFailureIssue(
              error,
              latestResetEvidence,
            ),
          }));
          return false;
        }
      }
    }
    try {
      const reset = await resetRuntime(resetEvidence, current.draft, causeOperationId);
      if (reset.kind === "recoveryRequired") {
        if (!mountedRef.current) return false;
        setStudio((value) => ({
          ...value,
          loading: false,
          saving: false,
          error: null,
          runtimeRecovery: reset.issue,
        }));
        return false;
      }
      if (!mountedRef.current) return false;
      setStudio((value) => ({
        ...value,
        runtime: reset.runtime,
        loading: false,
        saving: false,
        error: null,
        runtimeRecovery: null,
      }));
      return true;
    } catch (error) {
      const latestResetEvidence =
        structuredPrototypeRuntimeResetEvidenceFromApiError(error, issue.sessionId) ??
        resetEvidence;
      if (mountedRef.current) {
        setStudio((value) => ({
          ...value,
          runtimeRecovery: structuredPrototypeRuntimeResetFailureIssue(error, latestResetEvidence),
        }));
      }
      return reportMutationFailure("structured prototype runtime reset failed", error);
    }
  }, [reportMutationFailure, resetRuntime]);

  const adoptAiDraft = useCallback(
    async (draft: StructuredPrototypeDraft): Promise<boolean> => {
      if (studioRef.current.runtimeRecovery !== null) return false;
      try {
        return await stageDraftAndRebuildRuntime(draft);
      } catch (error) {
        if (mountedRef.current) setStudio((current) => ({ ...current, draft }));
        return reportMutationFailure("structured prototype AI draft runtime rebuild failed", error);
      }
    },
    [reportMutationFailure, stageDraftAndRebuildRuntime],
  );

  return {
    ...studio,
    applyCommands,
    applyCommandsWithResult,
    undo,
    redo,
    sendRuntimeEvents,
    checkpointRuntime,
    publish,
    deletePrototype,
    adoptAiDraft,
    resetRuntimePreview,
    retry: load,
  };
}
