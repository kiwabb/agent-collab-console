"use client";

import { useDndMonitor, useDraggable, useDroppable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import {
  Box,
  ChevronDown,
  ChevronRight,
  Eye,
  EyeOff,
  FormInput,
  Frame,
  GripVertical,
  LayoutGrid,
  MousePointerClick,
  Pencil,
  Table2,
  TextCursorInput,
  Type,
} from "lucide-react";
import { useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

import { cn } from "@/lib/utils";

import { isStructuredPrototypeContainerNode } from "./structuredPrototypeNodes";
import {
  createStructuredPrototypeLayerDragData,
  createStructuredPrototypeLayerDropData,
  deriveStructuredPrototypeLayerTreeState,
  readStructuredPrototypeLayerDragData,
  readStructuredPrototypeLayerDropData,
  resolveStructuredPrototypeLayerDrop,
  resolveStructuredPrototypeLayerTreeKeyboardAction,
  structuredPrototypeLayerDraggableId,
  structuredPrototypeLayerDroppableId,
  type StructuredPrototypeLayerDropAccepted,
  type StructuredPrototypeLayerDropIntent,
  type StructuredPrototypeLayerDropRefusalReason,
  type StructuredPrototypeLayerRowModel,
} from "./structuredPrototypeLayerTreeModel";
import type { StructuredPrototypeNode } from "./types";

export interface StructuredPrototypeLayerTreeLabels {
  tree: string;
  select: (name: string) => string;
  expand: (name: string) => string;
  collapse: (name: string) => string;
  rename: (name: string) => string;
  renameInput: (name: string) => string;
  show: (name: string) => string;
  hide: (name: string) => string;
  drag: (name: string) => string;
  nameRequired: string;
  renameFailed: string;
}

interface Props {
  root: StructuredPrototypeNode;
  selectedNodeId: string | null;
  error: string | null;
  labels: StructuredPrototypeLayerTreeLabels;
  selectionDisabled: boolean;
  mutationDisabled: boolean;
  dragDisabled: boolean;
  onSelect: (nodeId: string) => void;
  onRename: (nodeId: string, name: string) => Promise<boolean>;
  onVisibilityChange: (nodeId: string, visibility: "visible" | "hidden") => void;
  onMove: (move: StructuredPrototypeLayerDropAccepted) => void;
  onDropRefused: (reason: StructuredPrototypeLayerDropRefusalReason) => void;
}

const LAYER_ICONS: Record<StructuredPrototypeNode["type"], typeof Box> = {
  Freeform: Frame,
  Stack: Box,
  Grid: LayoutGrid,
  Form: FormInput,
  Text: Type,
  Input: TextCursorInput,
  Button: MousePointerClick,
  Table: Table2,
};

function LayerDropZone({
  row,
  intent,
  disabled,
}: {
  row: StructuredPrototypeLayerRowModel;
  intent: StructuredPrototypeLayerDropIntent;
  disabled: boolean;
}) {
  const { isOver, setNodeRef } = useDroppable({
    id: structuredPrototypeLayerDroppableId(row.node.id, intent),
    data: createStructuredPrototypeLayerDropData(row, intent),
    disabled,
  });
  return (
    <span
      ref={setNodeRef}
      className={cn(
        "pointer-events-none absolute inset-x-0 z-20",
        intent === "before" && "top-0 h-2",
        intent === "inside" && "inset-y-2",
        intent === "after" && "bottom-0 h-2",
      )}
      data-prototype-layer-drop-intent={intent}
      data-prototype-layer-drop-active={isOver ? "true" : "false"}
      aria-hidden
    >
      {isOver && intent === "inside" && (
        <span className="absolute inset-0 border border-brand bg-brand-bg" />
      )}
      {isOver && intent !== "inside" && (
        <span
          className={cn(
            "absolute inset-x-0 h-0.5 bg-brand",
            intent === "before" ? "top-0" : "bottom-0",
          )}
        />
      )}
    </span>
  );
}

function LayerTreeRow({
  row,
  expanded,
  selected,
  labels,
  selectionDisabled,
  mutationDisabled,
  dragDisabled,
  editing,
  renameValue,
  renameError,
  renamePending,
  renameErrorId,
  focused,
  onTreeItemRef,
  onFocusNode,
  onTreeKeyDown,
  onToggleExpanded,
  onSelect,
  onBeginRename,
  onRenameValueChange,
  onCommitRename,
  onCancelRename,
  onVisibilityChange,
}: {
  row: StructuredPrototypeLayerRowModel;
  expanded: boolean;
  selected: boolean;
  labels: StructuredPrototypeLayerTreeLabels;
  selectionDisabled: boolean;
  mutationDisabled: boolean;
  dragDisabled: boolean;
  editing: boolean;
  renameValue: string;
  renameError: string | null;
  renamePending: boolean;
  renameErrorId: string;
  focused: boolean;
  onTreeItemRef: (nodeId: string, element: HTMLDivElement | null) => void;
  onFocusNode: (nodeId: string) => void;
  onTreeKeyDown: (
    row: StructuredPrototypeLayerRowModel,
    event: ReactKeyboardEvent<HTMLDivElement>,
  ) => void;
  onToggleExpanded: (nodeId: string) => void;
  onSelect: (nodeId: string) => void;
  onBeginRename: (row: StructuredPrototypeLayerRowModel) => void;
  onRenameValueChange: (value: string) => void;
  onCommitRename: (row: StructuredPrototypeLayerRowModel) => Promise<void>;
  onCancelRename: (nodeId: string) => void;
  onVisibilityChange: (nodeId: string, visibility: "visible" | "hidden") => void;
}) {
  const root = row.parentId === null;
  const container = isStructuredPrototypeContainerNode(row.node);
  const dragData = createStructuredPrototypeLayerDragData(row);
  const { attributes, listeners, setActivatorNodeRef, setNodeRef, transform, isDragging } =
    useDraggable({
      id: structuredPrototypeLayerDraggableId(row.node.id),
      data: dragData,
      disabled: dragDisabled || root,
    });
  const Icon = LAYER_ICONS[row.node.type];
  const hidden = row.node.visibility === "hidden";
  const dragActivatorAttributes = { ...attributes, tabIndex: -1 };
  return (
    <div
      ref={(element) => onTreeItemRef(row.node.id, element)}
      className="relative w-max min-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand"
      role="treeitem"
      tabIndex={focused ? 0 : -1}
      aria-level={row.depth + 1}
      aria-selected={root ? undefined : selected}
      aria-expanded={container ? expanded : undefined}
      aria-label={row.node.name}
      aria-keyshortcuts={root ? "Enter Space" : "Enter Space F2 V"}
      onFocus={() => onFocusNode(row.node.id)}
      onKeyDown={(event) => {
        if (event.target === event.currentTarget) onTreeKeyDown(row, event);
      }}
      data-prototype-layer-node-id={row.node.id}
      data-prototype-layer-depth={row.depth}
      data-prototype-layer-hidden={hidden ? "true" : "false"}
      data-prototype-layer-root={root ? "true" : "false"}
      data-prototype-layer-root-actions={root ? "structural" : "editable"}
    >
      {!root && <LayerDropZone row={row} intent="before" disabled={dragDisabled} />}
      {container && <LayerDropZone row={row} intent="inside" disabled={dragDisabled} />}
      {!root && <LayerDropZone row={row} intent="after" disabled={dragDisabled} />}
      <div
        ref={setNodeRef}
        className={cn(
          "relative grid min-h-9 grid-cols-[28px_minmax(120px,1fr)_28px_28px_28px] items-center border-l-2 pr-1 text-xs transition-colors motion-reduce:transition-none",
          selected
            ? "border-brand bg-brand-bg text-foreground"
            : "border-transparent hover:bg-surface-hover",
          hidden && "text-text-faint",
          isDragging && "opacity-35",
        )}
        style={{
          paddingInlineStart: `${row.depth * 14 + 2}px`,
          transform: CSS.Translate.toString(transform),
        }}
      >
        {container ? (
          <button
            type="button"
            tabIndex={-1}
            className="relative z-30 grid size-7 cursor-pointer place-items-center text-text-muted hover:text-foreground"
            onClick={() => onToggleExpanded(row.node.id)}
            aria-label={labels[expanded ? "collapse" : "expand"](row.node.name)}
            title={labels[expanded ? "collapse" : "expand"](row.node.name)}
          >
            {expanded ? (
              <ChevronDown size={14} aria-hidden />
            ) : (
              <ChevronRight size={14} aria-hidden />
            )}
          </button>
        ) : (
          <span className="size-7" aria-hidden />
        )}

        {editing ? (
          <label className="relative z-30 flex min-w-0 items-center gap-2">
            <Icon size={14} className="shrink-0 text-text-faint" aria-hidden />
            <input
              autoFocus
              className={cn(
                "h-7 min-w-0 flex-1 border bg-surface-input px-2 text-xs text-foreground outline-none",
                renameError === null
                  ? "border-border-muted focus:border-brand"
                  : "border-status-failed",
              )}
              disabled={mutationDisabled || renamePending}
              value={renameValue}
              onChange={(event) => onRenameValueChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void onCommitRename(row);
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  event.stopPropagation();
                  onCancelRename(row.node.id);
                }
              }}
              aria-label={labels.renameInput(row.node.name)}
              aria-invalid={renameError !== null}
              aria-describedby={renameError === null ? undefined : renameErrorId}
            />
          </label>
        ) : root ? (
          <div className="relative z-30 flex min-h-9 min-w-0 items-center gap-2 px-1">
            <Icon size={14} className="shrink-0 text-text-faint" aria-hidden />
            <span className={cn("truncate font-medium", hidden && "line-through")}>
              {row.node.name}
            </span>
          </div>
        ) : (
          <button
            type="button"
            tabIndex={-1}
            className="relative z-30 flex min-h-9 min-w-0 cursor-pointer items-center gap-2 px-1 text-left disabled:cursor-not-allowed disabled:opacity-45"
            onClick={() => onSelect(row.node.id)}
            onDoubleClick={() => {
              if (!mutationDisabled) onBeginRename(row);
            }}
            disabled={selectionDisabled}
            aria-label={labels.select(row.node.name)}
          >
            <Icon size={14} className="shrink-0 text-text-faint" aria-hidden />
            <span className={cn("truncate font-medium", hidden && "line-through")}>
              {row.node.name}
            </span>
          </button>
        )}

        {root ? (
          <span className="size-7" aria-hidden />
        ) : (
          <button
            type="button"
            tabIndex={-1}
            className="relative z-30 grid size-7 cursor-pointer place-items-center text-text-faint hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
            onClick={() => onBeginRename(row)}
            disabled={mutationDisabled || renamePending}
            aria-label={labels.rename(row.node.name)}
            title={labels.rename(row.node.name)}
          >
            <Pencil size={13} aria-hidden />
          </button>
        )}
        {root ? (
          <span className="size-7" aria-hidden />
        ) : (
          <button
            type="button"
            tabIndex={-1}
            className="relative z-30 grid size-7 cursor-pointer place-items-center text-text-faint hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
            onClick={() => onVisibilityChange(row.node.id, hidden ? "visible" : "hidden")}
            disabled={mutationDisabled}
            aria-label={labels[hidden ? "show" : "hide"](row.node.name)}
            title={labels[hidden ? "show" : "hide"](row.node.name)}
          >
            {hidden ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />}
          </button>
        )}
        {root ? (
          <span className="size-7" aria-hidden />
        ) : (
          <button
            ref={setActivatorNodeRef}
            type="button"
            className="relative z-30 grid size-7 cursor-grab place-items-center text-text-faint hover:text-foreground active:cursor-grabbing disabled:cursor-not-allowed disabled:opacity-45"
            disabled={dragDisabled}
            {...dragActivatorAttributes}
            {...listeners}
            aria-label={labels.drag(row.node.name)}
            title={labels.drag(row.node.name)}
          >
            <GripVertical size={14} aria-hidden />
          </button>
        )}
      </div>
      {editing && renameError !== null && (
        <p
          id={renameErrorId}
          className="border-l-2 border-status-failed bg-status-failed/10 px-2 py-1 text-[10px] text-status-failed"
          style={{ paddingInlineStart: `${row.depth * 14 + 32}px` }}
          role="alert"
        >
          {renameError}
        </p>
      )}
    </div>
  );
}

