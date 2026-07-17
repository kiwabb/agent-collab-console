import assert from "node:assert/strict";
import test from "node:test";

import {
  isTerminalStructuredPrototypeOperationError,
  isTerminalStructuredPrototypeGenerationOperationError,
  StructuredPrototypeApiError,
  StructuredPrototypeGenerationApiError,
} from "../src/lib/api/prototypes";
import { isKeyboardShortcutEditableTarget } from "../src/hooks/useKeyboardShortcuts";
import {
  readStructuredPrototypeRuntimeRecoveryIssue,
  shouldRecreateMissingStoredRuntimeSession,
  structuredPrototypeRuntimeResetEvidenceFromApiError,
  structuredPrototypeRuntimeResetEvidenceFromSession,
  structuredPrototypeRuntimeResetFailureIssue,
} from "../src/features/prototype/structured/structuredPrototypeRuntimeRecovery";
import {
  structuredPrototypeGenerationAcceptRequestKey,
  structuredPrototypeGenerationConfirmRequestKey,
  structuredPrototypeHistoryRequestKey,
  structuredPrototypeRuntimeCreateRequestKey,
  structuredPrototypeRuntimeResetRequestKey,
} from "../src/features/prototype/structured/structuredPrototypeStorage";
import type { StructuredPrototypeRuntimeSession } from "../src/features/prototype/structured/types";
import { readCompactSource } from "./sourceTestUtils";

