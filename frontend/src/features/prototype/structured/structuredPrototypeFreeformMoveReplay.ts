import { isRecord, safeJsonParse } from "@/lib/utils";

import { canonicalRuntimeJson, hashRuntimeValue } from "../runtime/canonical";
import type { StructuredPrototypeFreeformMoveEvidenceInput } from "./structuredPrototypeFreeformMoveEvidence";
import { cloneStructuredPrototypeFreeformGrids } from "./structuredPrototypeFreeformGrids";
import {
  resolveStructuredPrototypeFreeformMoveSnap,
  type StructuredPrototypeFreeformMoveSnapDiagnostics,
  type StructuredPrototypeFreeformMoveSnapResult,
  type StructuredPrototypeFreeformSnapBounds,
  type StructuredPrototypeFreeformSnapDiagnosticCandidate,
  type StructuredPrototypeFreeformSnapPoint,
  type StructuredPrototypeFreeformSnapSibling,
} from "./structuredPrototypeSnapping";
import {
  STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION,
  STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH,
} from "./structuredPrototypeSnapBuildIdentity";
import type {
  StructuredPrototypeFreeformGrid,
  StructuredPrototypeFreeformMoveEvidence,
  StructuredPrototypeFreeformMoveEvidenceBounds,
  StructuredPrototypeFreeformMoveEvidenceCandidate,
  StructuredPrototypeFreeformMoveEvidencePoint,
  StructuredPrototypeFreeformMoveEvidenceSibling,
} from "./types";

const SHA256_PATTERN = /^sha256:[0-9a-f]{64}$/u;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const SIGNED_DECIMAL_PATTERN = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$/u;
const NON_NEGATIVE_DECIMAL_PATTERN = /^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$/u;
const TECHNICAL_KEY_PATTERN = /^[a-z][a-z0-9-]{0,63}$/u;

export type StructuredPrototypeFreeformMoveReplayErrorCode =
  | "invalid_replay_input"
  | "invalid_evidence_json"
  | "invalid_evidence"
  | "solver_identity_mismatch"
  | "evidence_mismatch";

export class StructuredPrototypeFreeformMoveReplayError extends Error {
  readonly code: StructuredPrototypeFreeformMoveReplayErrorCode;

  constructor(code: StructuredPrototypeFreeformMoveReplayErrorCode, message: string) {
    super(message);
    this.name = "StructuredPrototypeFreeformMoveReplayError";
    this.code = code;
  }
}

export interface StructuredPrototypeFreeformMoveReplayInput {
  readonly selectionBounds: Readonly<StructuredPrototypeFreeformSnapBounds>;
  readonly selectedNodeIds: readonly string[];
  readonly requestedDelta: Readonly<StructuredPrototypeFreeformSnapPoint>;
  readonly containerWidth: number;
  readonly containerHeight: number;
  readonly previewScale: number;
  readonly directSiblings: readonly Readonly<StructuredPrototypeFreeformSnapSibling>[];
  readonly grids: readonly Readonly<StructuredPrototypeFreeformGrid>[];
  readonly gridSnappingEnabled: boolean;
  readonly bypassSnapping: boolean;
}

export interface CanonicalStructuredPrototypeFreeformMoveReplayInput extends StructuredPrototypeFreeformMoveReplayInput {
  readonly selectionBounds: StructuredPrototypeFreeformSnapBounds;
  readonly selectedNodeIds: readonly string[];
  readonly requestedDelta: StructuredPrototypeFreeformSnapPoint;
  readonly directSiblings: readonly StructuredPrototypeFreeformSnapSibling[];
  readonly grids: readonly StructuredPrototypeFreeformGrid[];
}

export interface StructuredPrototypeFreeformMoveReplayResult extends StructuredPrototypeFreeformMoveSnapResult {
  readonly canonicalInput: CanonicalStructuredPrototypeFreeformMoveReplayInput;
}

