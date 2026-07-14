import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  PROCUREMENT_IDS,
  PROCUREMENT_RUNTIME_DEFINITION,
  procurementApprovalEventBatches,
} from "../src/features/prototype/runtime/procurementFixture";
import { createInitialRuntimeState } from "../src/features/prototype/runtime/runtimeCore";
import { parseRuntimeDefinition } from "../src/features/prototype/runtime/runtimeInputCodec";
import {
  parsePrototypeRuntimeStateJson,
  serializePrototypeRuntimeState,
} from "../src/features/prototype/runtime/runtimeStateCodec";
import {
  executeRuntimeWorkerRequest,
  parseRuntimeWorkerRequest,
  parseRuntimeWorkerRequestJson,
  RUNTIME_WORKER_PROTOCOL_VERSION,
  RuntimeWorkerProtocolError,
} from "../src/features/prototype/runtime/runtimeWorkerProtocol";

function requestBase(requestId: string) {
  return {
    protocolVersion: RUNTIME_WORKER_PROTOCOL_VERSION,
    requestId,
  } as const;
}

function initializedStateJson(sessionId: string): string {
  return serializePrototypeRuntimeState(
    createInitialRuntimeState(
      PROCUREMENT_RUNTIME_DEFINITION,
      PROCUREMENT_IDS.scenarios.happyPath,
      sessionId,
    ),
  );
}

describe("prototype runtime worker protocol", () => {
  it("initializes, applies, and replays through the shared runtime core", async () => {
    const initialized = await executeRuntimeWorkerRequest(
      parseRuntimeWorkerRequest({
        ...requestBase("worker-initialize"),
        action: "initialize",
        definition: PROCUREMENT_RUNTIME_DEFINITION,
        scenarioId: PROCUREMENT_IDS.scenarios.happyPath,
        sessionId: "compatibility-runtime-session",
      }),
    );
    assert.equal(initialized.action, "initialize");
    const initialState = parsePrototypeRuntimeStateJson(initialized.result.stateJson);
    assert.equal(initialState.sessionId, "compatibility-runtime-session");
    const batches = procurementApprovalEventBatches();
    const firstBatch = batches[0];
    assert.ok(firstBatch, "procurement submit batch must exist");

    const applied = await executeRuntimeWorkerRequest(
      parseRuntimeWorkerRequest({
        ...requestBase("worker-apply"),
        action: "apply",
        definition: PROCUREMENT_RUNTIME_DEFINITION,
        stateJson: initialized.result.stateJson,
        batch: firstBatch,
      }),
    );
    assert.equal(applied.action, "apply");
    assert.equal(applied.result.report.resultStateHash, applied.result.stateHash);
    assert.equal(applied.result.report.resultViewModelHash, applied.result.viewModelHash);
    assert.match(applied.result.eventBatchHash, /^sha256:[0-9a-f]{64}$/u);
    assert.match(applied.result.guardReportHash, /^sha256:[0-9a-f]{64}$/u);
    assert.match(applied.result.effectReportHash, /^sha256:[0-9a-f]{64}$/u);

    const replayed = await executeRuntimeWorkerRequest(
      parseRuntimeWorkerRequest({
        ...requestBase("worker-replay"),
        action: "replay",
        definition: PROCUREMENT_RUNTIME_DEFINITION,
        stateJson: initialized.result.stateJson,
        batches,
      }),
    );
    assert.equal(replayed.action, "replay");
    assert.equal(replayed.result.transitions.length, 3);
    assert.equal(
      replayed.result.final.stateHash,
      "sha256:fdfa2274b2a58f387a527cabd5517e7b5d33cdb5373c168d3e6d5a79da66ff4c",
    );
    assert.equal(
      replayed.result.final.viewModelHash,
      "sha256:83ad5001aa21d47d77b6e521263fd8754d040305dee8f89bfd20612b693e7646",
    );
  });

  it("rejects malformed protocol, extended definitions, and extended events", () => {
    assert.throws(
      () => parseRuntimeWorkerRequestJson("{"),
      (error: unknown) =>
        error instanceof RuntimeWorkerProtocolError &&
        error.code === "runtime_worker_request_invalid_json",
    );
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          unexpected: true,
        }),
      /runtimeDefinition contains unknown field unexpected/u,
    );
    const batch = procurementApprovalEventBatches()[0];
    assert.ok(batch, "procurement submit batch must exist");
    const firstEvent = batch.events[0];
    assert.ok(firstEvent, "procurement submit event must exist");
    assert.throws(
      () =>
        parseRuntimeWorkerRequest({
          ...requestBase("worker-extended-event"),
          action: "apply",
          definition: PROCUREMENT_RUNTIME_DEFINITION,
          stateJson: initializedStateJson("extended-event-session"),
          batch: {
            ...batch,
            events: [{ ...firstEvent, unexpected: true }],
          },
        }),
      /runtimeEventBatch.events\[0\] contains unknown field unexpected/u,
    );
  });

  it("refuses replay tails above the durable limit", () => {
    const batch = procurementApprovalEventBatches()[0];
    assert.ok(batch, "procurement submit batch must exist");
    const initializedState = initializedStateJson("oversized-replay");
    assert.throws(
      () =>
        parseRuntimeWorkerRequest({
          ...requestBase("worker-oversized-replay"),
          action: "replay",
          definition: PROCUREMENT_RUNTIME_DEFINITION,
          stateJson: initializedState,
          batches: Array.from({ length: 201 }, () => batch),
        }),
      (error: unknown) =>
        error instanceof RuntimeWorkerProtocolError &&
        error.code === "runtime_worker_replay_tail_limit_exceeded",
    );
  });
});
