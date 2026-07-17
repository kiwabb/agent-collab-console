import assert from "node:assert/strict";
import test from "node:test";

import {
  StructuredPrototypeApiError,
  type StructuredPrototypeOperationOutcome,
} from "../src/lib/api/prototypes";
import {
  StructuredPrototypeOperationRecoveryPendingError,
  waitForStructuredPrototypeOperationOutcome,
} from "../src/features/prototype/structured/structuredPrototypeOperationRecovery";
import {
  commitSucceededStructuredPrototypeRuntimeResetOutcome,
  readStructuredPrototypeRuntimeRecoveryIssue,
} from "../src/features/prototype/structured/structuredPrototypeRuntimeRecovery";
import {
  beginStructuredPrototypePendingOperation,
  finishStructuredPrototypePendingOperation,
  isStructuredPrototypeStudioPendingOperation,
  loadStructuredPrototypePendingOperation,
  parseStructuredPrototypePendingOperation,
  readStructuredPrototypePendingLockState,
  structuredPrototypeCommandRequestKey,
  structuredPrototypeStorageKey,
  STRUCTURED_PROTOTYPE_PENDING_OPERATION_KEY,
  StructuredPrototypeStorageError,
  type StructuredPrototypePendingOperation,
} from "../src/features/prototype/structured/structuredPrototypeStorage";

const PROJECT_ID = "09cca906-b5e1-4601-aa7a-14fb58f9f06b";
const CLIENT_REQUEST_ID = "11111111-1111-4111-8111-111111111111";
const DRAFT_ID = "33333333-3333-4333-8333-333333333333";
const REPLACEMENT_SESSION_ID = "44444444-4444-4444-8444-444444444444";
const SHA = `sha256:${"a".repeat(64)}`;

function pendingOperation(): StructuredPrototypePendingOperation {
  return {
    contractVersion: 1,
    projectId: PROJECT_ID,
    operationKind: "apply_command_batch",
    resourceKind: "draft",
    resourceId: DRAFT_ID,
    contextId: null,
    clientRequestId: CLIENT_REQUEST_ID,
    requestKey: "command-request:draft-1:7:sha256:document",
    createdAt: "2026-07-16T00:00:00.000Z",
  };
}

