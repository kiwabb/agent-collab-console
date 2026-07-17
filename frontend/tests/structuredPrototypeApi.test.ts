import assert from "node:assert/strict";
import test from "node:test";

import {
  acceptStructuredPrototypeGenerationCandidate,
  applyPrototypeAiProposal,
  applyStructuredPrototypeCommands,
  applyStructuredPrototypeRuntimeEvents,
  checkpointStructuredPrototypeRuntimeSession,
  confirmStructuredPrototypeGenerationBlueprint,
  createPrototypeAiThread,
  createStructuredPrototypeGenerationJob,
  createStructuredPrototypeRuntimeSession,
  deleteProjectStructuredPrototype,
  getCurrentStructuredPrototypeDraft,
  getCurrentStructuredPrototypeGenerationJob,
  getStructuredPrototypeOperationDetail,
  getStructuredPrototypeOperationEvents,
  getStructuredPrototypeOperationOutcome,
  getStructuredPrototypePublication,
  getPrototypeAiThread,
  getStructuredPrototypeGenerationJob,
  isTerminalStructuredPrototypeOperationError,
  isTerminalRetryableStructuredPrototypeError,
  publishStructuredPrototypeDraft,
  rejectPrototypeAiProposal,
  redoStructuredPrototypeDraft,
  recoverStructuredPrototypeDraft,
  recoverStructuredPrototypeRuntimeSession,
  resetStructuredPrototypeRuntimeSession,
  runStructuredPrototypeRequestWithDeadline,
  StructuredPrototypeApiError,
  StructuredPrototypeAiApiError,
  StructuredPrototypeRequestDeadlineError,
  undoStructuredPrototypeDraft,
  sendPrototypeAiMessage,
} from "../src/lib/api/prototypes";
import { jsonRequestBody, withMockFetch } from "./fetchTestUtils";

const SHA = `sha256:${"a".repeat(64)}`;

function operationOutcome(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    contractVersion: 1,
    known: true,
    terminal: true,
    operationId: "22222222-2222-4222-8222-222222222222",
    operationKind: "apply_command_batch",
    projectId: "09cca906-b5e1-4601-aa7a-14fb58f9f06b",
    resourceKind: "draft",
    resourceId: "33333333-3333-4333-8333-333333333333",
    clientRequestId: "11111111-1111-4111-8111-111111111111",
    correlationId: "44444444-4444-4444-8444-444444444444",
    parentOperationId: null,
    status: "succeeded",
    phase: "completed",
    attempt: 1,
    requestManifestHash: SHA,
    configManifestHash: SHA,
    resultManifestHash: SHA,
    failureEvidenceHash: null,
    errorCode: null,
    createdAt: "2026-07-16T00:00:00Z",
    startedAt: "2026-07-16T00:00:01Z",
    completedAt: "2026-07-16T00:00:02Z",
    ...overrides,
  };
}

function operationStep(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "55555555-5555-4555-8555-555555555555",
    operationId: "22222222-2222-4222-8222-222222222222",
    parentStepId: null,
    stepKind: "apply_commands",
    stepOrdinal: 0,
    attempt: 1,
    status: "succeeded",
    phase: "completed",
    inputManifestHash: SHA,
    configManifestHash: SHA,
    outputManifestHash: SHA,
    completionEvidenceKind: "replay_manifest",
    completionEvidenceRef: SHA,
    errorCode: null,
    startedAt: "2026-07-16T00:00:01Z",
    completedAt: "2026-07-16T00:00:02Z",
    ...overrides,
  };
}