function replayError(
  code: StructuredPrototypeFreeformMoveReplayErrorCode,
  message: string,
): StructuredPrototypeFreeformMoveReplayError {
  return new StructuredPrototypeFreeformMoveReplayError(code, message);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function canonicalSignedNumber(value: number, path: string): number {
  if (!Number.isFinite(value)) {
    throw replayError("invalid_replay_input", `${path} must be finite`);
  }
  const canonical = Number(value.toFixed(4));
  return Object.is(canonical, -0) ? 0 : canonical;
}

function canonicalPoint(
  point: Readonly<StructuredPrototypeFreeformSnapPoint>,
  path: string,
): StructuredPrototypeFreeformSnapPoint {
  return {
    x: canonicalSignedNumber(point.x, `${path}.x`),
    y: canonicalSignedNumber(point.y, `${path}.y`),
  };
}

function canonicalBounds(
  bounds: Readonly<StructuredPrototypeFreeformSnapBounds>,
  path: string,
): StructuredPrototypeFreeformSnapBounds {
  return {
    ...canonicalPoint(bounds, path),
    width: canonicalSignedNumber(bounds.width, `${path}.width`),
    height: canonicalSignedNumber(bounds.height, `${path}.height`),
  };
}

function compareCanonicalIds(left: string, right: string): number {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

export function canonicalizeStructuredPrototypeFreeformMoveReplayInput(
  input: StructuredPrototypeFreeformMoveReplayInput,
): CanonicalStructuredPrototypeFreeformMoveReplayInput {
  const selectedNodeIds = [...input.selectedNodeIds].sort(compareCanonicalIds);
  const directSiblings = input.directSiblings
    .map((sibling) => ({
      nodeId: sibling.nodeId,
      ...canonicalBounds(sibling, `directSiblings.${sibling.nodeId}`),
    }))
    .sort((left, right) => compareCanonicalIds(left.nodeId, right.nodeId));

  return {
    selectionBounds: canonicalBounds(input.selectionBounds, "selectionBounds"),
    selectedNodeIds,
    requestedDelta: canonicalPoint(input.requestedDelta, "requestedDelta"),
    containerWidth: canonicalSignedNumber(input.containerWidth, "containerWidth"),
    containerHeight: canonicalSignedNumber(input.containerHeight, "containerHeight"),
    previewScale: canonicalSignedNumber(input.previewScale, "previewScale"),
    directSiblings,
    grids: cloneStructuredPrototypeFreeformGrids(input.grids),
    gridSnappingEnabled: input.gridSnappingEnabled,
    bypassSnapping: input.bypassSnapping,
  };
}

function bypassProjection(
  canonicalInput: CanonicalStructuredPrototypeFreeformMoveReplayInput,
  projection: StructuredPrototypeFreeformMoveSnapResult,
): StructuredPrototypeFreeformMoveSnapResult {
  const position = { ...projection.diagnostics.rawPosition };
  const diagnostics: StructuredPrototypeFreeformMoveSnapDiagnostics = {
    rawPosition: { ...position },
    threshold: projection.diagnostics.threshold,
    axisWinners: { x: "raw", y: "raw" },
    candidates: [],
  };
  return {
    position,
    delta: {
      x: position.x - canonicalInput.selectionBounds.x,
      y: position.y - canonicalInput.selectionBounds.y,
    },
    guides: [],
    spacingGuides: [],
    diagnostics,
  };
}

export function replayStructuredPrototypeFreeformMove(
  input: StructuredPrototypeFreeformMoveReplayInput,
): StructuredPrototypeFreeformMoveReplayResult {
  const canonicalInput = canonicalizeStructuredPrototypeFreeformMoveReplayInput(input);
  let projection: StructuredPrototypeFreeformMoveSnapResult;
  try {
    projection = resolveStructuredPrototypeFreeformMoveSnap({
      selectionBounds: canonicalInput.selectionBounds,
      selectedNodeIds: canonicalInput.selectedNodeIds,
      requestedDelta: canonicalInput.requestedDelta,
      containerWidth: canonicalInput.containerWidth,
      containerHeight: canonicalInput.containerHeight,
      previewScale: canonicalInput.previewScale,
      directSiblings: canonicalInput.directSiblings,
      grids: canonicalInput.grids,
      gridSnappingEnabled: canonicalInput.gridSnappingEnabled,
    });
  } catch (error) {
    if (error instanceof StructuredPrototypeFreeformMoveReplayError) throw error;
    throw replayError(
      "invalid_replay_input",
      `Freeform move replay failed: ${errorMessage(error)}`,
    );
  }
  const resolved = canonicalInput.bypassSnapping
    ? bypassProjection(canonicalInput, projection)
    : projection;
  return { ...resolved, canonicalInput };
}

function canonicalSignedDecimal(value: number): string {
  const canonical = canonicalSignedNumber(value, "evidence decimal");
  return String(canonical);
}

function serializePoint(
  point: Readonly<StructuredPrototypeFreeformSnapPoint>,
): StructuredPrototypeFreeformMoveEvidencePoint {
  return {
    x: canonicalSignedDecimal(point.x),
    y: canonicalSignedDecimal(point.y),
  };
}

function serializeBounds(
  bounds: Readonly<StructuredPrototypeFreeformSnapBounds>,
): StructuredPrototypeFreeformMoveEvidenceBounds {
  return {
    ...serializePoint(bounds),
    width: canonicalSignedDecimal(bounds.width),
    height: canonicalSignedDecimal(bounds.height),
  };
}

function serializeSibling(
  sibling: Readonly<StructuredPrototypeFreeformSnapSibling>,
): StructuredPrototypeFreeformMoveEvidenceSibling {
  return {
    nodeId: sibling.nodeId,
    ...serializeBounds(sibling),
  };
}

function serializeCandidateCommon(candidate: StructuredPrototypeFreeformSnapDiagnosticCandidate) {
  return {
    axis: candidate.axis,
    position: canonicalSignedDecimal(candidate.position),
    correction: canonicalSignedDecimal(candidate.correction),
    distance: canonicalSignedDecimal(candidate.distance),
    sortKey: candidate.sortKey,
    outcome: candidate.outcome,
  };
}

function serializeCandidate(
  candidate: StructuredPrototypeFreeformSnapDiagnosticCandidate,
): StructuredPrototypeFreeformMoveEvidenceCandidate {
  const common = serializeCandidateCommon(candidate);
  switch (candidate.source) {
    case "alignment":
      return {
        source: candidate.source,
        ...common,
        coordinate: canonicalSignedDecimal(candidate.coordinate),
        movingAnchor: candidate.movingAnchor,
        targetAnchor: candidate.targetAnchor,
        targetKind: candidate.targetKind,
        targetNodeId: candidate.targetNodeId,
      };
    case "spacing":
      return {
        source: candidate.source,
        ...common,
        placement: candidate.placement,
        gap: canonicalSignedDecimal(candidate.gap),
        referenceNodeIds: [candidate.referenceNodeIds[0], candidate.referenceNodeIds[1]],
      };
    case "grid":
      return {
        source: candidate.source,
        ...common,
        gridId: candidate.gridId,
        gridType: candidate.gridType,
        gridLineIndex: candidate.gridLineIndex,
        coordinate: canonicalSignedDecimal(candidate.coordinate),
        movingAnchor: candidate.movingAnchor,
      };
  }
}

export async function buildStructuredPrototypeFreeformMoveEvidence(
  input: StructuredPrototypeFreeformMoveEvidenceInput,
): Promise<StructuredPrototypeFreeformMoveEvidence> {
  const replay = replayStructuredPrototypeFreeformMove(input);
  const canonicalInput = replay.canonicalInput;
  const grids = cloneStructuredPrototypeFreeformGrids(canonicalInput.grids);
  const rawPosition = replay.diagnostics.rawPosition;
  const finalPosition = replay.position;

  return {
    evidenceVersion: 2,
    kind: "freeformMove",
    snapSolverVersion: STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION,
    snapSolverSourceHash: STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH,
    documentId: input.documentId,
    draftId: input.draftId,
    freeformId: input.freeformId,
    baseHeadSequenceNo: input.baseHeadSequenceNo,
    baseDocumentHash: input.baseDocumentHash,
    selectedNodeIds: [...canonicalInput.selectedNodeIds],
    grids,
    gridListHash: await hashRuntimeValue(grids),
    gridSnappingEnabled: canonicalInput.gridSnappingEnabled,
    previewScale: canonicalSignedDecimal(canonicalInput.previewScale),
    clientThreshold: "6",
    selectionBounds: serializeBounds(canonicalInput.selectionBounds),
    directSiblings: canonicalInput.directSiblings.map((sibling) => serializeSibling(sibling)),
    containerSize: {
      width: canonicalSignedDecimal(canonicalInput.containerWidth),
      height: canonicalSignedDecimal(canonicalInput.containerHeight),
    },
    requestedDelta: serializePoint(canonicalInput.requestedDelta),
    rawPosition: serializePoint(rawPosition),
    finalPosition: serializePoint(finalPosition),
    correction: serializePoint({
      x: finalPosition.x - rawPosition.x,
      y: finalPosition.y - rawPosition.y,
    }),
    bypassSnapping: canonicalInput.bypassSnapping,
    axisWinners: { ...replay.diagnostics.axisWinners },
    candidates: replay.diagnostics.candidates.map((candidate) => serializeCandidate(candidate)),
    terminalReason: "pointerup",
  };
}

function invalidEvidence(message: string): never {
  throw replayError("invalid_evidence", message);
}

function evidenceRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) invalidEvidence(`${path} must be an object`);
  return value;
}