test("structured studio resolves durable request IDs through outcome and resource recovery", () => {
  const source = readCompactSource("features/prototype/structured/useStructuredPrototypeStudio.ts");

  assert.match(source, /waitForStructuredPrototypeOperationOutcome\(descriptor\)/);
  assert.match(source, /beginStructuredPrototypePendingOperation\(projectId/);
  assert.match(source, /finishStructuredPrototypePendingOperation\(/);
  assert.match(source, /getCurrentStructuredPrototypeDraft\(/);
  assert.doesNotMatch(source, /isTerminalStructuredPrototypeOperationError\(error\)/);
  assert.match(
    source,
    /structuredPrototypeHistoryRequestKey\( operation, currentDraft\.draftId, currentDraft\.headSequenceNo, currentDraft\.documentHash, \)/,
  );
  assert.match(
    source,
    /structuredPrototypeRuntimeCreateRequestKey\( draft\.draftId, draft\.headSequenceNo, draft\.documentHash, \)/,
  );
});

test("runtime creation request keys pin the complete draft head", () => {
  assert.equal(
    structuredPrototypeRuntimeCreateRequestKey("draft-1", 7, "sha256:document"),
    "runtime-create-request:draft-1:7:sha256:document",
  );
  assert.notEqual(
    structuredPrototypeRuntimeCreateRequestKey("draft-1", 7, "sha256:document"),
    structuredPrototypeRuntimeCreateRequestKey("draft-1", 8, "sha256:next"),
  );
});

test("runtime reset request keys pin old session and target draft evidence", () => {
  const key = structuredPrototypeRuntimeResetRequestKey(
    "session-1",
    4,
    "sha256:old-state",
    "sha256:old-view",
    "sha256:old-core",
    "draft-2",
    8,
    "sha256:target-document",
    "scenario-2",
    "cause-operation",
  );
  assert.equal(
    key,
    "runtime-reset-request:session-1:4:sha256:old-state:sha256:old-view:sha256:old-core:draft-2:8:sha256:target-document:scenario-2:cause-operation",
  );
  assert.notEqual(
    key,
    structuredPrototypeRuntimeResetRequestKey(
      "session-1",
      5,
      "sha256:new-state",
      "sha256:old-view",
      "sha256:old-core",
      "draft-2",
      8,
      "sha256:target-document",
      "scenario-2",
      "cause-operation",
    ),
  );
});

test("runtime recovery classification is explicit and requires complete reset evidence", () => {
  for (const code of [
    "runtime_session_corrupt",
    "runtime_replay_version_mismatch",
    "runtime_replay_contract_unsupported",
  ]) {
    const issue = readStructuredPrototypeRuntimeRecoveryIssue(
      new StructuredPrototypeApiError({
        status: 409,
        code,
        message: "runtime cannot replay",
        retryable: false,
        operationId: "operation-1",
        correlationId: "correlation-1",
        currentHeadSequenceNo: 4,
        currentStateHash: "sha256:state",
        currentViewModelHash: "sha256:view",
        currentRuntimeCoreBundleHash: "sha256:core",
      }),
      "session-1",
    );
    assert.equal(issue?.code, code);
    assert.deepEqual(issue?.resetEvidence, {
      sessionId: "session-1",
      headSequenceNo: 4,
      stateHash: "sha256:state",
      viewModelHash: "sha256:view",
      runtimeCoreBundleHash: "sha256:core",
    });
  }

  const missingEvidence = readStructuredPrototypeRuntimeRecoveryIssue(
    new StructuredPrototypeApiError({
      status: 409,
      code: "runtime_session_corrupt",
      message: "runtime is corrupt",
      retryable: false,
      operationId: null,
      correlationId: "correlation-2",
      currentHeadSequenceNo: 4,
      currentStateHash: "sha256:state",
    }),
    "session-1",
  );
  assert.ok(missingEvidence);
  assert.equal(missingEvidence.resetEvidence, null);

  assert.equal(
    readStructuredPrototypeRuntimeRecoveryIssue(
      new StructuredPrototypeApiError({
        status: 500,
        code: "runtime_worker_identity_mismatch",
        message: "worker disagrees with its manifest",
        retryable: false,
        operationId: null,
        correlationId: "correlation-3",
      }),
      "session-1",
    ),
    null,
  );
});

test("only an unowned missing stored runtime session can be recreated", () => {
  const missing = new StructuredPrototypeApiError({
    status: 404,
    code: "runtime_session_missing",
    message: "runtime session does not exist",
    retryable: false,
    operationId: null,
    correlationId: "correlation-missing",
  });

  assert.equal(
    shouldRecreateMissingStoredRuntimeSession(missing, {
      hasCommittedReset: false,
      hasResetOutcomeError: false,
    }),
    true,
  );
  assert.equal(
    shouldRecreateMissingStoredRuntimeSession(missing, {
      hasCommittedReset: true,
      hasResetOutcomeError: false,
    }),
    false,
  );
  assert.equal(
    shouldRecreateMissingStoredRuntimeSession(missing, {
      hasCommittedReset: false,
      hasResetOutcomeError: true,
    }),
    false,
  );
  assert.equal(
    shouldRecreateMissingStoredRuntimeSession(
      new StructuredPrototypeApiError({
        status: 500,
        code: "runtime_session_missing",
        message: "runtime session lookup failed",
        retryable: true,
        operationId: null,
        correlationId: "correlation-server-error",
      }),
      { hasCommittedReset: false, hasResetOutcomeError: false },
    ),
    false,
  );
  assert.equal(
    shouldRecreateMissingStoredRuntimeSession(
      new StructuredPrototypeApiError({
        status: 409,
        code: "runtime_session_corrupt",
        message: "runtime session is corrupt",
        retryable: false,
        operationId: "operation-corrupt",
        correlationId: "correlation-corrupt",
      }),
      { hasCommittedReset: false, hasResetOutcomeError: false },
    ),
    false,
  );
  assert.equal(
    shouldRecreateMissingStoredRuntimeSession(new TypeError("network unavailable"), {
      hasCommittedReset: false,
      hasResetOutcomeError: false,
    }),
    false,
  );
});

test("the last valid snapshot supplies reset evidence only for the same session", () => {
  const session: StructuredPrototypeRuntimeSession = {
    contractVersion: 1,
    operationId: "operation-1",
    correlationId: "correlation-1",
    sessionId: "session-1",
    documentId: "document-1",
    sourceKind: "draft",
    sourceId: "draft-1",
    pinnedDocumentObjectHash: "sha256:document",
    status: "active",
    recordingKind: "studio_preview",
    headSequenceNo: 6,
    stateHash: "sha256:state",
    viewModelHash: "sha256:view",
    stateJson: "{}",
    viewModelJson: "{}",
    runtimeCoreVersion: "runtime/1",
    runtimeCoreBundleHash: "sha256:core",
    stateMachineKernelVersion: "xstate/1",
    checkpointId: "checkpoint-1",
    checkpointSequenceNo: 0,
    replayedEventBatchIds: [],
    replacesSessionId: null,
    resetManifestHash: null,
  };
  const error = new StructuredPrototypeApiError({
    status: 409,
    code: "runtime_replay_version_mismatch",
    message: "runtime version changed",
    retryable: false,
    operationId: null,
    correlationId: "correlation-2",
  });

  assert.deepEqual(
    readStructuredPrototypeRuntimeRecoveryIssue(error, "session-1", session)?.resetEvidence,
    structuredPrototypeRuntimeResetEvidenceFromSession(session),
  );
  assert.equal(
    readStructuredPrototypeRuntimeRecoveryIssue(error, "session-2", session)?.resetEvidence,
    null,
  );
});

test("a failed reset keeps retry evidence and an explicit recovery lock reason", () => {
  const resetEvidence = {
    sessionId: "session-1",
    headSequenceNo: 6,
    stateHash: "sha256:state",
    viewModelHash: "sha256:view",
    runtimeCoreBundleHash: "sha256:core",
  };
  const issue = structuredPrototypeRuntimeResetFailureIssue(
    new StructuredPrototypeApiError({
      status: 409,
      code: "runtime_session_conflict",
      message: "session changed",
      retryable: true,
      operationId: "operation-reset",
      correlationId: "correlation-reset",
    }),
    resetEvidence,
  );
  assert.equal(issue.code, "runtime_reset_failed");
  assert.equal(issue.operationId, "operation-reset");
  assert.equal(issue.correlationId, "correlation-reset");
  assert.deepEqual(issue.resetEvidence, resetEvidence);
});

test("runtime reset CAS evidence is readable independently from the recovery error code", () => {
  const evidence = structuredPrototypeRuntimeResetEvidenceFromApiError(
    new StructuredPrototypeApiError({
      status: 503,
      code: "runtime_worker_unavailable",
      message: "worker is unavailable",
      retryable: true,
      operationId: "operation-worker",
      correlationId: "correlation-worker",
      currentHeadSequenceNo: 9,
      currentStateHash: "sha256:state-next",
      currentViewModelHash: "sha256:view-next",
      currentRuntimeCoreBundleHash: "sha256:core-next",
    }),
    "session-1",
  );
  assert.deepEqual(evidence, {
    sessionId: "session-1",
    headSequenceNo: 9,
    stateHash: "sha256:state-next",
    viewModelHash: "sha256:view-next",
    runtimeCoreBundleHash: "sha256:core-next",
  });
  assert.equal(
    structuredPrototypeRuntimeResetEvidenceFromApiError(
      new StructuredPrototypeApiError({
        status: 503,
        code: "runtime_worker_unavailable",
        message: "worker is unavailable",
        retryable: true,
        operationId: null,
        correlationId: "correlation-worker-missing",
      }),
      "session-1",
    ),
    null,
  );
});

test("runtime creation rotates request identity after every known terminal failure", () => {
  const terminalFailure = new StructuredPrototypeApiError({
    status: 422,
    code: "runtime_scenario_missing",
    message: "runtime scenario is missing",
    retryable: false,
    operationId: "operation-terminal",
    correlationId: "correlation-terminal",
  });
  const inProgress = new StructuredPrototypeApiError({
    status: 409,
    code: "operation_in_progress",
    message: "operation is still running",
    retryable: true,
    operationId: "operation-running",
    correlationId: "correlation-running",
  });

  assert.equal(isTerminalStructuredPrototypeOperationError(terminalFailure), true);
  assert.equal(isTerminalStructuredPrototypeOperationError(inProgress), false);
  assert.equal(
    isTerminalStructuredPrototypeOperationError(new TypeError("network outcome unknown")),
    false,
  );
});

test("structured history request keys pin operation and draft head evidence", () => {
  assert.equal(
    structuredPrototypeHistoryRequestKey("undo", "draft-1", 7, "sha256:document"),
    "undo-request:draft-1:7:sha256:document",
  );
  assert.equal(
    structuredPrototypeHistoryRequestKey("redo", "draft-1", 8, "sha256:next"),
    "redo-request:draft-1:8:sha256:next",
  );
});

test("generation accept request keys pin candidate, preview, and source evidence", () => {
  const key = structuredPrototypeGenerationAcceptRequestKey(
    "job-1",
    "sha256:candidate",
    "sha256:preview",
    "sha256:source",
  );
  assert.equal(
    key,
    "generation-accept-request:job-1:sha256:candidate:sha256:preview:sha256:source",
  );
  assert.notEqual(
    key,
    structuredPrototypeGenerationAcceptRequestKey(
      "job-1",
      "sha256:candidate-next",
      "sha256:preview",
      "sha256:source",
    ),
  );
});

test("generation confirm request keys pin the complete blueprint identity", () => {
  const key = structuredPrototypeGenerationConfirmRequestKey("job-1", 3, "sha256:blueprint");
  assert.equal(key, "generation-confirm-request:job-1:3:sha256:blueprint");
  assert.notEqual(
    key,
    structuredPrototypeGenerationConfirmRequestKey("job-1", 4, "sha256:blueprint-next"),
  );
});

test("generation request IDs survive unknown and in-progress outcomes", () => {
  const terminal = new StructuredPrototypeGenerationApiError({
    status: 409,
    code: "generation_confirm_idempotency_conflict",
    message: "confirmation request changed",
    jobId: "job-1",
    correlationId: "correlation-terminal",
  });
  const inProgress = new StructuredPrototypeGenerationApiError({
    status: 409,
    code: "generation_confirm_in_progress",
    message: "confirmation is still running",
    jobId: "job-1",
    correlationId: "correlation-running",
  });

  assert.equal(isTerminalStructuredPrototypeGenerationOperationError(terminal), true);
  assert.equal(isTerminalStructuredPrototypeGenerationOperationError(inProgress), false);
  assert.equal(
    isTerminalStructuredPrototypeGenerationOperationError(new TypeError("network outcome unknown")),
    false,
  );
});

test("generation confirm reuses its request identity until the outcome is known", () => {
  const source = readCompactSource(
    "features/prototype/structured/useStructuredPrototypeGeneration.ts",
  );
  const confirmIndex = source.indexOf("await confirmStructuredPrototypeGenerationBlueprint(job.id");
  const resourceIndex = source.indexOf("confirmed = await getStructuredPrototypeGenerationJob");
  const finishIndex = source.indexOf("finishStructuredPrototypePendingOperation", confirmIndex);

  assert.match(source, /structuredPrototypeGenerationConfirmRequestKey\(/);
  assert.match(source, /clientRequestId: descriptor\.clientRequestId/);
  assert.match(source, /reconcilePendingPrototypeGenerationOperation\(descriptor\)/);
  assert.ok(confirmIndex >= 0, "expected a durable Confirm request");
  assert.ok(resourceIndex > confirmIndex, "Confirm must read the authoritative job");
  assert.ok(finishIndex > resourceIndex, "Confirm must clear pending only after the job read");
});

test("generation accept clears pending after the authoritative draft and before runtime rebuild", () => {
  const source = readCompactSource(
    "features/prototype/structured/useStructuredPrototypeGeneration.ts",
  );
  const acceptFunctionIndex = source.indexOf("const accept = useCallback");
  const acceptedIndex = source.indexOf("await onAccepted(draft)", acceptFunctionIndex);
  const draftIndex = source.indexOf("getCurrentStructuredPrototypeDraft", acceptFunctionIndex);
  const finishIndex = source.indexOf("finishStructuredPrototypePendingOperation", draftIndex);
  assert.match(source, /structuredPrototypeGenerationAcceptRequestKey\(/);
  assert.match(source, /clientRequestId: descriptor\.clientRequestId/);
  assert.match(source, /expectedSourceFingerprint: job\.sourceFingerprint/);
  assert.ok(acceptedIndex >= 0, "expected accepted draft recovery");
  assert.ok(finishIndex > draftIndex, "Accept must retain pending through the current draft read");
  assert.ok(acceptedIndex > finishIndex, "Runtime rebuild starts as its own recoverable operation");
});

test("structured studio stages a draft and resets the prior runtime without dropping its pointer", () => {
  const source = readCompactSource("features/prototype/structured/useStructuredPrototypeStudio.ts");
  const stageIndex = source.indexOf("const stageDraftAndRebuildRuntime");
  const stageEndIndex = source.indexOf("const applyReconciledOperation", stageIndex);
  const stageSource = source.slice(stageIndex, stageEndIndex);
  const stagedDraftIndex = source.indexOf("draft, runtime: current.runtime");
  const stagedResetIndex = stageSource.indexOf("await resetRuntime(resetEvidence, draft, null)");
  const adoptIndex = source.indexOf("const adoptAiDraft");
  const adoptStageIndex = source.indexOf("stageDraftAndRebuildRuntime(draft)", adoptIndex);
  const publishedDraftIndex = source.indexOf(
    "stageDraftAndRebuildRuntime(activeDraft, publication)",
  );
  const studioPage = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  const recoveryNotice = readCompactSource(
    "features/prototype/structured/StructuredPrototypeRuntimeRecoveryNotice.tsx",
  );
  const resetIndex = source.indexOf("const resetRuntime = useCallback");
  const pendingResetIndex = source.indexOf('case "reset_runtime_session"');
  const pendingResetEndIndex = source.indexOf('case "apply_runtime_event"', pendingResetIndex);
  const pendingResetSource = source.slice(pendingResetIndex, pendingResetEndIndex);
  const responseLostRecoveryIndex = source.indexOf(
    "recoverStructuredPrototypeRuntimeSession( reconciled.replacementSessionId",
    resetIndex,
  );
  const responseLostIssueIndex = source.indexOf(
    "readStructuredPrototypeRuntimeRecoveryIssue( recoveryError, reconciled.replacementSessionId",
    responseLostRecoveryIndex,
  );
  const coldReplacementValidationIndex = source.indexOf(
    "committedReset?.replacementSessionId === storedSessionId ? decodeReplacementRuntime(recovered, committedReset.replacedSessionId, false)",
  );
  const storedRuntimeIndex = source.indexOf("const storedSessionId");
  const missingRuntimeRecreateIndex = source.indexOf(
    "shouldRecreateMissingStoredRuntimeSession",
    storedRuntimeIndex,
  );
  const missingRuntimeCreateIndex = source.indexOf(
    "runtime = await createRuntime(draft)",
    missingRuntimeRecreateIndex,
  );
  const missingRuntimeIssueIndex = source.indexOf(
    "readStructuredPrototypeRuntimeRecoveryIssue",
    missingRuntimeRecreateIndex,
  );
  const decodedResetIndex = source.indexOf("decodeResetRuntime(session", resetIndex);
  const resetPointerIndex = source.indexOf(
    'structuredPrototypeStorageKey(projectId, "runtime-session-id")',
    decodedResetIndex,
  );
  const resetFinishIndex = source.indexOf(
    "finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId)",
    resetPointerIndex,
  );
  const resetPreviewIndex = source.indexOf("const resetRuntimePreview = useCallback");
  const resetPreviewEndIndex = source.indexOf("const adoptAiDraft", resetPreviewIndex);
  const resetPreviewSource = source.slice(resetPreviewIndex, resetPreviewEndIndex);
  const refreshResetEvidenceIndex = resetPreviewSource.indexOf(
    "await recoverStructuredPrototypeRuntimeSession( issue.sessionId",
  );
  const retryResetIndex = resetPreviewSource.indexOf(
    "await resetRuntime(resetEvidence, current.draft, causeOperationId)",
  );

  assert.ok(stagedDraftIndex >= 0, "expected a changed draft to be staged");
  assert.ok(stagedResetIndex >= 0, "an existing runtime must reset after staging the draft");
  assert.doesNotMatch(stageSource, /removeItem/);
  assert.match(
    stageSource,
    /runtimeRecovery: structuredPrototypeRuntimeResetFailureIssue\( error, latestResetEvidence, \)/,
  );
  assert.match(source, /stageDraftAndRebuildRuntime\(applied\)/);
  assert.ok(adoptIndex >= 0, "expected AI draft adoption");
  assert.ok(adoptStageIndex > adoptIndex, "AI adoption must stage the authoritative draft first");
  assert.ok(publishedDraftIndex >= 0, "expected the active published draft to be staged");
  assert.match(source, /stageDraftAndRebuildRuntime\(activeDraft, publication\)/);
  assert.match(
    source,
    /structuredPrototypeRuntimeResetEvidenceFromApiError\(\s*error,\s*storedSessionId/,
  );
  assert.ok(refreshResetEvidenceIndex >= 0, "failed reset retries must refresh old session CAS");
  assert.ok(
    retryResetIndex > refreshResetEvidenceIndex,
    "reset POST must use refreshed CAS evidence",
  );
  assert.match(
    resetPreviewSource,
    /runtimeRecovery: structuredPrototypeRuntimeResetFailureIssue\(/,
  );
  assert.match(
    pendingResetSource,
    /outcome\.status !== "succeeded".*finishFailedStudioOutcome\(descriptor, outcome\)/,
  );
  assert.match(
    pendingResetSource,
    /commitSucceededStructuredPrototypeRuntimeResetOutcome\( descriptor, outcome/,
  );
  assert.doesNotMatch(pendingResetSource, /recoverStructuredPrototypeRuntimeSession\(/);
  assert.doesNotMatch(pendingResetSource, /getCurrentStructuredPrototypeDraft\(/);
  assert.ok(
    responseLostRecoveryIndex >= 0,
    "a response-lost reset must recover the committed replacement session",
  );
  assert.ok(
    responseLostIssueIndex > responseLostRecoveryIndex,
    "a second replay failure must be classified against the replacement session",
  );
  assert.ok(
    coldReplacementValidationIndex >= 0,
    "cold recovery must validate the replacement against the session it replaced",
  );
  assert.ok(missingRuntimeRecreateIndex > storedRuntimeIndex);
  assert.ok(
    missingRuntimeIssueIndex > missingRuntimeRecreateIndex &&
      missingRuntimeCreateIndex > missingRuntimeIssueIndex,
    "only an unowned missing stored runtime may bypass failure classification and create a durable replacement",
  );
  assert.match(studioPage, /controller\.error \?\? t\("prototype\.structured\.loadFailed"\)/);
  assert.match(
    studioPage,
    /controller\.saving \|\| aiMutating \|\| controller\.runtimeRecovery !== null/,
  );
  assert.match(studioPage, /controller\.runtimeRecovery\.code === "runtime_reset_failed"/);
  assert.match(
    studioPage,
    /controller\.runtimeRecovery\.code === "runtime_reset_failed".*hasLastSnapshot=\{runtime !== null\}/,
  );
  assert.match(
    studioPage,
    /controller\.runtimeRecovery && \( <StructuredPrototypeRuntimeRecoveryNotice[^>]+hasLastSnapshot/,
  );
  assert.match(studioPage, /controller\.resetRuntimePreview\(\)/);
  assert.match(recoveryNotice, /disabled=\{isResetting \|\| issue\.resetEvidence === null\}/);
  assert.ok(decodedResetIndex >= 0, "reset response must decode before pointer replacement");
  assert.ok(resetPointerIndex > decodedResetIndex, "new runtime pointer must follow decoding");
  assert.ok(resetFinishIndex > resetPointerIndex, "pending reset clears after pointer replacement");
  assert.doesNotMatch(source, /draft, runtime: null/);
  assert.doesNotMatch(source, /draft: activeDraft, runtime: null/);
});

test("structured Studio exposes history controls and preserves native editing shortcuts", () => {
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  const keyboard = readCompactSource("hooks/useKeyboardShortcuts.ts");
  const types = readCompactSource("features/prototype/structured/types.ts");

  assert.match(types, /canUndo: boolean; canRedo: boolean;/);
  assert.match(studio, /<Undo2 size=\{15\} aria-hidden \/>/);
  assert.match(studio, /<Redo2 size=\{15\} aria-hidden \/>/);
  assert.match(
    studio,
    /disabled=\{interactionCapabilities\.documentControlsDisabled \|\| !controller\.draft\.canUndo\}/,
  );
  assert.match(
    studio,
    /disabled=\{interactionCapabilities\.documentControlsDisabled \|\| !controller\.draft\.canRedo\}/,
  );
  assert.match(studio, /t\("prototype\.structured\.undo"\)/);
  assert.match(studio, /t\("prototype\.structured\.redo"\)/);
  assert.equal((studio.match(/key: "z"/g) ?? []).length, 4);
  assert.match(
    keyboard,
    /target\.closest\("input, textarea, select, \[contenteditable\]"\) !== null/,
  );
  assert.equal(isKeyboardShortcutEditableTarget(null), false);
});

test("AI and generation mutations share pending outcome recovery and the Studio document lock", () => {
  const ai = readCompactSource("features/prototype/structured/useStructuredPrototypeAi.ts");
  const generation = readCompactSource(
    "features/prototype/structured/useStructuredPrototypeGeneration.ts",
  );
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  const aiPanel = readCompactSource("features/prototype/structured/StructuredPrototypeAiPanel.tsx");

  assert.match(ai, /operationKind: "ai_edit"/);
  assert.match(ai, /operationKind: "apply_command_batch"/);
  assert.match(ai, /operationKind: "reject_ai_proposal"/);
  assert.match(ai, /reconcilePendingPrototypeAiOperation\(descriptor\)/);
  assert.match(ai, /getCurrentStructuredPrototypeDraft/);
  assert.match(ai, /getPrototypeAiThread/);

  assert.match(generation, /operationKind: "generation_job"/);
  assert.match(generation, /operationKind: "create_document"/);
  assert.match(generation, /operationKind: "delete_project_prototype"/);
  assert.match(generation, /reconcilePendingPrototypeGenerationOperation\(descriptor\)/);
  assert.match(generation, /getCurrentStructuredPrototypeGenerationJob/);
  assert.match(generation, /getCurrentStructuredPrototypeDraft/);

  assert.match(studio, /const editorMutationLocked = controller\.saving \|\| aiMutating/);
  assert.match(studio, /onMutatingChange=\{setAiMutating\}/);
  assert.match(aiPanel, /onMutatingChange\(ai\.mutating\)/);
});