function replayManifest(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    manifestVersion: 1,
    operationId: "22222222-2222-4222-8222-222222222222",
    operationKind: "apply_command_batch",
    parentOperationId: null,
    requestManifestHash: SHA,
    contextManifestHash: null,
    orderedInputObjectHashes: [SHA],
    versions: {
      serviceVersion: "structured-prototype-service/v1",
      documentSchemaVersion: 1,
      commandContractVersion: 1,
      runtimeStateSchemaVersion: 1,
      runtimeEventContractVersion: 1,
      runtimeCoreVersion: null,
      runtimeCoreBundleHash: null,
      stateMachineKernelVersion: null,
      rendererVersion: null,
      rendererEnvironmentVersion: null,
      replayManifestVersion: 1,
    },
    agentTaskIdentity: null,
    submissionHash: null,
    orderedCommandBatchHashes: [SHA],
    baseCheckpointHash: SHA,
    baseSequenceNo: 0,
    resultCheckpointHash: SHA,
    resultSequenceNo: 1,
    rendererInputHash: null,
    rendererOutputHash: null,
    runtimeSessionId: null,
    runtimeCoreBundleHash: null,
    orderedRuntimeEventHashes: [],
    runtimeFinalStateHash: null,
    runtimeFinalViewModelHash: null,
    validationReportHashes: [],
    terminalStatus: "succeeded",
    errorCode: null,
    ...overrides,
  };
}

function operationDetail(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    contractVersion: 1,
    operation: operationOutcome(),
    steps: [operationStep()],
    childOperationIds: ["66666666-6666-4666-8666-666666666666"],
    replayManifest: replayManifest(),
    ...overrides,
  };
}

function operationEvent(
  eventNo: number,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  const operationId = "22222222-2222-4222-8222-222222222222";
  return {
    operationId,
    eventNo,
    stepId: eventNo === 0 ? null : "55555555-5555-4555-8555-555555555555",
    eventKind: eventNo === 0 ? "operation_queued" : "step_succeeded",
    status: eventNo === 0 ? "queued" : "succeeded",
    phase: eventNo === 0 ? "queued" : "completed",
    inputHash: SHA,
    outputHash: eventNo === 0 ? null : SHA,
    evidenceHash: eventNo === 0 ? null : SHA,
    errorCode: null,
    occurredAt: eventNo === 0 ? "2026-07-16T00:00:00Z" : "2026-07-16T00:00:02Z",
    ...overrides,
  };
}

function operationEvents(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const operationId = "22222222-2222-4222-8222-222222222222";
  return {
    contractVersion: 1,
    operationId,
    events: [operationEvent(0), operationEvent(1)],
    ...overrides,
  };
}

test("structured prototype request deadline aborts an outcome-unknown request", async () => {
  await assert.rejects(
    runStructuredPrototypeRequestWithDeadline(
      (signal) =>
        new Promise<never>((_resolve, reject) => {
          signal.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        }),
      { deadlineMs: 5 },
    ),
    (error: unknown) =>
      error instanceof StructuredPrototypeRequestDeadlineError && error.deadlineMs === 5,
  );
});

test("structured prototype operation outcome query validates identity and terminal evidence", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify(operationOutcome()), { status: 200 }),
    async (calls) => {
      const outcome = await getStructuredPrototypeOperationOutcome(
        "09cca906-b5e1-4601-aa7a-14fb58f9f06b",
        "apply_command_batch",
        "11111111-1111-4111-8111-111111111111",
      );
      assert.equal(outcome.status, "succeeded");
      assert.equal(outcome.terminal, true);
      assert.equal(
        calls[0]?.input,
        "/api/projects/09cca906-b5e1-4601-aa7a-14fb58f9f06b/structured-prototype-operations/outcome?operationKind=apply_command_batch&clientRequestId=11111111-1111-4111-8111-111111111111",
      );
      assert.ok(calls[0]?.init?.signal instanceof AbortSignal);
    },
  );
});

test("structured prototype operation outcome rejects inconsistent terminal state", async () => {
  await withMockFetch(
    () =>
      new Response(JSON.stringify(operationOutcome({ terminal: false, status: "succeeded" })), {
        status: 200,
      }),
    async () => {
      await assert.rejects(
        getStructuredPrototypeOperationOutcome(
          "09cca906-b5e1-4601-aa7a-14fb58f9f06b",
          "apply_command_batch",
          "11111111-1111-4111-8111-111111111111",
        ),
        /terminal disagrees with status/,
      );
    },
  );
});

