"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  DragOverlay,
  DndContext,
  KeyboardSensor,
  MeasuringStrategy,
  PointerSensor,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  CloudUpload,
  ExternalLink,
  Files,
  GitBranch,
  History,
  Magnet,
  Maximize2,
  Minimize2,
  PanelsTopLeft,
  Redo2,
  MessageSquare,
  MousePointer2,
  Play,
  Save,
  Trash2,
  Undo2,
} from "lucide-react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { getDictionaryValue } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import type { RuntimeEvent } from "../runtime/types";
import {
  deriveFormInputBindings,
  structuredPrototypeShowsRoleControl,
} from "./prototypeRendererCore";
import {
  addPageBatch,
  addBehaviorRuleBatch,
  createPaletteNode,
  defineComponentBatch,
  deletePageBatch,
  duplicatePageBatch,
  instantiateComponentBatch,
  insertPaletteNodeBatch,
  movePositionedSelectionBatch,
  moveNodeBatch,
  removeNodesBatch,
  removeComponentDefinitionBatch,
  reorderPageBatch,
  removeBehaviorRuleBatch,
  renamePageBatch,
  resolvePaletteFormDefinition,
  replaceBehaviorRuleBatch,
  setPositionedGroupLayoutBatch,
  setRuntimeFlowNodePositionBatch,
  structuredPrototypePageAllocationKey,
  STRUCTURED_PROTOTYPE_COMMAND_BATCH_LIMIT,
  updateNodeNameBatch,
} from "./structuredPrototypeCommands";
import {
  findStructuredPrototypeNode,
  findStructuredPrototypeFormForNode,
  runtimeNodeActivationEvents,
  runtimeNodeRows,
  runtimeTableRowsBinding,
  structuredPrototypeInputNodes,
  structuredPrototypeSubtreeHasRuntimeReferences,
} from "./structuredPrototypeDerived";
import {
  readStructuredPrototypeComponentDefinitionDragData,
  readStructuredPrototypeDropTarget,
  readStructuredPrototypeNodeDragData,
  readStructuredPrototypeNodeDragMirrorCapture,
  readStructuredPrototypePageDragData,
  readStructuredPrototypePaletteDragData,
  findStructuredPrototypeNodeLocation,
  materializeStructuredPrototypeComponentPreviewNode,
  materializeStructuredPrototypePalettePreviewNode,
  projectStructuredPrototypeNodeInsert,
  projectStructuredPrototypeNodeMoveToDropTarget,
  projectStructuredPrototypePageReorderByTargetPageId,
  shouldScheduleStructuredPrototypeFreeformRegistrationRemeasure,
  structuredPrototypeCollisionDetection,
  updateStructuredPrototypeActiveDragPointerState,
  type StructuredPrototypeActiveDragPointerState,
  type StructuredPrototypeDropTarget,
  type StructuredPrototypeNodeLocation,
} from "./structuredPrototypeDrag";
import { StructuredPrototypeDragMirrorView } from "./StructuredPrototypeDragMirrorView";
import { StructuredPrototypeComponentLibrary } from "./StructuredPrototypeComponentLibrary";
import type { StructuredPrototypeDragMirrorSnapshot } from "./structuredPrototypeDragMirror";
import {
  isStructuredPrototypeContainerNode,
  type StructuredPrototypeContainerNode,
} from "./structuredPrototypeNodes";
import {
  resolveStructuredPrototypePositionedGroupSelection,
  resolveStructuredPrototypePositionedSelection,
} from "./structuredPrototypeGroupSelection";
import {
  canonicalStructuredPrototypeFreeformValue,
  STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
  resolveStructuredPrototypeFreeformPointerPlacement,
} from "./structuredPrototypeFreeformGeometry";
import { serializeStructuredPrototypeFreeformMoveEvidence } from "./structuredPrototypeFreeformMoveEvidence";
import { replayStructuredPrototypeFreeformMove } from "./structuredPrototypeFreeformMoveReplay";
import type { StructuredPrototypeGroupTransformItem } from "./structuredPrototypeGroupTransform";
import {
  advanceStructuredPrototypeInteraction,
  beginStructuredPrototypeInteraction,
  createStructuredPrototypeIdleInteraction,
  endStructuredPrototypeInteraction,
  resolveStructuredPrototypeInteractionCapabilities,
  type StructuredPrototypeInteractionRequest,
  type StructuredPrototypeMutationOperation,
} from "./structuredPrototypeInteraction";
import { StructuredPrototypeAiPanel } from "./StructuredPrototypeAiPanel";
import { StructuredPrototypePublishDialog } from "./StructuredPrototypePublishDialog";
import { StructuredPrototypeReleaseHistoryDialog } from "./StructuredPrototypeReleaseHistory";
import {
  StructuredPrototypeNodeDragOverlay,
  type StructuredPrototypeMarqueeGestureEvent,
  type StructuredPrototypeNodeElementRegisteredEvent,
  type StructuredPrototypeNodeSelectionIntent,
  type StructuredPrototypeResizeGestureEvent,
} from "./StructuredPrototypeCanvas";
import { StructuredPrototypeFlow } from "./StructuredPrototypeFlow";
import { StructuredPrototypeGenerationPanel } from "./StructuredPrototypeGenerationPanel";
import {
  StructuredPrototypeInspector,
  type StructuredPrototypePlacementFrame,
  type StructuredPrototypeInspectorRuntimeTable,
} from "./StructuredPrototypeInspector";
import { StructuredPrototypeLayerTree } from "./StructuredPrototypeLayerTree";
import {
  deriveStructuredPrototypeLayerRows,
  readStructuredPrototypeLayerDragData,
  type StructuredPrototypeLayerDropAccepted,
  type StructuredPrototypeLayerDropRefusalReason,
} from "./structuredPrototypeLayerTreeModel";
import { StructuredPrototypePageRail } from "./StructuredPrototypePageRail";
import {
  resolveStructuredPrototypeCreatedPageId,
  resolveStructuredPrototypeNearestSurvivingPageId,
} from "./structuredPrototypePageActions";
import {
  StructuredPrototypePalette,
  type StructuredPrototypePaletteType,
} from "./StructuredPrototypePalette";
import { STRUCTURED_PROTOTYPE_PALETTE_TYPES } from "./structuredPrototypePaletteTypes";
import {
  StructuredPrototypePreview,
  type StructuredPrototypePreviewZoom,
} from "./StructuredPrototypePreview";
import { StructuredPrototypeRuntimeRecoveryNotice } from "./StructuredPrototypeRuntimeRecoveryNotice";
import {
  StructuredPrototypeResponsiveSideRegion,
  useStructuredPrototypeDesktopLayout,
} from "./StructuredPrototypeResponsiveSideRegion";
import { StructuredPrototypeRuleInspector } from "./StructuredPrototypeRuleInspector";
import {
  resolveStructuredPrototypeFlowRuleMutationOutcome,
  type StructuredPrototypeFlowRuleMutation,
  type StructuredPrototypeFlowRuleMutationTarget,
} from "./structuredPrototypeFlowRuleMutation";
import type {
  StructuredPrototypePendingRuleConnection,
  StructuredPrototypeRuleInspectorSelection,
} from "./structuredPrototypeRuleDraft";
import {
  createStructuredPrototypeEmptySelection,
  promoteStructuredPrototypePrimarySelection,
  resolveStructuredPrototypeNodeSelection,
  toggleStructuredPrototypeNodeSelection,
  type StructuredPrototypeNodeSelection,
} from "./structuredPrototypeSelection";
import type {
  NewStructuredPrototypeNode,
  StructuredPrototypeBehaviorRuleDefinition,
  StructuredPrototypeDocument,
  StructuredPrototypeFreeformPosition,
  StructuredPrototypeNode,
} from "./types";
import type {
  StructuredPrototypeFreeformMoveEvidenceCapture,
  StructuredPrototypeFreeformMoveGestureEvent,
} from "./useStructuredPrototypeFreeformMove";
import { useStructuredPrototypeStudio } from "./useStructuredPrototypeStudio";

interface Props {
  projectId: string;
}

type StudioMode = "design" | "flow";
type StudioViewport = "desktop" | "tablet" | "mobile";
type InspectorTab = "ai" | "properties";
type MobileDrawer = "left" | "right" | null;
type CanvasInteraction = "edit" | "preview";
type FlowRuleSelectionIdentity =
  | StructuredPrototypePendingRuleConnection
  | { kind: "existingRuleId"; ruleId: string }
  | { kind: "existingRuleKey"; ruleKey: string };
interface ProjectedPrototypeDocument {
  ownerSessionId: number;
  baseDocumentHash: string;
  token: symbol;
  status: "hover" | "pending";
  document: StructuredPrototypeDocument;
}
interface ActiveMoveProjectionSessionBase {
  interactionSessionId: number;
  baseDocumentHash: string;
  authoritativeDocument: StructuredPrototypeDocument;
  previewScale: number;
  animationFrameId: number | null;
  pendingFreeformRemeasure: { parentId: string; nodeId: string } | null;
}
type ActiveMoveProjectionSession =
  | (ActiveMoveProjectionSessionBase & {
      kind: "node";
      pageId: string;
      nodeId: string;
      latestTarget: StructuredPrototypeDropTarget | null;
      finalLocation: StructuredPrototypeNodeLocation | null;
    })
  | (ActiveMoveProjectionSessionBase & {
      kind: "page";
      pageId: string;
      originalIndex: number;
      latestTargetPageId: string | null;
      projectedTargetPageId: string | null;
      finalTargetIndex: number | null;
    })
  | (ActiveMoveProjectionSessionBase & {
      kind: "palette";
      pageId: string;
      commandNode: NewStructuredPrototypeNode;
      transientNode: StructuredPrototypeNode;
      latestTarget: StructuredPrototypeDropTarget | null;
      finalLocation: StructuredPrototypeNodeLocation | null;
    })
  | (ActiveMoveProjectionSessionBase & {
      kind: "component";
      pageId: string;
      componentId: string;
      transientNode: StructuredPrototypeNode;
      latestTarget: StructuredPrototypeDropTarget | null;
      finalLocation: StructuredPrototypeNodeLocation | null;
    });
type ActiveMoveProjectionResult =
  | { kind: "node" | "palette" | "component"; location: StructuredPrototypeNodeLocation }
  | { kind: "page"; targetIndex: number };
const PREVIEW_ZOOM_OPTIONS: readonly StructuredPrototypePreviewZoom[] = ["fit", 0.75, 1, 1.25];
const FIXED_OVERLAY_VIEWPORT_WIDTH = { tablet: 760, mobile: 390 } as const;
const FREEFORM_INSERT_ORIGIN = 24;
const FREEFORM_INSERT_STEP = 24;
const FREEFORM_INSERT_COLUMNS = 8;

function inactiveStructuredPrototypeDragPointerState(): StructuredPrototypeActiveDragPointerState {
  return { kind: "unknown", interactionSessionId: null, coordinates: null };
}

function visibleMutationError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim().length > 0 ? error.message : fallback;
}

function defaultFreeformPosition(index: number): StructuredPrototypeFreeformPosition {
  const column = index % FREEFORM_INSERT_COLUMNS;
  const row = Math.floor(index / FREEFORM_INSERT_COLUMNS) % FREEFORM_INSERT_COLUMNS;
  return {
    x: String(FREEFORM_INSERT_ORIGIN + column * FREEFORM_INSERT_STEP),
    y: String(FREEFORM_INSERT_ORIGIN + row * FREEFORM_INSERT_STEP),
  };
}

interface PersistentFreeformDropGeometry {
  container: HTMLElement;
  nodeWidth: number;
  nodeHeight: number;
}

interface FreeformDropPositionResolution {
  position: StructuredPrototypeFreeformPosition | null;
  remeasureAfterProjection: boolean;
}

function persistentCanvasWrapper(): HTMLElement | null {
  return globalThis.document.querySelector<HTMLElement>(
    '[data-prototype-canvas-region="persistent"] [data-prototype-canvas-wrapper="true"]',
  );
}

function findPersistentFreeformDropGeometry(
  parentId: string,
  nodeId: string,
): PersistentFreeformDropGeometry | null {
  const canvas = persistentCanvasWrapper();
  if (canvas === null) return null;
  const container = Array.from(canvas.querySelectorAll<HTMLElement>("[data-container-id]")).find(
    (candidate) => candidate.dataset["containerId"] === parentId,
  );
  if (container === undefined) return null;
  const node = Array.from(canvas.querySelectorAll<HTMLElement>("[data-node-id]")).find(
    (candidate) => candidate.dataset["nodeId"] === nodeId,
  );
  if (node === undefined || node.parentElement !== container) return null;
  const nodeWidth = node.offsetWidth;
  const nodeHeight = node.offsetHeight;
  if (
    nodeWidth <= 0 ||
    nodeHeight <= 0 ||
    container.clientWidth <= 0 ||
    container.clientHeight <= 0 ||
    !Number.isFinite(nodeWidth) ||
    !Number.isFinite(nodeHeight) ||
    !Number.isFinite(container.clientWidth) ||
    !Number.isFinite(container.clientHeight)
  ) {
    return null;
  }
  return { container, nodeWidth, nodeHeight };
}

function findDocumentContainer(
  document: StructuredPrototypeDocument,
  pageId: string,
  nodeId: string,
): StructuredPrototypeContainerNode | null {
  const page = document.pages.find((candidate) => candidate.id === pageId);
  if (page === undefined) return null;
  const node = findStructuredPrototypeNode(page.root, nodeId);
  return node !== null && isStructuredPrototypeContainerNode(node) ? node : null;
}

function sameNodeLocation(
  left: StructuredPrototypeNodeLocation,
  right: StructuredPrototypeNodeLocation,
): boolean {
  return (
    left.parentId === right.parentId &&
    left.index === right.index &&
    left.position?.x === right.position?.x &&
    left.position?.y === right.position?.y
  );
}

function sameStructuredPrototypeNodeIds(
  items: readonly StructuredPrototypeGroupTransformItem[],
  nodeIds: readonly string[],
): boolean {
  if (items.length !== nodeIds.length) return false;
  const expected = new Set(nodeIds);
  return expected.size === nodeIds.length && items.every((item) => expected.has(item.nodeId));
}

