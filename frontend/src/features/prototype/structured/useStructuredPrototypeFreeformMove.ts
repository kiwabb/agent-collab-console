"use client";

import type { PointerEvent } from "react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  structuredPrototypeCanStartTransform,
  resolveStructuredPrototypeFreeformMove,
  structuredPrototypeTransformPassedActivationThreshold,
} from "./structuredPrototypeFreeformGeometry";
import { cloneStructuredPrototypeFreeformGrids } from "./structuredPrototypeFreeformGrids";
import {
  canonicalizeStructuredPrototypeFreeformMoveReplayInput,
  replayStructuredPrototypeFreeformMove,
  type StructuredPrototypeFreeformMoveReplayResult,
} from "./structuredPrototypeFreeformMoveReplay";
import type { StructuredPrototypeFreeformMoveEvidenceInput } from "./structuredPrototypeFreeformMoveEvidence";
import type { StructuredPrototypeFreeformSnapSibling } from "./structuredPrototypeSnapping";
import type {
  StructuredPrototypeFreeformSnapGuideOverlay,
  StructuredPrototypeFreeformSnapGuideOverlayFrame,
} from "./structuredPrototypeSnapGuides";
import type { StructuredPrototypeFreeformGrid } from "./types";

export interface StructuredPrototypeFreeformMoveDraft {
  nodeId: string;
  x: number;
  y: number;
  groupItems?: readonly StructuredPrototypeFreeformMoveItemDraft[];
}

export interface StructuredPrototypeFreeformMoveItemDraft {
  nodeId: string;
  x: number;
  y: number;
}

export type StructuredPrototypeFreeformMoveEvidenceCapture = Omit<
  StructuredPrototypeFreeformMoveEvidenceInput,
  "documentId" | "draftId" | "baseHeadSequenceNo" | "baseDocumentHash"
>;

type FreeformMoveEnd = "none" | "pointerup" | "pointercancel" | "blur" | "escape";
type FreeformMoveEndReason = Exclude<FreeformMoveEnd, "none"> | "unmount";
type FreeformMovePhase = "idle" | "armed" | "preview" | "pending";

export type StructuredPrototypeFreeformMoveGestureEvent =
  | {
      phase: "start";
      nodeId: string;
      freeformId: string;
      pointerId: number;
      previewScale: number;
      gridSnappingEnabled: boolean;
      gridIds: readonly string[];
    }
  | { phase: "preview" | "commit"; nodeId: string; sessionId: number }
  | {
      phase: "end";
      nodeId: string;
      sessionId: number;
      reason: FreeformMoveEndReason;
    };

export interface StructuredPrototypeFreeformMoveStartFrame {
  readonly freeformId: string;
  readonly x: number;
  readonly y: number;
  readonly nodeWidth: number;
  readonly nodeHeight: number;
  readonly containerWidth: number;
  readonly containerHeight: number;
  readonly selectedNodeIds: readonly string[];
  readonly directSiblings: readonly Readonly<StructuredPrototypeFreeformSnapSibling>[];
  readonly grids: readonly Readonly<StructuredPrototypeFreeformGrid>[];
  readonly gridSnappingEnabled: boolean;
  readonly previewScale: number;
  readonly guideOverlayFrame: StructuredPrototypeFreeformSnapGuideOverlayFrame;
}

interface Props {
  disabled: boolean;
  onSelect: (nodeId: string) => void;
  onMoveNode: (
    nodeId: string,
    x: number,
    y: number,
    evidence: StructuredPrototypeFreeformMoveEvidenceCapture,
  ) => Promise<boolean>;
  onMoveError: (error: unknown) => void;
  onGestureChange: (event: StructuredPrototypeFreeformMoveGestureEvent) => number | null;
  resolveStartFrame: (nodeId: string) => StructuredPrototypeFreeformMoveStartFrame | null;
}

interface FreeformMoveGesture extends StructuredPrototypeFreeformMoveStartFrame {
  sessionId: number;
  nodeId: string;
  pointerId: number;
  startClientX: number;
  startClientY: number;
  latestClientX: number;
  latestClientY: number;
  latestBypassSnapping: boolean;
  projectionFrame: number | null;
  activated: boolean;
  handle: HTMLButtonElement;
}

interface FreeformMoveCommit {
  sessionId: number;
  nodeId: string;
}