function exactKeys(record: Record<string, unknown>, keys: readonly string[], path: string): void {
  const expected = new Set(keys);
  for (const key of Object.keys(record)) {
    if (!expected.has(key)) invalidEvidence(`${path} contains unknown field ${key}`);
  }
  for (const key of keys) {
    if (!Object.hasOwn(record, key)) invalidEvidence(`${path} is missing field ${key}`);
  }
}

function evidenceString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) {
    invalidEvidence(`${path} must be a non-empty string`);
  }
  return value;
}

function evidenceBoundedString(value: unknown, maximumLength: number, path: string): string {
  const parsed = evidenceString(value, path);
  if (Array.from(parsed).length > maximumLength) {
    invalidEvidence(`${path} must contain at most ${maximumLength} characters`);
  }
  return parsed;
}

function evidenceEntityId(value: unknown, path: string): string {
  const parsed = evidenceString(value, path);
  if (!UUID_PATTERN.test(parsed)) invalidEvidence(`${path} must be a canonical UUID`);
  return parsed;
}

function evidenceSha256(value: unknown, path: string): string {
  const parsed = evidenceString(value, path);
  if (!SHA256_PATTERN.test(parsed)) invalidEvidence(`${path} must be a SHA-256 value`);
  return parsed;
}

function evidenceBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") invalidEvidence(`${path} must be a boolean`);
  return value;
}

