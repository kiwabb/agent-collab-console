import assert from "node:assert/strict";
import test from "node:test";

import {
  canonicalRuntimeJson,
  hashRuntimeValue,
} from "../src/features/prototype/runtime/canonical";
import {
  serializeStructuredPrototypeFreeformMoveEvidence,
  type StructuredPrototypeFreeformMoveEvidenceInput,
} from "../src/features/prototype/structured/structuredPrototypeFreeformMoveEvidence";
import {
  attestStructuredPrototypeFreeformMoveEvidenceJson,
  replayStructuredPrototypeFreeformMove,
  StructuredPrototypeFreeformMoveReplayError,
} from "../src/features/prototype/structured/structuredPrototypeFreeformMoveReplay";
import {
  STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION,
  STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH,
} from "../src/features/prototype/structured/structuredPrototypeSnapBuildIdentity";
import type { StructuredPrototypeFreeformGrid } from "../src/features/prototype/structured/types";

const DOCUMENT_ID = "00000000-0000-0000-0000-000000000001";
const DRAFT_ID = "00000000-0000-0000-0000-000000000002";
const FREEFORM_ID = "00000000-0000-0000-0000-000000000003";
const SELECTED_A_ID = "10000000-0000-0000-0000-000000000001";
const SELECTED_Z_ID = "10000000-0000-0000-0000-000000000002";
const SIBLING_A_ID = "20000000-0000-0000-0000-000000000001";
const SIBLING_Z_ID = "20000000-0000-0000-0000-000000000002";

const squareGrid: StructuredPrototypeFreeformGrid = {
  id: "30000000-0000-0000-0000-000000000001",
  version: 1,
  type: "square",
  visible: true,
  snapEnabled: false,
  origin: { x: "0", y: "0" },
  params: {
    size: "8",
    colorTokenKey: "primary",
    opacity: "0.18",
  },
};

const columnGrid: StructuredPrototypeFreeformGrid = {
  id: "30000000-0000-0000-0000-000000000002",
  version: 1,
  type: "columns",
  visible: false,
  snapEnabled: false,
  origin: { x: "4", y: "0" },
  params: {
    count: 12,
    itemSize: null,
    gutter: "4",
    margin: "8",
    alignment: "stretch",
    colorTokenKey: "primary",
    opacity: "0.2",
  },
};

function evidenceInput(): StructuredPrototypeFreeformMoveEvidenceInput {
  return {
    documentId: DOCUMENT_ID,
    draftId: DRAFT_ID,
    baseHeadSequenceNo: 12,
    baseDocumentHash: `sha256:${"a".repeat(64)}`,
    freeformId: FREEFORM_ID,
    selectedNodeIds: [SELECTED_Z_ID, SELECTED_A_ID],
    grids: [squareGrid, columnGrid],
    gridSnappingEnabled: true,
    previewScale: 1,
    selectionBounds: { x: 20, y: 20, width: 10, height: 10 },
    directSiblings: [
      { nodeId: SIBLING_Z_ID, x: 36.00004, y: 20, width: 10, height: 10 },
      { nodeId: SIBLING_A_ID, x: 120, y: 60, width: 10, height: 10 },
    ],
    containerWidth: 200,
    containerHeight: 100,
    requestedDelta: { x: 0, y: 0 },
    bypassSnapping: false,
  };
}

function assertReplayErrorCode(
  error: unknown,
  code: StructuredPrototypeFreeformMoveReplayError["code"],
): boolean {
  assert.ok(error instanceof StructuredPrototypeFreeformMoveReplayError);
  assert.equal(error.code, code);
  return true;
}

test("canonical replay crosses the rounded threshold without mutating caller input", async () => {
  const input = evidenceInput();
  const snapshot = structuredClone(input);
  Object.freeze(input.selectedNodeIds);
  Object.freeze(input.directSiblings);
  Object.freeze(input.grids);

  const replay = replayStructuredPrototypeFreeformMove(input);
  const evidence = await serializeStructuredPrototypeFreeformMoveEvidence(input);

  assert.deepEqual(input, snapshot);
  assert.deepEqual(replay.canonicalInput.selectedNodeIds, [SELECTED_A_ID, SELECTED_Z_ID]);
  assert.deepEqual(
    replay.canonicalInput.directSiblings.map((sibling) => sibling.nodeId),
    [SIBLING_A_ID, SIBLING_Z_ID],
  );
  assert.equal(replay.canonicalInput.directSiblings[1]?.x, 36);
  assert.equal(replay.position.x, 26);
  assert.equal(replay.diagnostics.axisWinners.x, "alignment");
  assert.deepEqual(evidence.finalPosition, { x: "26", y: "20" });
  assert.deepEqual(evidence.rawPosition, { x: "20", y: "20" });
  assert.equal(evidence.directSiblings[1]?.x, "36");
  assert.equal(evidence.axisWinners.x, "alignment");
});