interface LocalLayerTreeViewState {
  expandedNodeIds: ReadonlySet<string>;
  collapsedNodeIds: ReadonlySet<string>;
  collapseSelectionNodeId: string | null;
}

export function StructuredPrototypeLayerTree({
  root,
  selectedNodeId,
  error,
  labels,
  selectionDisabled,
  mutationDisabled,
  dragDisabled,
  onSelect,
  onRename,
  onVisibilityChange,
  onMove,
  onDropRefused,
}: Props) {
  const renameErrorId = useId();
  const treeItemRefs = useRef(new Map<string, HTMLDivElement>());
  const [viewStateByRoot, setViewStateByRoot] = useState<
    ReadonlyMap<string, LocalLayerTreeViewState>
  >(() => new Map());
  const [focusedNodeId, setFocusedNodeId] = useState(selectedNodeId ?? root.id);
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [renamePending, setRenamePending] = useState(false);
  const localViewState = useMemo<LocalLayerTreeViewState>(() => {
    return (
      viewStateByRoot.get(root.id) ?? {
        expandedNodeIds: new Set([root.id]),
        collapsedNodeIds: new Set(),
        collapseSelectionNodeId: selectedNodeId,
      }
    );
  }, [root.id, selectedNodeId, viewStateByRoot]);
  const treeState = useMemo(
    () =>
      deriveStructuredPrototypeLayerTreeState(
        root,
        localViewState.expandedNodeIds,
        selectedNodeId,
        localViewState.collapseSelectionNodeId === selectedNodeId
          ? localViewState.collapsedNodeIds
          : new Set<string>(),
      ),
    [localViewState, root, selectedNodeId],
  );
  const effectiveFocusedNodeId = treeState.visibleRows.some((row) => row.node.id === focusedNodeId)
    ? focusedNodeId
    : (treeState.visibleRows.find((row) => row.node.id === selectedNodeId)?.node.id ?? root.id);

  useDndMonitor({
    onDragEnd(event) {
      const dragged = readStructuredPrototypeLayerDragData(event.active.data.current);
      if (dragged === null) return;
      const target =
        event.over === null ? null : readStructuredPrototypeLayerDropData(event.over.data.current);
      const resolution = resolveStructuredPrototypeLayerDrop(root, dragged, target);
      if (resolution.accepted) onMove(resolution);
      else onDropRefused(resolution.reason);
    },
  });

  const setNodeExpanded = (nodeId: string, expandedValue: boolean): void => {
    setViewStateByRoot((current) => {
      const previous = current.get(root.id);
      const expanded = new Set(previous?.expandedNodeIds ?? [root.id]);
      const collapsed = new Set(
        previous?.collapseSelectionNodeId === selectedNodeId ? previous.collapsedNodeIds : [],
      );
      if (expandedValue) {
        expanded.add(nodeId);
        collapsed.delete(nodeId);
      } else {
        expanded.delete(nodeId);
        collapsed.add(nodeId);
      }
      const next = new Map(current);
      next.set(root.id, {
        expandedNodeIds: expanded,
        collapsedNodeIds: collapsed,
        collapseSelectionNodeId: selectedNodeId,
      });
      return next;
    });
  };

  const toggleExpanded = (nodeId: string): void => {
    setNodeExpanded(nodeId, !treeState.effectiveExpandedNodeIds.has(nodeId));
  };

  const registerTreeItem = (nodeId: string, element: HTMLDivElement | null): void => {
    if (element === null) treeItemRefs.current.delete(nodeId);
    else treeItemRefs.current.set(nodeId, element);
  };

  const focusTreeItem = (nodeId: string): void => {
    setFocusedNodeId(nodeId);
    treeItemRefs.current.get(nodeId)?.focus();
  };

  const beginRename = (row: StructuredPrototypeLayerRowModel): void => {
    if (row.parentId === null) return;
    setEditingNodeId(row.node.id);
    setRenameValue(row.node.name);
    setRenameError(null);
  };

  const cancelRename = (nodeId: string): void => {
    setEditingNodeId(null);
    setRenameValue("");
    setRenameError(null);
    setRenamePending(false);
    focusTreeItem(nodeId);
  };

  const commitRename = async (row: StructuredPrototypeLayerRowModel): Promise<void> => {
    const name = renameValue.trim();
    if (name.length === 0) {
      setRenameError(labels.nameRequired);
      return;
    }
    if (name === row.node.name) {
      cancelRename(row.node.id);
      return;
    }
    setRenamePending(true);
    setRenameError(null);
    try {
      const persisted = await onRename(row.node.id, name);
      if (persisted) cancelRename(row.node.id);
      else setRenameError(labels.renameFailed);
    } catch (error) {
      console.error("structured prototype layer rename failed:", error);
      setRenameError(labels.renameFailed);
    } finally {
      setRenamePending(false);
    }
  };

  const selectNode = (nodeId: string): void => {
    focusTreeItem(nodeId);
    onSelect(nodeId);
  };

  const handleTreeKeyDown = (
    row: StructuredPrototypeLayerRowModel,
    event: ReactKeyboardEvent<HTMLDivElement>,
  ): void => {
    const action = resolveStructuredPrototypeLayerTreeKeyboardAction(
      treeState.visibleRows,
      treeState.effectiveExpandedNodeIds,
      row.node.id,
      event.key,
    );
    if (action === null) return;
    if (action.kind === "select" && selectionDisabled) return;
    if ((action.kind === "rename" || action.kind === "toggleVisibility") && mutationDisabled) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    switch (action.kind) {
      case "focus":
        focusTreeItem(action.nodeId);
        return;
      case "expand":
        setNodeExpanded(action.nodeId, true);
        return;
      case "collapse":
        setNodeExpanded(action.nodeId, false);
        return;
      case "select":
        selectNode(action.nodeId);
        return;
      case "rename":
        beginRename(row);
        return;
      case "toggleVisibility":
        onVisibilityChange(row.node.id, row.node.visibility === "hidden" ? "visible" : "hidden");
    }
  };

  return (
    <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)]">
      {error !== null && (
        <p
          className="border-b border-status-failed/30 px-3 py-1.5 text-[10px] text-status-failed"
          role="alert"
          data-prototype-layer-error
        >
          {error}
        </p>
      )}
      <div className="min-h-0 overflow-auto" role="tree" aria-label={labels.tree}>
        {treeState.visibleRows.map((row) => (
          <LayerTreeRow
            key={row.node.id}
            row={row}
            expanded={treeState.effectiveExpandedNodeIds.has(row.node.id)}
            selected={row.parentId !== null && row.node.id === selectedNodeId}
            labels={labels}
            selectionDisabled={selectionDisabled}
            mutationDisabled={mutationDisabled}
            dragDisabled={dragDisabled}
            editing={row.node.id === editingNodeId}
            renameValue={renameValue}
            renameError={row.node.id === editingNodeId ? renameError : null}
            renamePending={row.node.id === editingNodeId && renamePending}
            renameErrorId={renameErrorId}
            focused={row.node.id === effectiveFocusedNodeId}
            onTreeItemRef={registerTreeItem}
            onFocusNode={setFocusedNodeId}
            onTreeKeyDown={handleTreeKeyDown}
            onToggleExpanded={toggleExpanded}
            onSelect={selectNode}
            onBeginRename={beginRename}
            onRenameValueChange={(value) => {
              setRenameValue(value);
              setRenameError(null);
            }}
            onCommitRename={commitRename}
            onCancelRename={cancelRename}
            onVisibilityChange={onVisibilityChange}
          />
        ))}
      </div>
    </div>
  );
}