function evidenceInteger(value: unknown, minimum: number, maximum: number, path: string): number {
  if (
    !Number.isSafeInteger(value) ||
    typeof value !== "number" ||
    value < minimum ||
    value > maximum
  ) {
    invalidEvidence(`${path} must be an integer from ${minimum} to ${maximum}`);
  }
  return value;
}

function evidenceLiteral<const Values extends readonly string[]>(
  value: unknown,
  values: Values,
  path: string,
): Values[number] {
  for (const candidate of values) {
    if (value === candidate) return candidate;
  }
  invalidEvidence(`${path} is unsupported`);
}

function evidenceSignedDecimal(value: unknown, path: string): string {
  const parsed = evidenceString(value, path);
  if (!SIGNED_DECIMAL_PATTERN.test(parsed) || (parsed.startsWith("-") && Number(parsed) === 0)) {
    invalidEvidence(`${path} must be a canonical signed decimal`);
  }
  if (!Number.isFinite(Number(parsed))) invalidEvidence(`${path} must be finite`);
  return parsed;
}

function evidenceNonNegativeDecimal(value: unknown, path: string): string {
  const parsed = evidenceString(value, path);
  if (!NON_NEGATIVE_DECIMAL_PATTERN.test(parsed) || !Number.isFinite(Number(parsed))) {
    invalidEvidence(`${path} must be a canonical non-negative decimal`);
  }
  return parsed;
}

function evidencePositiveDecimal(value: unknown, path: string): string {
  const parsed = evidenceNonNegativeDecimal(value, path);
  if (Number(parsed) <= 0) invalidEvidence(`${path} must be positive`);
  return parsed;
}

function evidenceTechnicalKey(value: unknown, path: string): string {
  const parsed = evidenceString(value, path);
  if (!TECHNICAL_KEY_PATTERN.test(parsed)) invalidEvidence(`${path} must be a technical key`);
  return parsed;
}

function evidenceArray(value: unknown, maximumLength: number, path: string): unknown[] {
  if (!Array.isArray(value) || value.length > maximumLength) {
    invalidEvidence(`${path} must be an array with at most ${maximumLength} items`);
  }
  return value;
}

function parseEvidencePoint(
  value: unknown,
  path: string,
): StructuredPrototypeFreeformMoveEvidencePoint {
  const record = evidenceRecord(value, path);
  exactKeys(record, ["x", "y"], path);
  return {
    x: evidenceSignedDecimal(record["x"], `${path}.x`),
    y: evidenceSignedDecimal(record["y"], `${path}.y`),
  };
}

function parseEvidenceBounds(
  value: unknown,
  path: string,
): StructuredPrototypeFreeformMoveEvidenceBounds {
  const record = evidenceRecord(value, path);
  exactKeys(record, ["x", "y", "width", "height"], path);
  return {
    x: evidenceSignedDecimal(record["x"], `${path}.x`),
    y: evidenceSignedDecimal(record["y"], `${path}.y`),
    width: evidencePositiveDecimal(record["width"], `${path}.width`),
    height: evidencePositiveDecimal(record["height"], `${path}.height`),
  };
}

function parseEvidenceSibling(
  value: unknown,
  path: string,
): StructuredPrototypeFreeformMoveEvidenceSibling {
  const record = evidenceRecord(value, path);
  exactKeys(record, ["nodeId", "x", "y", "width", "height"], path);
  return {
    nodeId: evidenceEntityId(record["nodeId"], `${path}.nodeId`),
    x: evidenceSignedDecimal(record["x"], `${path}.x`),
    y: evidenceSignedDecimal(record["y"], `${path}.y`),
    width: evidencePositiveDecimal(record["width"], `${path}.width`),
    height: evidencePositiveDecimal(record["height"], `${path}.height`),
  };
}