export function useStructuredPrototypeFreeformMove({
  disabled,
  onSelect,
  onMoveNode,
  onMoveError,
  onGestureChange,
  resolveStartFrame,
}: Props) {
  const [draft, setDraft] = useState<StructuredPrototypeFreeformMoveDraft | null>(null);
  const [guideOverlay, setGuideOverlay] =
    useState<StructuredPrototypeFreeformSnapGuideOverlay | null>(null);
  const [phase, setPhase] = useState<FreeformMovePhase>("idle");
  const [lastEnd, setLastEnd] = useState<FreeformMoveEnd>("none");
  const gestureRef = useRef<FreeformMoveGesture | null>(null);
  const commitRef = useRef<FreeformMoveCommit | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const moveNodeRef = useRef(onMoveNode);
  const moveErrorRef = useRef(onMoveError);
  const gestureChangeRef = useRef(onGestureChange);
  const mountedRef = useRef(true);

  const clearGuideOverlay = useCallback((): void => {
    setGuideOverlay(null);
  }, []);

  useLayoutEffect(() => {
    moveNodeRef.current = onMoveNode;
    moveErrorRef.current = onMoveError;
    gestureChangeRef.current = onGestureChange;
  }, [onGestureChange, onMoveError, onMoveNode]);

  const detachPointer = useCallback(() => {
    const gesture = gestureRef.current;
    if (gesture === null) return null;
    gestureRef.current = null;
    if (gesture.projectionFrame !== null) {
      globalThis.window.cancelAnimationFrame(gesture.projectionFrame);
      gesture.projectionFrame = null;
    }
    cleanupRef.current?.();
    if (gesture.handle.hasPointerCapture(gesture.pointerId)) {
      gesture.handle.releasePointerCapture(gesture.pointerId);
    }
    return gesture;
  }, []);

  const endGesture = useCallback(
    (reason: FreeformMoveEndReason) => {
      const gesture = detachPointer();
      if (gesture === null) return null;
      gestureChangeRef.current({
        phase: "end",
        nodeId: gesture.nodeId,
        sessionId: gesture.sessionId,
        reason,
      });
      clearGuideOverlay();
      return gesture;
    },
    [clearGuideOverlay, detachPointer],
  );

  const endCommit = useCallback(
    (reason: FreeformMoveEndReason): void => {
      const commit = commitRef.current;
      if (commit === null) return;
      commitRef.current = null;
      gestureChangeRef.current({
        phase: "end",
        nodeId: commit.nodeId,
        sessionId: commit.sessionId,
        reason,
      });
      clearGuideOverlay();
    },
    [clearGuideOverlay],
  );

  const onPointerDown = useCallback(
    (nodeId: string, event: PointerEvent<HTMLButtonElement>): void => {
      if (disabled || !structuredPrototypeCanStartTransform(event.button, event.isPrimary)) return;
      if (endGesture("pointercancel") !== null) {
        setDraft(null);
        setPhase("idle");
        setLastEnd("pointercancel");
      }
      const startFrame = resolveStartFrame(nodeId);
      if (startFrame === null) return;
      const canonicalStartInput = canonicalizeStructuredPrototypeFreeformMoveReplayInput({
        selectionBounds: {
          x: startFrame.x,
          y: startFrame.y,
          width: startFrame.nodeWidth,
          height: startFrame.nodeHeight,
        },
        selectedNodeIds: startFrame.selectedNodeIds,
        requestedDelta: { x: 0, y: 0 },
        containerWidth: startFrame.containerWidth,
        containerHeight: startFrame.containerHeight,
        previewScale: startFrame.previewScale,
        directSiblings: startFrame.directSiblings,
        grids: startFrame.grids,
        gridSnappingEnabled: startFrame.gridSnappingEnabled,
        bypassSnapping: false,
      });
      const pointerId = event.pointerId;
      const sessionId = gestureChangeRef.current({
        phase: "start",
        nodeId,
        freeformId: startFrame.freeformId,
        pointerId,
        previewScale: canonicalStartInput.previewScale,
        gridSnappingEnabled: canonicalStartInput.gridSnappingEnabled,
        gridIds: canonicalStartInput.grids.map((grid) => grid.id),
      });
      if (sessionId === null) return;
      event.preventDefault();
      event.stopPropagation();
      onSelect(nodeId);
      setLastEnd("none");
      setPhase("armed");
      const handle = event.currentTarget;
      gestureRef.current = {
        freeformId: startFrame.freeformId,
        x: canonicalStartInput.selectionBounds.x,
        y: canonicalStartInput.selectionBounds.y,
        nodeWidth: canonicalStartInput.selectionBounds.width,
        nodeHeight: canonicalStartInput.selectionBounds.height,
        containerWidth: canonicalStartInput.containerWidth,
        containerHeight: canonicalStartInput.containerHeight,
        selectedNodeIds: [...canonicalStartInput.selectedNodeIds],
        directSiblings: canonicalStartInput.directSiblings.map((sibling) => ({ ...sibling })),
        grids: cloneStructuredPrototypeFreeformGrids(canonicalStartInput.grids),
        gridSnappingEnabled: canonicalStartInput.gridSnappingEnabled,
        previewScale: canonicalStartInput.previewScale,
        guideOverlayFrame: { ...startFrame.guideOverlayFrame },
        sessionId,
        nodeId,
        pointerId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        latestClientX: event.clientX,
        latestClientY: event.clientY,
        latestBypassSnapping: event.ctrlKey || event.metaKey,
        projectionFrame: null,
        activated: false,
        handle,
      };
      handle.setPointerCapture(pointerId);

      function resolveProjection(
        gesture: FreeformMoveGesture,
        clientX: number,
        clientY: number,
        bypassSnapping: boolean,
      ): StructuredPrototypeFreeformMoveReplayResult {
        const position = resolveStructuredPrototypeFreeformMove({
          startX: gesture.x,
          startY: gesture.y,
          startClientX: gesture.startClientX,
          startClientY: gesture.startClientY,
          clientX,
          clientY,
          previewScale: gesture.previewScale,
          nodeWidth: gesture.nodeWidth,
          nodeHeight: gesture.nodeHeight,
          containerWidth: gesture.containerWidth,
          containerHeight: gesture.containerHeight,
        });
        const requestedDelta = {
          x: position.x - gesture.x,
          y: position.y - gesture.y,
        };
        return replayStructuredPrototypeFreeformMove({
          selectionBounds: {
            x: gesture.x,
            y: gesture.y,
            width: gesture.nodeWidth,
            height: gesture.nodeHeight,
          },
          selectedNodeIds: gesture.selectedNodeIds,
          requestedDelta,
          containerWidth: gesture.containerWidth,
          containerHeight: gesture.containerHeight,
          previewScale: gesture.previewScale,
          directSiblings: gesture.directSiblings,
          grids: gesture.grids,
          gridSnappingEnabled: gesture.gridSnappingEnabled,
          bypassSnapping,
        });
      }

      function activate(
        clientX: number,
        clientY: number,
        bypassSnapping: boolean,
      ): FreeformMoveGesture | null {
        const gesture = gestureRef.current;
        if (gesture === null || gesture.pointerId !== pointerId) return null;
        gesture.latestClientX = clientX;
        gesture.latestClientY = clientY;
        gesture.latestBypassSnapping = bypassSnapping;
        if (
          !gesture.activated &&
          !structuredPrototypeTransformPassedActivationThreshold(
            gesture.startClientX,
            gesture.startClientY,
            clientX,
            clientY,
          )
        ) {
          return null;
        }
        gesture.activated = true;
        setPhase("preview");
        gestureChangeRef.current({
          phase: "preview",
          nodeId,
          sessionId: gesture.sessionId,
        });
        return gesture;
      }

      function schedule(clientX: number, clientY: number, bypassSnapping: boolean): void {
        const gesture = activate(clientX, clientY, bypassSnapping);
        if (gesture === null || gesture.projectionFrame !== null) return;
        gesture.projectionFrame = globalThis.window.requestAnimationFrame(() => {
          const current = gestureRef.current;
          if (
            current === null ||
            current.pointerId !== pointerId ||
            current.sessionId !== gesture.sessionId
          ) {
            return;
          }
          current.projectionFrame = null;
          const projection = resolveProjection(
            current,
            current.latestClientX,
            current.latestClientY,
            current.latestBypassSnapping,
          );
          setDraft({
            nodeId,
            ...projection.position,
          });
          setGuideOverlay(
            projection.guides.length === 0 && projection.spacingGuides.length === 0
              ? null
              : {
                  frame: current.guideOverlayFrame,
                  guides: projection.guides,
                  spacingGuides: projection.spacingGuides,
                  previewScale: current.previewScale,
                },
          );
        });
      }

      function cleanup(): void {
        globalThis.window.removeEventListener("pointermove", handlePointerMove);
        globalThis.window.removeEventListener("pointerup", handlePointerUp);
        globalThis.window.removeEventListener("pointercancel", handlePointerCancel);
        globalThis.window.removeEventListener("blur", handleBlur);
        globalThis.window.removeEventListener("keydown", handleKeyDown);
        handle.removeEventListener("lostpointercapture", handleLostPointerCapture);
        cleanupRef.current = null;
      }

      function cancel(reason: "pointercancel" | "blur" | "escape"): void {
        if (gestureRef.current?.pointerId !== pointerId) return;
        endGesture(reason);
        setDraft(null);
        setPhase("idle");
        setLastEnd(reason);
      }

      function handlePointerMove(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId !== pointerId) return;
        pointerEvent.preventDefault();
        pointerEvent.stopPropagation();
        schedule(
          pointerEvent.clientX,
          pointerEvent.clientY,
          pointerEvent.ctrlKey || pointerEvent.metaKey,
        );
      }

      function handlePointerUp(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId !== pointerId) return;
        pointerEvent.preventDefault();
        pointerEvent.stopPropagation();
        const bypassSnapping = pointerEvent.ctrlKey || pointerEvent.metaKey;
        const active = activate(pointerEvent.clientX, pointerEvent.clientY, bypassSnapping);
        const finalProjection =
          active === null
            ? null
            : resolveProjection(active, pointerEvent.clientX, pointerEvent.clientY, bypassSnapping);
        const gesture = detachPointer();
        if (gesture === null) return;
        clearGuideOverlay();
        setLastEnd("pointerup");
        if (finalProjection === null) {
          gestureChangeRef.current({
            phase: "end",
            nodeId,
            sessionId: gesture.sessionId,
            reason: "pointerup",
          });
          setDraft(null);
          setPhase("idle");
          return;
        }
        const accepted = gestureChangeRef.current({
          phase: "commit",
          nodeId,
          sessionId: gesture.sessionId,
        });
        if (accepted !== gesture.sessionId) {
          gestureChangeRef.current({
            phase: "end",
            nodeId,
            sessionId: gesture.sessionId,
            reason: "pointercancel",
          });
          setDraft(null);
          setPhase("idle");
          setLastEnd("pointercancel");
          return;
        }
        commitRef.current = { nodeId, sessionId: gesture.sessionId };
        setDraft({ nodeId, ...finalProjection.position });
        setPhase("pending");
        void (async () => {
          let applied = false;
          try {
            applied = await moveNodeRef.current(
              nodeId,
              finalProjection.position.x,
              finalProjection.position.y,
              {
                freeformId: gesture.freeformId,
                ...finalProjection.canonicalInput,
                selectedNodeIds: [...finalProjection.canonicalInput.selectedNodeIds],
                grids: cloneStructuredPrototypeFreeformGrids(finalProjection.canonicalInput.grids),
                directSiblings: finalProjection.canonicalInput.directSiblings.map((sibling) => ({
                  ...sibling,
                })),
              },
            );
          } catch (error) {
            if (commitRef.current?.sessionId === gesture.sessionId) moveErrorRef.current(error);
          } finally {
            if (commitRef.current?.sessionId !== gesture.sessionId) return;
            if (!applied && mountedRef.current) {
              setDraft(null);
              clearGuideOverlay();
              setPhase("idle");
            }
            endCommit("pointerup");
          }
        })();
      }

      function handlePointerCancel(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId === pointerId) cancel("pointercancel");
      }

      function handleLostPointerCapture(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId === pointerId) cancel("pointercancel");
      }

      function handleBlur(): void {
        cancel("blur");
      }

      function handleKeyDown(event: KeyboardEvent): void {
        if (event.key !== "Escape") return;
        event.preventDefault();
        cancel("escape");
      }

      globalThis.window.addEventListener("pointermove", handlePointerMove, { passive: false });
      globalThis.window.addEventListener("pointerup", handlePointerUp, { passive: false });
      globalThis.window.addEventListener("pointercancel", handlePointerCancel, { passive: false });
      globalThis.window.addEventListener("blur", handleBlur);
      globalThis.window.addEventListener("keydown", handleKeyDown);
      handle.addEventListener("lostpointercapture", handleLostPointerCapture);
      cleanupRef.current = cleanup;
    },
    [
      clearGuideOverlay,
      detachPointer,
      disabled,
      endCommit,
      endGesture,
      onSelect,
      resolveStartFrame,
    ],
  );

  const acknowledge = useCallback((): void => {
    setDraft(null);
    clearGuideOverlay();
    setPhase("idle");
  }, [clearGuideOverlay]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      endGesture("unmount");
      endCommit("unmount");
    };
  }, [endCommit, endGesture]);

  return { draft, guideOverlay, phase, lastEnd, onPointerDown, acknowledge };
}
