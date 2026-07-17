"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
} from "react";
import { useDndContext, useDroppable } from "@dnd-kit/core";
import {
  horizontalListSortingStrategy,
  rectSortingStrategy,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  AlignHorizontalJustifyCenter,
  AlignHorizontalJustifyEnd,
  AlignHorizontalJustifyStart,
  AlignHorizontalSpaceBetween,
  AlignVerticalJustifyCenter,
  AlignVerticalJustifyEnd,
  AlignVerticalJustifyStart,
  AlignVerticalSpaceBetween,
  GripVertical,
  Layers3,
} from "lucide-react";

import { isKeyboardShortcutEditableTarget } from "@/hooks/useKeyboardShortcuts";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import type { PrototypeRuntimeState, RuntimeEntity, RuntimeViewModel } from "../runtime/types";
import {
  findStructuredPrototypeNode,
  runtimeEntityFieldText,
  runtimeNodeTriggerEvents,
  runtimeNodeRows,
  runtimeNodeText,
  runtimeNodeVisible,
  runtimeTableRowsBinding,
} from "./structuredPrototypeDerived";
import {
  isStructuredPrototypeContainerNode,
  resolveStructuredPrototypeGridColumns,
  resolveStructuredPrototypeLayoutItem,
} from "./structuredPrototypeNodes";
import type { StructuredPrototypeContainerNode } from "./structuredPrototypeNodes";
import {
  resolveStructuredPrototypeMeasuredDropAreas,
  sameStructuredPrototypeDropAreas,
  type StructuredPrototypeDropRect,
  type StructuredPrototypeMeasuredDropArea,
} from "./structuredPrototypeDropAreas";
import { resolveStructuredPrototypeActiveLayoutNodeId } from "./structuredPrototypeDrag";
import {
  canonicalStructuredPrototypeFreeformValue,
  resolveStructuredPrototypeFreeformResize,
  STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
  STRUCTURED_PROTOTYPE_MIN_RESIZE_HEIGHT,
  STRUCTURED_PROTOTYPE_MIN_RESIZE_WIDTH,
  structuredPrototypeCanStartTransform,
  structuredPrototypeTransformPassedActivationThreshold,
  type StructuredPrototypeResizeDirection as FreeformResizeDirection,
} from "./structuredPrototypeFreeformGeometry";
import { StructuredPrototypeFreeformGridOverlay } from "./StructuredPrototypeFreeformGridOverlay";
import { resolveStructuredPrototypeFreeformGrids } from "./structuredPrototypeFreeformGrids";
import {
  resolveStructuredPrototypeFreeformGroupSelection,
  resolveStructuredPrototypeFreeformSelection,
} from "./structuredPrototypeGroupSelection";
import {
  resolveStructuredPrototypeGroupAlignment,
  resolveStructuredPrototypeGroupDistribution,
  resolveStructuredPrototypeGroupResize,
  resolveStructuredPrototypeGroupResizeSizeLimits,
  resolveStructuredPrototypeGroupTransformBounds,
  resolveStructuredPrototypeSelectionNudge,
  projectStructuredPrototypeGroupResizeItemsToBounds,
  type StructuredPrototypeGroupAlignment,
  type StructuredPrototypeGroupDistributionAxis,
  type StructuredPrototypeGroupTransformItem,
} from "./structuredPrototypeGroupTransform";
import {
  resolveStructuredPrototypeSelectionControlsGeometry,
  sameStructuredPrototypeSelectionBounds,
  type StructuredPrototypeSelectionBounds,
} from "./structuredPrototypeSelectionControls";
import {
  projectStructuredPrototypeFreeformSpacingGuides,
  projectStructuredPrototypeFreeformSnapGuides,
  type StructuredPrototypeFreeformSnapGuideOverlay,
} from "./structuredPrototypeSnapGuides";
import type { StructuredPrototypeFreeformSnapSibling } from "./structuredPrototypeSnapping";
import { resolveStructuredPrototypeFreeformResizeSnap } from "./structuredPrototypeResizeSnapping";
import {
  createStructuredPrototypeViewportTransform,
  resolveStructuredPrototypeClientDeltaToCanvas,
  resolveStructuredPrototypeInverseScale,
} from "./structuredPrototypeViewportTransform";
import {
  normalizeStructuredPrototypeSelectionRect,
  resolveStructuredPrototypeMarqueeNodeIds,
  resolveStructuredPrototypeOutermostCandidateNodeIds,
  structuredPrototypeMarqueePassedActivationThreshold,
  type StructuredPrototypeMarqueeCandidate,
  type StructuredPrototypeNodeSelection,
  type StructuredPrototypeSelectionRect,
} from "./structuredPrototypeSelection";
import {
  useStructuredPrototypeFreeformMove,
  type StructuredPrototypeFreeformMoveDraft,
  type StructuredPrototypeFreeformMoveEvidenceCapture,
  type StructuredPrototypeFreeformMoveGestureEvent,
} from "./useStructuredPrototypeFreeformMove";
import type {
  StructuredPrototypeDocument,
  StructuredPrototypeFreeformNode,
  StructuredPrototypeFreeformGrid,
  StructuredPrototypeLayoutItem,
  StructuredPrototypeLength,
  StructuredPrototypeNode,
  StructuredPrototypePage,
  StructuredPrototypeTableNode,
} from "./types";

interface Props {
  document: StructuredPrototypeDocument;
  page: StructuredPrototypePage;
  runtimeState: PrototypeRuntimeState | null;
  viewModel: RuntimeViewModel | null;
  viewportWidth: number;
  previewScale: number;
  editing: boolean;
  selection: StructuredPrototypeNodeSelection;
  formValues: Record<string, string>;
  disabled: boolean;
  dragDisabled: boolean;
  resizeDisabled: boolean;
  gridSnappingEnabled: boolean;
  marqueeDisabled: boolean;
  onSelect: (nodeId: string, intent: StructuredPrototypeNodeSelectionIntent) => void;
  onSelectionChange: (selection: StructuredPrototypeNodeSelection) => void;
  onMarqueeGestureChange: (event: StructuredPrototypeMarqueeGestureEvent) => number | null;
  onFreeformMoveNode: (
    nodeId: string,
    x: number,
    y: number,
    evidence: StructuredPrototypeFreeformMoveEvidenceCapture,
  ) => Promise<boolean>;
  onFreeformMoveError: (error: unknown) => void;
  onFreeformMoveGestureChange: (
    event: StructuredPrototypeFreeformMoveGestureEvent,
  ) => number | null;
  onFreeformGroupArrange: (
    items: readonly StructuredPrototypeGroupTransformItem[],
  ) => Promise<boolean>;
  onFreeformSelectionNudge: (
    items: readonly StructuredPrototypeGroupTransformItem[],
  ) => Promise<boolean>;
  onResizeNode: (
    nodeId: string,
    widthPx: number,
    heightPx: number,
    position?: { x: number; y: number },
    groupItems?: readonly StructuredPrototypeGroupTransformItem[],
  ) => Promise<boolean>;
  onResizeError: (error: unknown) => void;
  onResizeGestureChange: (event: StructuredPrototypeResizeGestureEvent) => number | null;
  onFormValue: (nodeId: string, value: string) => void;
  onNodeActivate: (nodeId: string, event: "click" | "submit") => void;
  onRowActivate: (nodeId: string, entity: RuntimeEntity) => void;
}

interface NodeRendererProps extends Omit<
  Props,
  | "page"
  | "onFreeformMoveError"
  | "onFreeformMoveGestureChange"
  | "onFreeformMoveNode"
  | "onFreeformSelectionNudge"
  | "onMarqueeGestureChange"
  | "onResizeError"
  | "onResizeGestureChange"
> {
  node: StructuredPrototypeNode;
  depth: number;
  ancestorNodeIds: readonly string[];
  freeformMoveDraft: StructuredPrototypeFreeformMoveDraft | null;
  resizeDraft: StructuredPrototypeResizeDraft | null;
  registerNodeElement: (
    nodeId: string,
    registrationKey: symbol,
    element: HTMLElement | null,
    ancestorNodeIds: readonly string[],
    container: boolean,
  ) => void;
  registerSortableControls: (
    nodeId: string,
    registrationKey: symbol,
    controls: StructuredPrototypeSortableControls | null,
  ) => void;
}

interface SortableCanvasNodeProps extends NodeRendererProps {
  parentId: string;
  index: number;
  dropAxis: "horizontal" | "vertical";
  onMeasuredElement: (nodeId: string, element: HTMLElement | null) => void;
}

interface SortableCanvasContainerProps extends Omit<NodeRendererProps, "node"> {
  node: StructuredPrototypeContainerNode;
  isRoot: boolean;
}

type StructuredPrototypeSortableControls = Pick<
  ReturnType<typeof useSortable>,
  "attributes" | "listeners" | "setActivatorNodeRef"
>;

interface StructuredPrototypeResizeDraft {
  nodeId: string;
  width: number;
  height: number;
  position?: { x: number; y: number };
  groupItems?: readonly StructuredPrototypeGroupTransformItem[];
}

type StructuredPrototypeResizeEnd = "none" | "pointerup" | "pointercancel" | "blur" | "escape";
type StructuredPrototypeResizeEndReason = Exclude<StructuredPrototypeResizeEnd, "none"> | "unmount";
type StructuredPrototypeResizePhase = "idle" | "armed" | "preview" | "pending";

export type StructuredPrototypeResizeGestureEvent =
  | { phase: "start"; nodeId: string; pointerId: number; previewScale: number }
  | { phase: "preview" | "commit"; nodeId: string; sessionId: number }
  | {
      phase: "end";
      nodeId: string;
      sessionId: number;
      reason: StructuredPrototypeResizeEndReason;
    };

interface StructuredPrototypeNodeElementRegistration {
  registrationKey: symbol;
  element: HTMLElement;
  ancestorNodeIds: readonly string[];
  container: boolean;
}

interface StructuredPrototypeSortableControlRegistration {
  registrationKey: symbol;
  controls: StructuredPrototypeSortableControls;
}

interface StructuredPrototypeFreeformSnapContext {
  readonly freeformId: string;
  readonly selectedNodeIds: readonly string[];
  readonly directSiblings: readonly Readonly<StructuredPrototypeFreeformSnapSibling>[];
  readonly grids: readonly Readonly<StructuredPrototypeFreeformGrid>[];
  readonly gridSnappingEnabled: boolean;
  readonly previewScale: number;
  readonly guideOverlayFrame: StructuredPrototypeFreeformSnapGuideOverlay["frame"];
}

interface StructuredPrototypeResizeGesture {
  sessionId: number;
  nodeId: string;
  pointerId: number;
  startX: number;
  startY: number;
  startWidth: number;
  startHeight: number;
  startPosition: { x: number; y: number } | null;
  containerWidth: number;
  containerHeight: number;
  latestClientX: number;
  latestClientY: number;
  latestLockAspectRatio: boolean;
  latestResizeFromCenter: boolean;
  latestBypassSnapping: boolean;
  projectionFrame: number | null;
  direction: StructuredPrototypeResizeDirection;
  groupItems: readonly StructuredPrototypeGroupTransformItem[] | null;
  snapContext: StructuredPrototypeFreeformSnapContext | null;
  previewScale: number;
  activated: boolean;
  handle: HTMLButtonElement;
}

interface StructuredPrototypeResizeCommit {
  sessionId: number;
  nodeId: string;
}

interface StructuredPrototypeMarqueeGesture {
  sessionId: number;
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startCanvasX: number;
  startCanvasY: number;
  latestClientX: number;
  latestClientY: number;
  projectionFrame: number | null;
  activated: boolean;
  additive: boolean;
  initialSelection: StructuredPrototypeNodeSelection;
  owner: HTMLDivElement;
}

type StructuredPrototypeMarqueeEnd = "none" | "pointerup" | "pointercancel" | "blur" | "escape";
type StructuredPrototypeMarqueeEndReason =
  Exclude<StructuredPrototypeMarqueeEnd, "none"> | "unmount";
type StructuredPrototypeMarqueePhase = "idle" | "armed" | "preview";

const SURFACE_TEXT_STYLE: CSSProperties & Record<"--prototype-text", string> = {
  "--prototype-text": "var(--prototype-surface-text)",
};
const EMPTY_ANCESTOR_NODE_IDS: readonly string[] = [];
export type StructuredPrototypeResizeDirection = FreeformResizeDirection;

const GROUP_RESIZE_HANDLES: readonly {
  direction: StructuredPrototypeResizeDirection;
  className: string;
  translate: string;
}[] = [
  {
    direction: "northwest",
    className: "bottom-full right-full origin-bottom-right cursor-nwse-resize",
    translate: "",
  },
  {
    direction: "north",
    className: "bottom-full left-1/2 origin-bottom cursor-ns-resize",
    translate: "translateX(-50%) ",
  },
  {
    direction: "northeast",
    className: "bottom-full left-full origin-bottom-left cursor-nesw-resize",
    translate: "",
  },
  {
    direction: "east",
    className: "left-full top-1/2 origin-left cursor-ew-resize",
    translate: "translateY(-50%) ",
  },
  {
    direction: "southeast",
    className: "left-full top-full origin-top-left cursor-nwse-resize",
    translate: "",
  },
  {
    direction: "south",
    className: "left-1/2 top-full origin-top cursor-ns-resize",
    translate: "translateX(-50%) ",
  },
  {
    direction: "southwest",
    className: "right-full top-full origin-top-right cursor-nesw-resize",
    translate: "",
  },
  {
    direction: "west",
    className: "right-full top-1/2 origin-right cursor-ew-resize",
    translate: "translateY(-50%) ",
  },
];

export type StructuredPrototypeNodeSelectionIntent = "primary" | "replace" | "toggle";

export type StructuredPrototypeMarqueeGestureEvent =
  | { phase: "start"; pointerId: number }
  | {
      phase: "end";
      sessionId: number;
      reason: StructuredPrototypeMarqueeEndReason;
    };

interface StructuredPrototypeResizeSizeInput {
  startWidth: number;
  startHeight: number;
  startClientX: number;
  startClientY: number;
  clientX: number;
  clientY: number;
  previewScale: number;
  direction: StructuredPrototypeResizeDirection;
  lockAspectRatio: boolean;
}

export function resolveStructuredPrototypeResizeSize({
  startWidth,
  startHeight,
  startClientX,
  startClientY,
  clientX,
  clientY,
  previewScale,
  direction,
  lockAspectRatio,
}: StructuredPrototypeResizeSizeInput): { width: number; height: number } {
  const frame = resolveStructuredPrototypeFreeformResize({
    x: 2048,
    y: 2048,
    width: startWidth,
    height: startHeight,
    startClientX,
    startClientY,
    clientX,
    clientY,
    previewScale,
    direction,
    lockAspectRatio,
    resizeFromCenter: false,
    containerWidth: 4096,
    containerHeight: 4096,
  });
  return { width: frame.width, height: frame.height };
}

export function structuredPrototypeResizePassedActivationThreshold(
  startClientX: number,
  startClientY: number,
  clientX: number,
  clientY: number,
): boolean {
  return structuredPrototypeTransformPassedActivationThreshold(
    startClientX,
    startClientY,
    clientX,
    clientY,
  );
}

function canvasLengthValue(length: StructuredPrototypeLength): string {
  if (length.unit === "auto") return "auto";
  if (length.unit === "percent") return `${length.value}%`;
  return `${length.value}${length.unit}`;
}

function canvasLayoutStyle(layoutItem: StructuredPrototypeLayoutItem): CSSProperties {
  return {
    width: canvasLengthValue(layoutItem.width),
    height: canvasLengthValue(layoutItem.height),
    ...(layoutItem.minWidth !== null ? { minWidth: canvasLengthValue(layoutItem.minWidth) } : {}),
    ...(layoutItem.maxWidth !== null ? { maxWidth: canvasLengthValue(layoutItem.maxWidth) } : {}),
    ...(layoutItem.minHeight !== null
      ? { minHeight: canvasLengthValue(layoutItem.minHeight) }
      : {}),
    ...(layoutItem.maxHeight !== null
      ? { maxHeight: canvasLengthValue(layoutItem.maxHeight) }
      : {}),
    flexGrow: layoutItem.grow,
    flexShrink: layoutItem.shrink,
    alignSelf: layoutItem.alignSelf,
    ...(layoutItem.position === undefined
      ? {}
      : {
          position: "absolute",
          left: `${layoutItem.position.x}px`,
          top: `${layoutItem.position.y}px`,
        }),
  };
}