test("structured prototype operation outcome accepts active and interrupted evidence shapes", async () => {
  const validPayloads = [
    operationOutcome({
      terminal: false,
      status: "running",
      resultManifestHash: null,
      completedAt: null,
    }),
    operationOutcome({
      status: "interrupted",
      resultManifestHash: null,
      errorCode: "service_restart",
    }),
  ];
  for (const payload of validPayloads) {
    await withMockFetch(
      () => new Response(JSON.stringify(payload), { status: 200 }),
      async () => {
        const outcome = await getStructuredPrototypeOperationOutcome(
          "09cca906-b5e1-4601-aa7a-14fb58f9f06b",
          "apply_command_batch",
          "11111111-1111-4111-8111-111111111111",
        );
        assert.equal(outcome.status, payload["status"]);
      },
    );
  }
});

test("structured prototype operation outcome rejects a cross-query response", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify(operationOutcome({ projectId: "55555555-5555-4555-8555-555555555555" })),
        { status: 200 },
      ),
    async () => {
      await assert.rejects(
        getStructuredPrototypeOperationOutcome(
          "09cca906-b5e1-4601-aa7a-14fb58f9f06b",
          "apply_command_batch",
          "11111111-1111-4111-8111-111111111111",
        ),
        /does not match its query identity/,
      );
    },
  );
});

test("structured prototype operation outcome rejects unknown fields and forged lifecycle evidence", async () => {
  const invalidPayloads = [
    operationOutcome({ unexpected: true }),
    operationOutcome({
      terminal: false,
      status: "running",
      startedAt: null,
      completedAt: null,
      resultManifestHash: null,
    }),
    operationOutcome({
      status: "failed",
      resultManifestHash: null,
      failureEvidenceHash: null,
      errorCode: "command_failed",
    }),
    operationOutcome({ failureEvidenceHash: SHA }),
    operationOutcome({
      terminal: false,
      status: "running",
      completedAt: null,
    }),
    operationOutcome({
      status: "failed",
      failureEvidenceHash: SHA,
      errorCode: "command_failed",
    }),
    operationOutcome({
      status: "interrupted",
      errorCode: "service_restart",
    }),
  ];
  for (const payload of invalidPayloads) {
    await withMockFetch(
      () => new Response(JSON.stringify(payload), { status: 200 }),
      async () => {
        await assert.rejects(
          getStructuredPrototypeOperationOutcome(
            "09cca906-b5e1-4601-aa7a-14fb58f9f06b",
            "apply_command_batch",
            "11111111-1111-4111-8111-111111111111",
          ),
        );
      },
    );
  }
});

test("structured prototype operation detail and events expose replayable evidence", async () => {
  const operationId = "22222222-2222-4222-8222-222222222222";
  await withMockFetch(
    (input) =>
      new Response(
        JSON.stringify(String(input).endsWith("/events") ? operationEvents() : operationDetail()),
        { status: 200 },
      ),
    async (calls) => {
      const detail = await getStructuredPrototypeOperationDetail(operationId);
      assert.equal(detail.operation.operationId, operationId);
      assert.equal(detail.steps[0]?.status, "succeeded");
      assert.equal(detail.replayManifest?.versions.replayManifestVersion, 1);
      assert.deepEqual(detail.childOperationIds, ["66666666-6666-4666-8666-666666666666"]);

      const events = await getStructuredPrototypeOperationEvents(operationId);
      assert.deepEqual(
        events.events.map((event) => event.eventNo),
        [0, 1],
      );
      assert.equal(calls[0]?.input, `/api/prototype-operations/${operationId}`);
      assert.equal(calls[1]?.input, `/api/prototype-operations/${operationId}/events`);
    },
  );
});