function operationOutcome(
  overrides: Partial<StructuredPrototypeOperationOutcome> = {},
): StructuredPrototypeOperationOutcome {
  return {
    contractVersion: 1,
    known: true,
    terminal: true,
    operationId: "operation-1",
    operationKind: "apply_command_batch",
    projectId: PROJECT_ID,
    resourceKind: "draft",
    resourceId: DRAFT_ID,
    clientRequestId: CLIENT_REQUEST_ID,
    correlationId: "correlation-1",
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

class MemoryStorage implements Storage {
  readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

async function withMemoryStorage(run: (storage: MemoryStorage) => Promise<void>): Promise<void> {
  const originalWindow = globalThis.window;
  const storage = new MemoryStorage();
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { localStorage: storage },
  });
  try {
    await run(storage);
  } finally {
    if (originalWindow === undefined) delete (globalThis as { window?: Window }).window;
    else {
      Object.defineProperty(globalThis, "window", {
        configurable: true,
        value: originalWindow,
      });
    }
  }
}

test("pending operation parser rejects cross-project and operation-resource drift", () => {
  assert.throws(
    () => parseStructuredPrototypePendingOperation(pendingOperation(), "another-project"),
    StructuredPrototypeStorageError,
  );
  assert.throws(
    () =>
      parseStructuredPrototypePendingOperation({
        ...pendingOperation(),
        resourceKind: "runtime_session",
      }),
    /resource does not match/,
  );
  assert.throws(
    () => parseStructuredPrototypePendingOperation({ ...pendingOperation(), unexpected: true }),
    /unknown field unexpected/,
  );
  assert.throws(
    () =>
      parseStructuredPrototypePendingOperation({ ...pendingOperation(), resourceId: "draft-1" }),
    /resourceId must be a canonical UUID/,
  );
  assert.throws(
    () => parseStructuredPrototypePendingOperation({ ...pendingOperation(), contextId: "run-1" }),
    /contextId must be null, generation, or a UUID/,
  );
  assert.throws(
    () =>
      parseStructuredPrototypePendingOperation({
        ...pendingOperation(),
        operationKind: "publish",
        contextId: "generation",
      }),
    /context does not match its operation kind/,
  );
  assert.throws(
    () =>
      parseStructuredPrototypePendingOperation({
        ...pendingOperation(),
        createdAt: "2026-07-16 00:00:00",
      }),
    /createdAt must be a canonical UTC timestamp/,
  );
  assert.throws(
    () =>
      parseStructuredPrototypePendingOperation({
        ...pendingOperation(),
        requestKey: "runtime-session-id",
      }),
    /request key does not match its operation/,
  );
});

test("pending request keys are owned by their operation and controller context", () => {
  const cases: StructuredPrototypePendingOperation[] = [
    pendingOperation(),
    { ...pendingOperation(), operationKind: "undo", requestKey: "undo-request:evidence" },
    { ...pendingOperation(), operationKind: "redo", requestKey: "redo-request:evidence" },
    {
      ...pendingOperation(),
      operationKind: "create_runtime_session",
      requestKey: "runtime-create-request:evidence",
    },
    {
      ...pendingOperation(),
      operationKind: "reset_runtime_session",
      resourceKind: "runtime_session",
      requestKey: "runtime-reset-request:evidence",
    },
    {
      ...pendingOperation(),
      operationKind: "apply_command_batch",
      contextId: CLIENT_REQUEST_ID,
      requestKey: "ai-apply-request:evidence",
    },
    {
      ...pendingOperation(),
      operationKind: "create_checkpoint",
      resourceKind: "runtime_session",
      requestKey: "runtime-checkpoint-request:evidence",
    },
    {
      ...pendingOperation(),
      operationKind: "apply_runtime_event",
      resourceKind: "runtime_session",
      requestKey: "runtime-event-request:evidence",
    },
    { ...pendingOperation(), operationKind: "publish", requestKey: "publish-request:evidence" },
    {
      ...pendingOperation(),
      operationKind: "delete_project_prototype",
      resourceKind: "project_prototype",
      resourceId: PROJECT_ID,
      requestKey: "delete-project-request",
    },
    {
      ...pendingOperation(),
      operationKind: "delete_project_prototype",
      resourceKind: "project_prototype",
      resourceId: PROJECT_ID,
      contextId: "generation",
      requestKey: "delete-project-request",
    },
    {
      ...pendingOperation(),
      operationKind: "ai_edit",
      resourceKind: "ai_thread",
      requestKey: "ai-message-request:evidence",
    },
    {
      ...pendingOperation(),
      operationKind: "reject_ai_proposal",
      resourceKind: "ai_edit_run",
      requestKey: "ai-reject-request:evidence",
    },
    {
      ...pendingOperation(),
      operationKind: "generation_job",
      resourceKind: "project",
      resourceId: PROJECT_ID,
      requestKey: "generation-start-request",
    },
    {
      ...pendingOperation(),
      operationKind: "generation_job",
      resourceKind: "generation_job",
      requestKey: "generation-confirm-request:evidence",
    },
    {
      ...pendingOperation(),
      operationKind: "create_document",
      resourceKind: "generation_job",
      requestKey: "generation-accept-request:evidence",
    },
  ];

  for (const descriptor of cases) {
    assert.deepEqual(parseStructuredPrototypePendingOperation(descriptor, PROJECT_ID), descriptor);
  }
  const reset = cases.find((descriptor) => descriptor.operationKind === "reset_runtime_session");
  assert.ok(reset);
  assert.equal(isStructuredPrototypeStudioPendingOperation(reset), true);
});

test("pending operation identity persists until authoritative completion", async () => {
  await withMemoryStorage(async (storage) => {
    const requestKey = structuredPrototypeCommandRequestKey("draft-1", 7, "sha256:document");
    const first = beginStructuredPrototypePendingOperation(PROJECT_ID, {
      operationKind: "apply_command_batch",
      resourceKind: "draft",
      resourceId: DRAFT_ID,
      requestKey,
    });
    const resumed = beginStructuredPrototypePendingOperation(PROJECT_ID, {
      operationKind: "apply_command_batch",
      resourceKind: "draft",
      resourceId: DRAFT_ID,
      requestKey,
    });
    assert.equal(resumed.clientRequestId, first.clientRequestId);
    assert.equal(
      loadStructuredPrototypePendingOperation(PROJECT_ID)?.clientRequestId,
      first.clientRequestId,
    );
    assert.throws(
      () =>
        beginStructuredPrototypePendingOperation(PROJECT_ID, {
          operationKind: "publish",
          resourceKind: "draft",
          resourceId: DRAFT_ID,
          requestKey: "publish-request:evidence",
        }),
      /is still pending/,
    );

    finishStructuredPrototypePendingOperation(PROJECT_ID, first.clientRequestId);
    assert.equal(loadStructuredPrototypePendingOperation(PROJECT_ID), null);
    assert.equal(
      storage.getItem(
        structuredPrototypeStorageKey(PROJECT_ID, STRUCTURED_PROTOTYPE_PENDING_OPERATION_KEY),
      ),
      null,
    );
  });
});

test("a succeeded reset outcome commits its replacement before replay recovery", async () => {
  await withMemoryStorage(async (storage) => {
    const descriptor = beginStructuredPrototypePendingOperation(PROJECT_ID, {
      operationKind: "reset_runtime_session",
      resourceKind: "runtime_session",
      resourceId: DRAFT_ID,
      requestKey: "runtime-reset-request:old-session-evidence",
    });
    const effects: string[] = [];
    const committedReset = commitSucceededStructuredPrototypeRuntimeResetOutcome(
      descriptor,
      operationOutcome({
        operationKind: "reset_runtime_session",
        resourceKind: "runtime_session",
        resourceId: REPLACEMENT_SESSION_ID,
        clientRequestId: descriptor.clientRequestId,
      }),
      {
        writeReplacementPointer: (sessionId) => {
          effects.push(`pointer:${sessionId}`);
          storage.setItem(
            structuredPrototypeStorageKey(PROJECT_ID, "runtime-session-id"),
            sessionId,
          );
        },
        clearPendingOperation: () => {
          effects.push("pending:cleared");
          finishStructuredPrototypePendingOperation(PROJECT_ID, descriptor.clientRequestId);
        },
      },
    );

    assert.deepEqual(committedReset, {
      replacedSessionId: DRAFT_ID,
      replacementSessionId: REPLACEMENT_SESSION_ID,
    });
    assert.deepEqual(effects, [`pointer:${REPLACEMENT_SESSION_ID}`, "pending:cleared"]);
    const coldRefreshSessionId = storage.getItem(
      structuredPrototypeStorageKey(PROJECT_ID, "runtime-session-id"),
    );
    assert.equal(coldRefreshSessionId, REPLACEMENT_SESSION_ID);
    assert.ok(coldRefreshSessionId);
    assert.equal(loadStructuredPrototypePendingOperation(PROJECT_ID), null);
    assert.equal(readStructuredPrototypePendingLockState(PROJECT_ID, () => true).locked, false);

    const replayIssue = readStructuredPrototypeRuntimeRecoveryIssue(
      new StructuredPrototypeApiError({
        status: 409,
        code: "runtime_replay_version_mismatch",
        message: "replacement runtime version changed before replay",
        retryable: false,
        operationId: "replacement-replay-operation",
        correlationId: "replacement-replay-correlation",
        currentHeadSequenceNo: 0,
        currentStateHash: SHA,
        currentViewModelHash: SHA,
        currentRuntimeCoreBundleHash: SHA,
      }),
      coldRefreshSessionId,
    );
    assert.equal(replayIssue?.sessionId, REPLACEMENT_SESSION_ID);
    assert.notEqual(replayIssue?.sessionId, descriptor.resourceId);
    assert.equal(replayIssue?.resetEvidence?.sessionId, REPLACEMENT_SESSION_ID);
  });
});

test("corrupt pending storage stays visible and keeps the controller locked", async () => {
  await withMemoryStorage(async (storage) => {
    const key = structuredPrototypeStorageKey(
      PROJECT_ID,
      STRUCTURED_PROTOTYPE_PENDING_OPERATION_KEY,
    );
    storage.setItem(key, "{broken");
    const state = readStructuredPrototypePendingLockState(PROJECT_ID, () => true);
    assert.equal(state.locked, true);
    assert.ok(state.storageError instanceof StructuredPrototypeStorageError);
    assert.match(state.storageError.message, /not valid JSON/);
    assert.equal(storage.getItem(key), "{broken", "corrupt evidence must not be deleted");
  });
});

test("corrupt request identity fails closed before creating a pending descriptor", async () => {
  await withMemoryStorage(async (storage) => {
    const requestKey = structuredPrototypeCommandRequestKey("draft-1", 7, "sha256:document");
    const identityKey = structuredPrototypeStorageKey(PROJECT_ID, requestKey);
    const pendingKey = structuredPrototypeStorageKey(
      PROJECT_ID,
      STRUCTURED_PROTOTYPE_PENDING_OPERATION_KEY,
    );
    storage.setItem(identityKey, "not-a-uuid");

    assert.throws(
      () =>
        beginStructuredPrototypePendingOperation(PROJECT_ID, {
          operationKind: "apply_command_batch",
          resourceKind: "draft",
          resourceId: DRAFT_ID,
          requestKey,
        }),
      /request identity must be a canonical UUID/,
    );
    assert.equal(storage.getItem(identityKey), "not-a-uuid");
    assert.equal(storage.getItem(pendingKey), null);
  });
});

test("corrupt pending request key cannot delete another project storage entry", async () => {
  await withMemoryStorage(async (storage) => {
    const pendingKey = structuredPrototypeStorageKey(
      PROJECT_ID,
      STRUCTURED_PROTOTYPE_PENDING_OPERATION_KEY,
    );
    const runtimeKey = structuredPrototypeStorageKey(PROJECT_ID, "runtime-session-id");
    storage.setItem(
      pendingKey,
      JSON.stringify({ ...pendingOperation(), requestKey: "runtime-session-id" }),
    );
    storage.setItem(runtimeKey, "runtime-session");

    assert.throws(
      () => finishStructuredPrototypePendingOperation(PROJECT_ID, CLIENT_REQUEST_ID),
      /request key does not match its operation/,
    );
    assert.equal(storage.getItem(runtimeKey), "runtime-session");
    assert.notEqual(storage.getItem(pendingKey), null);
  });
});

test("outcome polling survives unknown and running states before terminal success", async () => {
  const descriptor = pendingOperation();
  const responses: Array<StructuredPrototypeOperationOutcome | Error> = [
    new StructuredPrototypeApiError({
      status: 404,
      code: "operation_outcome_unknown",
      message: "unknown",
      retryable: true,
      operationId: null,
      correlationId: "correlation-unknown",
    }),
    operationOutcome({ terminal: false, status: "running", completedAt: null }),
    operationOutcome(),
  ];
  let reads = 0;
  const outcome = await waitForStructuredPrototypeOperationOutcome(descriptor, {
    maxAttempts: 3,
    intervalMs: 0,
    readOutcome: () => {
      const response = responses[reads];
      reads += 1;
      assert.ok(response);
      return response instanceof Error ? Promise.reject(response) : Promise.resolve(response);
    },
    wait: () => Promise.resolve(),
  });
  assert.equal(outcome.status, "succeeded");
  assert.equal(reads, 3);
});

test("outcome polling exhaustion preserves a pending operation", async () => {
  await withMemoryStorage(async () => {
    const descriptor = beginStructuredPrototypePendingOperation(PROJECT_ID, {
      operationKind: "apply_command_batch",
      resourceKind: "draft",
      resourceId: DRAFT_ID,
      requestKey: "command-request:draft-1:7:sha256:document",
    });
    await assert.rejects(
      waitForStructuredPrototypeOperationOutcome(descriptor, {
        maxAttempts: 2,
        intervalMs: 0,
        readOutcome: () =>
          Promise.resolve(
            operationOutcome({
              clientRequestId: descriptor.clientRequestId,
              terminal: false,
              status: "running",
              completedAt: null,
            }),
          ),
        wait: () => Promise.resolve(),
      }),
      (error: unknown) =>
        error instanceof StructuredPrototypeOperationRecoveryPendingError &&
        error.descriptor.clientRequestId === descriptor.clientRequestId,
    );
    assert.equal(
      loadStructuredPrototypePendingOperation(PROJECT_ID)?.clientRequestId,
      descriptor.clientRequestId,
    );
    assert.equal(readStructuredPrototypePendingLockState(PROJECT_ID, () => true).locked, true);
  });
});

test("known non-terminal outcome remains pending even after the resource is observable", async () => {
  const descriptor = pendingOperation();
  await assert.rejects(
    waitForStructuredPrototypeOperationOutcome(descriptor, {
      maxAttempts: 1,
      readOutcome: () =>
        Promise.resolve(
          operationOutcome({ terminal: false, status: "running", completedAt: null }),
        ),
    }),
    (error: unknown) =>
      error instanceof StructuredPrototypeOperationRecoveryPendingError &&
      error.descriptor.clientRequestId === descriptor.clientRequestId,
  );
});
