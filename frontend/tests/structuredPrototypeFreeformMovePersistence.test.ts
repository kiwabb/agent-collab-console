import assert from "node:assert/strict";
import test from "node:test";

import { readCompactSource } from "./sourceTestUtils";

test("positioned pointer-up persists one evidence-linked same-parent move batch", () => {
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  const moveStart = studio.indexOf("const movePositionedNode = async");
  const moveEnd = studio.indexOf("const handleFreeformMoveError", moveStart);
  assert.ok(moveStart >= 0 && moveEnd > moveStart);
  const move = studio.slice(moveStart, moveEnd);

  assert.match(move, /evidenceCapture: StructuredPrototypeFreeformMoveEvidenceCapture/);
  assert.match(move, /moveInteraction\.freeformId !== evidenceCapture\.freeformId/);
  assert.match(move, /currentDraft\.documentHash !== moveInteraction\.baseDocumentHash/);
  assert.match(move, /moveInteraction\.previewScale !== replay\.canonicalInput\.previewScale/);
  assert.match(
    move,
    /moveInteraction\.gridSnappingEnabled !== replay\.canonicalInput\.gridSnappingEnabled/,
  );
  assert.match(move, /sameOrderedIds\(moveInteraction\.gridIds, capturedGridIds\)/);
  assert.match(move, /const replay = replayStructuredPrototypeFreeformMove\(evidenceCapture\)/);
  assert.match(move, /x !== replay\.position\.x/);
  assert.match(move, /y !== replay\.position\.y/);
  assert.match(move, /positionedSelection\.parent\.id !== moveInteraction\.freeformId/);
  assert.match(move, /positionedSelection\.parent\.type === "Freeform"/);
  assert.match(move, /sameOrderedIds\(currentGridIds, capturedGridIds\)/);

  assert.match(move, /deltaX = replay\.position\.x - replay\.canonicalInput\.selectionBounds\.x/);
  assert.match(move, /deltaY = replay\.position\.y - replay\.canonicalInput\.selectionBounds\.y/);
  assert.doesNotMatch(move, /evidenceCapture\.finalPosition|evidenceCapture\.diagnostics/);
  assert.match(move, /if \(!projectedItems\.some\(\(item\) => item\.changed\)\)/);
  assert.match(move, /movePositionedSelectionBatch\(/);
  assert.match(move, /projectedItems\.map\(/);
  assert.doesNotMatch(move, /setNodeLayout|setPositionedGroupLayoutBatch|projectedItems\.filter/);

  assert.match(move, /serializeStructuredPrototypeFreeformMoveEvidence\(/);
  for (const field of [
    "documentId: currentDraft.documentId",
    "draftId: currentDraft.draftId",
    "baseHeadSequenceNo: currentDraft.headSequenceNo",
    "baseDocumentHash: currentDraft.documentHash",
  ]) {
    assert.ok(move.includes(field), `missing persisted evidence identity: ${field}`);
  }
  assert.equal([...move.matchAll(/controller\.applyCommands\(/g)].length, 1);
  assert.match(move, /controller\.applyCommands\(\{\.\.\.batch, evidence\}\)/);
});

test("Freeform move production paths enter the arithmetic solver only through replay", () => {
  const replay = readCompactSource(
    "features/prototype/structured/structuredPrototypeFreeformMoveReplay.ts",
  );
  const hook = readCompactSource(
    "features/prototype/structured/useStructuredPrototypeFreeformMove.ts",
  );
  const evidence = readCompactSource(
    "features/prototype/structured/structuredPrototypeFreeformMoveEvidence.ts",
  );
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );

  assert.match(replay, /projection = resolveStructuredPrototypeFreeformMoveSnap\(\{/);
  assert.doesNotMatch(
    [hook, evidence, studio].join("\n"),
    /resolveStructuredPrototypeFreeformMoveSnap/,
  );
  assert.match(hook, /return replayStructuredPrototypeFreeformMove\(\{/);
  assert.match(evidence, /return buildStructuredPrototypeFreeformMoveEvidence\(input\)/);
  assert.match(studio, /const replay = replayStructuredPrototypeFreeformMove\(evidenceCapture\)/);
});