function sameOrderedIds(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

export function StructuredPrototypeStudioPage({ projectId }: Props) {
  const { t } = useI18n();
  const controller = useStructuredPrototypeStudio(projectId);
  const undoHistory = controller.undo;
  const redoHistory = controller.redo;
  const [mode, setMode] = useState<StudioMode>("design");
  const [viewportOverride, setViewportOverride] = useState<StudioViewport | null>(null);
  const [previewZoom, setPreviewZoom] = useState<StructuredPrototypePreviewZoom>("fit");
  const [effectivePreviewScale, setEffectivePreviewScale] = useState(1);
  const [gridSnappingEnabled, setGridSnappingEnabled] = useState(true);
  const [previewViewResetKey, setPreviewViewResetKey] = useState(0);
  const [canvasInteraction, setCanvasInteraction] = useState<CanvasInteraction>("edit");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("ai");
  const [manualPageId, setManualPageId] = useState<string | null>(null);
  const [nodeSelection, setNodeSelection] = useState(createStructuredPrototypeEmptySelection);
  const [flowPageId, setFlowPageId] = useState<string | null>(null);
  const [flowRuleSelection, setFlowRuleSelection] = useState<FlowRuleSelectionIdentity | null>(
    null,
  );
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [paletteFormId, setPaletteFormId] = useState<string | null>(null);
  const [flowRuleMutation, setFlowRuleMutation] =
    useState<StructuredPrototypeFlowRuleMutation | null>(null);
  const [interactionError, setInteractionError] = useState<string | null>(null);
  const [mobileDrawer, setMobileDrawer] = useState<MobileDrawer>(null);
  const desktopLayout = useStructuredPrototypeDesktopLayout();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [publishDialogOpen, setPublishDialogOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [aiMutating, setAiMutating] = useState(false);
  const [interaction, setInteraction] = useState(createStructuredPrototypeIdleInteraction);
  const [projectedDocument, setProjectedDocument] = useState<ProjectedPrototypeDocument | null>(
    null,
  );
  const [activeNodeDragMirror, setActiveNodeDragMirror] =
    useState<StructuredPrototypeDragMirrorSnapshot | null>(null);
  const [activePaletteDragNode, setActivePaletteDragNode] =
    useState<StructuredPrototypeNode | null>(null);
  const [activeComponentDragNode, setActiveComponentDragNode] =
    useState<StructuredPrototypeNode | null>(null);
  const projectedDocumentRef = useRef<ProjectedPrototypeDocument | null>(null);
  const activeMoveProjectionRef = useRef<ActiveMoveProjectionSession | null>(null);
  const activeDragPointerStateRef = useRef<StructuredPrototypeActiveDragPointerState>(
    inactiveStructuredPrototypeDragPointerState(),
  );
  const interactionRef = useRef(interaction);
  const nextInteractionSessionIdRef = useRef(1);
  const editorMutationLocked =
    controller.saving || aiMutating || controller.runtimeRecovery !== null;
  const flowRuleMutationOutcome = useMemo(
    () =>
      flowRuleMutation === null
        ? null
        : resolveStructuredPrototypeFlowRuleMutationOutcome(
            flowRuleMutation,
            controller.draft?.documentHash ?? null,
            controller.saving,
          ),
    [controller.draft?.documentHash, controller.saving, flowRuleMutation],
  );
  useEffect(() => {
    if (flowRuleMutationOutcome === null || flowRuleMutationOutcome.kind === "pending") return;
    if (flowRuleMutationOutcome.kind === "persisted") {
      if (flowRuleMutationOutcome.target.kind === "ruleKey") {
        setFlowRuleSelection({
          kind: "existingRuleKey",
          ruleKey: flowRuleMutationOutcome.target.ruleKey,
        });
      } else if (flowRuleMutationOutcome.target.kind === "ruleId") {
        setFlowRuleSelection({
          kind: "existingRuleId",
          ruleId: flowRuleMutationOutcome.target.ruleId,
        });
      } else {
        setFlowRuleSelection(null);
      }
      setInteractionError(null);
    } else {
      setInteractionError(flowRuleMutationOutcome.message);
    }
    setFlowRuleMutation(null);
  }, [flowRuleMutationOutcome]);
  const beginInteraction = useCallback((request: StructuredPrototypeInteractionRequest) => {
    const current = interactionRef.current;
    const sessionId = nextInteractionSessionIdRef.current;
    const next = beginStructuredPrototypeInteraction(current, request, sessionId);
    if (next === current) return null;
    nextInteractionSessionIdRef.current += 1;
    interactionRef.current = next;
    setInteraction(next);
    return sessionId;
  }, []);
  const advanceInteraction = useCallback(
    (sessionId: number, phase: "preview" | "committing"): boolean => {
      const current = interactionRef.current;
      const next = advanceStructuredPrototypeInteraction(current, sessionId, phase);
      if (next === current) return false;
      interactionRef.current = next;
      setInteraction(next);
      return true;
    },
    [],
  );
  const endInteraction = useCallback((sessionId: number): boolean => {
    const current = interactionRef.current;
    const next = endStructuredPrototypeInteraction(current, sessionId);
    if (next === current) return false;
    interactionRef.current = next;
    setInteraction(next);
    return true;
  }, []);
  const runLockedMutation = useCallback(
    async <T,>(
      operation: StructuredPrototypeMutationOperation,
      action: () => Promise<T>,
    ): Promise<T | null> => {
      const currentDraft = controller.draft;
      if (editorMutationLocked || currentDraft === null) return null;
      const sessionId = beginInteraction({
        kind: "mutation",
        operation,
        baseDocumentHash: currentDraft.documentHash,
      });
      if (sessionId === null) return null;
      try {
        return await action();
      } finally {
        endInteraction(sessionId);
      }
    },
    [beginInteraction, controller.draft, editorMutationLocked, endInteraction],
  );
  const interactionCapabilities = resolveStructuredPrototypeInteractionCapabilities(
    interaction,
    editorMutationLocked,
  );
  const gestureActive = interactionCapabilities.busy;
  const activeDrag =
    interaction.kind === "move" && interaction.phase === "active" ? interaction.source : null;
  const captureStructuredPrototypeDragPointer: CollisionDetection = useCallback((args) => {
    const activeInteraction = interactionRef.current;
    activeDragPointerStateRef.current =
      activeInteraction.kind === "move" && activeInteraction.phase === "active"
        ? updateStructuredPrototypeActiveDragPointerState(activeDragPointerStateRef.current, {
            interactionSessionId: activeInteraction.sessionId,
            pointerCoordinates: args.pointerCoordinates,
            collisionRect: args.collisionRect,
          })
        : inactiveStructuredPrototypeDragPointerState();
    return structuredPrototypeCollisionDetection(args);
  }, []);
  const handleResizeGestureChange = useCallback(
    (event: StructuredPrototypeResizeGestureEvent): number | null => {
      if (event.phase === "start") {
        const currentDraft = controller.draft;
        if (editorMutationLocked || currentDraft === null) return null;
        const sessionId = beginInteraction({
          kind: "resize",
          nodeId: event.nodeId,
          pointerId: event.pointerId,
          baseDocumentHash: currentDraft.documentHash,
          previewScale: event.previewScale,
        });
        if (sessionId !== null) setInteractionError(null);
        return sessionId;
      }
      if (event.phase === "preview") {
        return advanceInteraction(event.sessionId, "preview") ? event.sessionId : null;
      }
      if (event.phase === "commit") {
        return advanceInteraction(event.sessionId, "committing") ? event.sessionId : null;
      }
      endInteraction(event.sessionId);
      return null;
    },
    [advanceInteraction, beginInteraction, controller.draft, editorMutationLocked, endInteraction],
  );
  const handleFreeformMoveGestureChange = useCallback(
    (event: StructuredPrototypeFreeformMoveGestureEvent): number | null => {
      if (event.phase === "start") {
        const currentDraft = controller.draft;
        if (editorMutationLocked || currentDraft === null) return null;
        const sessionId = beginInteraction({
          kind: "freeformMove",
          nodeId: event.nodeId,
          freeformId: event.freeformId,
          pointerId: event.pointerId,
          baseDocumentHash: currentDraft.documentHash,
          previewScale: event.previewScale,
          gridSnappingEnabled: event.gridSnappingEnabled,
          gridIds: [...event.gridIds],
        });
        if (sessionId !== null) setInteractionError(null);
        return sessionId;
      }
      if (event.phase === "preview") {
        return advanceInteraction(event.sessionId, "preview") ? event.sessionId : null;
      }
      if (event.phase === "commit") {
        return advanceInteraction(event.sessionId, "committing") ? event.sessionId : null;
      }
      endInteraction(event.sessionId);
      return null;
    },
    [advanceInteraction, beginInteraction, controller.draft, editorMutationLocked, endInteraction],
  );
  const handlePanGestureStart = useCallback(
    (pointerId: number): number | null => {
      if (controller.saving) return null;
      return beginInteraction({ kind: "pan", pointerId });
    },
    [beginInteraction, controller.saving],
  );
  const handlePanGestureEnd = useCallback(
    (sessionId: number): void => {
      endInteraction(sessionId);
    },
    [endInteraction],
  );
  const handleMarqueeGestureChange = useCallback(
    (event: StructuredPrototypeMarqueeGestureEvent): number | null => {
      if (event.phase === "start") {
        if (controller.saving) return null;
        return beginInteraction({ kind: "marquee", pointerId: event.pointerId });
      }
      endInteraction(event.sessionId);
      return null;
    },
    [beginInteraction, controller.saving, endInteraction],
  );
  const handleAiApplyStart = useCallback((): number | null => {
    const currentDraft = controller.draft;
    if (controller.saving || currentDraft === null) return null;
    return beginInteraction({
      kind: "mutation",
      operation: "aiApply",
      baseDocumentHash: currentDraft.documentHash,
    });
  }, [beginInteraction, controller.draft, controller.saving]);
  const handleAiApplyEnd = useCallback(
    (sessionId: number): void => {
      endInteraction(sessionId);
    },
    [endInteraction],
  );
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor),
  );
  const historyShortcuts = useMemo(
    () => [
      {
        key: "z",
        ctrlKey: true,
        metaKey: false,
        shiftKey: false,
        altKey: false,
        action: () => {
          if (interactionRef.current.kind !== "idle") return;
          void runLockedMutation("history", undoHistory);
        },
      },
      {
        key: "z",
        ctrlKey: false,
        metaKey: true,
        shiftKey: false,
        altKey: false,
        action: () => {
          if (interactionRef.current.kind !== "idle") return;
          void runLockedMutation("history", undoHistory);
        },
      },
      {
        key: "z",
        ctrlKey: true,
        metaKey: false,
        shiftKey: true,
        altKey: false,
        action: () => {
          if (interactionRef.current.kind !== "idle") return;
          void runLockedMutation("history", redoHistory);
        },
      },
      {
        key: "z",
        ctrlKey: false,
        metaKey: true,
        shiftKey: true,
        altKey: false,
        action: () => {
          if (interactionRef.current.kind !== "idle") return;
          void runLockedMutation("history", redoHistory);
        },
      },
    ],
    [redoHistory, runLockedMutation, undoHistory],
  );
  useKeyboardShortcuts(historyShortcuts);
  const fullscreenShortcuts = useMemo(
    () =>
      isFullscreen && !gestureActive
        ? [
            {
              key: "Escape",
              action: () => {
                if (interactionRef.current.kind !== "idle") return;
                setIsFullscreen(false);
              },
            },
          ]
        : [],
    [gestureActive, isFullscreen],
  );
  useKeyboardShortcuts(fullscreenShortcuts);
  useEffect(
    () => () => {
      const frameId = activeMoveProjectionRef.current?.animationFrameId;
      if (frameId !== null && frameId !== undefined) cancelAnimationFrame(frameId);
    },
    [],
  );

  const persistedDocument = controller.draft?.document ?? null;
  const projectedDocumentOwnedByInteraction =
    projectedDocument !== null &&
    interaction.kind === "move" &&
    projectedDocument.ownerSessionId === interaction.sessionId;
  const document =
    projectedDocument !== null &&
    projectedDocumentOwnedByInteraction &&
    controller.draft?.documentHash === projectedDocument.baseDocumentHash
      ? projectedDocument.document
      : persistedDocument;
  const pageRailPages =
    interaction.kind === "move" &&
    interaction.phase === "active" &&
    interaction.source.kind === "page" &&
    persistedDocument !== null
      ? persistedDocument.pages
      : document?.pages;
  const runtime = controller.runtime;
  const viewport = viewportOverride ?? document?.settings.defaultViewport ?? "desktop";
  const inputBindings = useMemo(
    () => (document ? deriveFormInputBindings(document, false) : []),
    [document],
  );
  const paletteFormDefinition = useMemo(
    () => resolvePaletteFormDefinition(document?.runtime.forms ?? [], paletteFormId),
    [document, paletteFormId],
  );
  const activePage = useMemo(() => {
    if (!document || !runtime) return null;
    const targetId = manualPageId ?? runtime.state.currentPageId;
    return document.pages.find((page) => page.id === targetId) ?? document.pages[0] ?? null;
  }, [document, manualPageId, runtime]);
  const selectedFlowPage =
    document?.pages.find((page) => page.id === flowPageId) ?? document?.pages[0] ?? null;
  const selectedFlowPageId = selectedFlowPage?.id ?? null;
  const selectedFlowRule =
    document === null ||
    flowRuleSelection === null ||
    flowRuleSelection.kind === "pendingConnection"
      ? null
      : flowRuleSelection.kind === "existingRuleId"
        ? (document.runtime.rules.find((rule) => rule.id === flowRuleSelection.ruleId) ?? null)
        : (document.runtime.rules.find((rule) => rule.key === flowRuleSelection.ruleKey) ?? null);
  const selectedFlowRuleId = selectedFlowRule?.id ?? null;
  const flowInspectorSelection: StructuredPrototypeRuleInspectorSelection | null =
    flowRuleSelection?.kind === "pendingConnection"
      ? flowRuleSelection
      : selectedFlowRule === null
        ? null
        : { kind: "existingRule", rule: selectedFlowRule };
  const activeNodeSelection = useMemo(
    () =>
      activePage === null
        ? createStructuredPrototypeEmptySelection()
        : resolveStructuredPrototypeNodeSelection(
            activePage.root,
            nodeSelection.nodeIds,
            nodeSelection.primaryNodeId,
          ),
    [activePage, nodeSelection.nodeIds, nodeSelection.primaryNodeId],
  );
  const selectedNode =
    activePage !== null && activeNodeSelection.primaryNodeId !== null
      ? findStructuredPrototypeNode(activePage.root, activeNodeSelection.primaryNodeId)
      : null;
  const activeSelectedNodeIds = activeNodeSelection.nodeIds;
  const selectedNodeLocation =
    document !== null && activePage !== null && selectedNode !== null
      ? findStructuredPrototypeNodeLocation(document, activePage.id, selectedNode.id)
      : null;
  const selectedNodeParent =
    activePage !== null && selectedNodeLocation !== null
      ? findStructuredPrototypeNode(activePage.root, selectedNodeLocation.parentId)
      : null;
  const selectedNodePlacementModeAvailable =
    activeSelectedNodeIds.length === 1 &&
    selectedNodeParent !== null &&
    isStructuredPrototypeContainerNode(selectedNodeParent) &&
    selectedNodeParent.type !== "Freeform";
  const selectedNodeIsRuntimeBoundTable =
    document !== null &&
    selectedNode?.type === "Table" &&
    runtimeTableRowsBinding(document, selectedNode.id) !== null;
  const canSaveSelectedNodeAsComponent =
    document !== null &&
    activePage !== null &&
    activeSelectedNodeIds.length === 1 &&
    selectedNode !== null &&
    selectedNode.id !== activePage.root.id &&
    !structuredPrototypeSubtreeHasRuntimeReferences(document, selectedNode);
  const selectedRuntimeTable = useMemo<StructuredPrototypeInspectorRuntimeTable | null>(() => {
    if (document === null || runtime === null || selectedNode?.type !== "Table") return null;
    const binding = runtimeTableRowsBinding(document, selectedNode.id);
    if (binding === null) return null;
    const schema =
      document.runtime.entitySchemas.find((candidate) => candidate.id === binding.schemaId) ?? null;
    const rows = runtimeNodeRows(runtime.viewModel, selectedNode.id);
    if (schema === null || rows === null) return null;
    return {
      scenarioId: runtime.state.scenarioId,
      schemaId: binding.schemaId,
      fields: schema.fields,
      rows,
    };
  }, [document, runtime, selectedNode]);
  const deleteSelectedNodes = useCallback(async (): Promise<void> => {
    if (interactionRef.current.kind !== "idle") return;
    if (activePage === null || activeSelectedNodeIds.length === 0) return;
    if (activeSelectedNodeIds.length > STRUCTURED_PROTOTYPE_COMMAND_BATCH_LIMIT) {
      setInteractionError(
        t("prototype.structured.selection.deleteLimit", {
          count: String(STRUCTURED_PROTOTYPE_COMMAND_BATCH_LIMIT),
        }),
      );
      return;
    }
    setInteractionError(null);
    const deletingNodeIds = activeSelectedNodeIds;
    const removed = await runLockedMutation("commands", () =>
      controller.applyCommands(removeNodesBatch(deletingNodeIds)),
    );
    if (removed === true) {
      setNodeSelection(createStructuredPrototypeEmptySelection());
    }
  }, [activePage, activeSelectedNodeIds, controller, runLockedMutation, t]);
  const deleteShortcuts = useMemo(
    () =>
      mode === "design" &&
      canvasInteraction === "edit" &&
      !gestureActive &&
      activeSelectedNodeIds.length > 0 &&
      activePage !== null
        ? [
            { key: "Delete", action: () => void deleteSelectedNodes() },
            { key: "Backspace", action: () => void deleteSelectedNodes() },
          ]
        : [],
    [
      activePage,
      activeSelectedNodeIds.length,
      canvasInteraction,
      deleteSelectedNodes,
      gestureActive,
      mode,
    ],
  );
  useKeyboardShortcuts(deleteShortcuts);

  if (controller.loading && (!controller.draft || !runtime)) {
    return (
      <div className="grid h-full min-h-[420px] place-items-center bg-surface/70 text-sm text-text-muted">
        {t("prototype.structured.loading")}
      </div>
    );
  }
  if (!controller.draft && !runtime && !controller.error) {
    return (
      <StructuredPrototypeGenerationPanel
        projectId={projectId}
        onAccepted={controller.adoptAiDraft}
      />
    );
  }
  if (
    controller.draft &&
    controller.runtimeRecovery &&
    (!runtime || controller.runtimeRecovery.code === "runtime_reset_failed")
  ) {
    return (
      <div className="h-full min-h-[420px] bg-background/60">
        <StructuredPrototypeRuntimeRecoveryNotice
          issue={controller.runtimeRecovery}
          hasLastSnapshot={runtime !== null}
          isResetting={controller.saving}
          resetError={controller.error}
          onReset={() => void controller.resetRuntimePreview()}
        />
      </div>
    );
  }
  if (!controller.draft || !runtime || !document || !activePage) {
    return (
      <div className="grid h-full min-h-[420px] place-items-center bg-surface/70 p-6">
        <div className="max-w-md rounded-lg border border-failed-ring bg-failed-bg p-6 text-center">
          <p className="text-sm leading-6 text-status-failed">
            {controller.error ?? t("prototype.structured.loadFailed")}
          </p>
          <button
            type="button"
            className="mt-4 min-h-11 cursor-pointer rounded-lg bg-brand px-4 text-sm font-semibold text-black hover:bg-brand-strong"
            onClick={() => void controller.retry()}
          >
            {t("prototype.structured.retry")}
          </button>
        </div>
      </div>
    );
  }

  const runEvents = async (events: RuntimeEvent[]) => {
    if (interactionRef.current.kind !== "idle") return;
    setInteractionError(null);
    const applied = await runLockedMutation("runtime", () => controller.sendRuntimeEvents(events));
    if (applied === true) setManualPageId(null);
  };

  const activateNode = async (nodeId: string, event: "click" | "submit") => {
    const activationEvents = runtimeNodeActivationEvents(document, nodeId);
    if (!activationEvents.some((candidate) => candidate.event === event)) return;
    const events: RuntimeEvent[] = [];
    if (activationEvents.some((candidate) => candidate.event === "submit")) {
      const form = findStructuredPrototypeFormForNode(document, nodeId);
      if (form === null) {
        setInteractionError(t("prototype.structured.form.invalid"));
        return;
      }
      const inputNodeIds = new Set(structuredPrototypeInputNodes(form).map((input) => input.id));
      for (const binding of inputBindings) {
        if (binding.formId !== form.formDefinitionId || !inputNodeIds.has(binding.nodeId)) continue;
        const input = findStructuredPrototypeNode(form, binding.nodeId);
        if (input?.type !== "Input") continue;
        const rawValue = formValues[input.id] ?? input.value;
        if (binding.valueType === "integer") {
          const value = Number(rawValue);
          if (!Number.isSafeInteger(value)) {
            setInteractionError(t("prototype.structured.form.invalid"));
            return;
          }
          events.push({
            kind: "fieldValueCommitted",
            nodeId: input.id,
            formId: binding.formId,
            fieldId: binding.fieldId,
            value: { type: "integer", value },
          });
        } else {
          events.push({
            kind: "fieldValueCommitted",
            nodeId: input.id,
            formId: binding.formId,
            fieldId: binding.fieldId,
            value: { type: "string", value: rawValue },
          });
        }
      }
    }
    events.push(...activationEvents);
    await runEvents(events);
  };

  const clearProjectedDocumentForSession = (ownerSessionId: number): void => {
    const projection = projectedDocumentRef.current;
    if (projection === null || projection.ownerSessionId !== ownerSessionId) return;
    projectedDocumentRef.current = null;
    setProjectedDocument((current) => (current?.token === projection.token ? null : current));
  };

  const publishMoveProjection = (
    session: ActiveMoveProjectionSession,
    projected: StructuredPrototypeDocument,
    status: ProjectedPrototypeDocument["status"],
  ): ProjectedPrototypeDocument => {
    const current = projectedDocumentRef.current;
    if (
      current?.ownerSessionId === session.interactionSessionId &&
      current.document === projected &&
      current.status === status
    ) {
      return current;
    }
    const next = {
      ownerSessionId: session.interactionSessionId,
      baseDocumentHash: session.baseDocumentHash,
      token:
        current?.ownerSessionId === session.interactionSessionId
          ? current.token
          : Symbol(`prototype-move-${session.interactionSessionId}`),
      status,
      document: projected,
    };
    projectedDocumentRef.current = next;
    setProjectedDocument(next);
    return next;
  };

  const clearActiveMoveProjection = (): void => {
    const session = activeMoveProjectionRef.current;
    if (session === null) return;
    if (session.animationFrameId !== null) cancelAnimationFrame(session.animationFrameId);
    activeMoveProjectionRef.current = null;
    activeDragPointerStateRef.current = inactiveStructuredPrototypeDragPointerState();
    setActiveComponentDragNode(null);
    clearProjectedDocumentForSession(session.interactionSessionId);
  };

  const resolveFreeformDropPosition = (
    session: ActiveMoveProjectionSession,
    parentId: string,
    nodeId: string,
    targetIndex: number,
    fallback: StructuredPrototypeFreeformPosition | undefined,
    phase: "hover" | "drop",
  ): FreeformDropPositionResolution => {
    const deterministicFallback = fallback ?? defaultFreeformPosition(targetIndex);
    const pointerState = activeDragPointerStateRef.current;
    if (
      pointerState.kind === "keyboard" &&
      pointerState.interactionSessionId === session.interactionSessionId
    ) {
      return { position: deterministicFallback, remeasureAfterProjection: false };
    }
    if (
      pointerState.kind !== "pointer" ||
      pointerState.interactionSessionId !== session.interactionSessionId
    ) {
      return {
        position: phase === "drop" ? null : deterministicFallback,
        remeasureAfterProjection: false,
      };
    }
    const geometry = findPersistentFreeformDropGeometry(parentId, nodeId);
    if (geometry === null) {
      return {
        position: phase === "drop" ? null : deterministicFallback,
        remeasureAfterProjection: phase === "hover",
      };
    }
    const rect = geometry.container.getBoundingClientRect();
    if (
      !Number.isFinite(rect.left) ||
      !Number.isFinite(rect.top) ||
      !Number.isFinite(session.previewScale) ||
      session.previewScale <= 0
    ) {
      return {
        position: phase === "drop" ? null : deterministicFallback,
        remeasureAfterProjection: false,
      };
    }
    const position = resolveStructuredPrototypeFreeformPointerPlacement({
      pointerClientX: pointerState.coordinates.x,
      pointerClientY: pointerState.coordinates.y,
      grabOffsetClient: pointerState.grabOffsetClient,
      containerRect: { left: rect.left, top: rect.top },
      containerClientLeft: geometry.container.clientLeft,
      containerClientTop: geometry.container.clientTop,
      previewScale: session.previewScale,
      nodeWidth: geometry.nodeWidth,
      nodeHeight: geometry.nodeHeight,
      containerWidth: geometry.container.clientWidth,
      containerHeight: geometry.container.clientHeight,
    });
    session.pendingFreeformRemeasure = null;
    if (
      position.x > STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE ||
      position.y > STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE
    ) {
      return {
        position: phase === "drop" ? null : deterministicFallback,
        remeasureAfterProjection: false,
      };
    }
    return {
      position: {
        x: canonicalStructuredPrototypeFreeformValue(position.x),
        y: canonicalStructuredPrototypeFreeformValue(position.y),
      },
      remeasureAfterProjection: false,
    };
  };

  const projectActiveMove = (
    session: ActiveMoveProjectionSession,
    phase: "hover" | "drop" = "hover",
  ): ActiveMoveProjectionResult | null => {
    const currentProjection = projectedDocumentRef.current;
    const ownedProjection =
      currentProjection?.ownerSessionId === session.interactionSessionId ? currentProjection : null;
    if (session.kind === "page") {
      const targetPageId = session.latestTargetPageId;
      if (targetPageId === null) return null;
      if (
        session.projectedTargetPageId === targetPageId &&
        session.finalTargetIndex !== null &&
        (session.finalTargetIndex === session.originalIndex || ownedProjection !== null)
      ) {
        return { kind: "page", targetIndex: session.finalTargetIndex };
      }
      const projection = projectStructuredPrototypePageReorderByTargetPageId(
        session.authoritativeDocument,
        session.pageId,
        targetPageId,
      );
      if (projection === null) return null;
      const { targetIndex } = projection;
      session.finalTargetIndex = targetIndex;
      if (targetIndex === session.originalIndex) {
        session.projectedTargetPageId = targetPageId;
        clearProjectedDocumentForSession(session.interactionSessionId);
        return { kind: "page", targetIndex };
      }
      session.projectedTargetPageId = targetPageId;
      publishMoveProjection(session, projection.document, "hover");
      return { kind: "page", targetIndex };
    }
    if (session.kind === "node") {
      const target = session.latestTarget;
      if (target === null) return null;
      const sourceDocument = ownedProjection?.document ?? session.authoritativeDocument;
      const targetParent = findDocumentContainer(sourceDocument, session.pageId, target.parentId);
      if (targetParent === null) return null;
      if (
        session.pendingFreeformRemeasure !== null &&
        (session.pendingFreeformRemeasure.parentId !== targetParent.id ||
          session.pendingFreeformRemeasure.nodeId !== session.nodeId)
      ) {
        session.pendingFreeformRemeasure = null;
      }
      const authoritativeLocation = findStructuredPrototypeNodeLocation(
        session.authoritativeDocument,
        session.pageId,
        session.nodeId,
      );
      const authoritativePosition = authoritativeLocation?.position ?? undefined;
      const placement =
        targetParent.type === "Freeform"
          ? resolveFreeformDropPosition(
              session,
              targetParent.id,
              session.nodeId,
              target.index,
              authoritativePosition,
              phase,
            )
          : { position: authoritativePosition ?? null, remeasureAfterProjection: false };
      if (targetParent.type !== "Freeform") session.pendingFreeformRemeasure = null;
      const targetPosition = placement.position;
      if (targetParent.type === "Freeform" && targetPosition === null) return null;
      const projection = projectStructuredPrototypeNodeMoveToDropTarget(
        sourceDocument,
        session.pageId,
        session.nodeId,
        target,
        targetPosition,
      );
      if (projection === null) return null;
      session.finalLocation = projection.location;
      const originalLocation = findStructuredPrototypeNodeLocation(
        session.authoritativeDocument,
        session.pageId,
        session.nodeId,
      );
      if (originalLocation !== null && sameNodeLocation(projection.location, originalLocation)) {
        session.pendingFreeformRemeasure = null;
        clearProjectedDocumentForSession(session.interactionSessionId);
      } else {
        if (placement.remeasureAfterProjection) {
          session.pendingFreeformRemeasure = {
            parentId: targetParent.id,
            nodeId: session.nodeId,
          };
        }
        publishMoveProjection(session, projection.document, "hover");
      }
      return { kind: "node", location: projection.location };
    }
    const target = session.latestTarget;
    if (target === null) return null;
    const sourceDocument = ownedProjection?.document ?? session.authoritativeDocument;
    const targetParent = findDocumentContainer(sourceDocument, session.pageId, target.parentId);
    if (targetParent === null) return null;
    if (
      session.pendingFreeformRemeasure !== null &&
      (session.pendingFreeformRemeasure.parentId !== targetParent.id ||
        session.pendingFreeformRemeasure.nodeId !== session.transientNode.id)
    ) {
      session.pendingFreeformRemeasure = null;
    }
    const currentLocation = findStructuredPrototypeNodeLocation(
      sourceDocument,
      session.pageId,
      session.transientNode.id,
    );
    const currentPosition =
      currentLocation?.parentId === targetParent.id
        ? (currentLocation.position ?? undefined)
        : undefined;
    const placement =
      targetParent.type === "Freeform"
        ? resolveFreeformDropPosition(
            session,
            targetParent.id,
            session.transientNode.id,
            target.index,
            currentPosition,
            phase,
          )
        : { position: null, remeasureAfterProjection: false };
    if (targetParent.type !== "Freeform") session.pendingFreeformRemeasure = null;
    const targetPosition = placement.position;
    if (targetParent.type === "Freeform" && targetPosition === null) return null;
    const projection =
      currentLocation === null
        ? projectStructuredPrototypeNodeInsert(
            session.authoritativeDocument,
            session.pageId,
            target.parentId,
            target.index,
            session.transientNode,
            targetPosition,
          )
        : projectStructuredPrototypeNodeMoveToDropTarget(
            sourceDocument,
            session.pageId,
            session.transientNode.id,
            target,
            targetPosition,
          )?.document;
    if (projection === null || projection === undefined) return null;
    const location = findStructuredPrototypeNodeLocation(
      projection,
      session.pageId,
      session.transientNode.id,
    );
    if (location === null) return null;
    session.finalLocation = location;
    if (placement.remeasureAfterProjection) {
      session.pendingFreeformRemeasure = {
        parentId: targetParent.id,
        nodeId: session.transientNode.id,
      };
    }
    publishMoveProjection(session, projection, "hover");
    return { kind: session.kind, location };
  };

  const scheduleActiveMoveProjection = (session: ActiveMoveProjectionSession): void => {
    if (session.animationFrameId !== null) return;
    session.animationFrameId = requestAnimationFrame(() => {
      const activeSession = activeMoveProjectionRef.current;
      const activeInteraction = interactionRef.current;
      if (
        activeSession !== session ||
        activeInteraction.kind !== "move" ||
        activeInteraction.phase !== "active" ||
        activeInteraction.sessionId !== session.interactionSessionId
      ) {
        return;
      }
      activeSession.animationFrameId = null;
      const hasTarget =
        activeSession.kind === "page"
          ? activeSession.latestTargetPageId !== null
          : activeSession.latestTarget !== null;
      if (!hasTarget) {
        if (activeSession.kind === "page") {
          activeSession.projectedTargetPageId = null;
          activeSession.finalTargetIndex = null;
        } else {
          activeSession.finalLocation = null;
          activeSession.pendingFreeformRemeasure = null;
        }
        clearProjectedDocumentForSession(activeSession.interactionSessionId);
        return;
      }
      projectActiveMove(activeSession);
    });
  };

  const handleNodeElementRegistered = ({
    nodeId,
    parentId,
    element,
  }: StructuredPrototypeNodeElementRegisteredEvent): void => {
    const session = activeMoveProjectionRef.current;
    if (session === null || session.kind === "page") return;
    const activeInteraction = interactionRef.current;
    const projection = projectedDocumentRef.current;
    const expectedNodeId = session.kind === "node" ? session.nodeId : session.transientNode.id;
    const elementParentContainerId = element.parentElement?.dataset["containerId"] ?? null;
    if (
      !shouldScheduleStructuredPrototypeFreeformRegistrationRemeasure({
        sessionIsCurrent: activeMoveProjectionRef.current === session,
        sessionId: session.interactionSessionId,
        activeInteractionSessionId:
          activeInteraction.kind === "move" && activeInteraction.phase === "active"
            ? activeInteraction.sessionId
            : null,
        projectionOwnerSessionId: projection?.ownerSessionId ?? null,
        expectedNodeId,
        latestTargetParentId: session.latestTarget?.parentId ?? null,
        pending: session.pendingFreeformRemeasure,
        registration: { nodeId, parentId, elementParentContainerId },
      })
    ) {
      return;
    }
    session.pendingFreeformRemeasure = null;
    scheduleActiveMoveProjection(session);
  };

  const handleDragStart = (event: DragStartEvent) => {
    const currentDraft = controller.draft;
    if (
      editorMutationLocked ||
      currentDraft === null ||
      activePage === null ||
      interactionRef.current.kind !== "idle"
    ) {
      return;
    }
    clearActiveMoveProjection();
    setActiveNodeDragMirror(null);
    setActivePaletteDragNode(null);
    setActiveComponentDragNode(null);
    setInteractionError(null);
    const layer = readStructuredPrototypeLayerDragData(event.active.data.current);
    if (layer !== null) {
      beginInteraction({
        kind: "move",
        source: { kind: "layer", nodeId: layer.nodeId },
        baseDocumentHash: currentDraft.documentHash,
      });
      return;
    }
    const palette = readStructuredPrototypePaletteDragData(event.active.data.current);
    if (palette) {
      const formDefinition = resolvePaletteFormDefinition(
        currentDraft.document.runtime.forms,
        palette.formDefinitionId,
      );
      if (palette.nodeType === "Form" && formDefinition === null) {
        setInteractionError(t("prototype.structured.form.selectionRequired"));
        return;
      }
      const newNodeKey = `new-${palette.nodeType.toLowerCase()}-${crypto.randomUUID().slice(0, 8)}`;
      const commandNode = createPaletteNode(
        palette.nodeType,
        newNodeKey,
        formDefinition,
        prototypePaletteLabels,
      );
      const sessionId = beginInteraction({
        kind: "move",
        source: { kind: "palette", nodeType: palette.nodeType },
        baseDocumentHash: currentDraft.documentHash,
      });
      if (sessionId === null) return;
      const transientNode = materializeStructuredPrototypePalettePreviewNode(
        commandNode,
        sessionId,
      );
      setActivePaletteDragNode(transientNode);
      activeMoveProjectionRef.current = {
        kind: "palette",
        interactionSessionId: sessionId,
        baseDocumentHash: currentDraft.documentHash,
        authoritativeDocument: currentDraft.document,
        previewScale: effectivePreviewScale,
        pageId: activePage.id,
        commandNode,
        transientNode,
        latestTarget: null,
        finalLocation: null,
        animationFrameId: null,
        pendingFreeformRemeasure: null,
      };
      return;
    }
    const component = readStructuredPrototypeComponentDefinitionDragData(event.active.data.current);
    if (component !== null) {
      const definition = currentDraft.document.componentDefinitions.find(
        (candidate) => candidate.id === component.componentId,
      );
      if (definition === undefined) {
        setInteractionError(t("prototype.structured.canvas.invalidDrop"));
        return;
      }
      const sessionId = beginInteraction({
        kind: "move",
        source: { kind: "component", componentId: component.componentId },
        baseDocumentHash: currentDraft.documentHash,
      });
      if (sessionId === null) return;
      const transientNode = materializeStructuredPrototypeComponentPreviewNode(
        definition.root,
        sessionId,
      );
      setActiveComponentDragNode(transientNode);
      activeMoveProjectionRef.current = {
        kind: "component",
        interactionSessionId: sessionId,
        baseDocumentHash: currentDraft.documentHash,
        authoritativeDocument: currentDraft.document,
        previewScale: effectivePreviewScale,
        pageId: activePage.id,
        componentId: component.componentId,
        transientNode,
        latestTarget: null,
        finalLocation: null,
        animationFrameId: null,
        pendingFreeformRemeasure: null,
      };
      return;
    }
    const dragged = readStructuredPrototypeNodeDragData(event.active.data.current);
    if (dragged) {
      const dragMirror =
        readStructuredPrototypeNodeDragMirrorCapture(event.active.data.current)?.() ?? null;
      if (dragMirror === null) {
        setInteractionError(t("prototype.structured.canvas.dragPreviewFailed"));
        return;
      }
      const sessionId = beginInteraction({
        kind: "move",
        source: { kind: "node", nodeId: dragged.nodeId },
        baseDocumentHash: currentDraft.documentHash,
      });
      if (sessionId === null) return;
      setActiveNodeDragMirror(dragMirror);
      activeMoveProjectionRef.current = {
        kind: "node",
        interactionSessionId: sessionId,
        baseDocumentHash: currentDraft.documentHash,
        authoritativeDocument: currentDraft.document,
        previewScale: effectivePreviewScale,
        pageId: activePage.id,
        nodeId: dragged.nodeId,
        latestTarget: null,
        finalLocation: null,
        animationFrameId: null,
        pendingFreeformRemeasure: null,
      };
      return;
    }
    const page = readStructuredPrototypePageDragData(event.active.data.current);
    if (page) {
      const originalIndex = currentDraft.document.pages.findIndex(
        (candidate) => candidate.id === page.pageId,
      );
      if (originalIndex < 0) return;
      const sessionId = beginInteraction({
        kind: "move",
        source: { kind: "page", pageId: page.pageId },
        baseDocumentHash: currentDraft.documentHash,
      });
      if (sessionId === null) return;
      activeMoveProjectionRef.current = {
        kind: "page",
        interactionSessionId: sessionId,
        baseDocumentHash: currentDraft.documentHash,
        authoritativeDocument: currentDraft.document,
        previewScale: effectivePreviewScale,
        pageId: page.pageId,
        originalIndex,
        latestTargetPageId: null,
        projectedTargetPageId: null,
        finalTargetIndex: null,
        animationFrameId: null,
        pendingFreeformRemeasure: null,
      };
    }
  };

  const handleDragOver = (event: DragOverEvent) => {
    const session = activeMoveProjectionRef.current;
    const activeInteraction = interactionRef.current;
    if (
      session === null ||
      activeInteraction.kind !== "move" ||
      activeInteraction.phase !== "active" ||
      activeInteraction.sessionId !== session.interactionSessionId
    ) {
      return;
    }
    if (session.kind === "page") {
      const dragged = readStructuredPrototypePageDragData(event.active.data.current);
      if (dragged?.pageId !== session.pageId) return;
      const target =
        event.over === null ? null : readStructuredPrototypePageDragData(event.over.data.current);
      session.latestTargetPageId = target?.pageId ?? null;
    } else {
      const sourceMatches =
        session.kind === "node"
          ? readStructuredPrototypeNodeDragData(event.active.data.current)?.nodeId ===
            session.nodeId
          : session.kind === "palette"
            ? readStructuredPrototypePaletteDragData(event.active.data.current)?.nodeType ===
              session.commandNode.type
            : readStructuredPrototypeComponentDefinitionDragData(event.active.data.current)
                ?.componentId === session.componentId;
      if (!sourceMatches) return;
      session.latestTarget =
        event.over === null ? null : readStructuredPrototypeDropTarget(event.over.data.current);
    }
    scheduleActiveMoveProjection(session);
  };

  const handleDragMove = (): void => {
    const session = activeMoveProjectionRef.current;
    const activeInteraction = interactionRef.current;
    if (
      session === null ||
      activeInteraction.kind !== "move" ||
      activeInteraction.phase !== "active" ||
      activeInteraction.sessionId !== session.interactionSessionId
    ) {
      return;
    }
    scheduleActiveMoveProjection(session);
  };

  const cancelActiveMove = (session: ActiveMoveProjectionSession): void => {
    const activeInteraction = interactionRef.current;
    if (
      activeInteraction.kind !== "move" ||
      activeInteraction.phase !== "active" ||
      activeInteraction.sessionId !== session.interactionSessionId
    ) {
      return;
    }
    if (session.animationFrameId !== null) cancelAnimationFrame(session.animationFrameId);
    if (activeMoveProjectionRef.current === session) activeMoveProjectionRef.current = null;
    activeDragPointerStateRef.current = inactiveStructuredPrototypeDragPointerState();
    setActiveNodeDragMirror(null);
    setActivePaletteDragNode(null);
    setActiveComponentDragNode(null);
    clearProjectedDocumentForSession(session.interactionSessionId);
    endInteraction(session.interactionSessionId);
  };

  const commitActiveMove = (
    session: ActiveMoveProjectionSession,
    batch: Parameters<typeof controller.applyCommands>[0],
  ): boolean => {
    if (!advanceInteraction(session.interactionSessionId, "committing")) return false;
    if (session.animationFrameId !== null) cancelAnimationFrame(session.animationFrameId);
    if (activeMoveProjectionRef.current === session) activeMoveProjectionRef.current = null;
    activeDragPointerStateRef.current = inactiveStructuredPrototypeDragPointerState();
    setActiveNodeDragMirror(null);
    setActivePaletteDragNode(null);
    setActiveComponentDragNode(null);
    const hoverProjection = projectedDocumentRef.current;
    if (hoverProjection?.ownerSessionId !== session.interactionSessionId) {
      setInteractionError(t("prototype.structured.canvas.invalidDrop"));
      endInteraction(session.interactionSessionId);
      return false;
    }
    const pendingProjection = publishMoveProjection(session, hoverProjection.document, "pending");
    void (async () => {
      try {
        await controller.applyCommands(batch);
      } catch (error) {
        console.error("structured prototype move commit failed:", error);
        setInteractionError(t("prototype.structured.canvas.commitFailed"));
      } finally {
        if (projectedDocumentRef.current?.token === pendingProjection.token) {
          projectedDocumentRef.current = null;
          setProjectedDocument((current) =>
            current?.token === pendingProjection.token ? null : current,
          );
        }
        endInteraction(session.interactionSessionId);
      }
    })();
    return true;
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const activeInteraction = interactionRef.current;
    if (
      activeInteraction.kind === "move" &&
      activeInteraction.phase === "active" &&
      activeInteraction.source.kind === "layer"
    ) {
      const dragged = readStructuredPrototypeLayerDragData(event.active.data.current);
      activeDragPointerStateRef.current = inactiveStructuredPrototypeDragPointerState();
      endInteraction(activeInteraction.sessionId);
      if (dragged?.nodeId !== activeInteraction.source.nodeId) {
        setInteractionError(t("prototype.structured.canvas.invalidDrop"));
      }
      return;
    }
    const session = activeMoveProjectionRef.current;
    if (
      session === null ||
      activeInteraction.kind !== "move" ||
      activeInteraction.phase !== "active" ||
      activeInteraction.sessionId !== session.interactionSessionId
    ) {
      activeDragPointerStateRef.current = inactiveStructuredPrototypeDragPointerState();
      return;
    }
    const currentDraft = controller.draft;
    if (currentDraft === null || currentDraft.documentHash !== session.baseDocumentHash) {
      setInteractionError(t("prototype.structured.canvas.invalidDrop"));
      cancelActiveMove(session);
      return;
    }
    if (session.animationFrameId !== null) {
      cancelAnimationFrame(session.animationFrameId);
      session.animationFrameId = null;
    }
    if (session.kind === "page") {
      const dragged = readStructuredPrototypePageDragData(event.active.data.current);
      const target =
        event.over === null ? null : readStructuredPrototypePageDragData(event.over.data.current);
      if (dragged?.pageId !== session.pageId || target === null) {
        cancelActiveMove(session);
        return;
      }
      session.latestTargetPageId = target.pageId;
      const result = projectActiveMove(session);
      if (
        result?.kind !== "page" ||
        result.targetIndex === session.originalIndex ||
        projectedDocumentRef.current === null
      ) {
        cancelActiveMove(session);
        return;
      }
      const batch = reorderPageBatch(
        session.authoritativeDocument,
        session.pageId,
        result.targetIndex,
      );
      if (batch === null) {
        cancelActiveMove(session);
        return;
      }
      commitActiveMove(session, batch);
      return;
    }
    if (session.kind === "palette") {
      const dragged = readStructuredPrototypePaletteDragData(event.active.data.current);
      const target =
        event.over === null ? null : readStructuredPrototypeDropTarget(event.over.data.current);
      if (dragged?.nodeType !== session.commandNode.type || target === null) {
        cancelActiveMove(session);
        return;
      }
      session.latestTarget = target;
      const result = projectActiveMove(session, "drop");
      if (result?.kind !== "palette" || projectedDocumentRef.current === null) {
        setInteractionError(t("prototype.structured.canvas.invalidDrop"));
        cancelActiveMove(session);
        return;
      }
      const targetParent = findDocumentContainer(
        session.authoritativeDocument,
        session.pageId,
        result.location.parentId,
      );
      if (targetParent === null) {
        cancelActiveMove(session);
        return;
      }
      commitActiveMove(
        session,
        insertPaletteNodeBatch(
          targetParent,
          result.location.index,
          session.commandNode,
          result.location.position,
        ),
      );
      return;
    }
    if (session.kind === "component") {
      const dragged = readStructuredPrototypeComponentDefinitionDragData(event.active.data.current);
      const target =
        event.over === null ? null : readStructuredPrototypeDropTarget(event.over.data.current);
      if (dragged?.componentId !== session.componentId || target === null) {
        cancelActiveMove(session);
        return;
      }
      session.latestTarget = target;
      const result = projectActiveMove(session, "drop");
      if (result?.kind !== "component" || projectedDocumentRef.current === null) {
        setInteractionError(t("prototype.structured.canvas.invalidDrop"));
        cancelActiveMove(session);
        return;
      }
      const targetParent = findDocumentContainer(
        session.authoritativeDocument,
        session.pageId,
        result.location.parentId,
      );
      if (targetParent === null) {
        cancelActiveMove(session);
        return;
      }
      commitActiveMove(
        session,
        instantiateComponentBatch(
          session.componentId,
          targetParent,
          result.location.index,
          result.location.position,
        ),
      );
      return;
    }
    const dragged = readStructuredPrototypeNodeDragData(event.active.data.current);
    const target =
      event.over === null ? null : readStructuredPrototypeDropTarget(event.over.data.current);
    if (dragged?.nodeId !== session.nodeId || target === null) {
      cancelActiveMove(session);
      return;
    }
    session.latestTarget = target;
    const result = projectActiveMove(session, "drop");
    const originalLocation = findStructuredPrototypeNodeLocation(
      session.authoritativeDocument,
      session.pageId,
      session.nodeId,
    );
    if (
      result?.kind !== "node" ||
      originalLocation === null ||
      sameNodeLocation(result.location, originalLocation) ||
      projectedDocumentRef.current === null
    ) {
      if (result === null) setInteractionError(t("prototype.structured.canvas.invalidDrop"));
      cancelActiveMove(session);
      return;
    }
    const targetParent = findDocumentContainer(
      session.authoritativeDocument,
      session.pageId,
      result.location.parentId,
    );
    if (targetParent === null) {
      cancelActiveMove(session);
      return;
    }
    commitActiveMove(
      session,
      moveNodeBatch(session.nodeId, targetParent, result.location.index, result.location.position),
    );
  };

  const insertPaletteNode = (
    type: StructuredPrototypePaletteType,
    formDefinitionId: string | null,
  ) => {
    if (editorMutationLocked || interactionRef.current.kind !== "idle") return;
    const root = activePage.root;
    if (!isStructuredPrototypeContainerNode(root)) return;
    const formDefinition = resolvePaletteFormDefinition(document.runtime.forms, formDefinitionId);
    if (type === "Form" && formDefinition === null) {
      setInteractionError(t("prototype.structured.form.selectionRequired"));
      return;
    }
    const key = `new-${type.toLowerCase()}-${crypto.randomUUID().slice(0, 8)}`;
    void runLockedMutation("commands", () =>
      controller.applyCommands(
        insertPaletteNodeBatch(
          root,
          root.children.length,
          createPaletteNode(type, key, formDefinition, prototypePaletteLabels),
          root.type === "Freeform" ? defaultFreeformPosition(root.children.length) : undefined,
        ),
      ),
    );
    setMobileDrawer(null);
  };

  const insertComponentInstance = (componentId: string): void => {
    if (editorMutationLocked || interactionRef.current.kind !== "idle") return;
    const root = activePage.root;
    if (!isStructuredPrototypeContainerNode(root)) return;
    void runLockedMutation("commands", () =>
      controller.applyCommands(
        instantiateComponentBatch(
          componentId,
          root,
          root.children.length,
          root.type === "Freeform" ? defaultFreeformPosition(root.children.length) : undefined,
        ),
      ),
    );
    setMobileDrawer(null);
  };

  const removeComponentDefinition = (componentId: string): void => {
    void runLockedMutation("commands", () =>
      controller.applyCommands(removeComponentDefinitionBatch(componentId)),
    );
  };

  const saveNodeAsComponent = (nodeId: string): void => {
    void runLockedMutation("commands", () =>
      controller.applyCommands(
        defineComponentBatch(`component-${crypto.randomUUID().slice(0, 8)}`, nodeId),
      ),
    );
  };

  const handlePageSelect = (pageId: string): void => {
    if (interactionRef.current.kind !== "idle") return;
    setManualPageId(pageId);
    setNodeSelection(createStructuredPrototypeEmptySelection());
    setMobileDrawer(null);
  };

  const applyCreatedPage = async (
    kind: "add" | "duplicate",
    sourcePageId: string,
    batch: Parameters<typeof controller.applyCommandsWithResult>[0],
  ): Promise<boolean> => {
    const currentDraft = controller.draft;
    if (interactionRef.current.kind !== "idle" || currentDraft === null) return false;
    const previousPageIds = currentDraft.document.pages.map((page) => page.id);
    const allocationKey = structuredPrototypePageAllocationKey(kind, sourcePageId);
    setInteractionError(null);
    const application = await runLockedMutation("commands", () =>
      controller.applyCommandsWithResult(batch),
    );
    if (application === null) return false;
    const pageId = resolveStructuredPrototypeCreatedPageId(
      previousPageIds,
      allocationKey,
      application,
    );
    if (pageId === null) {
      setInteractionError(t("prototype.structured.pages.selectionFailed"));
      return false;
    }
    setManualPageId(pageId);
    setFlowPageId(pageId);
    setNodeSelection(createStructuredPrototypeEmptySelection());
    return true;
  };

  const addPage = async (): Promise<boolean> => {
    const sourcePageId = mode === "flow" ? (selectedFlowPageId ?? activePage.id) : activePage.id;
    try {
      return await applyCreatedPage(
        "add",
        sourcePageId,
        addPageBatch(sourcePageId, t("prototype.structured.pages.newTitle"), true),
      );
    } catch (error) {
      console.error("structured prototype page add failed:", error);
      setInteractionError(t("prototype.structured.pages.addFailed"));
      return false;
    }
  };

  const duplicatePage = async (pageId: string, title: string): Promise<boolean> => {
    try {
      return await applyCreatedPage(
        "duplicate",
        pageId,
        duplicatePageBatch(pageId, t("prototype.structured.pages.copyTitle", { name: title })),
      );
    } catch (error) {
      console.error("structured prototype page duplicate failed:", error);
      setInteractionError(t("prototype.structured.pages.duplicateFailed"));
      return false;
    }
  };

  const renamePage = async (pageId: string, title: string): Promise<boolean> => {
    if (interactionRef.current.kind !== "idle") return false;
    setInteractionError(null);
    try {
      const application = await runLockedMutation("commands", () =>
        controller.applyCommandsWithResult(renamePageBatch(pageId, title)),
      );
      return application !== null;
    } catch (error) {
      console.error("structured prototype page rename failed:", error);
      setInteractionError(t("prototype.structured.pages.renameFailed"));
      return false;
    }
  };

  const deletePage = async (pageId: string): Promise<boolean> => {
    const currentDraft = controller.draft;
    if (interactionRef.current.kind !== "idle" || currentDraft === null) return false;
    const pages = currentDraft.document.pages;
    const sourceIndex = pages.findIndex((page) => page.id === pageId);
    if (sourceIndex < 0 || pages.length <= 1) return false;
    const fallbackPageId = resolveStructuredPrototypeNearestSurvivingPageId(pages, pageId);
    if (fallbackPageId === null) return false;
    setInteractionError(null);
    try {
      const application = await runLockedMutation("commands", () =>
        controller.applyCommandsWithResult(deletePageBatch(pageId)),
      );
      if (application === null) return false;
      if (
        application.draft.document.pages.length !== pages.length - 1 ||
        application.draft.document.pages.some((page) => page.id === pageId)
      ) {
        setInteractionError(t("prototype.structured.pages.deleteFailed"));
        return false;
      }
      if (activePage.id === pageId) {
        setManualPageId(fallbackPageId);
        setNodeSelection(createStructuredPrototypeEmptySelection());
      }
      if (selectedFlowPageId === pageId) setFlowPageId(fallbackPageId);
      return true;
    } catch (error) {
      console.error("structured prototype page delete failed:", error);
      setInteractionError(
        visibleMutationError(error, t("prototype.structured.pages.deleteFailed")),
      );
      return false;
    }
  };

  const handleLayerSelect = (nodeId: string): void => {
    if (interactionRef.current.kind !== "idle") return;
    setNodeSelection(resolveStructuredPrototypeNodeSelection(activePage.root, [nodeId], nodeId));
    setInspectorTab("properties");
    setInteractionError(null);
    if (!desktopLayout) setMobileDrawer(null);
  };

  const renameLayer = async (nodeId: string, name: string): Promise<boolean> => {
    if (interactionRef.current.kind !== "idle") return false;
    setInteractionError(null);
    try {
      const renamed = await runLockedMutation("commands", () =>
        controller.applyCommandsWithResult(updateNodeNameBatch(nodeId, name)),
      );
      if (renamed !== null) return true;
      setInteractionError(t("prototype.structured.layers.renameFailed"));
      return false;
    } catch (error) {
      console.error("structured prototype layer rename failed:", error);
      setInteractionError(t("prototype.structured.layers.renameFailed"));
      return false;
    }
  };

  const changeLayerVisibility = (nodeId: string, visibility: "visible" | "hidden"): void => {
    if (interactionRef.current.kind !== "idle") return;
    setInteractionError(null);
    void (async () => {
      try {
        const changed = await runLockedMutation("commands", () =>
          controller.applyCommandsWithResult({
            commandContractVersion: 1,
            summary: visibility === "visible" ? "Show component" : "Hide component",
            commands: [
              {
                kind: "setNodeProperty",
                node: { kind: "existing", nodeId },
                update: { kind: "visibility", visibility },
              },
            ],
          }),
        );
        if (changed === null) {
          setInteractionError(t("prototype.structured.layers.visibilityFailed"));
        }
      } catch (error) {
        console.error("structured prototype layer visibility change failed:", error);
        setInteractionError(t("prototype.structured.layers.visibilityFailed"));
      }
    })();
  };

  const moveLayer = (move: StructuredPrototypeLayerDropAccepted): void => {
    const currentInteraction = interactionRef.current;
    if (
      currentInteraction.kind === "move" &&
      currentInteraction.source.kind === "layer" &&
      currentInteraction.source.nodeId === move.nodeId
    ) {
      endInteraction(currentInteraction.sessionId);
    } else if (currentInteraction.kind !== "idle") {
      return;
    }
    const targetParent = findDocumentContainer(document, activePage.id, move.targetParentId);
    if (targetParent === null) {
      setInteractionError(t("prototype.structured.canvas.invalidDrop"));
      return;
    }
    setInteractionError(null);
    void (async () => {
      try {
        const moved = await runLockedMutation("commands", () =>
          controller.applyCommandsWithResult(
            moveNodeBatch(move.nodeId, targetParent, move.targetIndex, move.targetPosition),
          ),
        );
        if (moved === null) setInteractionError(t("prototype.structured.layers.moveFailed"));
      } catch (error) {
        console.error("structured prototype layer move failed:", error);
        setInteractionError(t("prototype.structured.layers.moveFailed"));
      }
    })();
  };

  const refuseLayerDrop = (reason: StructuredPrototypeLayerDropRefusalReason): void => {
    const currentInteraction = interactionRef.current;
    if (currentInteraction.kind === "move" && currentInteraction.source.kind === "layer") {
      endInteraction(currentInteraction.sessionId);
    }
    if (reason === "unchanged" || reason === "target-not-found") {
      setInteractionError(null);
      return;
    }
    setInteractionError(t("prototype.structured.canvas.invalidDrop"));
  };

  const handleViewportSelect = (value: StudioViewport): void => {
    if (interactionRef.current.kind !== "idle") return;
    setViewportOverride(value);
  };

  const openDeleteDialog = (): void => {
    if (interactionRef.current.kind !== "idle") return;
    setDeleteError(null);
    setDeleteDialogOpen(true);
  };

  const activateRow = (nodeId: string, entity: { id: string; schemaId: string }) => {
    void runEvents([
      {
        kind: "tableRowActivated",
        nodeId,
        entityRef: {
          type: "entityRef",
          schemaId: entity.schemaId,
          entityId: entity.id,
        },
      },
    ]);
  };

  const roleLabels = document.runtime.roles;
  const showRoleControl =
    structuredPrototypeShowsRoleControl(document) && runtime.state.allowSimulatedRoleSwitch;
  const paletteLabels = {
    Freeform: t("prototype.structured.palette.freeform"),
    Stack: t("prototype.structured.palette.stack"),
    Grid: t("prototype.structured.palette.grid"),
    Form: t("prototype.structured.palette.form"),
    Text: t("prototype.structured.palette.text"),
    Input: t("prototype.structured.palette.input"),
    Button: t("prototype.structured.palette.button"),
    Table: t("prototype.structured.palette.table"),
    Divider: t("prototype.structured.palette.divider"),
    Badge: t("prototype.structured.palette.badge"),
  };
  const prototypePaletteLabels = {
    Freeform: getDictionaryValue(document.locale, "prototype.structured.palette.freeform"),
    Stack: getDictionaryValue(document.locale, "prototype.structured.palette.stack"),
    Grid: getDictionaryValue(document.locale, "prototype.structured.palette.grid"),
    Form: getDictionaryValue(document.locale, "prototype.structured.palette.form"),
    Text: getDictionaryValue(document.locale, "prototype.structured.palette.text"),
    Input: getDictionaryValue(document.locale, "prototype.structured.palette.input"),
    Button: getDictionaryValue(document.locale, "prototype.structured.palette.button"),
    Table: getDictionaryValue(document.locale, "prototype.structured.palette.table"),
    Divider: getDictionaryValue(document.locale, "prototype.structured.palette.divider"),
    Badge: getDictionaryValue(document.locale, "prototype.structured.palette.badge"),
  };
  const layerTreeLabels = {
    tree: t("prototype.structured.layers.tree"),
    select: (name: string) => t("prototype.structured.layers.select", { name }),
    expand: (name: string) => t("prototype.structured.layers.expand", { name }),
    collapse: (name: string) => t("prototype.structured.layers.collapse", { name }),
    rename: (name: string) => t("prototype.structured.layers.rename", { name }),
    renameInput: (name: string) => t("prototype.structured.layers.renameInput", { name }),
    show: (name: string) => t("prototype.structured.layers.show", { name }),
    hide: (name: string) => t("prototype.structured.layers.hide", { name }),
    drag: (name: string) => t("prototype.structured.layers.drag", { name }),
    nameRequired: t("prototype.structured.layers.nameRequired"),
    renameFailed: t("prototype.structured.layers.renameFailed"),
  };
  const activePageLayerCount = deriveStructuredPrototypeLayerRows(activePage.root).length;
  const visibleError =
    interactionError ?? (controller.runtimeRecovery === null ? controller.error : null);
  const activeDragPage =
    activeDrag?.kind === "page"
      ? document.pages.find((page) => page.id === activeDrag.pageId)
      : null;
  const activeOverlayViewportWidth =
    viewport === "desktop" ? activePage.viewport.width : FIXED_OVERLAY_VIEWPORT_WIDTH[viewport];

  const persistPositionedSelectionPositions = async (
    items: readonly StructuredPrototypeGroupTransformItem[],
    options: {
      minimumItems: number;
      summary: string;
      unavailableMessage: string;
      failureMessage: string;
    },
  ): Promise<boolean> => {
    if (interactionRef.current.kind !== "idle") return false;
    const positionedSelection = resolveStructuredPrototypePositionedSelection(
      activePage.root,
      activeSelectedNodeIds,
    );
    if (
      items.length < options.minimumItems ||
      positionedSelection === null ||
      !sameStructuredPrototypeNodeIds(
        items,
        positionedSelection.items.map((item) => item.node.id),
      )
    ) {
      setInteractionError(options.unavailableMessage);
      return false;
    }
    const currentItemsById = new Map(
      positionedSelection.items.map((item) => [item.node.id, item] as const),
    );
    const changedItems = items.filter((item) => {
      const current = currentItemsById.get(item.nodeId);
      if (current === undefined) {
        throw new Error(`selected group node ${item.nodeId} was not resolved`);
      }
      return (
        current.node.layoutItem.position?.x !== canonicalStructuredPrototypeFreeformValue(item.x) ||
        current.node.layoutItem.position.y !== canonicalStructuredPrototypeFreeformValue(item.y)
      );
    });
    if (changedItems.length === 0) {
      setInteractionError(null);
      return true;
    }
    setInteractionError(null);
    const applied = await runLockedMutation("commands", () =>
      controller.applyCommands(
        setPositionedGroupLayoutBatch(changedItems, "position", options.summary),
      ),
    );
    const succeeded = applied === true;
    setInteractionError(succeeded ? null : options.failureMessage);
    return succeeded;
  };

  const arrangePositionedGroup = (
    items: readonly StructuredPrototypeGroupTransformItem[],
  ): Promise<boolean> =>
    persistPositionedSelectionPositions(items, {
      minimumItems: 2,
      summary: `Arrange ${items.length} positioned components`,
      unavailableMessage: t("prototype.structured.canvas.freeformGroupMoveUnavailable"),
      failureMessage: t("prototype.structured.canvas.freeformGroupArrangeFailed"),
    });

  const nudgePositionedSelection = (
    items: readonly StructuredPrototypeGroupTransformItem[],
  ): Promise<boolean> =>
    persistPositionedSelectionPositions(items, {
      minimumItems: 1,
      summary: `Nudge ${items.length} positioned component${items.length === 1 ? "" : "s"}`,
      unavailableMessage: t("prototype.structured.canvas.freeformMoveFailed"),
      failureMessage: t("prototype.structured.canvas.freeformMoveFailed"),
    });

  const movePositionedNode = async (
    nodeId: string,
    x: number,
    y: number,
    evidenceCapture: StructuredPrototypeFreeformMoveEvidenceCapture,
  ): Promise<boolean> => {
    const moveInteraction = interactionRef.current;
    const currentDraft = controller.draft;
    const replay = replayStructuredPrototypeFreeformMove(evidenceCapture);
    const capturedGridIds = replay.canonicalInput.grids.map((grid) => grid.id);
    if (
      moveInteraction.kind !== "freeformMove" ||
      moveInteraction.phase !== "committing" ||
      moveInteraction.nodeId !== nodeId ||
      moveInteraction.freeformId !== evidenceCapture.freeformId ||
      currentDraft === null ||
      currentDraft.documentHash !== moveInteraction.baseDocumentHash ||
      moveInteraction.previewScale !== replay.canonicalInput.previewScale ||
      moveInteraction.gridSnappingEnabled !== replay.canonicalInput.gridSnappingEnabled ||
      !sameOrderedIds(moveInteraction.gridIds, capturedGridIds) ||
      x !== replay.position.x ||
      y !== replay.position.y ||
      editorMutationLocked
    ) {
      setInteractionError(t("prototype.structured.canvas.freeformMoveFailed"));
      return false;
    }
    const positionedSelection = resolveStructuredPrototypePositionedSelection(
      activePage.root,
      evidenceCapture.selectedNodeIds,
    );
    if (positionedSelection === null) {
      setInteractionError(
        activeSelectedNodeIds.length > 1
          ? t("prototype.structured.canvas.freeformGroupMoveUnavailable")
          : t("prototype.structured.canvas.freeformMoveFailed"),
      );
      return false;
    }
    const activeSelectedNodeIdSet = new Set(activeSelectedNodeIds);
    if (
      activeSelectedNodeIdSet.size !== activeSelectedNodeIds.length ||
      positionedSelection.items.length !== activeSelectedNodeIds.length ||
      !positionedSelection.items.every((item) => activeSelectedNodeIdSet.has(item.node.id))
    ) {
      setInteractionError(t("prototype.structured.canvas.freeformMoveFailed"));
      return false;
    }
    const currentGridIds =
      positionedSelection.parent.type === "Freeform"
        ? (positionedSelection.parent.grids ?? []).map((grid) => grid.id)
        : [];
    if (
      positionedSelection.parent.id !== moveInteraction.freeformId ||
      !positionedSelection.items.some((item) => item.node.id === nodeId) ||
      !sameOrderedIds(currentGridIds, capturedGridIds)
    ) {
      setInteractionError(t("prototype.structured.canvas.freeformMoveFailed"));
      return false;
    }
    const deltaX = replay.position.x - replay.canonicalInput.selectionBounds.x;
    const deltaY = replay.position.y - replay.canonicalInput.selectionBounds.y;
    const projectedItems = positionedSelection.items.map((item) => {
      const currentPosition = item.node.layoutItem.position;
      if (currentPosition === undefined) {
        throw new Error(`selected positioned node ${item.node.id} has no position`);
      }
      const targetX = item.x + deltaX;
      const targetY = item.y + deltaY;
      return {
        nodeId: item.node.id,
        x: targetX,
        y: targetY,
        changed:
          currentPosition.x !== canonicalStructuredPrototypeFreeformValue(targetX) ||
          currentPosition.y !== canonicalStructuredPrototypeFreeformValue(targetY),
      };
    });
    if (!projectedItems.some((item) => item.changed)) {
      setInteractionError(null);
      return true;
    }
    setNodeSelection((current) =>
      promoteStructuredPrototypePrimarySelection(activePage.root, current, nodeId),
    );
    const batch = movePositionedSelectionBatch(
      positionedSelection.parent,
      projectedItems.map(({ nodeId: itemNodeId, x: itemX, y: itemY }) => ({
        nodeId: itemNodeId,
        x: itemX,
        y: itemY,
      })),
      projectedItems.length === 1
        ? "Move positioned component"
        : `Move ${projectedItems.length} positioned components`,
    );
    const evidence = await serializeStructuredPrototypeFreeformMoveEvidence({
      ...evidenceCapture,
      ...replay.canonicalInput,
      documentId: currentDraft.documentId,
      draftId: currentDraft.draftId,
      baseHeadSequenceNo: currentDraft.headSequenceNo,
      baseDocumentHash: currentDraft.documentHash,
    });
    const applied = await controller.applyCommands({ ...batch, evidence });
    setInteractionError(applied ? null : t("prototype.structured.canvas.freeformMoveFailed"));
    return applied;
  };

  const handleFreeformMoveError = (error: unknown): void => {
    console.error("structured prototype freeform move commit failed:", error);
    setInteractionError(t("prototype.structured.canvas.freeformMoveFailed"));
  };

  const resizeNode = async (
    nodeId: string,
    widthPx: number,
    heightPx: number,
    position?: { x: number; y: number },
    groupItems?: readonly StructuredPrototypeGroupTransformItem[],
  ): Promise<boolean> => {
    const resizeInteraction = interactionRef.current;
    const currentDraft = controller.draft;
    if (
      resizeInteraction.kind !== "resize" ||
      resizeInteraction.phase !== "committing" ||
      resizeInteraction.nodeId !== nodeId ||
      currentDraft === null ||
      currentDraft.documentHash !== resizeInteraction.baseDocumentHash ||
      editorMutationLocked
    ) {
      setInteractionError(t("prototype.structured.canvas.resizeFailed"));
      return false;
    }
    if (groupItems !== undefined) {
      const groupSelection = resolveStructuredPrototypePositionedGroupSelection(
        activePage.root,
        activeSelectedNodeIds,
      );
      if (
        groupSelection === null ||
        !groupItems.some((item) => item.nodeId === nodeId) ||
        !sameStructuredPrototypeNodeIds(
          groupItems,
          groupSelection.items.map((item) => item.node.id),
        )
      ) {
        setInteractionError(t("prototype.structured.canvas.freeformGroupMoveUnavailable"));
        return false;
      }
      const currentItemsById = new Map(
        groupSelection.items.map((item) => [item.node.id, item.node] as const),
      );
      const changedItems = groupItems.filter((item) => {
        const current = currentItemsById.get(item.nodeId);
        if (current === undefined || current.layoutItem.position === undefined) {
          throw new Error(`group resize node ${item.nodeId} was not resolved`);
        }
        return (
          current.layoutItem.width.unit !== "px" ||
          current.layoutItem.width.value !==
            canonicalStructuredPrototypeFreeformValue(item.width) ||
          current.layoutItem.height.unit !== "px" ||
          current.layoutItem.height.value !==
            canonicalStructuredPrototypeFreeformValue(item.height) ||
          current.layoutItem.position.x !== canonicalStructuredPrototypeFreeformValue(item.x) ||
          current.layoutItem.position.y !== canonicalStructuredPrototypeFreeformValue(item.y)
        );
      });
      if (changedItems.length === 0) {
        setInteractionError(null);
        return true;
      }
      setNodeSelection((current) =>
        promoteStructuredPrototypePrimarySelection(activePage.root, current, nodeId),
      );
      const applied = await controller.applyCommands(
        setPositionedGroupLayoutBatch(
          changedItems,
          "frame",
          `Resize ${groupItems.length} freeform components`,
        ),
      );
      setInteractionError(applied ? null : t("prototype.structured.canvas.resizeFailed"));
      return applied;
    }
    const node = findStructuredPrototypeNode(activePage.root, nodeId);
    if (node === null) {
      setInteractionError(t("prototype.structured.canvas.resizeFailed"));
      return false;
    }
    const nextWidth = canonicalStructuredPrototypeFreeformValue(widthPx);
    const nextHeight = canonicalStructuredPrototypeFreeformValue(heightPx);
    const nextPosition =
      position === undefined
        ? undefined
        : {
            x: canonicalStructuredPrototypeFreeformValue(position.x),
            y: canonicalStructuredPrototypeFreeformValue(position.y),
          };
    if ((node.layoutItem.position === undefined) !== (nextPosition === undefined)) {
      setInteractionError(t("prototype.structured.canvas.resizeFailed"));
      return false;
    }
    if (
      node.layoutItem.width.unit === "px" &&
      node.layoutItem.width.value === nextWidth &&
      node.layoutItem.height.unit === "px" &&
      node.layoutItem.height.value === nextHeight &&
      (nextPosition === undefined ||
        (node.layoutItem.position?.x === nextPosition.x &&
          node.layoutItem.position.y === nextPosition.y))
    ) {
      setInteractionError(null);
      return true;
    }
    setNodeSelection((current) =>
      promoteStructuredPrototypePrimarySelection(activePage.root, current, nodeId),
    );
    const applied = await controller.applyCommands({
      commandContractVersion: 1,
      summary: "Resize component",
      commands: [
        {
          kind: "setNodeLayout",
          node: { kind: "existing", nodeId },
          update: {
            width: { unit: "px", value: nextWidth },
            height: { unit: "px", value: nextHeight },
            ...(nextPosition === undefined ? {} : { position: nextPosition }),
          },
        },
      ],
    });
    setInteractionError(applied ? null : t("prototype.structured.canvas.resizeFailed"));
    return applied;
  };

  const handleResizeError = (error: unknown): void => {
    console.error("structured prototype resize commit failed:", error);
    setInteractionError(t("prototype.structured.canvas.resizeFailed"));
  };

  const confirmDelete = async () => {
    if (interactionRef.current.kind !== "idle") return;
    setDeleteError(null);
    const deleted = await runLockedMutation("deletePrototype", controller.deletePrototype);
    if (deleted === true) {
      setDeleteDialogOpen(false);
      return;
    }
    setDeleteError(t("prototype.structured.deleteFailed"));
  };

  const checkpointRuntime = (): void => {
    if (interactionRef.current.kind !== "idle") return;
    void runLockedMutation("checkpoint", controller.checkpointRuntime);
  };

  const publishPrototype = (): void => {
    if (interactionRef.current.kind !== "idle") return;
    setPublishDialogOpen(true);
  };

  const confirmPublish = (summary: string | null): void => {
    setPublishDialogOpen(false);
    if (interactionRef.current.kind !== "idle") return;
    void runLockedMutation("publish", () => controller.publish(summary));
  };

  const applyInspectorCommands = (
    batch: Parameters<typeof controller.applyCommands>[0],
  ): Promise<boolean> => {
    if (interactionRef.current.kind !== "idle") return Promise.resolve(false);
    return runLockedMutation("commands", () => controller.applyCommands(batch)).then(
      (applied) => applied === true,
    );
  };

  const captureSelectedNodePlacementFrame = (): StructuredPrototypePlacementFrame | null => {
    if (
      interactionRef.current.kind !== "idle" ||
      selectedNode === null ||
      selectedNodeParent === null ||
      !selectedNodePlacementModeAvailable
    ) {
      setInteractionError(t("prototype.structured.inspector.placementCaptureFailed"));
      return null;
    }
    const canvas = globalThis.document.querySelector<HTMLElement>(
      '[data-prototype-canvas-region="persistent"] [data-prototype-canvas-wrapper="true"]',
    );
    const element = Array.from(canvas?.querySelectorAll<HTMLElement>("[data-node-id]") ?? []).find(
      (candidate) => candidate.dataset["nodeId"] === selectedNode.id,
    );
    const offsetParent = element?.offsetParent;
    if (
      element === undefined ||
      !(offsetParent instanceof HTMLElement) ||
      offsetParent.dataset["containerId"] !== selectedNodeParent.id
    ) {
      setInteractionError(t("prototype.structured.inspector.placementCaptureFailed"));
      return null;
    }
    const frame = {
      x: element.offsetLeft,
      y: element.offsetTop,
      width: element.offsetWidth,
      height: element.offsetHeight,
    };
    const values = [frame.x, frame.y, frame.width, frame.height];
    if (
      frame.width <= 0 ||
      frame.height <= 0 ||
      values.some(
        (value) =>
          !Number.isFinite(value) ||
          value < 0 ||
          value > STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
      )
    ) {
      setInteractionError(t("prototype.structured.inspector.placementCaptureFailed"));
      return null;
    }
    setInteractionError(null);
    return frame;
  };

  const applyFlowNodePosition = (flowNodeId: string, x: number, y: number): Promise<boolean> => {
    setInteractionError(null);
    return applyInspectorCommands(setRuntimeFlowNodePositionBatch(flowNodeId, x, y));
  };

  const applyFlowRuleBatch = (
    batch: Parameters<typeof controller.applyCommands>[0],
    target: StructuredPrototypeFlowRuleMutationTarget,
    failureMessage: string,
  ): void => {
    const draft = controller.draft;
    if (draft === null) {
      setInteractionError(failureMessage);
      return;
    }
    const mutation: StructuredPrototypeFlowRuleMutation = {
      baseDocumentHash: draft.documentHash,
      target,
      failureMessage,
      requestSettled: false,
    };
    setInteractionError(null);
    setFlowRuleMutation(mutation);
    void applyInspectorCommands(batch)
      .catch((error) => {
        console.error("structured prototype flow rule save failed:", error);
      })
      .finally(() => {
        setFlowRuleMutation((current) =>
          current === mutation ? { ...current, requestSettled: true } : current,
        );
      });
  };

  const createFlowRule = (
    newRuleKey: string,
    definition: StructuredPrototypeBehaviorRuleDefinition,
  ): void => {
    applyFlowRuleBatch(
      addBehaviorRuleBatch(newRuleKey, definition),
      { kind: "ruleKey", ruleKey: newRuleKey },
      t("prototype.structured.flow.saveFailed"),
    );
  };

  const replaceFlowRule = (
    ruleId: string,
    definition: StructuredPrototypeBehaviorRuleDefinition,
  ): void => {
    applyFlowRuleBatch(
      replaceBehaviorRuleBatch(ruleId, definition),
      { kind: "ruleId", ruleId },
      t("prototype.structured.flow.saveFailed"),
    );
  };

  const removeFlowRule = (ruleId: string): void => {
    applyFlowRuleBatch(
      removeBehaviorRuleBatch(ruleId),
      { kind: "clear" },
      t("prototype.structured.flow.removeFailed"),
    );
  };

  const selectFlowPage = (pageId: string): void => {
    if (interactionRef.current.kind !== "idle") return;
    setFlowPageId(pageId);
    setFlowRuleSelection(null);
    setInteractionError(null);
  };

  const selectFlowRule = (ruleId: string): void => {
    if (interactionRef.current.kind !== "idle") return;
    const rule = document.runtime.rules.find((candidate) => candidate.id === ruleId);
    const sourcePage =
      rule === undefined
        ? undefined
        : document.pages.find(
            (page) => findStructuredPrototypeNode(page.root, rule.trigger.nodeId) !== null,
          );
    if (sourcePage !== undefined) setFlowPageId(sourcePage.id);
    setFlowRuleSelection({ kind: "existingRuleId", ruleId });
    setInteractionError(null);
    setMobileDrawer("right");
  };

  const beginFlowConnection = (connection: StructuredPrototypePendingRuleConnection): void => {
    if (interactionRef.current.kind !== "idle") return;
    setFlowPageId(connection.sourcePageId);
    setFlowRuleSelection(connection);
    setInteractionError(null);
    setMobileDrawer("right");
  };

  const adoptAiDraft = (
    draft: Parameters<typeof controller.adoptAiDraft>[0],
    sessionId: number,
  ): Promise<boolean> => {
    const currentInteraction = interactionRef.current;
    const sessionMatches =
      currentInteraction.kind === "mutation" &&
      currentInteraction.operation === "aiApply" &&
      currentInteraction.sessionId === sessionId &&
      controller.draft?.documentHash === currentInteraction.baseDocumentHash;
    if (!sessionMatches) {
      console.error("structured prototype AI apply lost its interaction session", {
        expectedSessionId: sessionId,
        actualInteraction: currentInteraction,
      });
      setInteractionError(t("prototype.structured.ai.applySessionLost"));
      return Promise.resolve(false);
    }
    return controller.adoptAiDraft(draft);
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={captureStructuredPrototypeDragPointer}
      measuring={{ droppable: { strategy: MeasuringStrategy.Always } }}
      onDragStart={handleDragStart}
      onDragMove={handleDragMove}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
      onDragCancel={() => {
        activeDragPointerStateRef.current = inactiveStructuredPrototypeDragPointerState();
        const activeInteraction = interactionRef.current;
        if (activeInteraction.kind === "move" && activeInteraction.source.kind === "layer") {
          endInteraction(activeInteraction.sessionId);
          return;
        }
        const session = activeMoveProjectionRef.current;
        if (session !== null) cancelActiveMove(session);
      }}
    >
      <div
        className={cn(
          "relative grid h-full min-h-[640px] overflow-hidden bg-background/60 pb-14 text-foreground lg:grid-rows-[52px_minmax(0,1fr)] xl:pb-0",
          isFullscreen && "fixed inset-0 z-40 h-dvh min-h-0 bg-background pb-14 xl:pb-0",
        )}
        data-prototype-studio-fullscreen={isFullscreen ? "true" : "false"}
        data-prototype-interaction={interaction.kind}
        data-prototype-interaction-phase={
          interaction.kind === "move" ||
          interaction.kind === "freeformMove" ||
          interaction.kind === "resize" ||
          interaction.kind === "mutation"
            ? interaction.phase
            : interaction.kind
        }
        data-prototype-interaction-session={
          interaction.kind === "idle" ? "none" : interaction.sessionId
        }
        data-prototype-document-sequence={controller.draft.headSequenceNo}
        data-prototype-saving={controller.saving ? "true" : "false"}
        data-prototype-projection-status={projectedDocument?.status ?? "none"}
        data-prototype-projection-owner={projectedDocument?.ownerSessionId ?? "none"}
        data-prototype-mobile-drawer={mobileDrawer ?? "none"}
      >
        <header className="flex min-h-[52px] flex-wrap items-center gap-2 border-b border-border-subtle bg-surface px-3 py-2 sm:flex-nowrap sm:py-0">
          <div className="flex min-w-[150px] flex-1 items-center gap-2">
            <div className="min-w-0">
              <div className="truncate text-xs font-bold">{document.title}</div>
              <div className="text-[10px] text-text-muted">{t("prototype.structured.brand")}</div>
            </div>
          </div>
          <div className="inline-grid shrink-0 grid-cols-2 rounded-lg border border-border-muted bg-surface-input p-1">
            {(["design", "flow"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className={cn(
                  "min-h-8 min-w-18 cursor-pointer rounded-md px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45",
                  mode === value
                    ? "bg-surface-raised text-foreground shadow-sm"
                    : "text-text-muted hover:text-foreground",
                )}
                onClick={() => {
                  if (interactionRef.current.kind !== "idle") return;
                  setMode(value);
                }}
                disabled={interactionCapabilities.documentControlsDisabled}
                aria-pressed={mode === value}
              >
                {t(`prototype.structured.mode.${value}`)}
              </button>
            ))}
          </div>
          <div className="order-3 flex w-full min-w-0 flex-wrap items-center justify-between gap-2 sm:order-none sm:w-auto sm:flex-1 sm:flex-nowrap sm:justify-end">
            <span className="hidden text-[11px] text-text-muted xl:inline">
              {controller.saving
                ? t("prototype.structured.saving")
                : t("prototype.structured.saved")}
            </span>
            {showRoleControl && (
              <select
                className="min-h-9 max-w-32 cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-xs text-foreground"
                aria-label={t("prototype.structured.role.label")}
                value={runtime.state.actorRoleId}
                disabled={interactionCapabilities.documentControlsDisabled}
                onChange={(event) =>
                  void runEvents([{ kind: "switchSimulatedRole", roleId: event.target.value }])
                }
              >
                {roleLabels.map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.label}
                  </option>
                ))}
              </select>
            )}
            {mode === "design" && (
              <button
                type="button"
                className={cn(
                  "grid size-9 cursor-pointer place-items-center rounded-md border border-border-muted bg-surface-raised hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45",
                  gridSnappingEnabled ? "text-brand" : "text-text-muted",
                )}
                onClick={() => {
                  if (interactionRef.current.kind !== "idle") return;
                  setGridSnappingEnabled((current) => !current);
                }}
                disabled={interactionCapabilities.documentControlsDisabled}
                aria-pressed={gridSnappingEnabled}
                aria-label={t(
                  gridSnappingEnabled
                    ? "prototype.structured.gridSnapping.disable"
                    : "prototype.structured.gridSnapping.enable",
                )}
                title={t(
                  gridSnappingEnabled
                    ? "prototype.structured.gridSnapping.disable"
                    : "prototype.structured.gridSnapping.enable",
                )}
                data-prototype-grid-snapping-enabled={gridSnappingEnabled}
              >
                <Magnet size={15} aria-hidden />
              </button>
            )}
            <button
              type="button"
              className="grid size-9 cursor-pointer place-items-center rounded-md border border-border-muted bg-surface-raised text-brand hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
              onClick={() => {
                if (interactionRef.current.kind !== "idle") return;
                void runLockedMutation("history", controller.undo);
              }}
              disabled={
                interactionCapabilities.documentControlsDisabled || !controller.draft.canUndo
              }
              aria-label={t("prototype.structured.undo")}
              title={t("prototype.structured.undo")}
            >
              <Undo2 size={15} aria-hidden />
            </button>
            <button
              type="button"
              className="grid size-9 cursor-pointer place-items-center rounded-md border border-border-muted bg-surface-raised text-brand hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
              onClick={() => {
                if (interactionRef.current.kind !== "idle") return;
                void runLockedMutation("history", controller.redo);
              }}
              disabled={
                interactionCapabilities.documentControlsDisabled || !controller.draft.canRedo
              }
              aria-label={t("prototype.structured.redo")}
              title={t("prototype.structured.redo")}
            >
              <Redo2 size={15} aria-hidden />
            </button>
            <button
              type="button"
              className="grid size-9 cursor-pointer place-items-center rounded-md border border-border-muted bg-surface-raised text-brand hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
              onClick={checkpointRuntime}
              disabled={interactionCapabilities.documentControlsDisabled}
              aria-label={t("prototype.structured.checkpoint")}
              title={t("prototype.structured.checkpoint")}
            >
              <Save size={15} aria-hidden />
            </button>
            <button
              type="button"
              className="grid size-9 cursor-pointer place-items-center rounded-md border border-border-muted bg-surface-raised text-brand hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
              onClick={() => {
                if (interactionRef.current.kind !== "idle") return;
                setIsFullscreen((current) => !current);
              }}
              disabled={interactionCapabilities.documentControlsDisabled}
              aria-pressed={isFullscreen}
              aria-label={t(isFullscreen ? "ui.exitFullscreen" : "ui.enterFullscreen")}
              title={t(isFullscreen ? "ui.exitFullscreen" : "ui.enterFullscreen")}
            >
              {isFullscreen ? (
                <Minimize2 size={15} aria-hidden />
              ) : (
                <Maximize2 size={15} aria-hidden />
              )}
            </button>
            <button
              type="button"
              className="inline-flex min-h-9 cursor-pointer items-center justify-center gap-2 rounded-md bg-brand px-3 text-xs font-semibold text-black hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-45"
              onClick={publishPrototype}
              disabled={interactionCapabilities.documentControlsDisabled}
              aria-label={t("prototype.structured.publish")}
              title={t("prototype.structured.publish")}
            >
              <CloudUpload size={15} aria-hidden />
              <span className="hidden sm:inline">{t("prototype.structured.publish")}</span>
            </button>
            {controller.publication && (
              <Link
                href={controller.publication.sharePath}
                target="_blank"
                rel="noreferrer"
                className="grid size-9 cursor-pointer place-items-center rounded-md border border-border-muted bg-surface-raised text-brand hover:bg-surface-hover"
                aria-label={t("prototype.structured.openPublished")}
                title={t("prototype.structured.openPublished")}
              >
                <ExternalLink size={15} aria-hidden />
              </Link>
            )}
            <button
              type="button"
              className="grid size-9 cursor-pointer place-items-center rounded-md border border-border-muted bg-surface-raised text-brand hover:bg-surface-hover"
              onClick={() => setHistoryDialogOpen(true)}
              aria-label={t("prototype.structured.history")}
              title={t("prototype.structured.history")}
            >
              <History size={15} aria-hidden />
            </button>
            <button
              type="button"
              className="grid size-9 cursor-pointer place-items-center rounded-md border border-error/35 bg-surface-raised text-error hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-45"
              onClick={openDeleteDialog}
              disabled={interactionCapabilities.documentControlsDisabled}
              aria-label={t("prototype.structured.delete")}
              title={t("prototype.structured.delete")}
            >
              <Trash2 size={15} aria-hidden />
            </button>
          </div>
        </header>

        <main className="grid min-h-0 min-w-0 grid-cols-1 xl:grid-cols-[240px_minmax(440px,1fr)_300px]">
          <StructuredPrototypeResponsiveSideRegion
            desktop={desktopLayout}
            desktopClassName={cn(
              "grid min-h-0 border-r border-border-subtle bg-surface",
              mode === "design"
                ? "grid-rows-[44px_minmax(112px,1fr)_44px_minmax(160px,1.4fr)_minmax(180px,1fr)]"
                : "grid-rows-[44px_minmax(130px,1fr)_44px_minmax(180px,1fr)]",
            )}
            drawerClassName={cn(
              "grid w-[min(90vw,20rem)] bg-surface",
              mode === "design"
                ? "grid-rows-[44px_minmax(90px,0.8fr)_44px_minmax(120px,1.2fr)_minmax(160px,1fr)]"
                : "grid-rows-[44px_minmax(130px,1fr)_44px_minmax(180px,1fr)]",
            )}
            open={mobileDrawer === "left"}
            side="left"
            title={t(
              mode === "design" ? "prototype.structured.navigator" : "prototype.structured.pages",
            )}
            description={t("prototype.structured.mobile.pagesDescription")}
            closeLabel={t("prototype.structured.mobile.closeDrawer")}
            onOpenChange={(open) => {
              setMobileDrawer((current) => (open ? "left" : current === "left" ? null : current));
            }}
          >
            <div
              className={cn(
                "flex items-center justify-between border-b border-border-subtle px-3 text-xs font-bold uppercase",
                !desktopLayout && "pr-12",
              )}
            >
              {t("prototype.structured.pages")}
              <span className="font-normal text-text-muted">{document.pages.length}</span>
            </div>
            <StructuredPrototypePageRail
              pages={pageRailPages ?? document.pages}
              activePageId={mode === "flow" ? (selectedFlowPageId ?? activePage.id) : activePage.id}
              externalError={visibleError}
              dragDisabled={interactionCapabilities.moveDisabled}
              selectionDisabled={interactionCapabilities.documentControlsDisabled}
              mutationDisabled={interactionCapabilities.documentControlsDisabled}
              onSelect={mode === "flow" ? selectFlowPage : handlePageSelect}
              onAdd={addPage}
              onDuplicate={duplicatePage}
              onRename={renamePage}
              onDelete={deletePage}
            />
            {mode === "flow" ? (
              <>
                <div className="flex items-center justify-between border-y border-border-subtle px-3 text-xs font-bold uppercase">
                  {t("prototype.structured.flow.rules")}
                  <span className="font-normal text-text-muted">
                    {document.runtime.rules.length}
                  </span>
                </div>
                <div
                  className="min-h-0 overflow-auto divide-y divide-border-subtle border-b border-border-subtle"
                  aria-label={t("prototype.structured.flow.ruleList")}
                >
                  {document.runtime.rules.length === 0 ? (
                    <p className="px-3 py-4 text-xs text-text-muted">
                      {t("prototype.structured.flow.noRules")}
                    </p>
                  ) : (
                    document.runtime.rules.map((rule) => (
                      <button
                        key={rule.id}
                        type="button"
                        className={cn(
                          "grid min-h-14 w-full cursor-pointer grid-cols-[22px_minmax(0,1fr)] items-center gap-2 border-l-2 px-3 py-2 text-left disabled:cursor-not-allowed disabled:opacity-45",
                          selectedFlowRuleId === rule.id
                            ? "border-brand bg-brand-bg"
                            : "border-transparent hover:bg-surface-hover",
                        )}
                        onClick={() => selectFlowRule(rule.id)}
                        disabled={interactionCapabilities.documentControlsDisabled}
                        aria-pressed={selectedFlowRuleId === rule.id}
                        data-prototype-flow-rule={rule.id}
                      >
                        <GitBranch size={15} className="text-text-faint" aria-hidden />
                        <span className="min-w-0">
                          <strong className="block truncate text-xs font-semibold text-foreground">
                            {rule.key}
                          </strong>
                          <span className="mt-1 flex min-w-0 items-center justify-between gap-2 text-[10px] text-text-muted">
                            <span className="truncate">{rule.trigger.event}</span>
                            <span className="shrink-0">
                              {t(
                                rule.enabled
                                  ? "prototype.structured.flow.ruleEnabled"
                                  : "prototype.structured.flow.ruleDisabled",
                              )}
                            </span>
                          </span>
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="flex items-center justify-between border-y border-border-subtle px-3 text-xs font-bold uppercase">
                  {t("prototype.structured.layers")}
                  <span className="font-normal text-text-muted">{activePageLayerCount}</span>
                </div>
                <StructuredPrototypeLayerTree
                  root={activePage.root}
                  selectedNodeId={activeNodeSelection.primaryNodeId}
                  error={interactionError}
                  labels={layerTreeLabels}
                  selectionDisabled={interactionCapabilities.documentControlsDisabled}
                  mutationDisabled={interactionCapabilities.documentControlsDisabled}
                  dragDisabled={interactionCapabilities.moveDisabled}
                  onSelect={handleLayerSelect}
                  onRename={renameLayer}
                  onVisibilityChange={changeLayerVisibility}
                  onMove={moveLayer}
                  onDropRefused={refuseLayerDrop}
                />
                <div className="min-h-0 overflow-auto">
                  <div className="flex items-center justify-between border-y border-border-subtle px-3 text-xs font-bold uppercase">
                    {t("prototype.structured.components")}
                    <span className="font-normal text-text-muted">
                      {STRUCTURED_PROTOTYPE_PALETTE_TYPES.length}
                    </span>
                  </div>
                  <StructuredPrototypePalette
                    labels={paletteLabels}
                    forms={document.runtime.forms}
                    selectedFormId={paletteFormDefinition?.id ?? null}
                    formSelectorLabel={t("prototype.structured.palette.formSelector")}
                    formSelectorPlaceholder={t("prototype.structured.palette.formPlaceholder")}
                    dragDisabled={interactionCapabilities.moveDisabled}
                    controlsDisabled={interactionCapabilities.documentControlsDisabled}
                    onFormSelect={setPaletteFormId}
                    onInsert={insertPaletteNode}
                  />
                  <div className="flex items-center justify-between border-y border-border-subtle px-3 text-xs font-bold uppercase">
                    {t("prototype.structured.library")}
                    <span className="font-normal text-text-muted">
                      {document.componentDefinitions.length}
                    </span>
                  </div>
                  <StructuredPrototypeComponentLibrary
                    definitions={document.componentDefinitions}
                    disabled={interactionCapabilities.documentControlsDisabled}
                    insertLabel={t("prototype.structured.library.insert")}
                    deleteLabel={t("prototype.structured.library.delete")}
                    emptyLabel={t("prototype.structured.library.empty")}
                    onInsert={insertComponentInstance}
                    onDelete={removeComponentDefinition}
                  />
                </div>
              </>
            )}
          </StructuredPrototypeResponsiveSideRegion>

          <section
            className="grid min-h-0 min-w-0 grid-rows-[44px_minmax(0,1fr)]"
            data-prototype-canvas-region="persistent"
          >
            <div className="flex items-center justify-between gap-3 border-b border-border-subtle bg-surface px-3">
              <div className="min-w-0 truncate text-xs text-text-muted">
                {mode === "design"
                  ? t("prototype.structured.mode.design")
                  : t("prototype.structured.mode.flow")}
                <span className="mx-2">/</span>
                <strong className="text-foreground">
                  {mode === "flow"
                    ? (selectedFlowPage?.title ?? activePage.title)
                    : activePage.title}
                </strong>
                <span className="ml-2 font-mono text-[10px] text-text-faint">
                  doc {controller.draft.headSequenceNo}
                </span>
              </div>
              {visibleError && (
                <span className="min-w-0 max-w-64 truncate text-[10px] text-status-failed">
                  {visibleError}
                </span>
              )}
              {mode === "design" && (
                <div className="hidden min-w-0 items-center gap-2 sm:flex">
                  <div
                    className="grid grid-cols-2 rounded-lg border border-border-muted bg-surface-input p-1"
                    aria-label={t("prototype.structured.interaction.label")}
                  >
                    {(["edit", "preview"] as const).map((value) => {
                      const Icon = value === "edit" ? MousePointer2 : Play;
                      return (
                        <button
                          key={value}
                          type="button"
                          className={cn(
                            "inline-flex min-h-7 cursor-pointer items-center gap-1.5 rounded-md px-2 text-[10px] font-semibold disabled:cursor-not-allowed disabled:opacity-45",
                            canvasInteraction === value
                              ? "bg-surface-raised text-foreground shadow-sm"
                              : "text-text-muted hover:text-foreground",
                          )}
                          onClick={() => {
                            if (interactionRef.current.kind !== "idle") return;
                            setCanvasInteraction(value);
                          }}
                          disabled={interactionCapabilities.documentControlsDisabled}
                          aria-pressed={canvasInteraction === value}
                        >
                          <Icon size={12} aria-hidden />
                          {t(`prototype.structured.interaction.${value}`)}
                        </button>
                      );
                    })}
                  </div>
                  <div className="grid grid-cols-3 rounded-lg border border-border-muted bg-surface-input p-1">
                    {(["desktop", "tablet", "mobile"] as const).map((value) => (
                      <button
                        key={value}
                        type="button"
                        className={cn(
                          "min-h-7 cursor-pointer rounded-md px-3 text-[10px] font-semibold disabled:cursor-not-allowed disabled:opacity-45",
                          viewport === value
                            ? "bg-surface-raised text-foreground shadow-sm"
                            : "text-text-muted hover:text-foreground",
                        )}
                        onClick={() => handleViewportSelect(value)}
                        disabled={interactionCapabilities.documentControlsDisabled}
                        aria-pressed={viewport === value}
                      >
                        {t(`prototype.structured.viewport.${value}`)}
                      </button>
                    ))}
                  </div>
                  <div
                    className="grid grid-cols-4 rounded-lg border border-border-muted bg-surface-input p-1"
                    aria-label={t("prototype.structured.zoom.label")}
                  >
                    {PREVIEW_ZOOM_OPTIONS.map((value) => (
                      <button
                        key={value}
                        type="button"
                        className={cn(
                          "min-h-7 cursor-pointer rounded-md px-2 text-[10px] font-semibold disabled:cursor-not-allowed disabled:opacity-45",
                          previewZoom === value
                            ? "bg-surface-raised text-foreground shadow-sm"
                            : "text-text-muted hover:text-foreground",
                        )}
                        onClick={() => {
                          if (interactionRef.current.kind !== "idle") return;
                          setPreviewZoom(value);
                          if (value === "fit") {
                            setPreviewViewResetKey((current) => current + 1);
                          }
                        }}
                        disabled={interactionCapabilities.documentControlsDisabled}
                        aria-pressed={previewZoom === value}
                      >
                        {value === "fit"
                          ? t("prototype.structured.zoom.fit")
                          : `${Math.round(value * 100)}%`}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="flex min-h-0 flex-col">
              {controller.runtimeRecovery && (
                <StructuredPrototypeRuntimeRecoveryNotice
                  issue={controller.runtimeRecovery}
                  hasLastSnapshot
                  isResetting={controller.saving}
                  resetError={controller.error}
                  onReset={() => void controller.resetRuntimePreview()}
                />
              )}
              <div className="min-h-0 flex-1">
                {mode === "flow" ? (
                  <StructuredPrototypeFlow
                    document={document}
                    disabled={interactionCapabilities.documentControlsDisabled}
                    saving={controller.saving}
                    error={visibleError}
                    selectedPageId={selectedFlowPageId}
                    selectedRuleId={selectedFlowRuleId}
                    onNodePositionChange={applyFlowNodePosition}
                    onPageSelect={selectFlowPage}
                    onRuleSelect={selectFlowRule}
                    onConnectPages={beginFlowConnection}
                  />
                ) : (
                  <StructuredPrototypePreview
                    document={document}
                    page={activePage}
                    runtimeState={runtime.state}
                    viewModel={runtime.viewModel}
                    viewport={viewport}
                    zoom={previewZoom}
                    viewResetKey={previewViewResetKey}
                    editing={canvasInteraction === "edit"}
                    dragGestureActive={
                      interaction.kind === "move" || interaction.kind === "freeformMove"
                    }
                    activeInteractionKind={interaction.kind}
                    onZoomChange={setPreviewZoom}
                    onEffectiveScaleChange={setEffectivePreviewScale}
                    selection={activeNodeSelection}
                    formValues={formValues}
                    disabled={interactionCapabilities.documentControlsDisabled}
                    dragDisabled={interactionCapabilities.moveDisabled}
                    resizeDisabled={interactionCapabilities.resizeDisabled}
                    gridSnappingEnabled={gridSnappingEnabled}
                    onPageSelect={handlePageSelect}
                    onSelectNode={(
                      nodeId: string,
                      intent: StructuredPrototypeNodeSelectionIntent,
                    ) => {
                      if (interactionRef.current.kind !== "idle") return;
                      setNodeSelection((current) => {
                        if (intent === "toggle") {
                          return toggleStructuredPrototypeNodeSelection(
                            activePage.root,
                            current,
                            nodeId,
                          );
                        }
                        if (intent === "primary") {
                          return promoteStructuredPrototypePrimarySelection(
                            activePage.root,
                            current,
                            nodeId,
                          );
                        }
                        return resolveStructuredPrototypeNodeSelection(
                          activePage.root,
                          [nodeId],
                          nodeId,
                        );
                      });
                      setInspectorTab("properties");
                      setMobileDrawer("right");
                    }}
                    onSelectionChange={(selection: StructuredPrototypeNodeSelection) => {
                      setNodeSelection(
                        resolveStructuredPrototypeNodeSelection(
                          activePage.root,
                          selection.nodeIds,
                          selection.primaryNodeId,
                        ),
                      );
                    }}
                    onMarqueeGestureChange={handleMarqueeGestureChange}
                    onFreeformMoveNode={movePositionedNode}
                    onFreeformMoveError={handleFreeformMoveError}
                    onFreeformMoveGestureChange={handleFreeformMoveGestureChange}
                    onFreeformGroupArrange={arrangePositionedGroup}
                    onFreeformSelectionNudge={nudgePositionedSelection}
                    onResizeNode={resizeNode}
                    onResizeError={handleResizeError}
                    onResizeGestureChange={handleResizeGestureChange}
                    onNodeElementRegistered={handleNodeElementRegistered}
                    onPanGestureStart={handlePanGestureStart}
                    onPanGestureEnd={handlePanGestureEnd}
                    onFormValue={(nodeId, value) => {
                      if (interactionRef.current.kind !== "idle") return;
                      setFormValues((current) => ({ ...current, [nodeId]: value }));
                    }}
                    onNodeActivate={(nodeId, event) => void activateNode(nodeId, event)}
                    onRowActivate={activateRow}
                  />
                )}
              </div>
            </div>
          </section>

          <StructuredPrototypeResponsiveSideRegion
            desktop={desktopLayout}
            desktopClassName="grid min-h-0 grid-rows-[44px_minmax(0,1fr)] border-l border-border-subtle bg-surface"
            drawerClassName="grid w-[min(94vw,24rem)] grid-rows-[44px_minmax(0,1fr)] bg-surface"
            open={mobileDrawer === "right"}
            side="right"
            title={t("prototype.structured.mobile.inspectorTitle")}
            description={t("prototype.structured.mobile.inspectorDescription")}
            closeLabel={t("prototype.structured.mobile.closeDrawer")}
            onOpenChange={(open) => {
              setMobileDrawer((current) => (open ? "right" : current === "right" ? null : current));
            }}
          >
            {mode === "flow" ? (
              <div
                className={cn(
                  "flex items-center justify-between border-b border-border-subtle px-3",
                  !desktopLayout && "pr-12",
                )}
              >
                <span className="text-xs font-bold uppercase">
                  {t("prototype.structured.flow.ruleInspector")}
                </span>
                <span className="max-w-40 truncate text-[10px] text-text-muted">
                  {selectedFlowRule?.key ??
                    (flowRuleSelection?.kind === "pendingConnection"
                      ? t("prototype.structured.flow.pendingConnection")
                      : t("prototype.structured.flow.noRuleSelected"))}
                </span>
              </div>
            ) : (
              <div
                className={cn(
                  "grid grid-cols-2 border-b border-border-subtle bg-surface-input p-1",
                  !desktopLayout && "mr-11",
                )}
                role="tablist"
                aria-label={t("prototype.structured.inspector.properties")}
              >
                {(["ai", "properties"] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={cn(
                      "min-h-8 cursor-pointer rounded-md text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45",
                      inspectorTab === tab
                        ? "bg-surface-raised text-foreground shadow-sm"
                        : "text-text-muted hover:text-foreground",
                    )}
                    onClick={() => {
                      if (interactionRef.current.kind !== "idle") return;
                      setInspectorTab(tab);
                    }}
                    disabled={interactionCapabilities.documentControlsDisabled}
                    aria-selected={inspectorTab === tab}
                    aria-controls={`structured-inspector-${tab}`}
                    id={`structured-inspector-tab-${tab}`}
                    role="tab"
                  >
                    {t(`prototype.structured.inspector.${tab}`)}
                  </button>
                ))}
              </div>
            )}
            {mode === "flow" ? (
              <div className="min-h-0 overflow-auto" data-prototype-flow-rule-inspector>
                <StructuredPrototypeRuleInspector
                  document={document}
                  selection={flowInspectorSelection}
                  disabled={interactionCapabilities.documentControlsDisabled}
                  saving={controller.saving}
                  error={visibleError}
                  onCreate={createFlowRule}
                  onReplace={replaceFlowRule}
                  onRemove={removeFlowRule}
                  onCancel={() => {
                    if (interactionRef.current.kind !== "idle") return;
                    setFlowRuleSelection(null);
                    setInteractionError(null);
                  }}
                />
              </div>
            ) : (
              <div
                className="min-h-0 overflow-auto"
                id={`structured-inspector-${inspectorTab}`}
                role="tabpanel"
                aria-labelledby={`structured-inspector-tab-${inspectorTab}`}
              >
                {inspectorTab === "properties" ? (
                  <StructuredPrototypeInspector
                    key={`${selectedNode?.id ?? "none"}:${controller.draft.documentHash}`}
                    node={selectedNode}
                    colorTokens={document.tokens.colors}
                    selectedCount={activeSelectedNodeIds.length}
                    disabled={interactionCapabilities.documentControlsDisabled}
                    canDelete={activeSelectedNodeIds.length > 0}
                    canSaveAsComponent={canSaveSelectedNodeAsComponent}
                    placementModeAvailable={selectedNodePlacementModeAvailable}
                    isRuntimeBoundTable={selectedNodeIsRuntimeBoundTable}
                    runtimeTable={selectedRuntimeTable}
                    onCapturePlacementFrame={captureSelectedNodePlacementFrame}
                    onApply={applyInspectorCommands}
                    onDelete={() => void deleteSelectedNodes()}
                    onSaveAsComponent={saveNodeAsComponent}
                  />
                ) : (
                  <StructuredPrototypeAiPanel
                    projectId={projectId}
                    draft={controller.draft}
                    pageId={activePage.id}
                    selectedNodeIds={activeSelectedNodeIds}
                    viewport={viewport}
                    disabled={interactionCapabilities.documentControlsDisabled}
                    onApplyStart={handleAiApplyStart}
                    onDraftApplied={adoptAiDraft}
                    onApplyEnd={handleAiApplyEnd}
                    onMutatingChange={setAiMutating}
                  />
                )}
              </div>
            )}
          </StructuredPrototypeResponsiveSideRegion>
        </main>
        <nav
          className="absolute inset-x-0 bottom-0 z-[60] grid h-14 grid-cols-3 border-t border-border-subtle bg-surface p-1 xl:hidden"
          aria-label={t("prototype.structured.mobile.navigation")}
        >
          {[
            {
              action: "pages",
              drawer: "left" as const,
              label: t(
                mode === "design" ? "prototype.structured.navigator" : "prototype.structured.pages",
              ),
              icon: Files,
            },
            {
              action: "canvas",
              drawer: null,
              label: t("prototype.structured.canvas"),
              icon: PanelsTopLeft,
            },
            {
              action: "inspector",
              drawer: "right" as const,
              label: t(
                mode === "flow"
                  ? "prototype.structured.flow.ruleInspector"
                  : "prototype.structured.inspector.ai",
              ),
              icon: MessageSquare,
            },
          ].map((item) => {
            const Icon = item.icon;
            const active = mobileDrawer === item.drawer;
            return (
              <button
                key={item.action}
                type="button"
                className={cn(
                  "inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-md text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45",
                  active ? "bg-brand-bg text-brand" : "text-text-muted hover:text-foreground",
                )}
                onClick={() => {
                  if (interactionRef.current.kind !== "idle") return;
                  setMobileDrawer(item.drawer);
                }}
                disabled={interactionCapabilities.documentControlsDisabled}
                aria-pressed={active}
                data-prototype-mobile-action={item.action}
              >
                <Icon size={15} aria-hidden />
                {item.label}
              </button>
            );
          })}
        </nav>
      </div>
      <StructuredPrototypePublishDialog
        open={publishDialogOpen}
        onOpenChange={setPublishDialogOpen}
        onConfirm={confirmPublish}
      />
      <StructuredPrototypeReleaseHistoryDialog
        open={historyDialogOpen}
        onOpenChange={setHistoryDialogOpen}
        documentId={controller.draft.documentId}
        onRestored={() => void controller.refreshPublication()}
      />
      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={(open) => {
          setDeleteDialogOpen(open);
          if (!open) setDeleteError(null);
        }}
        title={t("prototype.structured.deleteTitle")}
        description={
          deleteError
            ? `${t("prototype.structured.deleteDescription")} ${deleteError}`
            : t("prototype.structured.deleteDescription")
        }
        confirmText={t("prototype.structured.deleteConfirm")}
        cancelText={t("prototype.structured.deleteCancel")}
        onConfirm={() => void confirmDelete()}
        isLoading={controller.saving}
        loadingMotionPhase="tool"
        loadingDensity="prototype-delete"
        variant="destructive"
      />
      <DragOverlay
        adjustScale={false}
        zIndex={1000}
        dropAnimation={{ duration: 160, easing: "cubic-bezier(0.2, 0, 0, 1)" }}
      >
        {activeDrag?.kind === "palette" && activePaletteDragNode !== null ? (
          <StructuredPrototypeNodeDragOverlay
            kind="palette"
            document={document}
            node={activePaletteDragNode}
            runtimeState={runtime.state}
            viewModel={runtime.viewModel}
            viewportWidth={activeOverlayViewportWidth}
            formValues={formValues}
            previewScale={effectivePreviewScale}
          />
        ) : activeDrag?.kind === "component" && activeComponentDragNode !== null ? (
          <StructuredPrototypeNodeDragOverlay
            kind="component"
            document={document}
            node={activeComponentDragNode}
            runtimeState={runtime.state}
            viewModel={runtime.viewModel}
            viewportWidth={activeOverlayViewportWidth}
            formValues={formValues}
            previewScale={effectivePreviewScale}
          />
        ) : activeDrag?.kind === "node" && activeNodeDragMirror !== null ? (
          <StructuredPrototypeDragMirrorView snapshot={activeNodeDragMirror} />
        ) : activeDragPage ? (
          <div
            className="pointer-events-none min-w-48 rounded-lg border border-brand bg-surface-raised px-3 py-2 text-sm font-bold text-foreground opacity-95 shadow-2xl ring-4 ring-brand-bg"
            data-prototype-drag-overlay="page"
          >
            <div className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
              {t("prototype.structured.pages")}
            </div>
            <div className="mt-1 truncate">{activeDragPage.title}</div>
            <div className="mt-1 truncate font-mono text-[10px] text-text-faint">
              {activeDragPage.route}
            </div>
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
