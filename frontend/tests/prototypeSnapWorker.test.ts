import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { canonicalRuntimeJson } from "../src/features/prototype/runtime/canonical";
import {
  serializeStructuredPrototypeFreeformMoveEvidence,
  type StructuredPrototypeFreeformMoveEvidenceInput,
} from "../src/features/prototype/structured/structuredPrototypeFreeformMoveEvidence";
import {
  executeSnapWorkerRequest,
  parseSnapWorkerRequest,
  parseSnapWorkerRequestJson,
  SNAP_WORKER_ATTEST_MANY_LIMIT,
  SNAP_WORKER_MAX_REQUEST_BYTES,
  SNAP_WORKER_PROTOCOL_VERSION,
  SnapWorkerProtocolError,
} from "../src/features/prototype/structured/structuredPrototypeSnapWorkerProtocol";
import {
  STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION,
  STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH,
} from "../src/features/prototype/structured/structuredPrototypeSnapBuildIdentity";
import { isRecord, safeJsonParse } from "../src/lib/utils";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function requestBase(requestId: string) {
  return {
    protocolVersion: SNAP_WORKER_PROTOCOL_VERSION,
    requestId,
  } as const;
}

function utf8Sha256(value: string): string {
  return `sha256:${createHash("sha256").update(value, "utf8").digest("hex")}`;
}

async function evidenceJson(requestedDeltaX: number): Promise<string> {
  const snapInput = {
    selectionBounds: { x: 10, y: 10, width: 20, height: 20 },
    selectedNodeIds: ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"],
    requestedDelta: { x: requestedDeltaX, y: 3 },
    containerWidth: 200,
    containerHeight: 120,
    previewScale: 1,
    directSiblings: [
      {
        nodeId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        x: 40,
        y: 10,
        width: 20,
        height: 20,
      },
    ],
    grids: [],
    gridSnappingEnabled: false,
  } as const;
  const input: StructuredPrototypeFreeformMoveEvidenceInput = {
    documentId: "11111111-1111-4111-8111-111111111111",
    draftId: "22222222-2222-4222-8222-222222222222",
    baseHeadSequenceNo: 7,
    baseDocumentHash: `sha256:${"a".repeat(64)}`,
    freeformId: "33333333-3333-4333-8333-333333333333",
    selectedNodeIds: snapInput.selectedNodeIds,
    grids: snapInput.grids,
    gridSnappingEnabled: snapInput.gridSnappingEnabled,
    previewScale: snapInput.previewScale,
    selectionBounds: snapInput.selectionBounds,
    directSiblings: snapInput.directSiblings,
    containerWidth: snapInput.containerWidth,
    containerHeight: snapInput.containerHeight,
    requestedDelta: snapInput.requestedDelta,
    bypassSnapping: false,
  };
  return canonicalRuntimeJson(await serializeStructuredPrototypeFreeformMoveEvidence(input));
}