function parseEvidenceOrigin(value: unknown, path: string): { x: string; y: string } {
  const record = evidenceRecord(value, path);
  exactKeys(record, ["x", "y"], path);
  const x = evidenceNonNegativeDecimal(record["x"], `${path}.x`);
  const y = evidenceNonNegativeDecimal(record["y"], `${path}.y`);
  if (Number(x) > 4096 || Number(y) > 4096) invalidEvidence(`${path} exceeds 4096`);
  return { x, y };
}

function parseEvidenceGrid(value: unknown, path: string): StructuredPrototypeFreeformGrid {
  const record = evidenceRecord(value, path);
  exactKeys(record, ["id", "version", "type", "visible", "snapEnabled", "origin", "params"], path);
  const id = evidenceEntityId(record["id"], `${path}.id`);
  if (record["version"] !== 1) invalidEvidence(`${path}.version is unsupported`);
  const visible = evidenceBoolean(record["visible"], `${path}.visible`);
  const snapEnabled = evidenceBoolean(record["snapEnabled"], `${path}.snapEnabled`);
  const origin = parseEvidenceOrigin(record["origin"], `${path}.origin`);
  const type = evidenceLiteral(
    record["type"],
    ["square", "columns", "rows"] as const,
    `${path}.type`,
  );
  const params = evidenceRecord(record["params"], `${path}.params`);
  if (type === "square") {
    exactKeys(params, ["size", "colorTokenKey", "opacity"], `${path}.params`);
    const size = evidencePositiveDecimal(params["size"], `${path}.params.size`);
    const opacity = evidenceNonNegativeDecimal(params["opacity"], `${path}.params.opacity`);
    if (Number(size) > 4096 || Number(opacity) > 1)
      invalidEvidence(`${path}.params is out of range`);
    return {
      id,
      version: 1,
      type,
      visible,
      snapEnabled,
      origin,
      params: {
        size,
        colorTokenKey: evidenceTechnicalKey(
          params["colorTokenKey"],
          `${path}.params.colorTokenKey`,
        ),
        opacity,
      },
    };
  }
  exactKeys(
    params,
    ["count", "itemSize", "gutter", "margin", "alignment", "colorTokenKey", "opacity"],
    `${path}.params`,
  );
  const alignment = evidenceLiteral(
    params["alignment"],
    ["stretch", "start", "center", "end"] as const,
    `${path}.params.alignment`,
  );
  const itemSize =
    params["itemSize"] === null
      ? null
      : evidencePositiveDecimal(params["itemSize"], `${path}.params.itemSize`);
  if ((alignment === "stretch") !== (itemSize === null)) {
    invalidEvidence(`${path}.params.itemSize does not match alignment`);
  }
  const gutter = evidenceNonNegativeDecimal(params["gutter"], `${path}.params.gutter`);
  const margin = evidenceNonNegativeDecimal(params["margin"], `${path}.params.margin`);
  const opacity = evidenceNonNegativeDecimal(params["opacity"], `${path}.params.opacity`);
  if (
    (itemSize !== null && Number(itemSize) > 4096) ||
    Number(gutter) > 4096 ||
    Number(margin) > 4096 ||
    Number(opacity) > 1
  ) {
    invalidEvidence(`${path}.params is out of range`);
  }
  return {
    id,
    version: 1,
    type,
    visible,
    snapEnabled,
    origin,
    params: {
      count: evidenceInteger(params["count"], 1, 24, `${path}.params.count`),
      itemSize,
      gutter,
      margin,
      alignment,
      colorTokenKey: evidenceTechnicalKey(params["colorTokenKey"], `${path}.params.colorTokenKey`),
      opacity,
    },
  };
}

function parseCandidateCommon(record: Record<string, unknown>, path: string) {
  return {
    axis: evidenceLiteral(record["axis"], ["x", "y"] as const, `${path}.axis`),
    position: evidenceSignedDecimal(record["position"], `${path}.position`),
    correction: evidenceSignedDecimal(record["correction"], `${path}.correction`),
    distance: evidenceNonNegativeDecimal(record["distance"], `${path}.distance`),
    sortKey: evidenceBoundedString(record["sortKey"], 512, `${path}.sortKey`),
    outcome: evidenceLiteral(
      record["outcome"],
      ["winner", "farther", "tiePriority", "crossAxisInvalid"] as const,
      `${path}.outcome`,
    ),
  };
}