test("structured prototype operation detail rejects identity lifecycle and ordering drift", async () => {
  const operationId = "22222222-2222-4222-8222-222222222222";
  const invalidPayloads = [
    operationDetail({
      replayManifest: replayManifest({ operationId: "77777777-7777-4777-8777-777777777777" }),
    }),
    operationDetail({ replayManifest: null }),
    operationDetail({ childOperationIds: [operationId, operationId] }),
    operationDetail({
      steps: [
        operationStep({
          id: "77777777-7777-4777-8777-777777777777",
          stepOrdinal: 1,
        }),
        operationStep({ stepOrdinal: 0 }),
      ],
    }),
    operationDetail({
      operation: operationOutcome({
        terminal: false,
        status: "running",
        completedAt: null,
        resultManifestHash: null,
      }),
    }),
    operationDetail({ unexpected: true }),
  ];
  for (const payload of invalidPayloads) {
    await withMockFetch(
      () => new Response(JSON.stringify(payload), { status: 200 }),
      async () => {
        await assert.rejects(getStructuredPrototypeOperationDetail(operationId));
      },
    );
  }
});

test("structured prototype operation events reject gaps and cross-operation records", async () => {
  const operationId = "22222222-2222-4222-8222-222222222222";
  const invalidPayloads = [
    operationEvents({ events: [] }),
    operationEvents({ events: [operationEvent(0), operationEvent(2)] }),
    operationEvents({
      events: [
        operationEvent(0),
        operationEvent(1, { operationId: "77777777-7777-4777-8777-777777777777" }),
      ],
    }),
    operationEvents({
      operationId: "77777777-7777-4777-8777-777777777777",
      events: [operationEvent(0, { operationId: "77777777-7777-4777-8777-777777777777" })],
    }),
  ];
  for (const payload of invalidPayloads) {
    await withMockFetch(
      () => new Response(JSON.stringify(payload), { status: 200 }),
      async () => {
        await assert.rejects(getStructuredPrototypeOperationEvents(operationId));
      },
    );
  }
});

test("structured prototype draft recovery sends the client request identity", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    async (calls) => {
      await recoverStructuredPrototypeDraft("draft/one", "request-id");
      assert.equal(
        calls[0]?.input,
        "/api/structured-prototype-drafts/draft%2Fone?clientRequestId=request-id",
      );
      assert.ok(calls[0]?.init?.signal instanceof AbortSignal);
    },
  );
});

test("project current draft recovery does not depend on browser storage", async () => {
  await withMockFetch(
    () => new Response("null", { status: 200 }),
    async (calls) => {
      const current = await getCurrentStructuredPrototypeDraft("project/one", "request-id");
      assert.equal(current, null);
      assert.equal(
        calls[0]?.input,
        "/api/projects/project%2Fone/structured-prototype-documents/current?clientRequestId=request-id",
      );
    },
  );
});

test("project prototype deletion uses an idempotent DELETE request identity", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          contractVersion: 1,
          operationId: "delete-operation",
          correlationId: "delete-correlation",
          deleted: true,
        }),
        { status: 200 },
      ),
    async (calls) => {
      const deleted = await deleteProjectStructuredPrototype("project/one", "delete-request");
      assert.equal(deleted.deleted, true);
      assert.equal(
        calls[0]?.input,
        "/api/projects/project%2Fone/structured-prototype-documents?clientRequestId=delete-request",
      );
      assert.equal(calls[0]?.init?.method, "DELETE");
    },
  );
});