function sameDropRect(
  left: StructuredPrototypeDropRect | null,
  right: StructuredPrototypeDropRect,
): boolean {
  return (
    left !== null &&
    left.top === right.top &&
    left.right === right.right &&
    left.bottom === right.bottom &&
    left.left === right.left &&
    left.width === right.width &&
    left.height === right.height
  );
}

function toneClass(tone: "default" | "muted" | "success" | "warning" | "danger"): string {
  if (tone === "success") return "text-[#237a45]";
  if (tone === "warning") return "text-[#9a5b13]";
  if (tone === "danger") return "text-[#b4233a]";
  if (tone === "muted") return "text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)]";
  return "text-[var(--prototype-text)]";
}

function RuntimeTable({
  document,
  node,
  viewModel,
  onRowActivate,
  disabled,
  editing,
}: {
  document: StructuredPrototypeDocument;
  node: StructuredPrototypeTableNode;
  viewModel: RuntimeViewModel | null;
  onRowActivate: (nodeId: string, entity: RuntimeEntity) => void;
  disabled: boolean;
  editing: boolean;
}) {
  const rows = runtimeNodeRows(viewModel, node.id);
  const rowsBinding = runtimeTableRowsBinding(document, node.id);
  const rowEvents = runtimeNodeTriggerEvents(document, node.id);
  const rowsInteractive =
    rowsBinding !== null && rowEvents.includes("rowActivated") && !disabled && !editing;
  const cellClassName = node.density === "compact" ? "px-2.5 py-2" : "px-3.5 py-3";
  if (rows) {
    return (
      <div
        className="overflow-x-auto border border-[color-mix(in_srgb,var(--prototype-text)_15%,transparent)] bg-[var(--prototype-surface)]"
        style={SURFACE_TEXT_STYLE}
      >
        <table className="w-full min-w-[520px] border-collapse text-left text-xs">
          <thead className="bg-[color-mix(in_srgb,var(--prototype-surface)_94%,var(--prototype-text))] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)]">
            <tr>
              {node.columns.map((column) => (
                <th key={column.key} className={cn(cellClassName, "font-semibold")}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((entity) => (
              <tr
                key={entity.id}
                className={cn(
                  "border-t border-[color-mix(in_srgb,var(--prototype-text)_12%,transparent)]",
                  rowsInteractive &&
                    "cursor-pointer hover:bg-[color-mix(in_srgb,var(--prototype-accent)_8%,transparent)]",
                )}
                tabIndex={rowsInteractive ? 0 : undefined}
                onClick={() => {
                  if (rowsInteractive) onRowActivate(node.id, entity);
                }}
                onKeyDown={(event) => {
                  if (!rowsInteractive || (event.key !== "Enter" && event.key !== " ")) return;
                  event.preventDefault();
                  onRowActivate(node.id, entity);
                }}
              >
                {node.columns.map((column) => (
                  <td key={column.key} className={cellClassName}>
                    {runtimeEntityFieldText(entity, column.fieldId)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <div
      className="overflow-x-auto border border-[color-mix(in_srgb,var(--prototype-text)_15%,transparent)] bg-[var(--prototype-surface)]"
      style={SURFACE_TEXT_STYLE}
    >
      <table className="w-full border-collapse text-left text-xs">
        <thead className="bg-[color-mix(in_srgb,var(--prototype-surface)_94%,var(--prototype-text))] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)]">
          <tr>
            {node.columns.map((column) => (
              <th key={column.key} className={cn(cellClassName, "font-semibold")}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {node.rows.map((row) => (
            <tr
              key={row.id}
              className="border-t border-[color-mix(in_srgb,var(--prototype-text)_12%,transparent)]"
            >
              {node.columns.map((column) => (
                <td key={column.key} className={cellClassName}>
                  {row.cells.find((cell) => cell.columnKey === column.key)?.value ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NodeRenderer({
  document,
  node,
  depth,
  ancestorNodeIds,
  runtimeState,
  viewModel,
  viewportWidth,
  previewScale,
  editing,
  selection,
  formValues,
  disabled,
  dragDisabled,
  resizeDisabled,
  gridSnappingEnabled,
  marqueeDisabled,
  onSelect,
  onSelectionChange,
  onFreeformGroupArrange,
  onResizeNode,
  onFormValue,
  onNodeActivate,
  onRowActivate,
  freeformMoveDraft,
  resizeDraft,
  registerNodeElement,
  registerSortableControls,
}: NodeRendererProps) {
  if (node.visibility === "hidden" || !runtimeNodeVisible(viewModel, node.id)) return null;
  const select = (event: React.MouseEvent) => {
    if (!editing) return;
    event.stopPropagation();
    onSelect(node.id, event.shiftKey ? "toggle" : "replace");
  };
  if (isStructuredPrototypeContainerNode(node)) {
    return (
      <SortableCanvasContainer
        document={document}
        node={node}
        depth={depth}
        ancestorNodeIds={ancestorNodeIds}
        runtimeState={runtimeState}
        viewModel={viewModel}
        viewportWidth={viewportWidth}
        previewScale={previewScale}
        editing={editing}
        selection={selection}
        formValues={formValues}
        disabled={disabled}
        dragDisabled={dragDisabled}
        resizeDisabled={resizeDisabled}
        gridSnappingEnabled={gridSnappingEnabled}
        marqueeDisabled={marqueeDisabled}
        onSelect={onSelect}
        onSelectionChange={onSelectionChange}
        onFreeformGroupArrange={onFreeformGroupArrange}
        onResizeNode={onResizeNode}
        onFormValue={onFormValue}
        onNodeActivate={onNodeActivate}
        onRowActivate={onRowActivate}
        freeformMoveDraft={freeformMoveDraft}
        resizeDraft={resizeDraft}
        registerNodeElement={registerNodeElement}
        registerSortableControls={registerSortableControls}
        isRoot={false}
      />
    );
  }
  if (node.type === "Text") {
    const text = runtimeNodeText(viewModel, node.id, node.content);
    if (node.semantic === "heading") {
      return (
        <h2 className={cn("text-xl font-bold", toneClass(node.tone))} onClick={select}>
          {text}
        </h2>
      );
    }
    return (
      <p className={cn("text-sm", toneClass(node.tone))} onClick={select}>
        {text}
      </p>
    );
  }
  if (node.type === "Input") {
    const invalid =
      node.formDefinitionId !== null &&
      node.formFieldId !== null &&
      runtimeState?.formStates
        .find((form) => form.formId === node.formDefinitionId)
        ?.errors.some((error) => error.fieldId === node.formFieldId) === true;
    return (
      <label className="grid gap-1.5 text-xs font-semibold" onClick={select}>
        {node.label}
        <input
          className="min-h-10 w-full border border-[color-mix(in_srgb,var(--prototype-surface-text)_20%,transparent)] bg-[var(--prototype-surface)] px-3 text-sm text-[var(--prototype-surface-text)] outline-none focus:border-[var(--prototype-accent)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--prototype-accent)_15%,transparent)]"
          type={node.inputType}
          placeholder={node.placeholder}
          required={node.required}
          disabled={disabled || node.disabled}
          readOnly={editing}
          aria-invalid={invalid}
          value={formValues[node.id] ?? node.value}
          onChange={(event) => onFormValue(node.id, event.target.value)}
        />
      </label>
    );
  }
  if (node.type === "Button") {
    const triggerEvents = runtimeNodeTriggerEvents(document, node.id);
    const activationEvent = triggerEvents.includes("submit")
      ? "submit"
      : triggerEvents.includes("click")
        ? "click"
        : null;
    return (
      <button
        type={activationEvent === "submit" ? "submit" : "button"}
        className={cn(
          "inline-flex w-fit items-center justify-center font-semibold disabled:cursor-not-allowed disabled:opacity-45",
          node.size === "small" && "min-h-8 px-3 text-xs",
          node.size === "medium" && "min-h-10 px-4 text-[13px]",
          node.size === "large" && "min-h-12 px-5 text-sm",
          node.variant === "primary" &&
            "bg-[var(--prototype-accent)] text-[var(--prototype-accent-text)] brightness-100 hover:brightness-90",
          node.variant === "secondary" &&
            "border border-[color-mix(in_srgb,var(--prototype-surface-text)_20%,transparent)] bg-[var(--prototype-surface)] text-[var(--prototype-surface-text)]",
          node.variant === "danger" && "bg-[#b4233a] text-white",
          node.variant === "ghost" && "bg-transparent text-[var(--prototype-accent)]",
        )}
        disabled={disabled || node.disabled}
        onClick={(event) => {
          select(event);
          if (!editing && activationEvent !== null) onNodeActivate(node.id, activationEvent);
        }}
      >
        {node.label}
      </button>
    );
  }
  return (
    <div onClick={select}>
      <RuntimeTable
        document={document}
        node={node}
        viewModel={viewModel}
        onRowActivate={onRowActivate}
        disabled={disabled}
        editing={editing}
      />
    </div>
  );
}

function SortableCanvasContainer({
  node,
  isRoot,
  depth,
  ancestorNodeIds,
  ...props
}: SortableCanvasContainerProps) {
  const { t } = useI18n();
  const containerElementRef = useRef<HTMLElement | null>(null);
  const childElementsRef = useRef(new Map<string, HTMLElement>());
  const [dropGeometry, setDropGeometry] = useState<{
    parentRect: StructuredPrototypeDropRect | null;
    areas: StructuredPrototypeMeasuredDropArea[];
  }>({ parentRect: null, areas: [] });
  const { active, setNodeRef, isOver } = useDroppable({
    id: `container:${node.id}`,
    data: {
      kind: "container",
      intent: "inside",
      ownerNodeId: node.id,
      depth,
      ancestorNodeIds,
      parentId: node.id,
      index: node.children.length,
    },
    disabled: props.dragDisabled || !props.editing,
  });
  const renderedChildren = useMemo(
    () =>
      node.children
        .map((child, index) => ({ child, index }))
        .filter(
          ({ child }) =>
            child.visibility === "visible" && runtimeNodeVisible(props.viewModel, child.id),
        ),
    [node.children, props.viewModel],
  );
  const activeNodeId = resolveStructuredPrototypeActiveLayoutNodeId(
    active?.data.current,
    node.id,
    renderedChildren.map(({ child }) => child),
  );
  const activeIndex =
    renderedChildren.find(({ child }) => child.id === activeNodeId)?.index ?? null;
  const measuredLayoutChildren = useMemo(
    () => renderedChildren.filter(({ child }) => child.id !== activeNodeId),
    [activeNodeId, renderedChildren],
  );
  const dropLayout =
    node.type === "Grid"
      ? "grid"
      : node.type === "Stack" && node.direction === "row"
        ? "horizontal"
        : "vertical";
  const setContainerRefs = useCallback(
    (element: HTMLElement | null) => {
      containerElementRef.current = element;
      setNodeRef(element);
    },
    [setNodeRef],
  );
  const registerChildElement = useCallback((nodeId: string, element: HTMLElement | null) => {
    if (element === null) {
      childElementsRef.current.delete(nodeId);
      return;
    }
    childElementsRef.current.set(nodeId, element);
  }, []);
  const measureDropAreas = useCallback(() => {
    const parentElement = containerElementRef.current;
    if (parentElement === null) return;
    const parentRect = {
      top: 0,
      right: parentElement.clientWidth,
      bottom: parentElement.clientHeight,
      left: 0,
      width: parentElement.clientWidth,
      height: parentElement.clientHeight,
    };
    const measuredChildren = measuredLayoutChildren.flatMap(({ child, index }) => {
      const element = childElementsRef.current.get(child.id);
      return element === undefined
        ? []
        : [
            {
              nodeId: child.id,
              index,
              rect: {
                top: element.offsetTop,
                right: element.offsetLeft + element.offsetWidth,
                bottom: element.offsetTop + element.offsetHeight,
                left: element.offsetLeft,
                width: element.offsetWidth,
                height: element.offsetHeight,
              },
            },
          ];
    });
    const areas =
      node.type !== "Freeform" && measuredChildren.length === measuredLayoutChildren.length
        ? resolveStructuredPrototypeMeasuredDropAreas({
            parentRect,
            children: measuredChildren,
            childCount: node.children.length,
            activeIndex,
            layout: dropLayout,
          })
        : [];
    setDropGeometry((current) =>
      sameDropRect(current.parentRect, parentRect) &&
      sameStructuredPrototypeDropAreas(current.areas, areas)
        ? current
        : { parentRect, areas },
    );
  }, [activeIndex, dropLayout, measuredLayoutChildren, node.children.length, node.type]);
  useLayoutEffect(() => {
    measureDropAreas();
    const observer = new ResizeObserver(measureDropAreas);
    const parentElement = containerElementRef.current;
    if (parentElement !== null) observer.observe(parentElement);
    for (const { child } of measuredLayoutChildren) {
      const element = childElementsRef.current.get(child.id);
      if (element !== undefined) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [measureDropAreas, measuredLayoutChildren]);
  const strategy =
    node.type === "Grid"
      ? rectSortingStrategy
      : node.type === "Stack" && node.direction === "row"
        ? horizontalListSortingStrategy
        : verticalListSortingStrategy;
  const padding =
    node.type === "Freeform"
      ? undefined
      : `${node.padding.top}px ${node.padding.right}px ${node.padding.bottom}px ${node.padding.left}px`;
  const style: CSSProperties & Partial<Record<"--prototype-text", string>> = {
    ...(isRoot
      ? canvasLayoutStyle(resolveStructuredPrototypeLayoutItem(node, props.viewportWidth))
      : {}),
    ...(node.type === "Freeform" ? {} : { gap: node.gap, padding }),
    ...(node.type === "Stack"
      ? {
          alignItems: node.align,
          justifyContent: node.justify === "between" ? "space-between" : node.justify,
        }
      : {}),
    ...(node.type === "Grid"
      ? {
          gridTemplateColumns: `repeat(${resolveStructuredPrototypeGridColumns(node, props.viewportWidth)}, minmax(0, 1fr))`,
        }
      : {}),
    ...(node.type === "Form" ? SURFACE_TEXT_STYLE : {}),
    ...(node.type === "Freeform" ? { position: "relative", overflow: "hidden" } : {}),
  };
  const className = cn(
    "relative min-w-0 content-start transition-colors",
    node.type === "Stack" && (node.direction === "column" ? "flex flex-col" : "flex flex-row"),
    node.type === "Grid" && "grid",
    node.type === "Freeform" && "block",
    node.type === "Form" &&
      "flex flex-col border border-[color-mix(in_srgb,var(--prototype-text)_15%,transparent)] bg-[var(--prototype-surface)]",
    isRoot && "min-h-[430px]",
    node.type !== "Freeform" && !isRoot && renderedChildren.length === 0 && "min-h-24",
    isOver && "outline outline-2 outline-offset-[-2px] outline-[var(--prototype-accent)]",
  );
  const childAncestorNodeIds = useMemo(
    () => [...ancestorNodeIds, node.id],
    [ancestorNodeIds, node.id],
  );
  const children = (
    <>
      {node.type === "Freeform" && props.editing && dropGeometry.parentRect !== null && (
        <StructuredPrototypeFreeformGridOverlay
          node={node}
          width={dropGeometry.parentRect.width}
          height={dropGeometry.parentRect.height}
          previewScale={props.previewScale}
          colorTokens={props.document.tokens.colors}
        />
      )}
      <SortableContext items={renderedChildren.map(({ child }) => child.id)} strategy={strategy}>
        {renderedChildren.map(({ child, index }) => (
          <SortableCanvasNode
            key={child.id}
            node={child}
            depth={depth + 1}
            ancestorNodeIds={childAncestorNodeIds}
            parentId={node.id}
            index={index}
            dropAxis={
              node.type === "Grid" || (node.type === "Stack" && node.direction === "row")
                ? "horizontal"
                : "vertical"
            }
            onMeasuredElement={registerChildElement}
            {...props}
          />
        ))}
        {renderedChildren.length === 0 && (
          <div
            className={cn(
              "col-span-full grid min-h-20 place-items-center border border-dashed border-[color-mix(in_srgb,var(--prototype-text)_25%,transparent)] px-3 text-center text-sm text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)]",
              node.type === "Freeform" && "absolute inset-4",
            )}
          >
            {t("prototype.structured.canvas.empty")}
          </div>
        )}
        {props.editing && dropGeometry.parentRect !== null && (
          <StructuredPrototypeMeasuredDropZones
            areas={dropGeometry.areas}
            ownerNodeId={node.id}
            depth={depth + 1}
            ancestorNodeIds={ancestorNodeIds}
            parentId={node.id}
            childCount={node.children.length}
            previewScale={props.previewScale}
            disabled={props.dragDisabled}
          />
        )}
      </SortableContext>
    </>
  );
  const select = (event: React.MouseEvent) => {
    if (!props.editing) return;
    event.stopPropagation();
    props.onSelect(node.id, event.shiftKey ? "toggle" : "replace");
  };
  if (node.type === "Form") {
    return (
      <form
        ref={setContainerRefs}
        className={className}
        style={style}
        data-container-id={node.id}
        data-prototype-active-layout-node-id={activeNodeId ?? "none"}
        data-prototype-measured-layout-child-count={measuredLayoutChildren.length}
        data-prototype-drop-area-count={dropGeometry.areas.length}
        noValidate
        onSubmit={(event) => event.preventDefault()}
        onClick={isRoot ? undefined : select}
      >
        {children}
      </form>
    );
  }
  return (
    <div
      ref={setContainerRefs}
      className={className}
      style={style}
      data-container-id={node.id}
      data-prototype-active-layout-node-id={activeNodeId ?? "none"}
      data-prototype-measured-layout-child-count={measuredLayoutChildren.length}
      data-prototype-drop-area-count={dropGeometry.areas.length}
      onClick={isRoot ? undefined : select}
    >
      {children}
    </div>
  );
}

function StructuredPrototypeMeasuredDropZone({
  area,
  ownerNodeId,
  depth,
  ancestorNodeIds,
  parentId,
  childCount,
  previewScale,
  disabled,
}: {
  area: StructuredPrototypeMeasuredDropArea;
  ownerNodeId: string;
  depth: number;
  ancestorNodeIds: readonly string[];
  parentId: string;
  childCount: number;
  previewScale: number;
  disabled: boolean;
}) {
  const intent = area.targetIndex === childCount ? "after" : "before";
  const { setNodeRef, isOver } = useDroppable({
    id: `drop-area:${parentId}:${area.key}`,
    data: {
      kind: "slot",
      intent,
      ownerNodeId,
      depth,
      ancestorNodeIds,
      parentId,
      index: area.targetIndex,
    },
    disabled,
  });
  const style: CSSProperties = {
    left: area.rect.left,
    top: area.rect.top,
    width: area.rect.width,
    height: area.rect.height,
  };
  const inverseScale = resolveStructuredPrototypeInverseScale(previewScale);
  const lineStyle: CSSProperties =
    area.indicator.direction === "horizontal"
      ? {
          left: area.indicator.position - area.rect.left,
          top: area.indicator.crossStart - area.rect.top,
          width: 2 * inverseScale,
          height: area.indicator.crossEnd - area.indicator.crossStart,
        }
      : {
          left: area.indicator.crossStart - area.rect.left,
          top: area.indicator.position - area.rect.top,
          width: area.indicator.crossEnd - area.indicator.crossStart,
          height: 2 * inverseScale,
        };
  return (
    <span
      ref={setNodeRef}
      className="pointer-events-none absolute z-20"
      style={style}
      data-prototype-drop-intent={intent}
      data-prototype-drop-active={isOver ? "true" : "false"}
      data-prototype-drop-measured="true"
      aria-hidden
    >
      {isOver && (
        <span
          className="absolute bg-[var(--prototype-accent)] shadow-[0_0_0_1px_var(--prototype-surface)]"
          style={lineStyle}
          data-prototype-drop-indicator={area.indicator.direction}
        />
      )}
    </span>
  );
}

function StructuredPrototypeMeasuredDropZones({
  areas,
  ...props
}: Omit<Parameters<typeof StructuredPrototypeMeasuredDropZone>[0], "area"> & {
  areas: readonly StructuredPrototypeMeasuredDropArea[];
}) {
  return areas.map((area) => (
    <StructuredPrototypeMeasuredDropZone key={area.key} area={area} {...props} />
  ));
}

function StructuredPrototypeNodeDropZone({
  id,
  intent,
  ownerNodeId,
  depth,
  ancestorNodeIds,
  parentId,
  index,
  axis,
  container,
  disabled,
}: {
  id: string;
  intent: "before" | "inside" | "after";
  ownerNodeId: string;
  depth: number;
  ancestorNodeIds: readonly string[];
  parentId: string;
  index: number;
  axis: "horizontal" | "vertical";
  container: boolean;
  disabled: boolean;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id,
    data:
      intent === "inside"
        ? { kind: "container", intent, ownerNodeId, depth, ancestorNodeIds, parentId, index }
        : { kind: "slot", intent, ownerNodeId, depth, ancestorNodeIds, parentId, index },
    disabled,
  });
  const edgeSize = container ? "20%" : "50%";
  const style: CSSProperties =
    intent === "inside"
      ? axis === "vertical"
        ? { left: 0, right: 0, top: "20%", bottom: "20%" }
        : { top: 0, bottom: 0, left: "20%", right: "20%" }
      : axis === "vertical"
        ? intent === "before"
          ? { left: 0, right: 0, top: 0, height: edgeSize }
          : { left: 0, right: 0, bottom: 0, height: edgeSize }
        : intent === "before"
          ? { top: 0, bottom: 0, left: 0, width: edgeSize }
          : { top: 0, bottom: 0, right: 0, width: edgeSize };
  return (
    <span
      ref={setNodeRef}
      className="pointer-events-none absolute z-20"
      style={style}
      data-prototype-drop-intent={intent}
      data-prototype-drop-active={isOver ? "true" : "false"}
      aria-hidden
    >
      {isOver && intent === "inside" && (
        <span className="absolute inset-0 border-2 border-[var(--prototype-accent)] bg-[color-mix(in_srgb,var(--prototype-accent)_8%,transparent)]" />
      )}
      {isOver && intent !== "inside" && (
        <span
          className={cn(
            "absolute bg-[var(--prototype-accent)] shadow-[0_0_0_1px_var(--prototype-surface)]",
            axis === "vertical" ? "inset-x-0 h-0.5" : "inset-y-0 w-0.5",
            axis === "vertical" && intent === "before" && "top-0",
            axis === "vertical" && intent === "after" && "bottom-0",
            axis === "horizontal" && intent === "before" && "left-0",
            axis === "horizontal" && intent === "after" && "right-0",
          )}
        />
      )}
    </span>
  );
}

function SortableCanvasNode({
  node,
  depth,
  ancestorNodeIds,
  parentId,
  index,
  dropAxis,
  onMeasuredElement,
  registerNodeElement,
  registerSortableControls,
  ...props
}: SortableCanvasNodeProps) {
  const [registrationKey] = useState(() => Symbol(node.id));
  const {
    attributes,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: node.id,
    data: {
      kind: "node",
      nodeId: node.id,
      ownerNodeId: node.id,
      depth,
      ancestorNodeIds,
      parentId,
      index,
      ...(isStructuredPrototypeContainerNode(node)
        ? { containerId: node.id, containerIndex: node.children.length }
        : {}),
    },
    disabled: props.dragDisabled || !props.editing,
  });
  const sortableControls = useMemo<StructuredPrototypeSortableControls>(
    () => ({ attributes, listeners, setActivatorNodeRef }),
    [attributes, listeners, setActivatorNodeRef],
  );
  useLayoutEffect(() => {
    registerSortableControls(node.id, registrationKey, sortableControls);
  }, [node.id, registerSortableControls, registrationKey, sortableControls]);
  useLayoutEffect(
    () => () => registerSortableControls(node.id, registrationKey, null),
    [node.id, registerSortableControls, registrationKey],
  );
  const container = isStructuredPrototypeContainerNode(node);
  const setRefs = useCallback(
    (element: HTMLElement | null) => {
      setNodeRef(element);
      onMeasuredElement(node.id, element);
      registerNodeElement(node.id, registrationKey, element, ancestorNodeIds, container);
    },
    [
      ancestorNodeIds,
      container,
      node.id,
      onMeasuredElement,
      registerNodeElement,
      registrationKey,
      setNodeRef,
    ],
  );
  if (node.visibility === "hidden" || !runtimeNodeVisible(props.viewModel, node.id)) return null;
  const groupResizeDraft = props.resizeDraft?.groupItems?.find(
    (candidate) => candidate.nodeId === node.id,
  );
  const draftSize =
    groupResizeDraft === undefined
      ? props.resizeDraft?.nodeId === node.id
        ? props.resizeDraft
        : null
      : {
          nodeId: groupResizeDraft.nodeId,
          width: groupResizeDraft.width,
          height: groupResizeDraft.height,
          position: { x: groupResizeDraft.x, y: groupResizeDraft.y },
        };
  const groupMoveDraft = props.freeformMoveDraft?.groupItems?.find(
    (candidate) => candidate.nodeId === node.id,
  );
  const moveDraft =
    groupMoveDraft ??
    (props.freeformMoveDraft?.nodeId === node.id ? props.freeformMoveDraft : null);
  const resolvedLayoutItem = resolveStructuredPrototypeLayoutItem(node, props.viewportWidth);
  return (
    <section
      ref={setRefs}
      style={{
        ...SURFACE_TEXT_STYLE,
        ...canvasLayoutStyle(resolvedLayoutItem),
        ...(draftSize
          ? {
              width: `${draftSize.width}px`,
              height: `${draftSize.height}px`,
              ...(draftSize.position === undefined
                ? {}
                : {
                    position: "absolute",
                    left: `${draftSize.position.x}px`,
                    top: `${draftSize.position.y}px`,
                  }),
            }
          : {}),
        ...(moveDraft === null
          ? {}
          : { position: "absolute", left: `${moveDraft.x}px`, top: `${moveDraft.y}px` }),
        transform: CSS.Transform.toString(transform),
        transition,
      }}
      className={cn(
        "relative min-w-0",
        isDragging && "opacity-20",
        (draftSize !== null || resolvedLayoutItem.width.unit !== "auto") &&
          "[&>:last-child]:w-full",
        (draftSize !== null || resolvedLayoutItem.height.unit !== "auto") &&
          "[&>:last-child]:h-full",
      )}
      data-node-id={node.id}
      tabIndex={props.editing ? 0 : undefined}
      aria-label={`${node.type}: ${node.name}`}
      onClick={(event) => {
        if (!props.editing) return;
        event.stopPropagation();
        props.onSelect(node.id, event.shiftKey ? "toggle" : "replace");
      }}
      onKeyDown={(event) => {
        if (!props.editing || event.currentTarget !== event.target) return;
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        event.stopPropagation();
        props.onSelect(node.id, event.shiftKey ? "toggle" : "replace");
      }}
    >
      {props.editing && container && (
        <StructuredPrototypeNodeDropZone
          id={`drop:${node.id}:inside`}
          intent="inside"
          ownerNodeId={node.id}
          depth={depth + 1}
          ancestorNodeIds={ancestorNodeIds}
          parentId={node.id}
          index={node.children.length}
          axis={dropAxis}
          container
          disabled={props.dragDisabled}
        />
      )}
      <NodeRenderer
        node={node}
        depth={depth}
        ancestorNodeIds={ancestorNodeIds}
        registerNodeElement={registerNodeElement}
        registerSortableControls={registerSortableControls}
        {...props}
      />
    </section>
  );
}

interface StructuredPrototypeSelectionControlTarget {
  node: StructuredPrototypeNode;
  element: HTMLElement;
  freeformPositioned: boolean;
}

function sameStructuredPrototypeSelectionBoundsMap(
  current: ReadonlyMap<string, StructuredPrototypeSelectionBounds>,
  next: ReadonlyMap<string, StructuredPrototypeSelectionBounds>,
): boolean {
  if (current.size !== next.size) return false;
  for (const [nodeId, bounds] of next) {
    if (!sameStructuredPrototypeSelectionBounds(current.get(nodeId) ?? null, bounds)) return false;
  }
  return true;
}

function StructuredPrototypeSelectionControlsLayer({
  canvasElement,
  targets,
  primaryNodeId,
  sortableControls,
  marqueeBounds,
  previewScale,
  editing,
  dragDisabled,
  resizeDisabled,
  groupMoveEnabled,
  freeformMoveDraft,
  freeformMoveGuideOverlay,
  freeformMovePhase,
  freeformMoveLastEnd,
  resizeDraft,
  resizeGuideOverlay,
  resizePhase,
  resizeLastEnd,
  resizeDirection,
  registryVersion,
  onSelect,
  onFreeformGroupArrange,
  onFreeformSelectionNudge,
  onFreeformMovePointerDown,
  onResizePointerDown,
}: {
  canvasElement: HTMLDivElement | null;
  targets: readonly StructuredPrototypeSelectionControlTarget[];
  primaryNodeId: string | null;
  sortableControls: StructuredPrototypeSortableControls | null;
  marqueeBounds: StructuredPrototypeSelectionRect | null;
  previewScale: number;
  editing: boolean;
  dragDisabled: boolean;
  resizeDisabled: boolean;
  groupMoveEnabled: boolean;
  freeformMoveDraft: StructuredPrototypeFreeformMoveDraft | null;
  freeformMoveGuideOverlay: StructuredPrototypeFreeformSnapGuideOverlay | null;
  freeformMovePhase: "idle" | "armed" | "preview" | "pending";
  freeformMoveLastEnd: "none" | "pointerup" | "pointercancel" | "blur" | "escape";
  resizeDraft: StructuredPrototypeResizeDraft | null;
  resizeGuideOverlay: StructuredPrototypeFreeformSnapGuideOverlay | null;
  resizePhase: StructuredPrototypeResizePhase;
  resizeLastEnd: StructuredPrototypeResizeEnd;
  resizeDirection: StructuredPrototypeResizeDirection | "none";
  registryVersion: number;
  onSelect: (nodeId: string, intent: StructuredPrototypeNodeSelectionIntent) => void;
  onFreeformGroupArrange: (
    items: readonly StructuredPrototypeGroupTransformItem[],
  ) => Promise<boolean>;
  onFreeformSelectionNudge: (
    items: readonly StructuredPrototypeGroupTransformItem[],
  ) => Promise<boolean>;
  onFreeformMovePointerDown: (nodeId: string, event: PointerEvent<HTMLButtonElement>) => void;
  onResizePointerDown: (
    nodeId: string,
    direction: StructuredPrototypeResizeDirection,
    event: PointerEvent<HTMLButtonElement>,
  ) => void;
}) {
  const { t } = useI18n();
  const { active } = useDndContext();
  const [boundsByNodeId, setBoundsByNodeId] = useState(
    new Map<string, StructuredPrototypeSelectionBounds>(),
  );
  const measure = useCallback(() => {
    const next = new Map<string, StructuredPrototypeSelectionBounds>();
    if (canvasElement !== null) {
      const canvasRect = canvasElement.getBoundingClientRect();
      for (const target of targets) {
        next.set(
          target.node.id,
          resolveStructuredPrototypeSelectionControlsGeometry(
            canvasRect,
            target.element.getBoundingClientRect(),
            previewScale,
          ).bounds,
        );
      }
    }
    setBoundsByNodeId((current) =>
      sameStructuredPrototypeSelectionBoundsMap(current, next) ? current : next,
    );
  }, [canvasElement, previewScale, targets]);
  useLayoutEffect(() => {
    measure();
    if (canvasElement === null) return;
    const observer = new ResizeObserver(measure);
    observer.observe(canvasElement);
    for (const target of targets) observer.observe(target.element);
    globalThis.window.addEventListener("resize", measure);
    globalThis.window.addEventListener("scroll", measure, true);
    return () => {
      observer.disconnect();
      globalThis.window.removeEventListener("resize", measure);
      globalThis.window.removeEventListener("scroll", measure, true);
    };
  }, [canvasElement, measure, registryVersion, targets]);
  useLayoutEffect(() => {
    measure();
  }, [freeformMoveDraft, measure, resizeDraft]);
  useEffect(() => {
    if (active === null || !targets.some((target) => target.node.id === active.id)) return;
    let animationFrameId = 0;
    const measureDuringDrag = () => {
      measure();
      animationFrameId = requestAnimationFrame(measureDuringDrag);
    };
    animationFrameId = requestAnimationFrame(measureDuringDrag);
    return () => cancelAnimationFrame(animationFrameId);
  }, [active, measure, targets]);

  const handleScale = resolveStructuredPrototypeInverseScale(previewScale);
  const activeSnapGuideOverlay =
    resizePhase === "preview"
      ? resizeGuideOverlay
      : freeformMovePhase === "preview"
        ? freeformMoveGuideOverlay
        : null;
  const snapGuideSource =
    resizePhase === "preview"
      ? resizeGuideOverlay === null
        ? "none"
        : "resize"
      : freeformMovePhase === "preview" && freeformMoveGuideOverlay !== null
        ? "move"
        : "none";
  const projectedFreeformSnapGuides = useMemo(
    () =>
      activeSnapGuideOverlay === null
        ? []
        : projectStructuredPrototypeFreeformSnapGuides({
            freeformOrigin: {
              x: activeSnapGuideOverlay.frame.x,
              y: activeSnapGuideOverlay.frame.y,
            },
            containerWidth: activeSnapGuideOverlay.frame.width,
            containerHeight: activeSnapGuideOverlay.frame.height,
            previewScale: activeSnapGuideOverlay.previewScale,
            guides: activeSnapGuideOverlay.guides,
          }),
    [activeSnapGuideOverlay],
  );
  const projectedFreeformSpacingGuides = useMemo(
    () =>
      activeSnapGuideOverlay === null
        ? []
        : projectStructuredPrototypeFreeformSpacingGuides({
            freeformOrigin: {
              x: activeSnapGuideOverlay.frame.x,
              y: activeSnapGuideOverlay.frame.y,
            },
            previewScale: activeSnapGuideOverlay.previewScale,
            guides: activeSnapGuideOverlay.spacingGuides,
          }),
    [activeSnapGuideOverlay],
  );
  const groupBounds = useMemo(() => {
    if (!groupMoveEnabled || targets.length < 2) return null;
    const bounds = targets.map((target) => boundsByNodeId.get(target.node.id));
    if (bounds.some((candidate) => candidate === undefined)) return null;
    const resolved = bounds.filter(
      (candidate): candidate is StructuredPrototypeSelectionBounds => candidate !== undefined,
    );
    const left = Math.min(...resolved.map((candidate) => candidate.left));
    const top = Math.min(...resolved.map((candidate) => candidate.top));
    const right = Math.max(...resolved.map((candidate) => candidate.left + candidate.width));
    const bottom = Math.max(...resolved.map((candidate) => candidate.top + candidate.height));
    return { left, top, width: right - left, height: bottom - top };
  }, [boundsByNodeId, groupMoveEnabled, targets]);
  const primaryTarget = targets.find((target) => target.node.id === primaryNodeId) ?? null;
  const singleTransformEnabled = targets.length === 1;
  const readFreeformTransformItems = useCallback((): {
    items: StructuredPrototypeGroupTransformItem[];
    containerWidth: number;
    containerHeight: number;
  } | null => {
    if (targets.length === 0 || targets.some((target) => !target.freeformPositioned)) return null;
    const inverseScale = resolveStructuredPrototypeInverseScale(previewScale);
    const measured = targets.map((target) => {
      const position = target.node.layoutItem.position;
      const container = target.element.parentElement;
      if (position === undefined || container === null) return null;
      const rect = target.element.getBoundingClientRect();
      return {
        item: {
          nodeId: target.node.id,
          x: Number(position.x),
          y: Number(position.y),
          width: rect.width * inverseScale,
          height: rect.height * inverseScale,
        },
        container,
      };
    });
    if (measured.some((candidate) => candidate === null)) return null;
    const resolved = measured.filter(
      (
        candidate,
      ): candidate is {
        item: StructuredPrototypeGroupTransformItem;
        container: HTMLElement;
      } => candidate !== null,
    );
    const container = resolved[0]?.container;
    if (
      container === undefined ||
      resolved.some((candidate) => candidate.container !== container) ||
      container.clientWidth <= 0 ||
      container.clientHeight <= 0
    ) {
      return null;
    }
    return {
      items: resolved.map((candidate) => candidate.item),
      containerWidth: container.clientWidth,
      containerHeight: container.clientHeight,
    };
  }, [previewScale, targets]);
  const readGroupTransformItems = (): StructuredPrototypeGroupTransformItem[] | null => {
    if (!groupMoveEnabled) return null;
    return readFreeformTransformItems()?.items ?? null;
  };
  useEffect(() => {
    if (!editing || dragDisabled) return;
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (
        event.defaultPrevented ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        isKeyboardShortcutEditableTarget(event.target)
      ) {
        return;
      }
      const step = event.shiftKey ? 10 : 1;
      let deltaX = 0;
      let deltaY = 0;
      switch (event.key) {
        case "ArrowLeft":
          deltaX = -step;
          break;
        case "ArrowRight":
          deltaX = step;
          break;
        case "ArrowUp":
          deltaY = -step;
          break;
        case "ArrowDown":
          deltaY = step;
          break;
        default:
          return;
      }
      const selection = readFreeformTransformItems();
      if (selection === null) return;
      event.preventDefault();
      void onFreeformSelectionNudge(
        resolveStructuredPrototypeSelectionNudge({
          items: selection.items,
          deltaX,
          deltaY,
          containerWidth: selection.containerWidth,
          containerHeight: selection.containerHeight,
        }),
      );
    };
    globalThis.window.addEventListener("keydown", handleKeyDown);
    return () => globalThis.window.removeEventListener("keydown", handleKeyDown);
  }, [dragDisabled, editing, onFreeformSelectionNudge, readFreeformTransformItems]);
  const arrangeGroupAlignment = (alignment: StructuredPrototypeGroupAlignment): void => {
    const items = readGroupTransformItems();
    if (items === null) return;
    void onFreeformGroupArrange(resolveStructuredPrototypeGroupAlignment(items, alignment));
  };
  const arrangeGroupDistribution = (axis: StructuredPrototypeGroupDistributionAxis): void => {
    const items = readGroupTransformItems();
    if (items === null) return;
    void onFreeformGroupArrange(resolveStructuredPrototypeGroupDistribution(items, axis));
  };
  return (
    <div
      className="pointer-events-none absolute inset-0 z-40"
      data-prototype-controls-layer="selection"
      data-prototype-selection-count={targets.length}
      data-prototype-keyboard-nudge="arrow-shift-10"
      data-prototype-snap-guide-count={
        projectedFreeformSnapGuides.length + projectedFreeformSpacingGuides.length
      }
      data-prototype-spacing-guide-count={projectedFreeformSpacingGuides.length}
      data-prototype-snap-guide-source={snapGuideSource}
    >
      {editing && marqueeBounds !== null && (
        <div
          className="absolute border border-[var(--prototype-accent)] bg-[color-mix(in_srgb,var(--prototype-accent)_10%,transparent)]"
          style={{
            left: marqueeBounds.left,
            top: marqueeBounds.top,
            width: marqueeBounds.width,
            height: marqueeBounds.height,
            borderWidth: handleScale,
          }}
          data-prototype-marquee="true"
          aria-hidden
        />
      )}
      {editing &&
        projectedFreeformSnapGuides.map((guide) => (
          <div
            key={`${guide.axis}:${guide.targetKind}:${guide.gridId ?? guide.targetNodeId ?? "container"}`}
            className="absolute bg-[var(--prototype-accent)] shadow-[0_0_0_1px_var(--prototype-surface)]"
            style={{
              left: guide.left,
              top: guide.top,
              width: guide.width,
              height: guide.height,
            }}
            data-prototype-snap-guide="true"
            data-prototype-snap-guide-kind={guide.targetKind === "grid" ? "grid" : "alignment"}
            data-prototype-snap-source={snapGuideSource}
            data-prototype-snap-axis={guide.axis}
            data-prototype-snap-moving-anchor={guide.movingAnchor}
            data-prototype-snap-target-anchor={guide.targetAnchor}
            data-prototype-snap-target-kind={guide.targetKind}
            data-prototype-snap-target-node-id={guide.targetNodeId ?? guide.gridId ?? "container"}
            data-prototype-snap-grid-id={guide.gridId}
            data-prototype-snap-grid-type={guide.gridType}
            data-prototype-snap-grid-line-index={guide.gridLineIndex}
            aria-hidden
          />
        ))}
      {editing &&
        projectedFreeformSpacingGuides.map((guide) => {
          const horizontal = guide.axis === "x";
          const endCapLeft = horizontal
            ? guide.left + guide.width - guide.capThickness
            : guide.left - guide.capLength / 2;
          const endCapTop = horizontal
            ? guide.top - guide.capLength / 2
            : guide.top + guide.height - guide.capThickness;
          return (
            <div
              key={`${guide.axis}:${guide.placement}:${guide.referenceNodeIds.join(":")}:${guide.segmentIndex}`}
              className="contents"
              data-prototype-snap-guide-kind="spacing"
              data-prototype-snap-source={snapGuideSource}
              data-prototype-spacing-guide="true"
              data-prototype-spacing-axis={guide.axis}
              data-prototype-spacing-placement={guide.placement}
              data-prototype-spacing-gap={guide.gap}
              data-prototype-spacing-reference-node-ids={guide.referenceNodeIds.join(",")}
              data-prototype-spacing-segment-index={guide.segmentIndex}
              aria-hidden
            >
              <div
                className="absolute bg-[var(--prototype-accent)]"
                style={{
                  left: guide.left,
                  top: guide.top,
                  width: guide.width,
                  height: guide.height,
                }}
                data-prototype-spacing-line="true"
              />
              <div
                className="absolute bg-[var(--prototype-accent)]"
                style={{
                  left: horizontal ? guide.left : guide.left - guide.capLength / 2,
                  top: horizontal ? guide.top - guide.capLength / 2 : guide.top,
                  width: horizontal ? guide.capThickness : guide.capLength,
                  height: horizontal ? guide.capLength : guide.capThickness,
                }}
                data-prototype-spacing-cap="start"
              />
              <div
                className="absolute bg-[var(--prototype-accent)]"
                style={{
                  left: endCapLeft,
                  top: endCapTop,
                  width: horizontal ? guide.capThickness : guide.capLength,
                  height: horizontal ? guide.capLength : guide.capThickness,
                }}
                data-prototype-spacing-cap="end"
              />
              <div
                className="absolute rounded-sm bg-[var(--prototype-accent)] px-1 py-0.5 text-[10px] font-medium leading-none text-white shadow-sm"
                style={{
                  left: guide.left + guide.width / 2,
                  top: guide.top + guide.height / 2,
                  transform: `translate(-50%, -50%) scale(${handleScale})`,
                  transformOrigin: "center",
                }}
                data-prototype-spacing-label="true"
              >
                {canonicalStructuredPrototypeFreeformValue(guide.gap)} px
              </div>
            </div>
          );
        })}
      {editing && groupBounds !== null && primaryTarget !== null && (
        <div
          className="pointer-events-none absolute outline outline-[var(--prototype-accent)] outline-offset-0"
          style={{
            left: groupBounds.left,
            top: groupBounds.top,
            width: groupBounds.width,
            height: groupBounds.height,
            outlineWidth: handleScale,
          }}
          data-prototype-group-selection-controls="true"
          data-prototype-group-selection-count={targets.length}
        >
          <div
            className="pointer-events-auto absolute bottom-full left-1/2 z-20 flex origin-bottom items-center rounded-md border border-[color-mix(in_srgb,var(--prototype-text)_15%,transparent)] bg-[var(--prototype-surface)] p-1 text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm"
            style={{
              marginBottom: 44 * handleScale,
              transform: `translateX(-50%) scale(${handleScale})`,
            }}
            role="toolbar"
            aria-label={t("prototype.structured.canvas.groupTools")}
            data-prototype-freeform-group-toolbar="true"
          >
            <button
              type="button"
              className="grid size-8 cursor-move place-items-center rounded-sm hover:bg-[color-mix(in_srgb,var(--prototype-accent)_12%,transparent)] focus-visible:outline-2 focus-visible:outline-[var(--prototype-accent)] active:cursor-grabbing disabled:pointer-events-none disabled:opacity-40"
              aria-label={t("prototype.structured.canvas.dragSelection", {
                count: String(targets.length),
              })}
              title={t("prototype.structured.canvas.dragSelection", {
                count: String(targets.length),
              })}
              disabled={dragDisabled}
              onFocus={() => onSelect(primaryTarget.node.id, "primary")}
              onPointerDown={(event) => onFreeformMovePointerDown(primaryTarget.node.id, event)}
              data-prototype-freeform-group-move-handle="true"
            >
              <GripVertical size={14} aria-hidden />
            </button>
            <span className="mx-1 h-5 border-l border-[color-mix(in_srgb,var(--prototype-text)_15%,transparent)]" />
            <button
              type="button"
              className="grid size-8 cursor-pointer place-items-center rounded-sm hover:bg-[color-mix(in_srgb,var(--prototype-accent)_12%,transparent)] focus-visible:outline-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-40"
              aria-label={t("prototype.structured.canvas.alignLeft")}
              title={t("prototype.structured.canvas.alignLeft")}
              disabled={dragDisabled}
              onClick={() => arrangeGroupAlignment("left")}
            >
              <AlignHorizontalJustifyStart size={14} aria-hidden />
            </button>
            <button
              type="button"
              className="grid size-8 cursor-pointer place-items-center rounded-sm hover:bg-[color-mix(in_srgb,var(--prototype-accent)_12%,transparent)] focus-visible:outline-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-40"
              aria-label={t("prototype.structured.canvas.alignCenter")}
              title={t("prototype.structured.canvas.alignCenter")}
              disabled={dragDisabled}
              onClick={() => arrangeGroupAlignment("center")}
            >
              <AlignHorizontalJustifyCenter size={14} aria-hidden />
            </button>
            <button
              type="button"
              className="grid size-8 cursor-pointer place-items-center rounded-sm hover:bg-[color-mix(in_srgb,var(--prototype-accent)_12%,transparent)] focus-visible:outline-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-40"
              aria-label={t("prototype.structured.canvas.alignRight")}
              title={t("prototype.structured.canvas.alignRight")}
              disabled={dragDisabled}
              onClick={() => arrangeGroupAlignment("right")}
            >
              <AlignHorizontalJustifyEnd size={14} aria-hidden />
            </button>
            <button
              type="button"
              className="grid size-8 cursor-pointer place-items-center rounded-sm hover:bg-[color-mix(in_srgb,var(--prototype-accent)_12%,transparent)] focus-visible:outline-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-40"
              aria-label={t("prototype.structured.canvas.alignTop")}
              title={t("prototype.structured.canvas.alignTop")}
              disabled={dragDisabled}
              onClick={() => arrangeGroupAlignment("top")}
            >
              <AlignVerticalJustifyStart size={14} aria-hidden />
            </button>
            <button
              type="button"
              className="grid size-8 cursor-pointer place-items-center rounded-sm hover:bg-[color-mix(in_srgb,var(--prototype-accent)_12%,transparent)] focus-visible:outline-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-40"
              aria-label={t("prototype.structured.canvas.alignMiddle")}
              title={t("prototype.structured.canvas.alignMiddle")}
              disabled={dragDisabled}
              onClick={() => arrangeGroupAlignment("middle")}
            >
              <AlignVerticalJustifyCenter size={14} aria-hidden />
            </button>
            <button
              type="button"
              className="grid size-8 cursor-pointer place-items-center rounded-sm hover:bg-[color-mix(in_srgb,var(--prototype-accent)_12%,transparent)] focus-visible:outline-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-40"
              aria-label={t("prototype.structured.canvas.alignBottom")}
              title={t("prototype.structured.canvas.alignBottom")}
              disabled={dragDisabled}
              onClick={() => arrangeGroupAlignment("bottom")}
            >
              <AlignVerticalJustifyEnd size={14} aria-hidden />
            </button>
            <span className="mx-1 h-5 border-l border-[color-mix(in_srgb,var(--prototype-text)_15%,transparent)]" />
            <button
              type="button"
              className="grid size-8 cursor-pointer place-items-center rounded-sm hover:bg-[color-mix(in_srgb,var(--prototype-accent)_12%,transparent)] focus-visible:outline-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-40"
              aria-label={t("prototype.structured.canvas.distributeHorizontal")}
              title={t("prototype.structured.canvas.distributeHorizontal")}
              disabled={dragDisabled || targets.length < 3}
              onClick={() => arrangeGroupDistribution("horizontal")}
            >
              <AlignHorizontalSpaceBetween size={14} aria-hidden />
            </button>
            <button
              type="button"
              className="grid size-8 cursor-pointer place-items-center rounded-sm hover:bg-[color-mix(in_srgb,var(--prototype-accent)_12%,transparent)] focus-visible:outline-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-40"
              aria-label={t("prototype.structured.canvas.distributeVertical")}
              title={t("prototype.structured.canvas.distributeVertical")}
              disabled={dragDisabled || targets.length < 3}
              onClick={() => arrangeGroupDistribution("vertical")}
            >
              <AlignVerticalSpaceBetween size={14} aria-hidden />
            </button>
          </div>
          {GROUP_RESIZE_HANDLES.map((handle) => (
            <button
              key={handle.direction}
              type="button"
              className={cn(
                "pointer-events-auto absolute z-10 grid size-8 place-items-center bg-transparent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-0",
                handle.className,
              )}
              style={{ transform: `${handle.translate}scale(${handleScale})` }}
              aria-label={t("prototype.structured.canvas.resizeSelection", {
                count: String(targets.length),
              })}
              title={t("prototype.structured.canvas.resizeSelection", {
                count: String(targets.length),
              })}
              disabled={resizeDisabled}
              onFocus={() => onSelect(primaryTarget.node.id, "primary")}
              onPointerDown={(event) =>
                onResizePointerDown(primaryTarget.node.id, handle.direction, event)
              }
              data-prototype-group-resize-direction={handle.direction}
            >
              <span
                aria-hidden
                className="size-2.5 border-2 border-[var(--prototype-accent)] bg-[var(--prototype-surface)]"
              />
            </button>
          ))}
          {freeformMoveDraft?.groupItems !== undefined && (
            <span
              className="pointer-events-none absolute bottom-0 left-0 z-10 origin-bottom-left bg-[var(--prototype-accent)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--prototype-accent-text)]"
              style={{ transform: `scale(${handleScale})` }}
              aria-live="polite"
            >
              x {canonicalStructuredPrototypeFreeformValue(freeformMoveDraft.x)} / y{" "}
              {canonicalStructuredPrototypeFreeformValue(freeformMoveDraft.y)}
            </span>
          )}
          {resizeDraft?.groupItems !== undefined && (
            <span
              className="pointer-events-none absolute bottom-0 left-0 z-10 origin-bottom-left bg-[var(--prototype-accent)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--prototype-accent-text)]"
              style={{ transform: `scale(${handleScale})` }}
              aria-live="polite"
            >
              {Math.round(resizeDraft.width)} x {Math.round(resizeDraft.height)}
            </span>
          )}
        </div>
      )}
      {editing &&
        targets.map((target) => {
          const bounds = boundsByNodeId.get(target.node.id);
          if (bounds === undefined) return null;
          const primary = target.node.id === primaryNodeId;
          const selectedDraft = resizeDraft?.nodeId === target.node.id ? resizeDraft : null;
          const selectedMoveDraft =
            freeformMoveDraft?.nodeId === target.node.id ? freeformMoveDraft : null;
          return (
            <div
              key={target.node.id}
              className={cn(
                "pointer-events-none absolute outline outline-[var(--prototype-accent)] outline-offset-0",
                primary && singleTransformEnabled ? "outline-solid" : "outline-dashed opacity-75",
              )}
              style={{
                left: bounds.left,
                top: bounds.top,
                width: bounds.width,
                height: bounds.height,
                outlineWidth: handleScale,
              }}
              data-prototype-selection-controls={primary ? "true" : undefined}
              data-prototype-selection-outline="true"
              data-prototype-node-selected="true"
              data-prototype-selection-primary={primary ? "true" : "false"}
              data-prototype-selection-node-id={target.node.id}
              data-prototype-resize-phase={primary ? resizePhase : undefined}
              data-prototype-resize-last-end={primary ? resizeLastEnd : undefined}
              data-prototype-resize-direction={primary ? resizeDirection : undefined}
              data-prototype-freeform-positioned={target.freeformPositioned ? "true" : "false"}
              data-prototype-freeform-move-phase={
                primary && target.freeformPositioned ? freeformMovePhase : undefined
              }
              data-prototype-freeform-move-last-end={
                primary && target.freeformPositioned ? freeformMoveLastEnd : undefined
              }
            >
              {primary && singleTransformEnabled && target.freeformPositioned && (
                <button
                  type="button"
                  className="pointer-events-auto absolute bottom-full left-full z-20 grid size-8 origin-bottom-left cursor-move place-items-center border border-[color-mix(in_srgb,var(--prototype-text)_15%,transparent)] bg-[var(--prototype-surface)] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] active:cursor-grabbing disabled:pointer-events-none disabled:opacity-0"
                  style={{ marginLeft: 44 * handleScale, transform: `scale(${handleScale})` }}
                  aria-label={t("prototype.structured.canvas.drag", { name: target.node.name })}
                  disabled={dragDisabled}
                  onFocus={() => onSelect(target.node.id, "primary")}
                  onPointerDown={(event) => onFreeformMovePointerDown(target.node.id, event)}
                  data-prototype-freeform-move-handle="true"
                >
                  <GripVertical size={14} aria-hidden />
                </button>
              )}
              {primary &&
                singleTransformEnabled &&
                target.freeformPositioned &&
                sortableControls !== null && (
                  <button
                    ref={sortableControls.setActivatorNodeRef}
                    type="button"
                    className="pointer-events-auto absolute bottom-full right-full z-20 grid size-8 origin-bottom-right cursor-grab place-items-center border border-[color-mix(in_srgb,var(--prototype-text)_15%,transparent)] bg-[var(--prototype-surface)] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] active:cursor-grabbing disabled:pointer-events-none disabled:opacity-0"
                    style={{ marginRight: 44 * handleScale, transform: `scale(${handleScale})` }}
                    aria-label={t("prototype.structured.canvas.reparent", {
                      name: target.node.name,
                    })}
                    title={t("prototype.structured.canvas.reparent", { name: target.node.name })}
                    disabled={dragDisabled}
                    onFocus={() => onSelect(target.node.id, "primary")}
                    data-prototype-freeform-layer-handle="true"
                    {...sortableControls.attributes}
                    {...sortableControls.listeners}
                  >
                    <Layers3 size={14} aria-hidden />
                  </button>
                )}
              {primary &&
                singleTransformEnabled &&
                !target.freeformPositioned &&
                sortableControls !== null && (
                  <button
                    ref={sortableControls.setActivatorNodeRef}
                    type="button"
                    className="pointer-events-auto absolute bottom-full right-0 z-10 grid size-8 origin-bottom-right cursor-grab place-items-center border border-[color-mix(in_srgb,var(--prototype-text)_15%,transparent)] bg-[var(--prototype-surface)] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] active:cursor-grabbing disabled:pointer-events-none disabled:opacity-0"
                    style={{ transform: `scale(${handleScale})` }}
                    aria-label={t("prototype.structured.canvas.drag", { name: target.node.name })}
                    disabled={dragDisabled}
                    onFocus={() => onSelect(target.node.id, "primary")}
                    {...sortableControls.attributes}
                    {...sortableControls.listeners}
                  >
                    <GripVertical size={14} aria-hidden />
                  </button>
                )}
              {primary && singleTransformEnabled && (
                <>
                  {target.freeformPositioned && (
                    <button
                      type="button"
                      className="pointer-events-auto absolute bottom-full right-full z-20 size-8 origin-bottom-right cursor-nwse-resize rounded-br-md border-b border-r border-[color-mix(in_srgb,var(--prototype-text)_18%,transparent)] bg-[var(--prototype-surface)] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-0"
                      style={{ transform: `scale(${handleScale})` }}
                      aria-label={t("prototype.structured.canvas.resize", {
                        name: target.node.name,
                      })}
                      disabled={resizeDisabled}
                      onFocus={() => onSelect(target.node.id, "primary")}
                      onPointerDown={(event) =>
                        onResizePointerDown(target.node.id, "northwest", event)
                      }
                      data-prototype-resize-direction="northwest"
                    >
                      <span
                        aria-hidden
                        className="absolute bottom-1 right-1 h-3 w-3 border-b-2 border-r-2"
                      />
                    </button>
                  )}
                  {target.freeformPositioned && (
                    <button
                      type="button"
                      className="pointer-events-auto absolute right-full top-1/2 z-10 size-8 origin-right cursor-ew-resize rounded-l-md border-y border-l border-[color-mix(in_srgb,var(--prototype-text)_18%,transparent)] bg-[var(--prototype-surface)] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-0"
                      style={{ transform: `translateY(-50%) scale(${handleScale})` }}
                      aria-label={t("prototype.structured.canvas.resizeWidth", {
                        name: target.node.name,
                      })}
                      disabled={resizeDisabled}
                      onFocus={() => onSelect(target.node.id, "primary")}
                      onPointerDown={(event) => onResizePointerDown(target.node.id, "west", event)}
                      data-prototype-resize-direction="west"
                    >
                      <span aria-hidden className="absolute inset-y-2 left-1/2 border-l-2" />
                    </button>
                  )}
                  {target.freeformPositioned && (
                    <button
                      type="button"
                      className="pointer-events-auto absolute bottom-full left-1/2 z-10 size-8 origin-bottom cursor-ns-resize rounded-t-md border-x border-t border-[color-mix(in_srgb,var(--prototype-text)_18%,transparent)] bg-[var(--prototype-surface)] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-0"
                      style={{ transform: `translateX(-50%) scale(${handleScale})` }}
                      aria-label={t("prototype.structured.canvas.resizeHeight", {
                        name: target.node.name,
                      })}
                      disabled={resizeDisabled}
                      onFocus={() => onSelect(target.node.id, "primary")}
                      onPointerDown={(event) => onResizePointerDown(target.node.id, "north", event)}
                      data-prototype-resize-direction="north"
                    >
                      <span aria-hidden className="absolute inset-x-2 top-1/2 border-t-2" />
                    </button>
                  )}
                  {target.freeformPositioned && (
                    <button
                      type="button"
                      className="pointer-events-auto absolute bottom-full left-full z-20 size-8 origin-bottom-left cursor-nesw-resize rounded-bl-md border-b border-l border-[color-mix(in_srgb,var(--prototype-text)_18%,transparent)] bg-[var(--prototype-surface)] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-0"
                      style={{ transform: `scale(${handleScale})` }}
                      aria-label={t("prototype.structured.canvas.resize", {
                        name: target.node.name,
                      })}
                      disabled={resizeDisabled}
                      onFocus={() => onSelect(target.node.id, "primary")}
                      onPointerDown={(event) =>
                        onResizePointerDown(target.node.id, "northeast", event)
                      }
                      data-prototype-resize-direction="northeast"
                    >
                      <span
                        aria-hidden
                        className="absolute bottom-1 left-1 h-3 w-3 border-b-2 border-l-2"
                      />
                    </button>
                  )}
                  <button
                    type="button"
                    className="pointer-events-auto absolute left-full top-1/2 z-10 size-8 origin-left cursor-ew-resize rounded-r-md border-y border-r border-[color-mix(in_srgb,var(--prototype-text)_18%,transparent)] bg-[var(--prototype-surface)] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-0"
                    style={{ transform: `translateY(-50%) scale(${handleScale})` }}
                    aria-label={t("prototype.structured.canvas.resizeWidth", {
                      name: target.node.name,
                    })}
                    disabled={resizeDisabled}
                    onFocus={() => onSelect(target.node.id, "primary")}
                    onPointerDown={(event) => onResizePointerDown(target.node.id, "east", event)}
                    data-prototype-resize-direction="east"
                  >
                    <span aria-hidden className="absolute inset-y-2 left-1/2 border-l-2" />
                  </button>
                  <button
                    type="button"
                    className="pointer-events-auto absolute left-1/2 top-full z-10 size-8 origin-top cursor-ns-resize rounded-b-md border-x border-b border-[color-mix(in_srgb,var(--prototype-text)_18%,transparent)] bg-[var(--prototype-surface)] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-0"
                    style={{ transform: `translateX(-50%) scale(${handleScale})` }}
                    aria-label={t("prototype.structured.canvas.resizeHeight", {
                      name: target.node.name,
                    })}
                    disabled={resizeDisabled}
                    onFocus={() => onSelect(target.node.id, "primary")}
                    onPointerDown={(event) => onResizePointerDown(target.node.id, "south", event)}
                    data-prototype-resize-direction="south"
                  >
                    <span aria-hidden className="absolute inset-x-2 top-1/2 border-t-2" />
                  </button>
                  {target.freeformPositioned && (
                    <button
                      type="button"
                      className="pointer-events-auto absolute right-full top-full z-20 size-8 origin-top-right cursor-nesw-resize rounded-tr-md border-r border-t border-[color-mix(in_srgb,var(--prototype-text)_18%,transparent)] bg-[var(--prototype-surface)] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-0"
                      style={{ transform: `scale(${handleScale})` }}
                      aria-label={t("prototype.structured.canvas.resize", {
                        name: target.node.name,
                      })}
                      disabled={resizeDisabled}
                      onFocus={() => onSelect(target.node.id, "primary")}
                      onPointerDown={(event) =>
                        onResizePointerDown(target.node.id, "southwest", event)
                      }
                      data-prototype-resize-direction="southwest"
                    >
                      <span
                        aria-hidden
                        className="absolute right-1 top-1 h-3 w-3 border-r-2 border-t-2"
                      />
                    </button>
                  )}
                  <button
                    type="button"
                    className="pointer-events-auto absolute right-0 top-full z-10 size-8 origin-top-right cursor-nwse-resize rounded-bl-md border-b border-l border-[color-mix(in_srgb,var(--prototype-text)_18%,transparent)] bg-[var(--prototype-surface)] text-[color-mix(in_srgb,var(--prototype-text)_64%,transparent)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--prototype-accent)] disabled:pointer-events-none disabled:opacity-0"
                    style={{ transform: `scale(${handleScale})` }}
                    aria-label={t("prototype.structured.canvas.resize", {
                      name: target.node.name,
                    })}
                    disabled={resizeDisabled}
                    onFocus={() => onSelect(target.node.id, "primary")}
                    onPointerDown={(event) =>
                      onResizePointerDown(target.node.id, "southeast", event)
                    }
                    data-prototype-resize-direction="southeast"
                  >
                    <span
                      aria-hidden
                      className="absolute bottom-1 right-1 h-3 w-3 border-b-2 border-r-2"
                    />
                  </button>
                </>
              )}
              {primary && singleTransformEnabled && selectedDraft !== null && (
                <span
                  className="pointer-events-none absolute bottom-0 left-0 z-10 origin-bottom-left bg-[var(--prototype-accent)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--prototype-accent-text)]"
                  style={{ transform: `scale(${handleScale})` }}
                  aria-live="polite"
                >
                  {selectedDraft.width} x {selectedDraft.height}
                </span>
              )}
              {primary && singleTransformEnabled && selectedMoveDraft !== null && (
                <span
                  className="pointer-events-none absolute bottom-0 left-0 z-10 origin-bottom-left bg-[var(--prototype-accent)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--prototype-accent-text)]"
                  style={{ transform: `scale(${handleScale})` }}
                  aria-live="polite"
                >
                  x {canonicalStructuredPrototypeFreeformValue(selectedMoveDraft.x)} / y{" "}
                  {canonicalStructuredPrototypeFreeformValue(selectedMoveDraft.y)}
                </span>
              )}
            </div>
          );
        })}
    </div>
  );
}

export function StructuredPrototypeCanvas({ page, ...props }: Props) {
  const {
    dragDisabled,
    onFreeformGroupArrange,
    onFreeformSelectionNudge,
    onFreeformMoveError,
    onFreeformMoveGestureChange,
    onFreeformMoveNode,
    onMarqueeGestureChange,
    onResizeError,
    onResizeGestureChange,
    onResizeNode,
    onSelect,
    onSelectionChange,
    previewScale,
    resizeDisabled,
  } = props;
  const [canvasElement, setCanvasElement] = useState<HTMLDivElement | null>(null);
  const nodeElementRegistrationsRef = useRef(
    new Map<string, StructuredPrototypeNodeElementRegistration>(),
  );
  const [nodeRegistryVersion, setNodeRegistryVersion] = useState(0);
  const [sortableControlRegistrations, setSortableControlRegistrations] = useState(
    new Map<string, StructuredPrototypeSortableControlRegistration>(),
  );
  const [resizeDraft, setResizeDraft] = useState<StructuredPrototypeResizeDraft | null>(null);
  const [resizeGuideOverlay, setResizeGuideOverlay] =
    useState<StructuredPrototypeFreeformSnapGuideOverlay | null>(null);
  const [resizePhase, setResizePhase] = useState<StructuredPrototypeResizePhase>("idle");
  const [resizeLastEnd, setResizeLastEnd] = useState<StructuredPrototypeResizeEnd>("none");
  const [resizeDirection, setResizeDirection] = useState<
    StructuredPrototypeResizeDirection | "none"
  >("none");
  const [marqueeBounds, setMarqueeBounds] = useState<StructuredPrototypeSelectionRect | null>(null);
  const [marqueePhase, setMarqueePhase] = useState<StructuredPrototypeMarqueePhase>("idle");
  const [marqueeLastEnd, setMarqueeLastEnd] = useState<StructuredPrototypeMarqueeEnd>("none");
  const resizeGestureRef = useRef<StructuredPrototypeResizeGesture | null>(null);
  const resizeCommitRef = useRef<StructuredPrototypeResizeCommit | null>(null);
  const resizeCleanupRef = useRef<(() => void) | null>(null);
  const resizeErrorRef = useRef(onResizeError);
  const resizeGestureChangeRef = useRef(onResizeGestureChange);
  const resizeNodeRef = useRef(onResizeNode);
  const marqueeGestureRef = useRef<StructuredPrototypeMarqueeGesture | null>(null);
  const marqueeCleanupRef = useRef<(() => void) | null>(null);
  const marqueeGestureChangeRef = useRef(onMarqueeGestureChange);
  const selectionChangeRef = useRef(onSelectionChange);
  const mountedRef = useRef(true);
  const freeformGroupSelection = useMemo(
    () => resolveStructuredPrototypeFreeformGroupSelection(page.root, props.selection.nodeIds),
    [page.root, props.selection.nodeIds],
  );
  const readFreeformGroupTransform = useCallback((): {
    items: StructuredPrototypeGroupTransformItem[];
    container: HTMLElement;
  } | null => {
    if (freeformGroupSelection === null) return null;
    const inverseScale = resolveStructuredPrototypeInverseScale(previewScale);
    const measuredItems = freeformGroupSelection.items.map((item) => {
      const element = nodeElementRegistrationsRef.current.get(item.node.id)?.element;
      const container = element?.parentElement;
      return element === undefined || container === undefined || container === null
        ? null
        : {
            item: {
              nodeId: item.node.id,
              x: item.x,
              y: item.y,
              width: element.getBoundingClientRect().width * inverseScale,
              height: element.getBoundingClientRect().height * inverseScale,
            },
            container,
          };
    });
    if (measuredItems.some((item) => item === null)) return null;
    const resolvedItems = measuredItems.filter(
      (
        item,
      ): item is {
        item: StructuredPrototypeGroupTransformItem;
        container: HTMLElement;
      } => item !== null,
    );
    const container = resolvedItems[0]?.container;
    if (container === undefined || resolvedItems.some((item) => item.container !== container)) {
      return null;
    }
    return { items: resolvedItems.map((item) => item.item), container };
  }, [freeformGroupSelection, previewScale]);

  const resolveFreeformSnapContext = useCallback(
    (
      parent: StructuredPrototypeFreeformNode,
      selectedNodeIds: readonly string[],
      container: HTMLElement,
    ): StructuredPrototypeFreeformSnapContext | null => {
      if (canvasElement === null || container.clientWidth <= 0 || container.clientHeight <= 0) {
        return null;
      }
      const selectedNodeIdSet = new Set(selectedNodeIds);
      const inverseScale = resolveStructuredPrototypeInverseScale(previewScale);
      const directSiblings = parent.children.flatMap((child) => {
        if (
          selectedNodeIdSet.has(child.id) ||
          child.visibility === "hidden" ||
          !runtimeNodeVisible(props.viewModel, child.id)
        ) {
          return [];
        }
        const position = child.layoutItem.position;
        const registration = nodeElementRegistrationsRef.current.get(child.id);
        if (
          position === undefined ||
          registration === undefined ||
          !registration.element.isConnected ||
          registration.element.parentElement !== container ||
          registration.ancestorNodeIds[registration.ancestorNodeIds.length - 1] !== parent.id
        ) {
          return [];
        }
        const rect = registration.element.getBoundingClientRect();
        const sibling = {
          nodeId: child.id,
          x: Number(position.x),
          y: Number(position.y),
          width: rect.width * inverseScale,
          height: rect.height * inverseScale,
        };
        if (sibling.width <= 0 || sibling.height <= 0 || sibling.x < 0 || sibling.y < 0) {
          return [];
        }
        return [sibling];
      });
      const canvasRect = canvasElement.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      return {
        freeformId: parent.id,
        selectedNodeIds: [...selectedNodeIds],
        directSiblings,
        grids: resolveStructuredPrototypeFreeformGrids(parent),
        gridSnappingEnabled: props.gridSnappingEnabled,
        previewScale,
        guideOverlayFrame: {
          x: (containerRect.left - canvasRect.left) * inverseScale + container.clientLeft,
          y: (containerRect.top - canvasRect.top) * inverseScale + container.clientTop,
          width: container.clientWidth,
          height: container.clientHeight,
        },
      };
    },
    [canvasElement, previewScale, props.gridSnappingEnabled, props.viewModel],
  );

  const resolveFreeformMoveStartFrame = useCallback(
    (nodeId: string) => {
      if (
        freeformGroupSelection !== null &&
        props.selection.primaryNodeId === nodeId &&
        freeformGroupSelection.items.some((item) => item.node.id === nodeId)
      ) {
        const group = readFreeformGroupTransform();
        if (group === null) return null;
        const bounds = resolveStructuredPrototypeGroupTransformBounds(group.items);
        const snapContext = resolveFreeformSnapContext(
          freeformGroupSelection.parent,
          group.items.map((item) => item.nodeId),
          group.container,
        );
        if (snapContext === null) return null;
        return {
          x: bounds.x,
          y: bounds.y,
          nodeWidth: bounds.width,
          nodeHeight: bounds.height,
          containerWidth: group.container.clientWidth,
          containerHeight: group.container.clientHeight,
          ...snapContext,
        };
      }
      const selection = resolveStructuredPrototypeFreeformSelection(page.root, [nodeId]);
      const item = selection?.items[0];
      const position = item?.node.layoutItem.position;
      const element = nodeElementRegistrationsRef.current.get(nodeId)?.element;
      const container = element?.parentElement;
      if (
        selection === null ||
        item === undefined ||
        position === undefined ||
        element === undefined ||
        container === undefined ||
        container === null
      ) {
        return null;
      }
      const snapContext = resolveFreeformSnapContext(selection.parent, [nodeId], container);
      if (snapContext === null) return null;
      const rect = element.getBoundingClientRect();
      const inverseScale = resolveStructuredPrototypeInverseScale(previewScale);
      return {
        x: Number(position.x),
        y: Number(position.y),
        nodeWidth: rect.width * inverseScale,
        nodeHeight: rect.height * inverseScale,
        containerWidth: container.clientWidth,
        containerHeight: container.clientHeight,
        ...snapContext,
      };
    },
    [
      freeformGroupSelection,
      page.root,
      previewScale,
      props.selection.primaryNodeId,
      readFreeformGroupTransform,
      resolveFreeformSnapContext,
    ],
  );
  const freeformMove = useStructuredPrototypeFreeformMove({
    disabled: dragDisabled,
    onSelect: (nodeId) => onSelect(nodeId, "primary"),
    onMoveNode: onFreeformMoveNode,
    onMoveError: onFreeformMoveError,
    onGestureChange: onFreeformMoveGestureChange,
    resolveStartFrame: resolveFreeformMoveStartFrame,
  });
  const {
    acknowledge: acknowledgeFreeformMove,
    draft: rawFreeformMoveDraft,
    guideOverlay: freeformMoveGuideOverlay,
    lastEnd: freeformMoveLastEnd,
    onPointerDown: handleFreeformMovePointerDown,
    phase: freeformMovePhase,
  } = freeformMove;
  const freeformMoveDraft = useMemo<StructuredPrototypeFreeformMoveDraft | null>(() => {
    if (
      rawFreeformMoveDraft === null ||
      freeformGroupSelection === null ||
      props.selection.primaryNodeId !== rawFreeformMoveDraft.nodeId ||
      !freeformGroupSelection.items.some((item) => item.node.id === rawFreeformMoveDraft.nodeId)
    ) {
      return rawFreeformMoveDraft;
    }
    const groupX = Math.min(...freeformGroupSelection.items.map((item) => item.x));
    const groupY = Math.min(...freeformGroupSelection.items.map((item) => item.y));
    const deltaX = rawFreeformMoveDraft.x - groupX;
    const deltaY = rawFreeformMoveDraft.y - groupY;
    return {
      ...rawFreeformMoveDraft,
      groupItems: freeformGroupSelection.items.map((item) => ({
        nodeId: item.node.id,
        x: item.x + deltaX,
        y: item.y + deltaY,
      })),
    };
  }, [freeformGroupSelection, props.selection.primaryNodeId, rawFreeformMoveDraft]);

  useLayoutEffect(() => {
    resizeErrorRef.current = onResizeError;
    resizeGestureChangeRef.current = onResizeGestureChange;
    resizeNodeRef.current = onResizeNode;
    marqueeGestureChangeRef.current = onMarqueeGestureChange;
    selectionChangeRef.current = onSelectionChange;
  }, [
    onMarqueeGestureChange,
    onResizeError,
    onResizeGestureChange,
    onResizeNode,
    onSelectionChange,
  ]);

  const registerNodeElement = useCallback(
    (
      nodeId: string,
      registrationKey: symbol,
      element: HTMLElement | null,
      ancestorNodeIds: readonly string[],
      container: boolean,
    ) => {
      const current = nodeElementRegistrationsRef.current.get(nodeId);
      if (element === null) {
        if (current?.registrationKey !== registrationKey) return;
        nodeElementRegistrationsRef.current.delete(nodeId);
        setNodeRegistryVersion((version) => version + 1);
        return;
      }
      if (
        current?.registrationKey === registrationKey &&
        current.element === element &&
        current.container === container &&
        current.ancestorNodeIds.length === ancestorNodeIds.length &&
        current.ancestorNodeIds.every(
          (ancestorNodeId, index) => ancestorNodeId === ancestorNodeIds[index],
        )
      ) {
        return;
      }
      nodeElementRegistrationsRef.current.set(nodeId, {
        registrationKey,
        element,
        ancestorNodeIds,
        container,
      });
      setNodeRegistryVersion((version) => version + 1);
    },
    [],
  );
  const registerSortableControls = useCallback(
    (
      nodeId: string,
      registrationKey: symbol,
      controls: StructuredPrototypeSortableControls | null,
    ) => {
      setSortableControlRegistrations((current) => {
        const registered = current.get(nodeId);
        if (controls === null) {
          if (registered?.registrationKey !== registrationKey) return current;
          const next = new Map(current);
          next.delete(nodeId);
          return next;
        }
        if (
          registered?.registrationKey === registrationKey &&
          registered.controls.attributes === controls.attributes &&
          registered.controls.listeners === controls.listeners &&
          registered.controls.setActivatorNodeRef === controls.setActivatorNodeRef
        ) {
          return current;
        }
        const next = new Map(current);
        next.set(nodeId, { registrationKey, controls });
        return next;
      });
    },
    [],
  );

  const detachMarqueePointer = useCallback(() => {
    const gesture = marqueeGestureRef.current;
    if (gesture === null) return null;
    marqueeGestureRef.current = null;
    if (gesture.projectionFrame !== null) {
      globalThis.window.cancelAnimationFrame(gesture.projectionFrame);
      gesture.projectionFrame = null;
    }
    marqueeCleanupRef.current?.();
    if (gesture.owner.hasPointerCapture(gesture.pointerId)) {
      gesture.owner.releasePointerCapture(gesture.pointerId);
    }
    return gesture;
  }, []);

  const endMarqueeGesture = useCallback(
    (reason: StructuredPrototypeMarqueeEndReason, restoreInitialSelection: boolean) => {
      const gesture = detachMarqueePointer();
      if (gesture === null) return null;
      if (restoreInitialSelection) selectionChangeRef.current(gesture.initialSelection);
      marqueeGestureChangeRef.current({ phase: "end", sessionId: gesture.sessionId, reason });
      setMarqueeBounds(null);
      setMarqueePhase("idle");
      setMarqueeLastEnd(reason === "unmount" ? "pointercancel" : reason);
      return gesture;
    },
    [detachMarqueePointer],
  );

  const handleMarqueePointerDown = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (!props.editing || props.marqueeDisabled || event.button !== 0 || !event.isPrimary) {
        return;
      }
      const target = event.target instanceof Element ? event.target : null;
      if (
        target !== null &&
        target.closest('[data-node-id], [data-prototype-controls-layer="selection"]') !== null
      ) {
        return;
      }
      const sessionId = marqueeGestureChangeRef.current({
        phase: "start",
        pointerId: event.pointerId,
      });
      if (sessionId === null) return;
      event.preventDefault();
      event.stopPropagation();
      const owner = event.currentTarget;
      const ownerRect = owner.getBoundingClientRect();
      const transform = createStructuredPrototypeViewportTransform({
        viewportOrigin: { x: ownerRect.left, y: ownerRect.top },
        canvasOrigin: { x: 0, y: 0 },
        pan: { x: 0, y: 0 },
        scale: previewScale,
      });
      const start = transform.clientToCanvas({ x: event.clientX, y: event.clientY });
      const pointerId = event.pointerId;
      const additive = event.shiftKey;
      marqueeGestureRef.current = {
        sessionId,
        pointerId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        startCanvasX: start.x,
        startCanvasY: start.y,
        latestClientX: event.clientX,
        latestClientY: event.clientY,
        projectionFrame: null,
        activated: false,
        additive,
        initialSelection: props.selection,
        owner,
      };
      setMarqueeBounds(null);
      setMarqueePhase("armed");
      setMarqueeLastEnd("none");
      owner.setPointerCapture(pointerId);

      function readCandidates(): StructuredPrototypeMarqueeCandidate[] {
        return Array.from(nodeElementRegistrationsRef.current.entries()).map(
          ([nodeId, registration]) => {
            const rect = registration.element.getBoundingClientRect();
            return {
              nodeId,
              ancestorNodeIds: registration.ancestorNodeIds,
              kind: registration.container ? "container" : "leaf",
              rect: {
                top: rect.top,
                right: rect.right,
                bottom: rect.bottom,
                left: rect.left,
                width: rect.width,
                height: rect.height,
              },
            };
          },
        );
      }

      function projectMarquee(
        gesture: StructuredPrototypeMarqueeGesture,
        clientX: number,
        clientY: number,
      ): void {
        const currentOwnerRect = gesture.owner.getBoundingClientRect();
        const currentTransform = createStructuredPrototypeViewportTransform({
          viewportOrigin: { x: currentOwnerRect.left, y: currentOwnerRect.top },
          canvasOrigin: { x: 0, y: 0 },
          pan: { x: 0, y: 0 },
          scale: previewScale,
        });
        const end = currentTransform.clientToCanvas({ x: clientX, y: clientY });
        const candidates = readCandidates();
        const matchedNodeIds = resolveStructuredPrototypeMarqueeNodeIds(
          candidates,
          normalizeStructuredPrototypeSelectionRect(
            { x: gesture.startClientX, y: gesture.startClientY },
            { x: clientX, y: clientY },
          ),
        );
        const requestedNodeIds = gesture.additive
          ? [...gesture.initialSelection.nodeIds, ...matchedNodeIds]
          : matchedNodeIds;
        const nodeIds = resolveStructuredPrototypeOutermostCandidateNodeIds(
          candidates,
          requestedNodeIds,
        );
        const preferredPrimaryNodeId =
          gesture.additive &&
          gesture.initialSelection.primaryNodeId !== null &&
          nodeIds.includes(gesture.initialSelection.primaryNodeId)
            ? gesture.initialSelection.primaryNodeId
            : (matchedNodeIds.find((nodeId) => nodeIds.includes(nodeId)) ?? nodeIds[0] ?? null);
        selectionChangeRef.current({ nodeIds, primaryNodeId: preferredPrimaryNodeId });
        setMarqueeBounds(
          normalizeStructuredPrototypeSelectionRect(
            { x: gesture.startCanvasX, y: gesture.startCanvasY },
            end,
          ),
        );
      }

      function activateMarquee(clientX: number, clientY: number) {
        const gesture = marqueeGestureRef.current;
        if (gesture === null || gesture.pointerId !== pointerId) return null;
        gesture.latestClientX = clientX;
        gesture.latestClientY = clientY;
        if (!gesture.activated) {
          if (
            !structuredPrototypeMarqueePassedActivationThreshold(
              gesture.startClientX,
              gesture.startClientY,
              clientX,
              clientY,
            )
          ) {
            return null;
          }
          gesture.activated = true;
          setMarqueePhase("preview");
        }
        return gesture;
      }

      function scheduleMarquee(clientX: number, clientY: number): void {
        const gesture = activateMarquee(clientX, clientY);
        if (gesture === null || gesture.projectionFrame !== null) return;
        gesture.projectionFrame = globalThis.window.requestAnimationFrame(() => {
          const current = marqueeGestureRef.current;
          if (
            current === null ||
            current.pointerId !== pointerId ||
            current.sessionId !== gesture.sessionId
          ) {
            return;
          }
          current.projectionFrame = null;
          projectMarquee(current, current.latestClientX, current.latestClientY);
        });
      }

      function cleanup(): void {
        globalThis.window.removeEventListener("pointermove", handlePointerMove);
        globalThis.window.removeEventListener("pointerup", handlePointerUp);
        globalThis.window.removeEventListener("pointercancel", handlePointerCancel);
        globalThis.window.removeEventListener("blur", handleBlur);
        globalThis.window.removeEventListener("keydown", handleKeyDown);
        owner.removeEventListener("lostpointercapture", handleLostPointerCapture);
        marqueeCleanupRef.current = null;
      }

      function cancelMarquee(reason: "pointercancel" | "blur" | "escape"): void {
        if (marqueeGestureRef.current?.pointerId !== pointerId) return;
        endMarqueeGesture(reason, true);
      }

      function handlePointerMove(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId !== pointerId) return;
        pointerEvent.preventDefault();
        pointerEvent.stopPropagation();
        scheduleMarquee(pointerEvent.clientX, pointerEvent.clientY);
      }

      function handlePointerUp(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId !== pointerId) return;
        pointerEvent.preventDefault();
        pointerEvent.stopPropagation();
        const gesture = activateMarquee(pointerEvent.clientX, pointerEvent.clientY);
        if (gesture !== null) {
          projectMarquee(gesture, pointerEvent.clientX, pointerEvent.clientY);
        } else if (!additive) {
          selectionChangeRef.current({ nodeIds: [], primaryNodeId: null });
        }
        endMarqueeGesture("pointerup", false);
      }

      function handlePointerCancel(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId === pointerId) cancelMarquee("pointercancel");
      }

      function handleLostPointerCapture(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId === pointerId) cancelMarquee("pointercancel");
      }

      function handleBlur(): void {
        cancelMarquee("blur");
      }

      function handleKeyDown(keyboardEvent: KeyboardEvent): void {
        if (keyboardEvent.key !== "Escape") return;
        keyboardEvent.preventDefault();
        cancelMarquee("escape");
      }

      globalThis.window.addEventListener("pointermove", handlePointerMove, { passive: false });
      globalThis.window.addEventListener("pointerup", handlePointerUp, { passive: false });
      globalThis.window.addEventListener("pointercancel", handlePointerCancel, { passive: false });
      globalThis.window.addEventListener("blur", handleBlur);
      globalThis.window.addEventListener("keydown", handleKeyDown);
      owner.addEventListener("lostpointercapture", handleLostPointerCapture);
      marqueeCleanupRef.current = cleanup;
    },
    [endMarqueeGesture, previewScale, props.editing, props.marqueeDisabled, props.selection],
  );

  const clearResizeGuideOverlay = useCallback((): void => {
    setResizeGuideOverlay(null);
  }, []);

  const detachResizePointer = useCallback(() => {
    const gesture = resizeGestureRef.current;
    if (gesture === null) return null;
    resizeGestureRef.current = null;
    if (gesture.projectionFrame !== null) {
      globalThis.window.cancelAnimationFrame(gesture.projectionFrame);
      gesture.projectionFrame = null;
    }
    resizeCleanupRef.current?.();
    if (gesture.handle.hasPointerCapture(gesture.pointerId)) {
      gesture.handle.releasePointerCapture(gesture.pointerId);
    }
    return gesture;
  }, []);

  const endResizeGesture = useCallback(
    (reason: StructuredPrototypeResizeEndReason) => {
      const gesture = detachResizePointer();
      if (gesture === null) return null;
      resizeGestureChangeRef.current({
        phase: "end",
        nodeId: gesture.nodeId,
        sessionId: gesture.sessionId,
        reason,
      });
      clearResizeGuideOverlay();
      return gesture;
    },
    [clearResizeGuideOverlay, detachResizePointer],
  );

  const endResizeCommit = useCallback(
    (reason: StructuredPrototypeResizeEndReason) => {
      const commit = resizeCommitRef.current;
      if (commit === null) return;
      resizeCommitRef.current = null;
      resizeGestureChangeRef.current({
        phase: "end",
        nodeId: commit.nodeId,
        sessionId: commit.sessionId,
        reason,
      });
      clearResizeGuideOverlay();
      setResizeDirection("none");
    },
    [clearResizeGuideOverlay],
  );

  const handleResizePointerDown = useCallback(
    (
      nodeId: string,
      direction: StructuredPrototypeResizeDirection,
      event: PointerEvent<HTMLButtonElement>,
    ) => {
      if (resizeDisabled || !structuredPrototypeCanStartTransform(event.button, event.isPrimary)) {
        return;
      }
      const nodeElement = nodeElementRegistrationsRef.current.get(nodeId)?.element;
      if (nodeElement === undefined) return;
      const node = findStructuredPrototypeNode(page.root, nodeId);
      if (node === null) return;
      const positioned = node.layoutItem.position;
      const directionSupportsUnpositioned =
        direction === "east" || direction === "south" || direction === "southeast";
      if (!directionSupportsUnpositioned && positioned === undefined) return;
      const group =
        freeformGroupSelection !== null &&
        props.selection.primaryNodeId === nodeId &&
        freeformGroupSelection.items.some((item) => item.node.id === nodeId)
          ? readFreeformGroupTransform()
          : null;
      if (endResizeGesture("pointercancel") !== null) {
        setResizeDraft(null);
        setResizePhase("idle");
        setResizeLastEnd("pointercancel");
        setResizeDirection("none");
      }
      const rect = nodeElement.getBoundingClientRect();
      const inverseScale = resolveStructuredPrototypeInverseScale(previewScale);
      const containerElement = nodeElement.parentElement;
      const groupBounds =
        group === null ? null : resolveStructuredPrototypeGroupTransformBounds(group.items);
      const singleFreeformSelection =
        group === null && positioned !== undefined
          ? resolveStructuredPrototypeFreeformSelection(page.root, [nodeId])
          : null;
      const snapParent =
        group === null ? singleFreeformSelection?.parent : freeformGroupSelection?.parent;
      const snapContainer = group?.container ?? containerElement;
      const snapSelectedNodeIds = group?.items.map((item) => item.nodeId) ?? [nodeId];
      const snapContext =
        snapParent === undefined || snapContainer === null
          ? null
          : resolveFreeformSnapContext(snapParent, snapSelectedNodeIds, snapContainer);
      const pointerId = event.pointerId;
      const sessionId = resizeGestureChangeRef.current({
        phase: "start",
        nodeId,
        pointerId,
        previewScale,
      });
      if (sessionId === null) return;
      event.preventDefault();
      event.stopPropagation();
      onSelect(nodeId, "primary");
      setResizeLastEnd("none");
      setResizeDirection(direction);
      setResizePhase("armed");
      clearResizeGuideOverlay();
      const handle = event.currentTarget;
      resizeGestureRef.current = {
        sessionId,
        nodeId,
        pointerId,
        startX: event.clientX,
        startY: event.clientY,
        startWidth: groupBounds?.width ?? rect.width * inverseScale,
        startHeight: groupBounds?.height ?? rect.height * inverseScale,
        startPosition:
          groupBounds ??
          (positioned === undefined ? null : { x: Number(positioned.x), y: Number(positioned.y) }),
        containerWidth: group?.container.clientWidth ?? containerElement?.clientWidth ?? 4096,
        containerHeight: group?.container.clientHeight ?? containerElement?.clientHeight ?? 4096,
        latestClientX: event.clientX,
        latestClientY: event.clientY,
        latestLockAspectRatio: event.shiftKey,
        latestResizeFromCenter: event.altKey,
        latestBypassSnapping: event.ctrlKey || event.metaKey,
        projectionFrame: null,
        direction,
        groupItems: group?.items ?? null,
        snapContext:
          snapContext === null
            ? null
            : {
                freeformId: snapContext.freeformId,
                selectedNodeIds: [...snapContext.selectedNodeIds],
                directSiblings: snapContext.directSiblings.map((sibling) => ({ ...sibling })),
                grids: snapContext.grids.map((grid) => grid),
                gridSnappingEnabled: snapContext.gridSnappingEnabled,
                previewScale: snapContext.previewScale,
                guideOverlayFrame: { ...snapContext.guideOverlayFrame },
              },
        previewScale,
        activated: false,
        handle,
      };
      handle.setPointerCapture(pointerId);

      function activateResize(
        clientX: number,
        clientY: number,
        lockAspectRatio: boolean,
        resizeFromCenter: boolean,
        bypassSnapping: boolean,
      ) {
        const gesture = resizeGestureRef.current;
        if (gesture === null || gesture.pointerId !== pointerId) return null;
        gesture.latestClientX = clientX;
        gesture.latestClientY = clientY;
        gesture.latestLockAspectRatio = lockAspectRatio;
        gesture.latestResizeFromCenter = resizeFromCenter;
        gesture.latestBypassSnapping = bypassSnapping;
        if (!gesture.activated) {
          if (
            !structuredPrototypeResizePassedActivationThreshold(
              gesture.startX,
              gesture.startY,
              clientX,
              clientY,
            )
          ) {
            return null;
          }
          gesture.activated = true;
          setResizePhase("preview");
          resizeGestureChangeRef.current({
            phase: "preview",
            nodeId,
            sessionId: gesture.sessionId,
          });
        }
        return gesture;
      }

      function resolveResizeProjection(
        gesture: StructuredPrototypeResizeGesture,
        clientX: number,
        clientY: number,
        lockAspectRatio: boolean,
        resizeFromCenter: boolean,
        bypassSnapping: boolean,
      ): {
        draft: Omit<StructuredPrototypeResizeDraft, "nodeId">;
        guides: StructuredPrototypeFreeformSnapGuideOverlay["guides"];
      } {
        if (gesture.startPosition !== null && gesture.snapContext !== null) {
          const requestedCanvasDelta = resolveStructuredPrototypeClientDeltaToCanvas(
            { x: clientX - gesture.startX, y: clientY - gesture.startY },
            gesture.previewScale,
          );
          const sizeLimits =
            gesture.groupItems === null
              ? {
                  minimumSize: {
                    width: STRUCTURED_PROTOTYPE_MIN_RESIZE_WIDTH,
                    height: STRUCTURED_PROTOTYPE_MIN_RESIZE_HEIGHT,
                  },
                  maximumSize: {
                    width: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
                    height: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
                  },
                }
              : resolveStructuredPrototypeGroupResizeSizeLimits({
                  items: gesture.groupItems,
                  direction: gesture.direction,
                  lockAspectRatio,
                  resizeFromCenter,
                });
          const projection = resolveStructuredPrototypeFreeformResizeSnap({
            startBounds: {
              x: gesture.startPosition.x,
              y: gesture.startPosition.y,
              width: gesture.startWidth,
              height: gesture.startHeight,
            },
            requestedCanvasDelta,
            direction: gesture.direction,
            lockAspectRatio,
            resizeFromCenter,
            bypassSnapping,
            minimumSize: sizeLimits.minimumSize,
            maximumSize: sizeLimits.maximumSize,
            selectedNodeIds: gesture.snapContext.selectedNodeIds,
            directSiblings: gesture.snapContext.directSiblings,
            containerWidth: gesture.containerWidth,
            containerHeight: gesture.containerHeight,
            previewScale: gesture.previewScale,
          });
          const groupItems =
            gesture.groupItems === null
              ? undefined
              : projectStructuredPrototypeGroupResizeItemsToBounds(
                  gesture.groupItems,
                  projection.bounds,
                );
          return {
            draft: {
              width: projection.bounds.width,
              height: projection.bounds.height,
              position: { x: projection.bounds.x, y: projection.bounds.y },
              ...(groupItems === undefined ? {} : { groupItems }),
            },
            guides: projection.guides,
          };
        }
        if (gesture.groupItems !== null) {
          const groupItems = resolveStructuredPrototypeGroupResize({
            items: gesture.groupItems,
            startClientX: gesture.startX,
            startClientY: gesture.startY,
            clientX,
            clientY,
            previewScale: gesture.previewScale,
            direction: gesture.direction,
            lockAspectRatio,
            resizeFromCenter,
            containerWidth: gesture.containerWidth,
            containerHeight: gesture.containerHeight,
          });
          const bounds = resolveStructuredPrototypeGroupTransformBounds(groupItems);
          return {
            draft: {
              width: bounds.width,
              height: bounds.height,
              position: { x: bounds.x, y: bounds.y },
              groupItems,
            },
            guides: [],
          };
        }
        if (gesture.startPosition !== null) {
          const frame = resolveStructuredPrototypeFreeformResize({
            x: gesture.startPosition.x,
            y: gesture.startPosition.y,
            width: gesture.startWidth,
            height: gesture.startHeight,
            startClientX: gesture.startX,
            startClientY: gesture.startY,
            clientX,
            clientY,
            previewScale: gesture.previewScale,
            direction: gesture.direction,
            lockAspectRatio,
            resizeFromCenter,
            containerWidth: gesture.containerWidth,
            containerHeight: gesture.containerHeight,
          });
          return {
            draft: {
              width: frame.width,
              height: frame.height,
              position: { x: frame.x, y: frame.y },
            },
            guides: [],
          };
        }
        return {
          draft: resolveStructuredPrototypeResizeSize({
            startWidth: gesture.startWidth,
            startHeight: gesture.startHeight,
            startClientX: gesture.startX,
            startClientY: gesture.startY,
            clientX,
            clientY,
            previewScale: gesture.previewScale,
            direction: gesture.direction,
            lockAspectRatio,
          }),
          guides: [],
        };
      }

      function scheduleResize(
        clientX: number,
        clientY: number,
        lockAspectRatio: boolean,
        resizeFromCenter: boolean,
        bypassSnapping: boolean,
      ): void {
        const gesture = activateResize(
          clientX,
          clientY,
          lockAspectRatio,
          resizeFromCenter,
          bypassSnapping,
        );
        if (gesture === null || gesture.projectionFrame !== null) return;
        gesture.projectionFrame = globalThis.window.requestAnimationFrame(() => {
          const current = resizeGestureRef.current;
          if (
            current === null ||
            current.pointerId !== pointerId ||
            current.sessionId !== gesture.sessionId
          ) {
            return;
          }
          current.projectionFrame = null;
          const projection = resolveResizeProjection(
            current,
            current.latestClientX,
            current.latestClientY,
            current.latestLockAspectRatio,
            current.latestResizeFromCenter,
            current.latestBypassSnapping,
          );
          setResizeDraft({ nodeId, ...projection.draft });
          setResizeGuideOverlay(
            projection.guides.length === 0 || current.snapContext === null
              ? null
              : {
                  frame: current.snapContext.guideOverlayFrame,
                  guides: projection.guides,
                  spacingGuides: [],
                  previewScale: current.snapContext.previewScale,
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
        resizeCleanupRef.current = null;
      }

      function cancelResize(reason: "pointercancel" | "blur" | "escape"): void {
        if (resizeGestureRef.current?.pointerId !== pointerId) return;
        endResizeGesture(reason);
        setResizeDraft(null);
        setResizePhase("idle");
        setResizeLastEnd(reason);
        setResizeDirection("none");
      }

      function handlePointerMove(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId !== pointerId) return;
        pointerEvent.preventDefault();
        pointerEvent.stopPropagation();
        scheduleResize(
          pointerEvent.clientX,
          pointerEvent.clientY,
          pointerEvent.shiftKey,
          pointerEvent.altKey,
          pointerEvent.ctrlKey || pointerEvent.metaKey,
        );
      }

      function handlePointerUp(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId !== pointerId) return;
        pointerEvent.preventDefault();
        pointerEvent.stopPropagation();
        const activeGesture = activateResize(
          pointerEvent.clientX,
          pointerEvent.clientY,
          pointerEvent.shiftKey,
          pointerEvent.altKey,
          pointerEvent.ctrlKey || pointerEvent.metaKey,
        );
        const finalProjection =
          activeGesture === null
            ? null
            : resolveResizeProjection(
                activeGesture,
                pointerEvent.clientX,
                pointerEvent.clientY,
                pointerEvent.shiftKey,
                pointerEvent.altKey,
                pointerEvent.ctrlKey || pointerEvent.metaKey,
              );
        const finalSize = finalProjection?.draft ?? null;
        const gesture = detachResizePointer();
        if (gesture === null) return;
        clearResizeGuideOverlay();
        setResizeLastEnd("pointerup");
        if (finalSize === null) {
          resizeGestureChangeRef.current({
            phase: "end",
            nodeId,
            sessionId: gesture.sessionId,
            reason: "pointerup",
          });
          setResizeDraft(null);
          setResizePhase("idle");
          setResizeDirection("none");
          return;
        }
        const acceptedSessionId = resizeGestureChangeRef.current({
          phase: "commit",
          nodeId,
          sessionId: gesture.sessionId,
        });
        if (acceptedSessionId !== gesture.sessionId) {
          resizeGestureChangeRef.current({
            phase: "end",
            nodeId,
            sessionId: gesture.sessionId,
            reason: "pointercancel",
          });
          setResizeDraft(null);
          setResizePhase("idle");
          setResizeLastEnd("pointercancel");
          setResizeDirection("none");
          return;
        }
        resizeCommitRef.current = { nodeId, sessionId: gesture.sessionId };
        setResizeDraft({ nodeId, ...finalSize });
        setResizePhase("pending");
        void (async () => {
          let applied = false;
          try {
            applied = await resizeNodeRef.current(
              nodeId,
              finalSize.width,
              finalSize.height,
              finalSize.position,
              finalSize.groupItems,
            );
          } catch (error) {
            if (resizeCommitRef.current?.sessionId === gesture.sessionId) {
              resizeErrorRef.current(error);
            }
          } finally {
            if (resizeCommitRef.current?.sessionId !== gesture.sessionId) return;
            if (!applied && mountedRef.current) {
              setResizeDraft(null);
              setResizePhase("idle");
            }
            endResizeCommit("pointerup");
          }
        })();
      }

      function handlePointerCancel(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId === pointerId) cancelResize("pointercancel");
      }

      function handleLostPointerCapture(pointerEvent: globalThis.PointerEvent): void {
        if (pointerEvent.pointerId === pointerId) cancelResize("pointercancel");
      }

      function handleBlur(): void {
        cancelResize("blur");
      }

      function handleKeyDown(keyboardEvent: KeyboardEvent): void {
        if (keyboardEvent.key !== "Escape") return;
        keyboardEvent.preventDefault();
        cancelResize("escape");
      }

      globalThis.window.addEventListener("pointermove", handlePointerMove, { passive: false });
      globalThis.window.addEventListener("pointerup", handlePointerUp, { passive: false });
      globalThis.window.addEventListener("pointercancel", handlePointerCancel, { passive: false });
      globalThis.window.addEventListener("blur", handleBlur);
      globalThis.window.addEventListener("keydown", handleKeyDown);
      handle.addEventListener("lostpointercapture", handleLostPointerCapture);
      resizeCleanupRef.current = cleanup;
    },
    [
      clearResizeGuideOverlay,
      detachResizePointer,
      endResizeCommit,
      endResizeGesture,
      onSelect,
      page.root,
      previewScale,
      freeformGroupSelection,
      props.selection.primaryNodeId,
      readFreeformGroupTransform,
      resolveFreeformSnapContext,
      resizeDisabled,
    ],
  );
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      endResizeGesture("unmount");
      endResizeCommit("unmount");
      const marqueeGesture = detachMarqueePointer();
      if (marqueeGesture !== null) {
        marqueeGestureChangeRef.current({
          phase: "end",
          sessionId: marqueeGesture.sessionId,
          reason: "unmount",
        });
      }
    };
  }, [detachMarqueePointer, endResizeCommit, endResizeGesture]);
  useEffect(() => {
    if (resizePhase !== "pending" || resizeDraft === null) return;
    const drafts = resizeDraft.groupItems ?? [
      {
        nodeId: resizeDraft.nodeId,
        width: resizeDraft.width,
        height: resizeDraft.height,
        ...(resizeDraft.position === undefined
          ? {}
          : { x: resizeDraft.position.x, y: resizeDraft.position.y }),
      },
    ];
    const applied = drafts.every((draft) => {
      const node = findStructuredPrototypeNode(page.root, draft.nodeId);
      const position =
        "x" in draft && "y" in draft && typeof draft.x === "number" && typeof draft.y === "number"
          ? { x: draft.x, y: draft.y }
          : null;
      return (
        node?.layoutItem.width.unit === "px" &&
        node.layoutItem.width.value === canonicalStructuredPrototypeFreeformValue(draft.width) &&
        node.layoutItem.height.unit === "px" &&
        node.layoutItem.height.value === canonicalStructuredPrototypeFreeformValue(draft.height) &&
        (position === null ||
          (node.layoutItem.position?.x === canonicalStructuredPrototypeFreeformValue(position.x) &&
            node.layoutItem.position.y === canonicalStructuredPrototypeFreeformValue(position.y)))
      );
    });
    if (applied) {
      setResizeDraft(null);
      clearResizeGuideOverlay();
      setResizePhase("idle");
    }
  }, [clearResizeGuideOverlay, page.root, resizeDraft, resizePhase]);
  useEffect(() => {
    if (freeformMovePhase !== "pending" || freeformMoveDraft === null) return;
    const drafts = freeformMoveDraft.groupItems ?? [freeformMoveDraft];
    const applied = drafts.every((draft) => {
      const node = findStructuredPrototypeNode(page.root, draft.nodeId);
      return (
        node?.layoutItem.position?.x === canonicalStructuredPrototypeFreeformValue(draft.x) &&
        node.layoutItem.position.y === canonicalStructuredPrototypeFreeformValue(draft.y)
      );
    });
    if (applied) {
      acknowledgeFreeformMove();
    }
  }, [acknowledgeFreeformMove, freeformMoveDraft, freeformMovePhase, page.root]);

  const root = page.root;
  const nodeRegistrySnapshot = useMemo(
    () => ({ version: nodeRegistryVersion, registrations: nodeElementRegistrationsRef.current }),
    [nodeRegistryVersion],
  );
  const selectionTargets = useMemo(
    () =>
      props.selection.nodeIds.flatMap((nodeId) => {
        const node = findStructuredPrototypeNode(page.root, nodeId);
        const registration = nodeRegistrySnapshot.registrations.get(nodeId);
        return node === null || registration === undefined
          ? []
          : [
              {
                node,
                element: registration.element,
                freeformPositioned: node.layoutItem.position !== undefined,
              },
            ];
      }),
    [nodeRegistrySnapshot, page.root, props.selection.nodeIds],
  );
  const primaryNodeId = selectionTargets.some(
    (target) => target.node.id === props.selection.primaryNodeId,
  )
    ? props.selection.primaryNodeId
    : null;
  const selectedSortableControls =
    primaryNodeId === null
      ? null
      : (sortableControlRegistrations.get(primaryNodeId)?.controls ?? null);
  const nodeLayer = isStructuredPrototypeContainerNode(root) ? (
    <SortableCanvasContainer
      node={root}
      isRoot
      depth={0}
      ancestorNodeIds={EMPTY_ANCESTOR_NODE_IDS}
      freeformMoveDraft={freeformMoveDraft}
      resizeDraft={resizeDraft}
      registerNodeElement={registerNodeElement}
      registerSortableControls={registerSortableControls}
      {...props}
    />
  ) : (
    <NodeRenderer
      node={root}
      depth={0}
      ancestorNodeIds={EMPTY_ANCESTOR_NODE_IDS}
      freeformMoveDraft={freeformMoveDraft}
      resizeDraft={resizeDraft}
      registerNodeElement={registerNodeElement}
      registerSortableControls={registerSortableControls}
      {...props}
    />
  );
  return (
    <div
      ref={setCanvasElement}
      className="relative min-w-0"
      data-prototype-canvas-wrapper="true"
      data-prototype-marquee-phase={marqueePhase}
      data-prototype-marquee-last-end={marqueeLastEnd}
      data-prototype-marquee-selection-count={
        marqueePhase === "preview" ? props.selection.nodeIds.length : 0
      }
      onPointerDown={handleMarqueePointerDown}
    >
      <div className="relative min-w-0" data-prototype-node-layer="business">
        {nodeLayer}
      </div>
      <StructuredPrototypeSelectionControlsLayer
        canvasElement={canvasElement}
        targets={selectionTargets}
        primaryNodeId={primaryNodeId}
        sortableControls={selectedSortableControls}
        marqueeBounds={marqueeBounds}
        previewScale={props.previewScale}
        editing={props.editing}
        dragDisabled={props.dragDisabled}
        resizeDisabled={props.resizeDisabled}
        groupMoveEnabled={
          freeformGroupSelection !== null &&
          freeformGroupSelection.items.length === selectionTargets.length
        }
        freeformMoveDraft={freeformMoveDraft}
        freeformMoveGuideOverlay={freeformMoveGuideOverlay}
        freeformMovePhase={freeformMovePhase}
        freeformMoveLastEnd={freeformMoveLastEnd}
        resizeDraft={resizeDraft}
        resizeGuideOverlay={resizeGuideOverlay}
        resizePhase={resizePhase}
        resizeLastEnd={resizeLastEnd}
        resizeDirection={resizeDirection}
        registryVersion={nodeRegistryVersion}
        onSelect={props.onSelect}
        onFreeformGroupArrange={onFreeformGroupArrange}
        onFreeformSelectionNudge={onFreeformSelectionNudge}
        onFreeformMovePointerDown={handleFreeformMovePointerDown}
        onResizePointerDown={handleResizePointerDown}
      />
    </div>
  );
}

function OverlayNodeContent({
  document,
  node,
  runtimeState,
  viewModel,
  viewportWidth,
  formValues,
}: {
  document: StructuredPrototypeDocument;
  node: StructuredPrototypeNode;
  runtimeState: PrototypeRuntimeState | null;
  viewModel: RuntimeViewModel | null;
  viewportWidth: number;
  formValues: Record<string, string>;
}) {
  if (isStructuredPrototypeContainerNode(node)) {
    const columns =
      node.type === "Grid"
        ? resolveStructuredPrototypeGridColumns(node, viewportWidth)
        : node.type === "Stack" && node.direction === "row"
          ? 2
          : 1;
    return (
      <div
        className={cn(
          "grid gap-2 rounded border border-border-subtle bg-surface p-2",
          columns === 2 && "grid-cols-2",
        )}
      >
        {node.children.slice(0, 6).map((child) => (
          <div key={child.id} className="rounded border border-border-subtle bg-surface-raised p-2">
            <OverlayNodeContent
              document={document}
              node={child}
              runtimeState={runtimeState}
              viewModel={viewModel}
              viewportWidth={viewportWidth}
              formValues={formValues}
            />
          </div>
        ))}
      </div>
    );
  }
  if (node.type === "Text") {
    return (
      <div className="line-clamp-3 text-sm font-semibold">
        {runtimeNodeText(viewModel, node.id, node.content)}
      </div>
    );
  }
  if (node.type === "Input") {
    return (
      <div className="grid gap-1 text-xs font-semibold">
        {node.label}
        <div className="min-h-8 rounded border border-border-muted bg-surface-input px-2 py-1 text-sm font-normal text-text-muted">
          {(formValues[node.id] ?? node.value) || node.placeholder}
        </div>
      </div>
    );
  }
  if (node.type === "Button") {
    return (
      <div className="inline-flex min-h-8 items-center rounded bg-brand px-3 text-xs font-semibold text-black">
        {node.label}
      </div>
    );
  }
  const rows = runtimeNodeRows(viewModel, node.id);
  const visibleRows = rows
    ? rows
        .slice(0, 3)
        .map((row) =>
          node.columns.map((column) => runtimeEntityFieldText(row, column.fieldId)).join(" · "),
        )
    : node.rows
        .slice(0, 3)
        .map((row) =>
          node.columns
            .map((column) => row.cells.find((cell) => cell.columnKey === column.key)?.value ?? "")
            .join(" · "),
        );
  return (
    <div className="grid gap-1 text-xs">
      {visibleRows.map((row, index) => (
        <div key={`${row}-${index}`} className="truncate rounded bg-surface-input px-2 py-1">
          {row}
        </div>
      ))}
    </div>
  );
}

export function StructuredPrototypeNodeDragOverlay({
  document,
  node,
  runtimeState,
  viewModel,
  viewportWidth,
  formValues,
}: {
  document: StructuredPrototypeDocument;
  node: StructuredPrototypeNode;
  runtimeState: PrototypeRuntimeState | null;
  viewModel: RuntimeViewModel | null;
  viewportWidth: number;
  formValues: Record<string, string>;
}) {
  return (
    <section
      className="pointer-events-none max-h-[360px] min-w-48 max-w-[420px] overflow-hidden rounded-lg border border-brand bg-surface-raised p-3 text-foreground opacity-95 shadow-2xl ring-4 ring-brand-bg"
      data-prototype-drag-overlay="node"
    >
      <div className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
        {node.type} · {node.name}
      </div>
      <div className="mt-2 rounded-md border border-border-subtle bg-background/80 p-3">
        <OverlayNodeContent
          document={document}
          node={node}
          runtimeState={runtimeState}
          viewModel={viewModel}
          viewportWidth={Math.min(viewportWidth, 360)}
          formValues={formValues}
        />
      </div>
    </section>
  );
}