function parseEvidenceCandidate(
  value: unknown,
  path: string,
): StructuredPrototypeFreeformMoveEvidenceCandidate {
  const record = evidenceRecord(value, path);
  const source = evidenceLiteral(
    record["source"],
    ["alignment", "spacing", "grid"] as const,
    `${path}.source`,
  );
  const commonKeys = ["source", "axis", "position", "correction", "distance", "sortKey", "outcome"];
  if (source === "alignment") {
    exactKeys(
      record,
      [...commonKeys, "coordinate", "movingAnchor", "targetAnchor", "targetKind", "targetNodeId"],
      path,
    );
    const common = parseCandidateCommon(record, path);
    const targetKind = evidenceLiteral(
      record["targetKind"],
      ["container", "sibling"] as const,
      `${path}.targetKind`,
    );
    const targetNodeId =
      record["targetNodeId"] === null
        ? null
        : evidenceEntityId(record["targetNodeId"], `${path}.targetNodeId`);
    if ((targetKind === "container") !== (targetNodeId === null)) {
      invalidEvidence(`${path}.targetNodeId does not match targetKind`);
    }
    return {
      source,
      ...common,
      coordinate: evidenceSignedDecimal(record["coordinate"], `${path}.coordinate`),
      movingAnchor: evidenceLiteral(
        record["movingAnchor"],
        ["left", "center", "right", "top", "middle", "bottom"] as const,
        `${path}.movingAnchor`,
      ),
      targetAnchor: evidenceLiteral(
        record["targetAnchor"],
        ["left", "center", "right", "top", "middle", "bottom"] as const,
        `${path}.targetAnchor`,
      ),
      targetKind,
      targetNodeId,
    };
  }
  if (source === "spacing") {
    exactKeys(record, [...commonKeys, "placement", "gap", "referenceNodeIds"], path);
    const common = parseCandidateCommon(record, path);
    const references = evidenceArray(record["referenceNodeIds"], 2, `${path}.referenceNodeIds`);
    if (references.length !== 2) invalidEvidence(`${path}.referenceNodeIds must contain two IDs`);
    const first = evidenceEntityId(references[0], `${path}.referenceNodeIds[0]`);
    const second = evidenceEntityId(references[1], `${path}.referenceNodeIds[1]`);
    if (first === second) invalidEvidence(`${path}.referenceNodeIds must be unique`);
    return {
      source,
      ...common,
      placement: evidenceLiteral(
        record["placement"],
        ["before", "between", "after"] as const,
        `${path}.placement`,
      ),
      gap: evidencePositiveDecimal(record["gap"], `${path}.gap`),
      referenceNodeIds: [first, second],
    };
  }
  exactKeys(
    record,
    [...commonKeys, "gridId", "gridType", "gridLineIndex", "coordinate", "movingAnchor"],
    path,
  );
  const common = parseCandidateCommon(record, path);
  return {
    source,
    ...common,
    gridId: evidenceEntityId(record["gridId"], `${path}.gridId`),
    gridType: evidenceLiteral(
      record["gridType"],
      ["square", "columns", "rows"] as const,
      `${path}.gridType`,
    ),
    gridLineIndex: evidenceInteger(
      record["gridLineIndex"],
      0,
      Number.MAX_SAFE_INTEGER,
      `${path}.gridLineIndex`,
    ),
    coordinate: evidenceSignedDecimal(record["coordinate"], `${path}.coordinate`),
    movingAnchor: evidenceLiteral(
      record["movingAnchor"],
      ["left", "center", "right", "top", "middle", "bottom"] as const,
      `${path}.movingAnchor`,
    ),
  };
}

function requireCanonicalSortedUnique(values: readonly string[], path: string): void {
  const unique = new Set(values);
  if (unique.size !== values.length) invalidEvidence(`${path} must contain unique values`);
  for (let index = 1; index < values.length; index += 1) {
    const previous = values[index - 1];
    const current = values[index];
    if (
      previous === undefined ||
      current === undefined ||
      compareCanonicalIds(previous, current) >= 0
    ) {
      invalidEvidence(`${path} must use canonical lexical order`);
    }
  }
}