test("structured prototype generation uses review and acceptance contracts", async () => {
  await withMockFetch(
    (input) => {
      const url = String(input);
      if (url.endsWith("/confirm")) {
        return new Response(
          JSON.stringify({
            contractVersion: 1,
            operationId: "confirm-operation",
            correlationId: "confirm-correlation",
            job: { id: "job/one" },
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/accept")) {
        return new Response(
          JSON.stringify({
            contractVersion: 1,
            operationId: "accept-operation",
            correlationId: "accept-correlation",
            job: { id: "job/one" },
            documentId: "document-one",
            draftId: "draft-one",
            checkpointId: "checkpoint-one",
            headSequenceNo: 1,
            documentHash: SHA,
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ id: "job/one" }), { status: 200 });
    },
    async (calls) => {
      await createStructuredPrototypeGenerationJob("project/one", {
        contractVersion: 1,
        clientRequestId: "create-job",
        mode: "requirements",
        brief: "生成采购审批原型",
      });
      await getCurrentStructuredPrototypeGenerationJob("project/one");
      await getStructuredPrototypeGenerationJob("job/one");
      const confirmed = await confirmStructuredPrototypeGenerationBlueprint("job/one", {
        contractVersion: 1,
        clientRequestId: "confirm-job",
        expectedBlueprintVersion: 3,
        expectedBlueprintHash: SHA,
      });
      const accepted = await acceptStructuredPrototypeGenerationCandidate("job/one", {
        contractVersion: 1,
        clientRequestId: "accept-job",
        expectedCandidateObjectHash: SHA,
        expectedPreviewOutputHash: SHA,
        expectedSourceFingerprint: SHA,
      });

      assert.equal(confirmed.operationId, "confirm-operation");
      assert.equal(confirmed.correlationId, "confirm-correlation");
      assert.equal(accepted.operationId, "accept-operation");
      assert.equal(accepted.correlationId, "accept-correlation");

      assert.equal(
        calls[0]?.input,
        "/api/projects/project%2Fone/prototype-document-generation-jobs",
      );
      const createCall = calls[0];
      const confirmCall = calls[3];
      const acceptCall = calls[4];
      assert.ok(createCall);
      assert.ok(confirmCall);
      assert.ok(acceptCall);
      assert.deepEqual(jsonRequestBody(createCall), {
        contractVersion: 1,
        clientRequestId: "create-job",
        mode: "requirements",
        brief: "生成采购审批原型",
      });
      assert.equal(
        calls[1]?.input,
        "/api/projects/project%2Fone/prototype-document-generation-jobs/current",
      );
      assert.equal(calls[2]?.input, "/api/prototype-document-generation-jobs/job%2Fone");
      assert.deepEqual(jsonRequestBody(confirmCall), {
        contractVersion: 1,
        clientRequestId: "confirm-job",
        expectedBlueprintVersion: 3,
        expectedBlueprintHash: SHA,
      });
      assert.deepEqual(jsonRequestBody(acceptCall), {
        contractVersion: 1,
        clientRequestId: "accept-job",
        expectedCandidateObjectHash: SHA,
        expectedPreviewOutputHash: SHA,
        expectedSourceFingerprint: SHA,
      });
    },
  );
});

test("structured prototype command apply preserves optimistic concurrency evidence", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    async (calls) => {
      await applyStructuredPrototypeCommands("draft-1", {
        contractVersion: 1,
        clientRequestId: "command-request",
        expectedHeadSequenceNo: 7,
        expectedDocumentHash: SHA,
        batch: {
          commandContractVersion: 1,
          summary: "移动组件",
          commands: [
            {
              kind: "moveNode",
              node: { kind: "existing", nodeId: "node-1" },
              targetParent: { kind: "existing", nodeId: "root-1" },
              targetSlot: null,
              targetIndex: 2,
            },
          ],
        },
      });
      const call = calls[0];
      assert.ok(call);
      assert.equal(call.input, "/api/structured-prototype-drafts/draft-1/commands");
      assert.deepEqual(jsonRequestBody(call), {
        contractVersion: 1,
        clientRequestId: "command-request",
        expectedHeadSequenceNo: 7,
        expectedDocumentHash: SHA,
        batch: {
          commandContractVersion: 1,
          summary: "移动组件",
          commands: [
            {
              kind: "moveNode",
              node: { kind: "existing", nodeId: "node-1" },
              targetParent: { kind: "existing", nodeId: "root-1" },
              targetSlot: null,
              targetIndex: 2,
            },
          ],
        },
      });
    },
  );
});

test("structured prototype undo and redo send only optimistic history evidence", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    async (calls) => {
      const request = {
        contractVersion: 1 as const,
        clientRequestId: "history-request",
        expectedHeadSequenceNo: 8,
        expectedDocumentHash: SHA,
      };
      await undoStructuredPrototypeDraft("draft/one", request);
      await redoStructuredPrototypeDraft("draft/one", request);

      assert.equal(calls[0]?.input, "/api/structured-prototype-drafts/draft%2Fone/undo");
      assert.equal(calls[1]?.input, "/api/structured-prototype-drafts/draft%2Fone/redo");
      for (const call of calls) {
        assert.equal(call.init?.method, "POST");
        assert.deepEqual(jsonRequestBody(call), request);
      }
    },
  );
});

