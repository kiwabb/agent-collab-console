import {
  buildStructuredPrototypeFreeformMoveEvidence,
  type StructuredPrototypeFreeformMoveReplayInput,
} from "./structuredPrototypeFreeformMoveReplay";
import type { StructuredPrototypeFreeformMoveEvidence } from "./types";

export interface StructuredPrototypeFreeformMoveEvidenceInput extends StructuredPrototypeFreeformMoveReplayInput {
  readonly documentId: string;
  readonly draftId: string;
  readonly baseHeadSequenceNo: number;
  readonly baseDocumentHash: string;
  readonly freeformId: string;
}

export function serializeStructuredPrototypeFreeformMoveEvidence(
  input: StructuredPrototypeFreeformMoveEvidenceInput,
): Promise<StructuredPrototypeFreeformMoveEvidence> {
  return buildStructuredPrototypeFreeformMoveEvidence(input);
}
