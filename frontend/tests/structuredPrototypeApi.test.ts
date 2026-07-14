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
  getCurrentStructuredPrototypeDraft,
  getCurrentStructuredPrototypeGenerationJob,
  getStructuredPrototypePublication,
  getPrototypeAiThread,
  getStructuredPrototypeGenerationJob,
  publishStructuredPrototypeDraft,
  rejectPrototypeAiProposal,
  recoverStructuredPrototypeDraft,
  recoverStructuredPrototypeRuntimeSession,
  StructuredPrototypeApiError,
  StructuredPrototypeAiApiError,
  sendPrototypeAiMessage,
} from "../src/lib/api/prototypes";
import { jsonRequestBody, withMockFetch } from "./fetchTestUtils";

const SHA = `sha256:${"a".repeat(64)}`;

test("structured prototype draft recovery sends the client request identity", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    async (calls) => {
      await recoverStructuredPrototypeDraft("draft/one", "request-id");
      assert.equal(
        calls[0]?.input,
        "/api/structured-prototype-drafts/draft%2Fone?clientRequestId=request-id",
      );
      assert.equal(calls[0]?.init, undefined);
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

test("structured prototype generation uses review and acceptance contracts", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    async (calls) => {
      await createStructuredPrototypeGenerationJob("project/one", {
        contractVersion: 1,
        clientRequestId: "create-job",
        mode: "requirements",
        brief: "生成采购审批原型",
      });
      await getCurrentStructuredPrototypeGenerationJob("project/one");
      await getStructuredPrototypeGenerationJob("job/one");
      await confirmStructuredPrototypeGenerationBlueprint("job/one", {
        contractVersion: 1,
        clientRequestId: "confirm-job",
        expectedBlueprintHash: SHA,
      });
      await acceptStructuredPrototypeGenerationCandidate("job/one", {
        contractVersion: 1,
        clientRequestId: "accept-job",
        expectedCandidateObjectHash: SHA,
        expectedPreviewOutputHash: SHA,
      });

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
        expectedBlueprintHash: SHA,
      });
      assert.deepEqual(jsonRequestBody(acceptCall), {
        contractVersion: 1,
        clientRequestId: "accept-job",
        expectedCandidateObjectHash: SHA,
        expectedPreviewOutputHash: SHA,
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
          error.operationId === "operation-1" &&
          error.correlationId === "correlation-1" &&
          error.message.includes("operation operation-1"),
      );
    },
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