describe("prototype snap worker protocol", () => {
  it("bounds one-process recovery input above the legal 200-tail envelope", () => {
    assert.equal(SNAP_WORKER_MAX_REQUEST_BYTES, 32 * 1024 * 1024);
  });

  it("describes an identity independent from the runtime and renderer workers", async () => {
    const response = await executeSnapWorkerRequest(
      parseSnapWorkerRequest({ ...requestBase("snap-describe"), action: "describe" }),
    );

    assert.equal(response.action, "describe");
    assert.equal(response.snapSolverVersion, STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION);
    assert.equal(response.snapSolverSourceHash, STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH);
    assert.deepEqual(response.result, {
      protocolVersion: SNAP_WORKER_PROTOCOL_VERSION,
      snapSolverVersion: STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION,
      snapSolverSourceHash: STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH,
    });
  });

  it("attests canonical evidence and returns its exact UTF-8 SHA-256 hash", async () => {
    const canonicalEvidence = await evidenceJson(8);
    const response = await executeSnapWorkerRequest(
      parseSnapWorkerRequest({
        ...requestBase("snap-attest"),
        action: "attest",
        evidenceJson: canonicalEvidence,
      }),
    );

    assert.equal(response.action, "attest");
    assert.equal(response.result.evidenceHash, utf8Sha256(canonicalEvidence));
  });

  it("separates malformed evidence from deterministic attestation mismatches", async () => {
    await assert.rejects(
      executeSnapWorkerRequest(
        parseSnapWorkerRequest({
          ...requestBase("snap-invalid-evidence"),
          action: "attest",
          evidenceJson: "{",
        }),
      ),
      (error: unknown) =>
        error instanceof SnapWorkerProtocolError && error.code === "snap_evidence_invalid",
    );

    const canonicalEvidence = await evidenceJson(8);
    const mismatchedIdentity = canonicalEvidence.replace(
      STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH,
      `sha256:${"f".repeat(64)}`,
    );
    assert.notEqual(mismatchedIdentity, canonicalEvidence);
    await assert.rejects(
      executeSnapWorkerRequest(
        parseSnapWorkerRequest({
          ...requestBase("snap-identity-mismatch"),
          action: "attest",
          evidenceJson: mismatchedIdentity,
        }),
      ),
      (error: unknown) =>
        error instanceof SnapWorkerProtocolError && error.code === "snap_attestation_mismatch",
    );
  });

  it("attests up to 200 items in input order and rejects the batch atomically", async () => {
    const firstEvidence = await evidenceJson(8);
    const secondEvidence = await evidenceJson(45);
    const response = await executeSnapWorkerRequest(
      parseSnapWorkerRequest({
        ...requestBase("snap-attest-many"),
        action: "attestMany",
        evidenceJsons: [firstEvidence, secondEvidence],
      }),
    );

    assert.equal(response.action, "attestMany");
    assert.deepEqual(response.result.evidenceHashes, [
      utf8Sha256(firstEvidence),
      utf8Sha256(secondEvidence),
    ]);

    await assert.rejects(
      executeSnapWorkerRequest(
        parseSnapWorkerRequest({
          ...requestBase("snap-attest-many-refusal"),
          action: "attestMany",
          evidenceJsons: [firstEvidence, `${secondEvidence}\n`],
        }),
      ),
      (error: unknown) =>
        error instanceof SnapWorkerProtocolError && error.code === "snap_attestation_mismatch",
    );
  });

  it("requires exact request keys and a non-empty attestMany batch capped at 200", () => {
    assert.throws(
      () =>
        parseSnapWorkerRequest({
          ...requestBase("snap-extra-key"),
          action: "describe",
          extra: true,
        }),
      (error: unknown) =>
        error instanceof SnapWorkerProtocolError && error.code === "snap_worker_request_invalid",
    );
    assert.throws(
      () => parseSnapWorkerRequestJson("{"),
      (error: unknown) =>
        error instanceof SnapWorkerProtocolError &&
        error.code === "snap_worker_request_invalid_json",
    );
    assert.throws(
      () =>
        parseSnapWorkerRequest({
          ...requestBase("snap-attest-extra-key"),
          action: "attest",
          evidenceJson: "{}",
          extra: true,
        }),
      (error: unknown) =>
        error instanceof SnapWorkerProtocolError && error.code === "snap_worker_request_invalid",
    );
    assert.throws(
      () =>
        parseSnapWorkerRequest({
          ...requestBase("snap-attest-many-extra-key"),
          action: "attestMany",
          evidenceJsons: ["{}"],
          extra: true,
        }),
      (error: unknown) =>
        error instanceof SnapWorkerProtocolError && error.code === "snap_worker_request_invalid",
    );
    assert.throws(
      () =>
        parseSnapWorkerRequest({
          ...requestBase("snap-empty-batch"),
          action: "attestMany",
          evidenceJsons: [],
        }),
      /must contain between 1 and 200 items/u,
    );
    assert.throws(
      () =>
        parseSnapWorkerRequest({
          ...requestBase("snap-oversized-batch"),
          action: "attestMany",
          evidenceJsons: Array.from({ length: SNAP_WORKER_ATTEST_MANY_LIMIT + 1 }, () => "{}"),
        }),
      /must contain between 1 and 200 items/u,
    );
    const maximumBatch = parseSnapWorkerRequest({
      ...requestBase("snap-maximum-batch"),
      action: "attestMany",
      evidenceJsons: Array.from({ length: SNAP_WORKER_ATTEST_MANY_LIMIT }, () => "{}"),
    });
    assert.equal(maximumBatch.action, "attestMany");
    assert.equal(maximumBatch.evidenceJsons.length, SNAP_WORKER_ATTEST_MANY_LIMIT);

    assert.throws(
      () =>
        parseSnapWorkerRequest({
          ...requestBase("snap-sparse-batch"),
          action: "attestMany",
          evidenceJsons: new Array<string>(1),
        }),
      /request\.evidenceJsons\[0\] must be a non-empty well-formed string/u,
    );
  });

  it("emits exactly one bounded CLI response", async () => {
    const canonicalEvidence = await evidenceJson(8);
    const processResult = spawnSync(
      process.execPath,
      ["--import", "tsx", "scripts/prototype-snap-worker.ts"],
      {
        cwd: frontendRoot,
        encoding: "utf8",
        input: JSON.stringify({
          ...requestBase("snap-cli"),
          action: "attest",
          evidenceJson: canonicalEvidence,
        }),
        maxBuffer: 1024 * 1024,
      },
    );

    assert.equal(processResult.status, 0, processResult.stderr);
    assert.equal(processResult.stderr, "");
    const lines = processResult.stdout.trimEnd().split("\n");
    assert.equal(lines.length, 1);
    assert.ok(Buffer.byteLength(lines[0] ?? "", "utf8") <= 64 * 1024);
    const parsed = safeJsonParse(lines[0] ?? "");
    assert.ok(isRecord(parsed));
    assert.equal(parsed["status"], "ok");
    assert.equal(parsed["action"], "attest");
    assert.ok(isRecord(parsed["result"]));
    assert.equal(parsed["result"]["evidenceHash"], utf8Sha256(canonicalEvidence));
  });
});