test("structured runtime session lifecycle uses versioned request envelopes", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    async (calls) => {
      await createStructuredPrototypeRuntimeSession("draft-1", {
        contractVersion: 1,
        clientRequestId: "create-session",
        scenarioId: "scenario-1",
        recordingKind: "studio_preview",
        actorSubjectId: null,
      });
      await recoverStructuredPrototypeRuntimeSession("session/1", "recover-session");
      await applyStructuredPrototypeRuntimeEvents("session/1", {
        contractVersion: 1,
        clientRequestId: "event-request",
        expectedHeadSequenceNo: 3,
        expectedStateHash: SHA,
        batch: {
          clientEventId: "event-request",
          expectedSequenceNo: 3,
          events: [{ kind: "switchSimulatedRole", roleId: "manager" }],
        },
      });
      await checkpointStructuredPrototypeRuntimeSession("session/1", {
        contractVersion: 1,
        clientRequestId: "checkpoint-session",
      });

      assert.equal(calls[0]?.input, "/api/structured-prototype-drafts/draft-1/runtime-sessions");
      assert.equal(
        calls[1]?.input,
        "/api/structured-prototype-runtime-sessions/session%2F1?clientRequestId=recover-session",
      );
      assert.equal(
        calls[2]?.input,
        "/api/structured-prototype-runtime-sessions/session%2F1/events",
      );
      const eventCall = calls[2];
      assert.ok(eventCall);
      assert.deepEqual(jsonRequestBody(eventCall), {
        contractVersion: 1,
        clientRequestId: "event-request",
        expectedHeadSequenceNo: 3,
        expectedStateHash: SHA,
        batch: {
          clientEventId: "event-request",
          expectedSequenceNo: 3,
          events: [{ kind: "switchSimulatedRole", roleId: "manager" }],
        },
      });
      assert.equal(
        calls[3]?.input,
        "/api/structured-prototype-runtime-sessions/session%2F1/checkpoint",
      );
    },
  );
});

test("structured runtime reset pins the old session and target draft evidence", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    async (calls) => {
      await resetStructuredPrototypeRuntimeSession("session/1", {
        contractVersion: 1,
        clientRequestId: "reset-request",
        causeOperationId: "cause-operation",
        expectedOldHeadSequenceNo: 4,
        expectedOldStateHash: SHA,
        expectedOldViewModelHash: SHA,
        expectedOldRuntimeCoreBundleHash: SHA,
        targetDraftId: "draft-2",
        expectedTargetHeadSequenceNo: 8,
        expectedTargetDocumentHash: SHA,
        scenarioId: "scenario-2",
      });

      const call = calls[0];
      assert.ok(call);
      assert.equal(call.input, "/api/structured-prototype-runtime-sessions/session%2F1/reset");
      assert.deepEqual(jsonRequestBody(call), {
        contractVersion: 1,
        clientRequestId: "reset-request",
        causeOperationId: "cause-operation",
        expectedOldHeadSequenceNo: 4,
        expectedOldStateHash: SHA,
        expectedOldViewModelHash: SHA,
        expectedOldRuntimeCoreBundleHash: SHA,
        targetDraftId: "draft-2",
        expectedTargetHeadSequenceNo: 8,
        expectedTargetDocumentHash: SHA,
        scenarioId: "scenario-2",
      });
    },
  );
});

