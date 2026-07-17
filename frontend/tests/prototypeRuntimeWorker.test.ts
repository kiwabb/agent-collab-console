import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  PROCUREMENT_IDS,
  PROCUREMENT_RUNTIME_DEFINITION,
  procurementApprovalEventBatches,
} from "./fixtures/procurementRuntimeFixture";
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
      "sha256:a2bbff2041ae041f31701277b637e21767b5b8a86c48fd645879934ad4c64e7f",
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
    const variable = PROCUREMENT_RUNTIME_DEFINITION.variables[0];
    assert.ok(variable, "procurement runtime variable must exist");
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          variables: [
            {
              id: variable.id,
              key: variable.key,
              valueType: variable.valueType,
              nullable: variable.nullable,
              defaultValue: variable.defaultValue,
            },
          ],
        }),
      /runtimeDefinition\.variables\[0\] is missing field entitySchemaId/u,
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

  it("parses optional canonical runtime flow layouts without changing legacy definitions", () => {
    const legacyDefinition = parseRuntimeDefinition(PROCUREMENT_RUNTIME_DEFINITION);
    assert.equal(Object.hasOwn(legacyDefinition, "flowLayout"), false);

    const flowLayout = {
      nodes: [
        { nodeId: "page-create", x: -32_768, y: 32_768 },
        { nodeId: "rule-submit", x: 0, y: 120 },
      ],
    };
    const definition = parseRuntimeDefinition({
      ...PROCUREMENT_RUNTIME_DEFINITION,
      flowLayout,
    });
    assert.deepEqual(definition.flowLayout, flowLayout);
  });

  it("rejects malformed and non-canonical runtime flow layouts", () => {
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          flowLayout: { nodes: [], unexpected: true },
        }),
      /runtimeDefinition\.flowLayout contains unknown field unexpected/u,
    );
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          flowLayout: {},
        }),
      /runtimeDefinition\.flowLayout is missing field nodes/u,
    );
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          flowLayout: {
            nodes: [{ nodeId: "page-create", x: 0, y: 0, unexpected: true }],
          },
        }),
      /runtimeDefinition\.flowLayout\.nodes\[0\] contains unknown field unexpected/u,
    );
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          flowLayout: { nodes: [{ nodeId: "page-create", x: 0 }] },
        }),
      /runtimeDefinition\.flowLayout\.nodes\[0\] is missing field y/u,
    );
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          flowLayout: { nodes: [{ nodeId: "", x: 0, y: 0 }] },
        }),
      /runtimeDefinition\.flowLayout\.nodes\[0\]\.nodeId must not be empty/u,
    );
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          flowLayout: { nodes: [{ nodeId: "page-create", x: 32_769, y: 0 }] },
        }),
      /runtimeDefinition\.flowLayout\.nodes\[0\]\.x must be between -32768 and 32768/u,
    );
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          flowLayout: { nodes: [{ nodeId: "page-create", x: 0.5, y: 0 }] },
        }),
      /runtimeDefinition\.flowLayout\.nodes\[0\]\.x must be a safe integer/u,
    );
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          flowLayout: {
            nodes: [
              { nodeId: "rule-submit", x: 0, y: 0 },
              { nodeId: "page-create", x: 0, y: 0 },
            ],
          },
        }),
      /runtimeDefinition\.flowLayout\.nodes must use canonical nodeId order/u,
    );
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          flowLayout: {
            nodes: [
              { nodeId: "page-create", x: 0, y: 0 },
              { nodeId: "page-create", x: 1, y: 1 },
            ],
          },
        }),
      /runtimeDefinition\.flowLayout\.nodes contains duplicate nodeId page-create/u,
    );
    assert.throws(
      () =>
        parseRuntimeDefinition({
          ...PROCUREMENT_RUNTIME_DEFINITION,
          flowLayout: {
            nodes: Array.from({ length: 301 }, (_, index) => ({
              nodeId: `node-${String(index).padStart(3, "0")}`,
              x: 0,
              y: 0,
            })),
          },
        }),
      /runtimeDefinition\.flowLayout\.nodes exceeds the maximum length of 300/u,
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