export function parseStructuredPrototypeFreeformMoveEvidence(
  value: unknown,
): StructuredPrototypeFreeformMoveEvidence {
  const record = evidenceRecord(value, "evidence");
  exactKeys(
    record,
    [
      "evidenceVersion",
      "kind",
      "snapSolverVersion",
      "snapSolverSourceHash",
      "documentId",
      "draftId",
      "freeformId",
      "baseHeadSequenceNo",
      "baseDocumentHash",
      "selectedNodeIds",
      "grids",
      "gridListHash",
      "gridSnappingEnabled",
      "previewScale",
      "clientThreshold",
      "selectionBounds",
      "directSiblings",
      "containerSize",
      "requestedDelta",
      "rawPosition",
      "finalPosition",
      "correction",
      "bypassSnapping",
      "axisWinners",
      "candidates",
      "terminalReason",
    ],
    "evidence",
  );
  if (record["evidenceVersion"] !== 2 || record["kind"] !== "freeformMove") {
    invalidEvidence("evidence contract is unsupported");
  }
  if (
    record["snapSolverVersion"] !== STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION ||
    record["snapSolverSourceHash"] !== STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH
  ) {
    throw replayError("solver_identity_mismatch", "Freeform move evidence solver identity differs");
  }
  const selectedNodeIds = evidenceArray(
    record["selectedNodeIds"],
    500,
    "evidence.selectedNodeIds",
  ).map((item, index) => evidenceEntityId(item, `evidence.selectedNodeIds[${index}]`));
  if (selectedNodeIds.length === 0) invalidEvidence("evidence.selectedNodeIds must not be empty");
  requireCanonicalSortedUnique(selectedNodeIds, "evidence.selectedNodeIds");
  const grids = evidenceArray(record["grids"], 8, "evidence.grids").map((grid, index) =>
    parseEvidenceGrid(grid, `evidence.grids[${index}]`),
  );
  const gridIds = grids.map((grid) => grid.id);
  if (new Set(gridIds).size !== gridIds.length)
    invalidEvidence("evidence.grids contains duplicate IDs");
  const directSiblings = evidenceArray(
    record["directSiblings"],
    500,
    "evidence.directSiblings",
  ).map((sibling, index) => parseEvidenceSibling(sibling, `evidence.directSiblings[${index}]`));
  const siblingIds = directSiblings.map((sibling) => sibling.nodeId);
  requireCanonicalSortedUnique(siblingIds, "evidence.directSiblings");
  const selectedSet = new Set(selectedNodeIds);
  if (siblingIds.some((nodeId) => selectedSet.has(nodeId))) {
    invalidEvidence("evidence selected nodes cannot also be direct siblings");
  }
  const freeformId = evidenceEntityId(record["freeformId"], "evidence.freeformId");
  const capturedIds = new Set([...selectedNodeIds, ...siblingIds, ...gridIds]);
  if (capturedIds.size !== selectedNodeIds.length + siblingIds.length + gridIds.length) {
    invalidEvidence("evidence node and grid IDs must be distinct");
  }
  if (capturedIds.has(freeformId)) invalidEvidence("evidence.freeformId must be distinct");

  const containerSize = evidenceRecord(record["containerSize"], "evidence.containerSize");
  exactKeys(containerSize, ["width", "height"], "evidence.containerSize");
  const axisWinners = evidenceRecord(record["axisWinners"], "evidence.axisWinners");
  exactKeys(axisWinners, ["x", "y"], "evidence.axisWinners");
  const candidates = evidenceArray(record["candidates"], 6, "evidence.candidates").map(
    (candidate, index) => parseEvidenceCandidate(candidate, `evidence.candidates[${index}]`),
  );
  const sortKeys = candidates.map((candidate) => candidate.sortKey);
  if (new Set(sortKeys).size !== sortKeys.length) {
    invalidEvidence("evidence.candidates contains duplicate sort keys");
  }

  return {
    evidenceVersion: 2,
    kind: "freeformMove",
    snapSolverVersion: STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION,
    snapSolverSourceHash: STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH,
    documentId: evidenceEntityId(record["documentId"], "evidence.documentId"),
    draftId: evidenceEntityId(record["draftId"], "evidence.draftId"),
    freeformId,
    baseHeadSequenceNo: evidenceInteger(
      record["baseHeadSequenceNo"],
      0,
      Number.MAX_SAFE_INTEGER,
      "evidence.baseHeadSequenceNo",
    ),
    baseDocumentHash: evidenceSha256(record["baseDocumentHash"], "evidence.baseDocumentHash"),
    selectedNodeIds,
    grids,
    gridListHash: evidenceSha256(record["gridListHash"], "evidence.gridListHash"),
    gridSnappingEnabled: evidenceBoolean(
      record["gridSnappingEnabled"],
      "evidence.gridSnappingEnabled",
    ),
    previewScale: evidencePositiveDecimal(record["previewScale"], "evidence.previewScale"),
    clientThreshold: evidenceLiteral(
      record["clientThreshold"],
      ["6"] as const,
      "evidence.clientThreshold",
    ),
    selectionBounds: parseEvidenceBounds(record["selectionBounds"], "evidence.selectionBounds"),
    directSiblings,
    containerSize: {
      width: evidencePositiveDecimal(containerSize["width"], "evidence.containerSize.width"),
      height: evidencePositiveDecimal(containerSize["height"], "evidence.containerSize.height"),
    },
    requestedDelta: parseEvidencePoint(record["requestedDelta"], "evidence.requestedDelta"),
    rawPosition: parseEvidencePoint(record["rawPosition"], "evidence.rawPosition"),
    finalPosition: parseEvidencePoint(record["finalPosition"], "evidence.finalPosition"),
    correction: parseEvidencePoint(record["correction"], "evidence.correction"),
    bypassSnapping: evidenceBoolean(record["bypassSnapping"], "evidence.bypassSnapping"),
    axisWinners: {
      x: evidenceLiteral(
        axisWinners["x"],
        ["raw", "alignment", "spacing", "grid"] as const,
        "evidence.axisWinners.x",
      ),
      y: evidenceLiteral(
        axisWinners["y"],
        ["raw", "alignment", "spacing", "grid"] as const,
        "evidence.axisWinners.y",
      ),
    },
    candidates,
    terminalReason: evidenceLiteral(
      record["terminalReason"],
      ["pointerup"] as const,
      "evidence.terminalReason",
    ),
  };
}