test("structured publication freezes the expected draft head and reads the public pointer", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    async (calls) => {
      await publishStructuredPrototypeDraft("draft/1", {
        contractVersion: 1,
        clientRequestId: "publish-request",
        expectedHeadSequenceNo: 9,
        expectedDocumentHash: SHA,
      });
      await getStructuredPrototypePublication("document/1");

      assert.equal(calls[0]?.input, "/api/structured-prototype-drafts/draft%2F1/publish");
      const publishCall = calls[0];
      assert.ok(publishCall);
      assert.deepEqual(jsonRequestBody(publishCall), {
        contractVersion: 1,
        clientRequestId: "publish-request",
        expectedHeadSequenceNo: 9,
        expectedDocumentHash: SHA,
      });
      assert.equal(calls[1]?.input, "/api/structured-prototype-documents/document%2F1/published");
    },
  );
});

test("structured prototype errors preserve operation and correlation evidence", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          contractVersion: 1,
          correlationId: "correlation-1",
          operationId: "operation-1",
          error: {
            code: "draft_conflict",
            message: "draft head changed",
            retryable: true,
            currentHeadSequenceNo: 8,
            currentDocumentHash: SHA,
            resourceUrl: null,
          },
        }),
        { status: 409 },
      ),
    async () => {
      await assert.rejects(
        recoverStructuredPrototypeDraft("draft-1", "request-1"),
        (error: unknown) =>
          error instanceof StructuredPrototypeApiError &&
          error.status === 409 &&
          error.code === "draft_conflict" &&
          error.retryable &&
          error.operationId === "operation-1" &&
          error.correlationId === "correlation-1" &&
          error.message.includes("operation operation-1"),
      );
    },
  );
});

test("structured runtime recovery errors preserve reset CAS evidence", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          contractVersion: 1,
          correlationId: "correlation-runtime",
          operationId: "operation-runtime",
          error: {
            code: "runtime_replay_version_mismatch",
            message: "runtime version changed",
            retryable: false,
            currentHeadSequenceNo: 5,
            currentStateHash: SHA,
            currentViewModelHash: SHA,
            runtimeCoreBundleHash: SHA,
            resourceUrl: "/api/structured-prototype-runtime-sessions/session-1/reset",
          },
        }),
        { status: 409 },
      ),
    async () => {
      await assert.rejects(
        recoverStructuredPrototypeRuntimeSession("session-1", "request-1"),
        (error: unknown) =>
          error instanceof StructuredPrototypeApiError &&
          error.code === "runtime_replay_version_mismatch" &&
          error.currentHeadSequenceNo === 5 &&
          error.currentStateHash === SHA &&
          error.currentViewModelHash === SHA &&
          error.currentRuntimeCoreBundleHash === SHA &&
          error.resourceUrl === "/api/structured-prototype-runtime-sessions/session-1/reset",
      );
    },
  );
});

