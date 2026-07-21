import type { StructuredPrototypePaletteType } from "./structuredPrototypePaletteTypes";

export type StructuredPrototypeMoveSource =
  | { kind: "node"; nodeId: string }
  | { kind: "layer"; nodeId: string }
  | { kind: "palette"; nodeType: StructuredPrototypePaletteType }
  | { kind: "component"; componentId: string }
  | { kind: "page"; pageId: string };

export type StructuredPrototypeInteraction =
  | { kind: "idle" }
  | { kind: "pan"; sessionId: number; pointerId: number }
  | { kind: "marquee"; sessionId: number; pointerId: number }
  | {
      kind: "mutation";
      sessionId: number;
      operation: StructuredPrototypeMutationOperation;
      phase: "committing";
      baseDocumentHash: string;
    }
  | {
      kind: "move";
      sessionId: number;
      source: StructuredPrototypeMoveSource;
      phase: "active" | "committing";
      baseDocumentHash: string;
    }
  | {
      kind: "freeformMove";
      sessionId: number;
      nodeId: string;
      freeformId: string;
      pointerId: number;
      phase: "armed" | "preview" | "committing";
      baseDocumentHash: string;
      previewScale: number;
      gridSnappingEnabled: boolean;
      gridIds: readonly string[];
    }
  | {
      kind: "resize";
      sessionId: number;
      nodeId: string;
      pointerId: number;
      phase: "armed" | "preview" | "committing";
      baseDocumentHash: string;
      previewScale: number;
    };

export type StructuredPrototypeInteractionRequest =
  | { kind: "pan"; pointerId: number }
  | { kind: "marquee"; pointerId: number }
  | {
      kind: "mutation";
      operation: StructuredPrototypeMutationOperation;
      baseDocumentHash: string;
    }
  | {
      kind: "move";
      source: StructuredPrototypeMoveSource;
      baseDocumentHash: string;
    }
  | {
      kind: "freeformMove";
      nodeId: string;
      freeformId: string;
      pointerId: number;
      baseDocumentHash: string;
      previewScale: number;
      gridSnappingEnabled: boolean;
      gridIds: readonly string[];
    }
  | {
      kind: "resize";
      nodeId: string;
      pointerId: number;
      baseDocumentHash: string;
      previewScale: number;
    };

export interface StructuredPrototypeInteractionCapabilities {
  busy: boolean;
  documentControlsDisabled: boolean;
  moveDisabled: boolean;
  resizeDisabled: boolean;
}

export type StructuredPrototypeMutationOperation =
  "aiApply" | "checkpoint" | "commands" | "deletePrototype" | "history" | "publish" | "runtime";

export function createStructuredPrototypeIdleInteraction(): StructuredPrototypeInteraction {
  return { kind: "idle" };
}

export function beginStructuredPrototypeInteraction(
  current: StructuredPrototypeInteraction,
  request: StructuredPrototypeInteractionRequest,
  sessionId: number,
): StructuredPrototypeInteraction {
  if (current.kind !== "idle") return current;
  if (request.kind === "move") {
    return { ...request, sessionId, phase: "active" };
  }
  if (request.kind === "freeformMove" || request.kind === "resize") {
    return { ...request, sessionId, phase: "armed" };
  }
  if (request.kind === "mutation") {
    return { ...request, sessionId, phase: "committing" };
  }
  return { ...request, sessionId };
}

export function advanceStructuredPrototypeInteraction(
  current: StructuredPrototypeInteraction,
  sessionId: number,
  phase: "preview" | "committing",
): StructuredPrototypeInteraction {
  if (current.kind === "idle" || current.sessionId !== sessionId) return current;
  if (current.kind === "move") {
    if (phase !== "committing") {
      throw new Error(`move interaction cannot advance to ${phase}`);
    }
    if (current.phase === "committing") return current;
    return { ...current, phase };
  }
  if (current.kind === "freeformMove" || current.kind === "resize") {
    if (phase === "preview") {
      if (current.phase === "preview") return current;
      if (current.phase !== "armed") {
        throw new Error(
          `${current.kind} interaction cannot advance from ${current.phase} to preview`,
        );
      }
      return { ...current, phase };
    }
    if (current.phase === "committing") return current;
    return { ...current, phase };
  }
  throw new Error(`${current.kind} interaction does not have a mutable phase`);
}

export function endStructuredPrototypeInteraction(
  current: StructuredPrototypeInteraction,
  sessionId: number,
): StructuredPrototypeInteraction {
  if (current.kind === "idle" || current.sessionId !== sessionId) return current;
  return createStructuredPrototypeIdleInteraction();
}

export function resolveStructuredPrototypeInteractionCapabilities(
  interaction: StructuredPrototypeInteraction,
  saving: boolean,
): StructuredPrototypeInteractionCapabilities {
  const busy = interaction.kind !== "idle";
  const activeMove = interaction.kind === "move" && interaction.phase === "active";
  const activeFreeformMove =
    interaction.kind === "freeformMove" &&
    (interaction.phase === "armed" || interaction.phase === "preview");
  const activeResize =
    interaction.kind === "resize" &&
    (interaction.phase === "armed" || interaction.phase === "preview");
  return {
    busy,
    documentControlsDisabled: saving || busy,
    moveDisabled: saving || (busy && !activeMove && !activeFreeformMove),
    resizeDisabled: saving || (busy && !activeResize),
  };
}