function evidenceNumber(value: string): number {
  return Number(value);
}

function evidencePointToSnapPoint(
  point: StructuredPrototypeFreeformMoveEvidencePoint,
): StructuredPrototypeFreeformSnapPoint {
  return { x: evidenceNumber(point.x), y: evidenceNumber(point.y) };
}

function evidenceBoundsToSnapBounds(
  bounds: StructuredPrototypeFreeformMoveEvidenceBounds,
): StructuredPrototypeFreeformSnapBounds {
  return {
    ...evidencePointToSnapPoint(bounds),
    width: evidenceNumber(bounds.width),
    height: evidenceNumber(bounds.height),
  };
}

function evidenceToBuildInput(
  evidence: StructuredPrototypeFreeformMoveEvidence,
): StructuredPrototypeFreeformMoveEvidenceInput {
  return {
    documentId: evidence.documentId,
    draftId: evidence.draftId,
    baseHeadSequenceNo: evidence.baseHeadSequenceNo,
    baseDocumentHash: evidence.baseDocumentHash,
    freeformId: evidence.freeformId,
    selectedNodeIds: evidence.selectedNodeIds,
    grids: evidence.grids,
    gridSnappingEnabled: evidence.gridSnappingEnabled,
    previewScale: evidenceNumber(evidence.previewScale),
    selectionBounds: evidenceBoundsToSnapBounds(evidence.selectionBounds),
    directSiblings: evidence.directSiblings.map((sibling) => ({
      nodeId: sibling.nodeId,
      ...evidenceBoundsToSnapBounds(sibling),
    })),
    containerWidth: evidenceNumber(evidence.containerSize.width),
    containerHeight: evidenceNumber(evidence.containerSize.height),
    requestedDelta: evidencePointToSnapPoint(evidence.requestedDelta),
    bypassSnapping: evidence.bypassSnapping,
  };
}

export async function attestStructuredPrototypeFreeformMoveEvidenceJson(
  evidenceJson: string,
): Promise<{ evidenceHash: string }> {
  const value = safeJsonParse(evidenceJson);
  if (value === null) {
    throw replayError("invalid_evidence_json", "Freeform move evidence JSON is invalid");
  }
  const evidence = parseStructuredPrototypeFreeformMoveEvidence(value);
  const canonicalEvidenceJson = canonicalRuntimeJson(evidence);
  if (evidenceJson !== canonicalEvidenceJson) {
    throw replayError("evidence_mismatch", "Freeform move evidence JSON is not canonical");
  }
  let rebuilt: StructuredPrototypeFreeformMoveEvidence;
  try {
    rebuilt = await buildStructuredPrototypeFreeformMoveEvidence(evidenceToBuildInput(evidence));
  } catch (error) {
    if (error instanceof StructuredPrototypeFreeformMoveReplayError) {
      throw replayError(
        "invalid_evidence",
        `Freeform move evidence cannot replay: ${error.message}`,
      );
    }
    throw replayError(
      "invalid_evidence",
      `Freeform move evidence cannot replay: ${errorMessage(error)}`,
    );
  }
  if (canonicalRuntimeJson(rebuilt) !== canonicalEvidenceJson) {
    throw replayError("evidence_mismatch", "Freeform move evidence differs from canonical replay");
  }
  return { evidenceHash: await hashRuntimeValue(evidence) };
}