test("serializes deterministic v2 solver identity and preserves grid document order", async () => {
  const input = evidenceInput();
  const first = await serializeStructuredPrototypeFreeformMoveEvidence(input);
  const second = await serializeStructuredPrototypeFreeformMoveEvidence(input);

  assert.deepEqual(first, second);
  assert.equal(first.evidenceVersion, 2);
  assert.equal(first.snapSolverVersion, STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION);
  assert.equal(first.snapSolverSourceHash, STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH);
  assert.deepEqual(
    first.grids.map((grid) => grid.id),
    [squareGrid.id, columnGrid.id],
  );
  assert.notEqual(first.grids, input.grids);
  assert.notEqual(first.grids[0], input.grids[0]);
  assert.equal(first.gridListHash, await hashRuntimeValue(first.grids));
  assert.notEqual(first.gridListHash, await hashRuntimeValue([...first.grids].reverse()));
});

test("canonicalizes every signed numeric solver input before evidence replay", async () => {
  const evidence = await serializeStructuredPrototypeFreeformMoveEvidence({
    ...evidenceInput(),
    previewScale: 1.23456,
    selectionBounds: { x: 20.00001, y: -0, width: 10.00001, height: 10.12345 },
    directSiblings: [],
    requestedDelta: { x: -0.00001, y: 7.65436 },
  });

  assert.equal(evidence.previewScale, "1.2346");
  assert.deepEqual(evidence.selectionBounds, {
    x: "20",
    y: "0",
    width: "10",
    height: "10.1235",
  });
  assert.deepEqual(evidence.requestedDelta, { x: "0", y: "7.6544" });
  assert.deepEqual(evidence.rawPosition, { x: "20", y: "7.6544" });
  assert.notEqual(evidence.selectionBounds.y, "-0");
  assert.notEqual(evidence.requestedDelta.x, "-0");
});

test("bypass uses the canonical raw solve and emits no snap winners or candidates", async () => {
  const input = { ...evidenceInput(), bypassSnapping: true };
  const replay = replayStructuredPrototypeFreeformMove(input);
  const evidence = await serializeStructuredPrototypeFreeformMoveEvidence(input);

  assert.deepEqual(replay.position, replay.diagnostics.rawPosition);
  assert.deepEqual(replay.guides, []);
  assert.deepEqual(replay.spacingGuides, []);
  assert.deepEqual(replay.diagnostics.axisWinners, { x: "raw", y: "raw" });
  assert.deepEqual(replay.diagnostics.candidates, []);
  assert.deepEqual(evidence.finalPosition, evidence.rawPosition);
  assert.deepEqual(evidence.correction, { x: "0", y: "0" });
  assert.deepEqual(evidence.axisWinners, { x: "raw", y: "raw" });
  assert.deepEqual(evidence.candidates, []);
});

test("attests exact canonical evidence bytes and returns their canonical hash", async () => {
  const evidence = await serializeStructuredPrototypeFreeformMoveEvidence(evidenceInput());
  const evidenceJson = canonicalRuntimeJson(evidence);

  assert.deepEqual(await attestStructuredPrototypeFreeformMoveEvidenceJson(evidenceJson), {
    evidenceHash: await hashRuntimeValue(evidence),
  });
  await assert.rejects(
    () => attestStructuredPrototypeFreeformMoveEvidenceJson(`${evidenceJson}\n`),
    (error) => assertReplayErrorCode(error, "evidence_mismatch"),
  );
});

test("attestation refuses solver identity, derived geometry, and shape tampering", async () => {
  const evidence = await serializeStructuredPrototypeFreeformMoveEvidence(evidenceInput());
  const wrongIdentity = {
    ...evidence,
    snapSolverSourceHash: `sha256:${"f".repeat(64)}`,
  };
  await assert.rejects(
    () => attestStructuredPrototypeFreeformMoveEvidenceJson(canonicalRuntimeJson(wrongIdentity)),
    (error) => assertReplayErrorCode(error, "solver_identity_mismatch"),
  );

  const wrongPosition = structuredClone(evidence);
  wrongPosition.finalPosition.x = "27";
  await assert.rejects(
    () => attestStructuredPrototypeFreeformMoveEvidenceJson(canonicalRuntimeJson(wrongPosition)),
    (error) => assertReplayErrorCode(error, "evidence_mismatch"),
  );

  const unknownField = { ...evidence, unexpected: true };
  await assert.rejects(
    () => attestStructuredPrototypeFreeformMoveEvidenceJson(canonicalRuntimeJson(unknownField)),
    (error) => assertReplayErrorCode(error, "invalid_evidence"),
  );

  const tooManyCandidates = structuredClone(evidence);
  const candidate = tooManyCandidates.candidates[0];
  assert.ok(candidate);
  while (tooManyCandidates.candidates.length < 7) {
    tooManyCandidates.candidates.push({
      ...candidate,
      sortKey: `extra-candidate-${tooManyCandidates.candidates.length}`,
      outcome: "farther",
    });
  }
  await assert.rejects(
    () =>
      attestStructuredPrototypeFreeformMoveEvidenceJson(canonicalRuntimeJson(tooManyCandidates)),
    (error) => assertReplayErrorCode(error, "invalid_evidence"),
  );

  const oversizedSortKey = structuredClone(evidence);
  const oversizedSortKeyCandidate = oversizedSortKey.candidates[0];
  assert.ok(oversizedSortKeyCandidate);
  oversizedSortKeyCandidate.sortKey = "x".repeat(513);
  await assert.rejects(
    () => attestStructuredPrototypeFreeformMoveEvidenceJson(canonicalRuntimeJson(oversizedSortKey)),
    (error) => assertReplayErrorCode(error, "invalid_evidence"),
  );
});