test("structured request retry rotation requires a terminal retryable service response", () => {
  const terminalRetryable = new StructuredPrototypeApiError({
    status: 503,
    code: "runtime_worker_timeout",
    message: "runtime worker timed out",
    retryable: true,
    operationId: "operation-1",
    correlationId: "correlation-1",
  });
  const stillRunning = new StructuredPrototypeApiError({
    status: 409,
    code: "operation_in_progress",
    message: "operation is still running",
    retryable: true,
    operationId: "operation-2",
    correlationId: "correlation-2",
  });
  const terminalNonRetryable = new StructuredPrototypeApiError({
    status: 422,
    code: "runtime_scenario_missing",
    message: "scenario does not exist",
    retryable: false,
    operationId: "operation-3",
    correlationId: "correlation-3",
  });

  assert.equal(isTerminalRetryableStructuredPrototypeError(terminalRetryable), true);
  assert.equal(isTerminalRetryableStructuredPrototypeError(stillRunning), false);
  assert.equal(isTerminalRetryableStructuredPrototypeError(terminalNonRetryable), false);
  assert.equal(isTerminalStructuredPrototypeOperationError(terminalRetryable), true);
  assert.equal(isTerminalStructuredPrototypeOperationError(stillRunning), false);
  assert.equal(isTerminalStructuredPrototypeOperationError(terminalNonRetryable), true);
  assert.equal(
    isTerminalRetryableStructuredPrototypeError(new TypeError("network outcome unknown")),
    false,
  );
  assert.equal(
    isTerminalStructuredPrototypeOperationError(new TypeError("network outcome unknown")),
    false,
  );
});

test("structured prototype AI thread, message, and proposal decisions use versioned APIs", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    async (calls) => {
      await createPrototypeAiThread("document/1", {
        contractVersion: 1,
        clientRequestId: "thread-request",
        title: "采购调整",
      });
      await getPrototypeAiThread("thread/1");
      await sendPrototypeAiMessage("thread/1", {
        contractVersion: 1,
        clientMessageId: "message-request",
        draftId: "draft-1",
        expectedHeadSequenceNo: 4,
        expectedDocumentHash: SHA,
        content: "把按钮改成提交采购申请",
        selection: {
          scope: "selection",
          pageId: "page-1",
          selectedNodeIds: ["button-1"],
          flowId: null,
          viewport: "desktop",
        },
      });
      await applyPrototypeAiProposal("run/1", {
        contractVersion: 1,
        clientRequestId: "apply-request",
        expectedHeadSequenceNo: 4,
        expectedDocumentHash: SHA,
      });
      await rejectPrototypeAiProposal("run/2", {
        contractVersion: 1,
        clientRequestId: "reject-request",
      });

      assert.equal(calls[0]?.input, "/api/prototype-documents/document%2F1/ai-threads");
      assert.equal(calls[1]?.input, "/api/prototype-ai-threads/thread%2F1");
      assert.equal(calls[2]?.input, "/api/prototype-ai-threads/thread%2F1/messages");
      const messageCall = calls[2];
      assert.ok(messageCall);
      assert.deepEqual(jsonRequestBody(messageCall), {
        contractVersion: 1,
        clientMessageId: "message-request",
        draftId: "draft-1",
        expectedHeadSequenceNo: 4,
        expectedDocumentHash: SHA,
        content: "把按钮改成提交采购申请",
        selection: {
          scope: "selection",
          pageId: "page-1",
          selectedNodeIds: ["button-1"],
          flowId: null,
          viewport: "desktop",
        },
      });
      assert.equal(calls[3]?.input, "/api/prototype-ai-edit-runs/run%2F1/apply");
      assert.equal(calls[4]?.input, "/api/prototype-ai-edit-runs/run%2F2/reject");
    },
  );
});

test("structured prototype AI errors preserve run and correlation evidence", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          contractVersion: 1,
          correlationId: "ai-correlation-1",
          error: {
            code: "draft_conflict",
            message: "proposal is stale",
            runId: "run-1",
          },
        }),
        { status: 409 },
      ),
    async () => {
      await assert.rejects(
        rejectPrototypeAiProposal("run-1", {
          contractVersion: 1,
          clientRequestId: "reject-request",
        }),
        (error: unknown) =>
          error instanceof StructuredPrototypeAiApiError &&
          error.status === 409 &&
          error.code === "draft_conflict" &&
          error.runId === "run-1" &&
          error.correlationId === "ai-correlation-1",
      );
    },
  );
});
